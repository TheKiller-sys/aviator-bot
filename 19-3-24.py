import telebot
from telebot import types
import random
import threading
import time
import datetime
import logging
from dotenv import load_dotenv
import os
import uuid  # For generating unique referral links
from typing import Optional, Dict, Any, List, Tuple  # For type hinting


# ------ Celery and Redis Imports ------
from celery import Celery
from celery.schedules import crontab

# ------ SQLAlchemy Imports (for MySQL) ------
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
from sqlalchemy import event
from sqlalchemy.pool import Pool
from sqlalchemy import exc

# ------ Database and Cache URLs from Environment ------
load_dotenv("config.env")

DB_URL = os.environ.get("DATABASE_URL", "mysql+mysqlconnector://user:password@host/database") # Changed SQLite to MySQL
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# ------ Celery Configuration ------
celery = Celery('aviastar_bot', broker=REDIS_URL, backend=REDIS_URL)

celery.conf.beat_schedule = {
    'cleanup_old_deposits_withdrawals': {  # Example: Cleanup tasks
        'task': 'bot.cleanup_old_deposits_withdrawals',
        'schedule': crontab(minute='0', hour='3'),  # Every day at 3:00 AM
    },
}
celery.conf.timezone = 'UTC'

# ------ SQLAlchemy Setup ------
engine = create_engine(DB_URL, pool_size=5, max_overflow=10) # Configure pool size
Base = declarative_base()
Session = sessionmaker(bind=engine)

# ------ Event Listener to Handle Disconnections ------
@event.listens_for(Pool, "checkout")
def ping_connection(dbapi_connection, connection_record, connection_proxy):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SELECT 1")
        cursor.close()
    except Exception as e:
        # Optional: Log the error
        raise exc.DisconnectionError() from e

# ------ Defining SQLAlchemy Models ------
class Usuario(Base):
    __tablename__ = 'usuarios'
    id_telegram = Column(Integer, primary_key=True)
    nombre = Column(String(255), nullable=False)
    balance = Column(Float, default=0.00)
    referral_link = Column(String(36), unique=True)  # Assuming UUID as referral link
    fecha_registro = Column(DateTime(timezone=True), server_default=func.now())
    apuestas = relationship("Apuesta", back_populates="usuario")
    estadistica = relationship("Estadistica", uselist=False, back_populates="usuario")
    referidos_recibidos = relationship("Referido", back_populates="referrer", foreign_keys="[Referido.referrer_id]")
    referidos_hechos = relationship("Referido", back_populates="referred", foreign_keys="[Referido.referred_id]")
    depositos_hechos = relationship("ReferidoDepositado", back_populates="referrer", foreign_keys="[ReferidoDepositado.referrer_id]")
    depositos_recibidos = relationship("ReferidoDepositado", back_populates="referred", foreign_keys="[ReferidoDepositado.referred_id]")
    blocked = Column(Boolean, default=False) # Added blocked column

class Apuesta(Base):
    __tablename__ = 'apuestas'
    id = Column(Integer, primary_key=True)
    id_telegram = Column(Integer, ForeignKey('usuarios.id_telegram'), nullable=False)
    amount = Column(Float, nullable=False)
    cashed_out = Column(Boolean, default=False)
    multiplier = Column(Float, default=1.0)
    fecha_apuesta = Column(DateTime(timezone=True), server_default=func.now())
    usuario = relationship("Usuario", back_populates="apuestas")

class Estadistica(Base):
    __tablename__ = 'estadisticas'
    id_telegram = Column(Integer, ForeignKey('usuarios.id_telegram'), primary_key=True)
    bets_made = Column(Integer, default=0)
    bets_won = Column(Integer, default=0)
    bets_lost = Column(Integer, default=0)
    total_won = Column(Float, default=0.0)
    total_lost = Column(Float, default=0.0)
    usuario = relationship("Usuario", back_populates="estadistica")

class Referido(Base):
    __tablename__ = 'referidos'
    referred_id = Column(Integer, ForeignKey('usuarios.id_telegram'), primary_key=True)
    referrer_id = Column(Integer, ForeignKey('usuarios.id_telegram'), nullable=False)
    referred = relationship("Usuario", back_populates="referidos_recibidos", foreign_keys=[referred_id])
    referrer = relationship("Usuario", back_populates="referidos_hechos", foreign_keys=[referrer_id])

class ReferidoDepositado(Base):
    __tablename__ = 'referidos_depositados'
    referred_id = Column(Integer, ForeignKey('usuarios.id_telegram'), primary_key=True)
    referrer_id = Column(Integer, ForeignKey('usuarios.id_telegram'), primary_key=True)
    referred = relationship("Usuario", back_populates="depositos_recibidos", foreign_keys=[referred_id])
    referrer = relationship("Usuario", back_populates="depositos_hechos", foreign_keys=[referrer_id])

# ------ Creates the Tables ------
Base.metadata.create_all(engine)

# ------ Redis Client (for Cache) ------
import redis
redis_client = redis.Redis.from_url(REDIS_URL)

# ------ Bot Configuration ------
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logging.critical("Telegram token not found in environment variables.")
    raise ValueError("Telegram token missing.")

ADMINS = [int(admin_id) for admin_id in os.environ.get('TELEGRAM_ADMIN_IDS', '').split(',') if admin_id]
MIN_BET = int(os.environ.get('MIN_BET', 1))
MAX_BET = int(os.environ.get('MAX_BET', 1000))
MIN_DEPOSITO = int(os.environ.get('MIN_DEPOSITO', 150))
MIN_RETIRO = int(os.environ.get('MIN_RETIRO', 20))
CRASH_PROBABILITY = float(os.environ.get('CRASH_PROBABILITY', 0.05))
REFERRAL_BONUS = float(os.environ.get('REFERRAL_BONUS', 0.10))

# ------ In-Memory Data (Consider using a more robust session management) ------
user_states: Dict[int, str] = {} # User states
deposit_requests: Dict[int, Dict[str, Any]] = {} # Deposit requests
withdraw_requests: Dict[int, Dict[str, Any]] = {}  # Withdrawal Requests

# ------ Logging Configuration ------
LOG_FILE = 'aviastar_bot.log'
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ------ Telegram Bot Instance ------
bot = telebot.TeleBot(TOKEN)

# ------ Game Class ------
class Game:
    def __init__(self):
        self.multiplier = 1.0
        self.crashed = False
        self.participants: Dict[int, Dict[str, Any]] = {}  # user_id: {'apuesta_id': int, 'amount': float}
        self.message_ids: Dict[int, int] = {}
        self.crash_point = 1.0
        self.round_active = False
        self.lock = threading.Lock()

    def start_round(self):
        """Starts a new round of the game."""
        with self.lock:
            if self.round_active:
                return

            self.round_active = True
            self.crashed = False
            self.multiplier = 1.0
            self.crash_point = self.generate_crash_point()
            self.message_ids = {}

            for user_id in list(self.participants.keys()): # Iterate over a copy to be able to delete safely
                # Before sending the message, check if the user is blocked
                if is_user_blocked_task.result(user_id):
                    self.remove_participant(user_id)
                    continue
                try:
                    msg = bot.send_message(
                        user_id,
                        self.generate_game_text(user_id),
                        reply_markup=self.generate_game_buttons()
                    )
                    self.message_ids[user_id] = msg.message_id
                except telebot.apihelper.ApiException as e:
                    logging.warning(f"Error sending message to user {user_id}: {e}")
                    self.remove_participant(user_id)
                except Exception as e:
                    logging.exception(f"Unexpected error starting round for user {user_id}: {e}")
                    self.remove_participant(user_id)

            threading.Thread(target=self.update_multiplier).start()

    def remove_participant(self, user_id: int):
         """Removes a participant from the game."""
         with self.lock:
             if user_id in self.participants:
                 del self.participants[user_id]
             if user_id in self.message_ids:
                 del self.message_ids[user_id]

    def generate_crash_point(self):
        """Generates the crash point for this round using weighted probabilities."""
        ranges = [(1.0, 2.0), (2.0, 3.0), (3.0, 4.0), (4.0, 5.0)]
        weights = [75, 20, 3, 2] # Probabilities for each range

        selected_range = random.choices(ranges, weights=weights, k=1)[0] # Select a range

        if selected_range[0] == 1.0: # Ensure a higher density of crashes in the first range
            return round(random.uniform(1.0, 2.0), 2)
        else:
            return round(random.uniform(selected_range[0], selected_range[1]), 2)

    def update_multiplier(self):
        """Updates the multiplier every 0.5 seconds until the game crashes."""
        while self.round_active and not self.crashed and self.multiplier < self.crash_point:
            time.sleep(0.5) # Short delay
            with self.lock:
                self.multiplier = round(self.multiplier + 0.10, 2)
            self.update_all_messages()

        with self.lock:
            if not self.crashed:
                self.crashed = True # Set crashed to True
                self.end_game()
            self.round_active = False

    def update_all_messages(self):
        """Updates the game message for all active participants."""
        for user_id, msg_id in list(self.message_ids.items()):
            # Check if the user is blocked before sending the message
            if is_user_blocked_task.result(user_id):
                self.remove_participant(user_id)
                continue
            try:
                bot.edit_message_text(
                    chat_id=user_id,
                    message_id=msg_id,
                    text=self.generate_game_text(user_id),
                    reply_markup=self.generate_game_buttons()
                )
            except telebot.apihelper.ApiException as e:
                logging.warning(f"Error editing message for user {user_id}: {e}")
                self.remove_participant(user_id)
            except Exception as e:
                logging.exception(f"Unexpected error updating messages for user {user_id}: {e}")
                self.remove_participant(user_id) # Safeguard

    def generate_game_text(self, user_id: int) -> str:
        """Generates the game text message for the specified user."""
        with Session() as session:
            apuesta = session.query(Apuesta).filter_by(id_telegram=user_id, cashed_out=False).first()
            amount = apuesta.amount if apuesta else 0.0

            with self.lock:
                return f"""
    🎮 **RONDA EN CURSO** 🚀
    ━━━━━━━━━━━━━━━━━━
    ✈ Multiplicador actual: `{self.multiplier}x`
    💰 Apuesta: `${amount}`
    🏆 Ganancia potencial: `${amount * self.multiplier:.2f}`

    ⚠️ _Presiona RETIRAR antes del crash!_
    """

    def generate_game_buttons(self):
        """Generates the game buttons for the user to interact with."""
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("🚀 Retirar", callback_data='cashout'),
            types.InlineKeyboardButton("🔄 Nueva Apuesta", callback_data='newbet')
        )
        return markup

    def end_game(self):
         """Ends the game round, handles payouts and crashes."""
         with self.lock:
             for user_id in list(self.participants.keys()):
                 # Check if the user is blocked before sending any message
                 if is_user_blocked_task.result(user_id):
                     self.remove_participant(user_id)
                     continue
                 with Session() as session:
                     apuesta = session.query(Apuesta).filter_by(id_telegram=user_id, cashed_out=False).first()
                     if apuesta: # Ensure the bet exists and wasn't cashed out early
                         if self.crashed:
                             # Update statistics for lost bets (using celery task)
                             update_statistics_task.delay(user_id, False, apuesta.amount)
                             try:
                                 bot.send_message(
                                     user_id,
                                     f"💥 **CRASH!** El juego se estrelló en `{self.multiplier}x`\n"
                                     f"❌ Perdiste: `${apuesta.amount}`"
                                 )
                             except telebot.apihelper.ApiException as e:
                                 logging.warning(f"Error sending crash message to user {user_id}: {e}")
                             except Exception as e:
                                 logging.exception(f"Unexpected error at game end for user {user_id}: {e}")
                     self.remove_participant(user_id)  # Clean up participants


game = Game()

# ------ Helper Functions (Move Database Operations into Celery Tasks) ------

@celery.task
def get_balance_task(user_id: int) -> float:
    """Gets user balance from the database."""
    try:
        with Session() as session:
            usuario = session.query(Usuario).filter_by(id_telegram=user_id, blocked=False).first() #Added blocked=False check
            return usuario.balance if usuario else 0.00
    except Exception as e:
        logging.exception(f"Error getting balance for user {user_id}: {e}")
        return 0.00

@celery.task
def update_balance_task(user_id: int, amount: float):
    """Updates user balance in the database."""
    try:
        with Session() as session:
            usuario = session.query(Usuario).filter_by(id_telegram=user_id, blocked=False).first() #Added blocked=False check
            if usuario:
                usuario.balance = amount
                session.commit()
            else:
                logging.warning(f"User {user_id} not found when trying to update balance.")
    except Exception as e:
        logging.exception(f"Error updating balance for user {user_id}: {e}")

@celery.task
def create_usuario_task(user_id: int, nombre: str, referral_link: str):
    """Creates a new user in the database."""
    try:
        with Session() as session:
            existing_user = session.query(Usuario).filter_by(id_telegram=user_id).first()
            if not existing_user:
                usuario = Usuario(id_telegram=user_id, nombre=nombre, referral_link=referral_link)
                estadistica = Estadistica(id_telegram=user_id) # Initialize statistics
                session.add_all([usuario, estadistica])
                session.commit()
            else:
                logging.warning(f"Attempted to create user {user_id} that already exists.")
    except Exception as e:
        logging.exception(f"Error creating user {user_id}: {e}")

@celery.task
def register_apuesta_task(user_id: int, amount: float) -> Optional[int]:
    """Registers a new bet in the database."""
    try:
        with Session() as session:
            apuesta = Apuesta(id_telegram=user_id, amount=amount)
            session.add(apuesta)
            session.commit()
            return apuesta.id
    except Exception as e:
        logging.exception(f"Error registering bet for user {user_id}: {e}")
        return None

@celery.task
def update_apuesta_task(apuesta_id: int, multiplier: float):
    """Updates a bet with the cashout multiplier."""
    try:
        with Session() as session:
            apuesta = session.query(Apuesta).filter_by(id=apuesta_id).first()
            if apuesta:
                apuesta.cashed_out = True
                apuesta.multiplier = multiplier
                session.commit()
            else:
                logging.warning(f"Apuesta {apuesta_id} not found when trying to update.")
    except Exception as e:
        logging.exception(f"Error updating bet {apuesta_id}: {e}")

@celery.task
def get_apuestas_activas_task(user_id: int) -> List[Tuple[int, float]]:
    """Gets all active bets for a user from the database."""
    try:
        with Session() as session:
            apuestas = session.query(Apuesta.id, Apuesta.amount).filter_by(id_telegram=user_id, cashed_out=False).all()
            return apuestas
    except Exception as e:
        logging.exception(f"Error getting active bets for user {user_id}: {e}")
        return []

@celery.task
def update_statistics_task(user_id: int, won: bool, amount: float):
    """Updates user statistics in the database."""
    try:
        with Session() as session:
            estadistica = session.query(Estadistica).filter_by(id_telegram=user_id).first()
            if estadistica:
                estadistica.bets_made += 1
                if won:
                    estadistica.bets_won += 1
                    estadistica.total_won += amount
                else:
                    estadistica.bets_lost += 1
                    estadistica.total_lost += amount
                session.commit()
            else:
                logging.warning(f"Estadistica for user {user_id} not found when trying to update.")
    except Exception as e:
        logging.exception(f"Error updating statistics for user {user_id}: {e}")

@celery.task
def register_referido_task(referred_id: int, referrer_id: int):
    """Registers a referral relationship in the database."""
    try:
        with Session() as session:
            existing_referral = session.query(Referido).filter_by(referred_id=referred_id).first()
            if not existing_referral:
                referido = Referido(referred_id=referred_id, referrer_id=referrer_id)
                session.add(referido)
                session.commit()
            else:
                logging.warning(f"Attempted to register referral {referred_id} that already exists.")
    except Exception as e:
        logging.exception(f"Error registering referral: {e}")

@celery.task
def get_referidos_task(referrer_id: int) -> List[int]:
    """Gets a list of referred user IDs from the database."""
    try:
        with Session() as session:
            referidos = session.query(Referido.referred_id).filter_by(referrer_id=referrer_id).all()
            return [ref[0] for ref in referidos]
    except Exception as e:
        logging.exception(f"Error getting referrals for user {referrer_id}: {e}")
        return []

@celery.task
def register_referido_depositado_task(referred_id: int, referrer_id: int):
    """Registers a referral deposit in the database."""
    try:
        with Session() as session:
            existing_deposit = session.query(ReferidoDepositado).filter_by(referred_id=referred_id, referrer_id=referrer_id).first()
            if not existing_deposit:
                referido_depositado = ReferidoDepositado(referred_id=referred_id, referrer_id=referrer_id)
                session.add(referido_depositado)
                session.commit()
            else:
                logging.warning(f"Attempted to register referral deposit {referred_id} that already exists.")
    except Exception as e:
        logging.exception(f"Error registering referral deposit: {e}")

@celery.task
def get_cantidad_referidos_depositados_task(referrer_id: int) -> int:
    """Gets the count of referred users who have made a deposit."""
    try:
        with Session() as session:
            count = session.query(func.count(ReferidoDepositado.referred_id)).filter_by(referrer_id=referrer_id).scalar()
            return count or 0
    except Exception as e:
        logging.exception(f"Error getting referral deposit count for user {referrer_id}: {e}")
        return 0

@celery.task
def process_referral_bonus_task(user_id: int, amount: float, call_from_user_username: str):
    """Processes the referral bonus when a user makes a bet."""
    try:
        with Session() as session:
            referral = session.query(Referido).filter_by(referred_id=user_id).first()
            if referral:
                referrer_id = referral.referrer_id
                bonus = amount * REFERRAL_BONUS

                # Update referrer's balance (using celery task)
                referrer_balance = get_balance_task.result(referrer_id)  # Wait for result
                update_balance_task.delay(referrer_id, referrer_balance + bonus)  # Async update

                # Notify referrer (consider using a more robust notification system)
                bot.send_message(
                    referrer_id,
                    f"🎉 ¡Bonus por referido! Obtuviste ${bonus:.2f}\n"
                    f"👤 De: @{call_from_user_username}\n"
                    f"💰 Apuesta: ${amount}"
                )
    except Exception as e:
        logging.exception(f"Error processing referral bonus for user {user_id}: {e}")

#------ Celery Task Example (Cleanup Old Requests) -----
@celery.task
def cleanup_old_deposits_withdrawals():
    """An example Celery task to cleanup old requests (replace with actual logic)."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    try:
        # Example: Using SQLAlchemy to cleanup old records from deposit_requests
        with Session() as session:
            # Replace 'DepositRequest' with your actual SQLAlchemy model for deposits
            #old_deposits = session.query(DepositRequest).filter(DepositRequest.created_at < cutoff).all()
            #for deposit in old_deposits:
            #    session.delete(deposit)
            #session.commit()
            logging.info(f"Successfully cleaned up old deposit requests before {cutoff}")
    except Exception as e:
        logging.error(f"Error during cleanup of old deposit requests: {e}")

@celery.task
def is_user_blocked_task(user_id: int) -> bool:
    """Checks if a user is blocked in the database."""
    try:
        with Session() as session:
            usuario = session.query(Usuario).filter_by(id_telegram=user_id).first()
            return usuario.blocked if usuario else False
    except Exception as e:
        logging.exception(f"Error checking if user {user_id} is blocked: {e}")
        return False

@celery.task
def block_user_task(user_id: int):
    """Blocks a user in the database."""
    try:
        with Session() as session:
            usuario = session.query(Usuario).filter_by(id_telegram=user_id).first()
            if usuario:
                usuario.blocked = True
                session.commit()
                return True
            else:
                logging.warning(f"User {user_id} not found when trying to block.")
                return False
    except Exception as e:
        logging.exception(f"Error blocking user {user_id}: {e}")
        return False

@celery.task
def unblock_user_task(user_id: int):
    """Unblocks a user in the database."""
    try:
        with Session() as session:
            usuario = session.query(Usuario).filter_by(id_telegram=user_id).first()
            if usuario:
                usuario.blocked = False
                session.commit()
                return True
            else:
                logging.warning(f"User {user_id} not found when trying to unblock.")
                return False
    except Exception as e:
        logging.exception(f"Error unblocking user {user_id}: {e}")
        return False

@celery.task
def get_bot_statistics_task() -> Dict[str, Any]:
    """Retrieves bot statistics from the database."""
    try:
        with Session() as session:
            total_users = session.query(func.count(Usuario.id_telegram)).scalar() or 0
            total_bets = session.query(func.count(Apuesta.id)).scalar() or 0
            total_deposits = 0  # TODO: Implement deposit tracking
            total_withdrawals = 0  # TODO: Implement withdrawal tracking
            total_won = session.query(func.sum(Estadistica.total_won)).scalar() or 0.0
            total_lost = session.query(func.sum(Estadistica.total_lost)).scalar() or 0.0

            return {
                'total_users': total_users,
                'total_bets': total_bets,
                'total_deposits': total_deposits,
                'total_withdrawals': total_withdrawals,
                'total_won': total_won,
                'total_lost': total_lost
            }
    except Exception as e:
        logging.exception(f"Error getting bot statistics: {e}")
        return {}

# ------ Telegram Bot Handlers ------
@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Handles the /start command."""
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        nombre = message.from_user.first_name

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            bot.send_message(message.chat.id, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.")
            return

        with Session() as session:
            existing_user = session.query(Usuario).filter_by(id_telegram=user_id).first()
            if not existing_user:
                referral_link = str(uuid.uuid4()) # Generate unique referral link
                create_usuario_task.delay(user_id, nombre, referral_link) # Create user (async)
            else:
                referral_link = existing_user.referral_link

        # Handle referrals (process referral bonus asynchronously)
        if len(message.text.split()) > 1:
            referral_code = message.text.split()[1]
            with Session() as session:
                referrer = session.query(Usuario).filter_by(referral_link=referral_code).first()
                if referrer and referrer.id_telegram != user_id:
                    register_referido_task.delay(user_id, referrer.id_telegram) # Register referral (async)

        referral_link_url = f"https://t.me/{bot.get_me().username}?start={referral_link}"
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🎮 JUGAR AHORA", callback_data='play'))
        markup.row(types.InlineKeyboardButton("📚 TUTORIAL", callback_data='tutorial'))
        markup.row(types.InlineKeyboardButton("💳 DEPOSITAR", callback_data='deposit'))
        markup.row(types.InlineKeyboardButton("📤 RETIRAR", callback_data='withdraw'))
        markup.row(types.InlineKeyboardButton("💎 MIS ESTADÍSTICAS", callback_data='stats'))
        markup.row(types.InlineKeyboardButton("🏆 LÍDERES", callback_data='leaders'))
        markup.row(types.InlineKeyboardButton("👥 REFERIDOS", callback_data='referrals'))

        balance = get_balance_task.result(user_id) # Get balance (wait for result)

        bot.send_message(
            message.chat.id,
            f"""
✨ **BIENVENIDO A AVIASTAR BOT** ✨
━━━━━━━━━━━━━━━━━━━━━━
✅ El bot *OFICIAL* del juego Aviator con:
➼ Retiros instantáneos
➼ Soporte 24/7
➼ Máxima seguridad

💰 **Balance:** `${balance:.2f}`
🚀 ¡Comienza a ganar ahora mismo!
""",
            parse_mode='Markdown',
            reply_markup=markup
        )

        logging.info(f"/start command executed by user {user_id}")
    except Exception as e:
        logging.exception(f"Error in /start: {e}")

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """Handles the /admin command."""
    try:
        user_id = message.from_user.id
        if user_id in ADMINS:
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("📊 Estadísticas del Bot", callback_data='admin_stats'))
            markup.row(types.InlineKeyboardButton("🔒 Bloquear Usuario", callback_data='admin_block_user'))
            markup.row(types.InlineKeyboardButton("🔓 Desbloquear Usuario", callback_data='admin_unblock_user'))

            bot.send_message(
                user_id,
                """
🚨 **PANEL DE ADMINISTRACIÓN** 🚨
━━━━━━━━━━━━━━━━━━━━━━
Selecciona una opción:
""",
                parse_mode='Markdown',
                reply_markup=markup
            )
            logging.info(f"Admin panel accessed by admin {user_id}")
        else:
            bot.send_message(user_id, "❌ No tienes permisos para acceder a este comando.")
            logging.warning(f"Unauthorized access attempt to admin panel by user {user_id}")
    except Exception as e:
        logging.exception(f"Error in /admin: {e}")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Handles all callback queries."""
    try:
        user_id = call.from_user.id

        callback_actions = {
            'play': show_bet_interface,
            'balance': show_balance,
            'cashout': cash_out,
            'newbet': show_bet_interface,
            'deposit': start_deposit,
            'withdraw': start_withdraw,
            'stats': show_stats,
            'leaders': show_leaders,
            'referrals': show_referrals,
            'menu': lambda call: send_welcome(call.message), # Uses lambda to pass the correct argument
            'refresh': handle_refresh,
            'admin_stats': show_admin_statistics,
            'admin_block_user': ask_admin_for_user_to_block,
            'admin_unblock_user': ask_admin_for_user_to_unblock
        }

        if call.data in callback_actions:
            callback_actions[call.data](call)
        elif call.data.startswith(('confirm_', 'reject_', 'approve_')):
            handle_admin_decision(call)
        elif call.data.startswith('bet_'):
            handle_bet_selection(call)
        elif call.data == 'custom_bet':
            handle_custom_bet(call)
        else:
            logging.warning(f"Unknown callback: {call.data}")

        logging.info(f"Callback '{call.data}' executed by user {user_id}")

    except Exception as e:
        logging.exception(f"Error in callback: {e}")

# ------ Game Actions ------
def show_bet_interface(call):
    """Displays the betting interface to the user."""
    try:
        user_id = call.from_user.id

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
            return

        # Retrieve balance (use Redis cache if available)
        balance_str = redis_client.get(f"user:{user_id}:balance")
        if balance_str:
            balance = float(balance_str.decode('utf-8')) # decode from bytes
        else:
            balance = get_balance_task.result(user_id) # Await from Celery
            redis_client.setex(f"user:{user_id}:balance", 60, balance) # Cache the value for 60 seconds

        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("💵 APOSTAR $10", callback_data='bet_10'),
            types.InlineKeyboardButton("💎 APOSTAR $50", callback_data='bet_50')
        )
        markup.row(
            types.InlineKeyboardButton("🚀 APOSTAR $100", callback_data='bet_100'),
            types.InlineKeyboardButton("💰 PERSONALIZADO", callback_data='custom_bet')
        )

        edit_message(
            call,
            f"""
🎯 **SELECCIÓN DE APUESTA**
━━━━━━━━━━━━━━━━━━
💰 Balance disponible: `${balance:.2f}`
📈 Máximo potencial: `1000x`

⚡ Elije tu apuesta inicial:
""",
            markup
        )
    except Exception as e:
        logging.exception(f"Error showing bet interface: {e}")

def handle_bet_selection(call):
    """Handles the user's bet selection and placing of the bet."""
    try:
        user_id = call.from_user.id

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
            return

        amount = float(call.data.split('_')[1])

        # Get cached balance or load from db
        balance_str = redis_client.get(f"user:{user_id}:balance")
        if balance_str:
            balance = float(balance_str.decode('utf-8'))
        else:
            balance = get_balance_task.result(user_id)
            redis_client.setex(f"user:{user_id}:balance", 60, balance)  # cache it


        if balance < amount:
            answer_callback(call, f"❌ Saldo insuficiente! Necesitas ${amount}", True)
            return

        # Register the bet asynchronously
        apuesta_id = register_apuesta_task.result(user_id, amount)

        if apuesta_id is None:
            answer_callback(call, "❌ Error al registrar la apuesta.", True)
            return

        nuevo_balance = balance - amount

        # Update the balance asynchronously
        update_balance_task.delay(user_id, nuevo_balance)
        redis_client.setex(f"user:{user_id}:balance", 60, nuevo_balance)  # Cache new value


        # Update statistics
        update_statistics_task.delay(user_id, False, amount)

        # Process referral bonus (using celery task)
        process_referral_bonus_task.delay(user_id, amount, call.from_user.username)

        # Start the game
        with game.lock:
            game.participants[user_id] = {'apuesta_id': apuesta_id, 'amount': amount}

        if not game.round_active:
            game.start_round()
        else:
            try:
                msg = bot.send_message(
                    user_id,
                    game.generate_game_text(user_id),
                    reply_markup=game.generate_game_buttons()
                )
                with game.lock:
                    game.message_ids[user_id] = msg.message_id
            except Exception as e:
                logging.exception(f"Error joining round: {e}")

        edit_message(
            call,
            f"""
🎰 **APUESTA CONFIRMADA!** ✅
━━━━━━━━━━━━━━━━━━
💰 Monto apostado: `${amount}`
📈 Multiplicador actual: `1.0x`
🏆 Ganancia potencial: `${amount * 1.0:.2f}`

🚀 El juego está comenzando...
""",
            types.InlineKeyboardMarkup().row(
                types.InlineKeyboardButton("🔄 Actualizar", callback_data='refresh')
            )
        )
    except Exception as e:
        logging.exception(f"Error handling bet selection: {e}")

def handle_custom_bet(call):
    """Handles the custom bet selection."""
    try:
        user_id = call.from_user.id

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
            return

        user_states[user_id] = 'awaiting_bet_amount'
        bot.send_message(
            call.message.chat.id,
            f"💰 Ingresa el monto que deseas apostar (${MIN_BET} - ${MAX_BET}):",
            reply_markup=types.ForceReply(selective=True)
        )
    except Exception as e:
        logging.exception(f"Error initializing custom bet: {e}")

# ------ Transaction Handlers ------
def start_deposit(call):
    """Starts the deposit process."""
    try:
        user_id = call.from_user.id

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
            return

        user_states[user_id] = 'awaiting_deposit_phone'
        bot.send_message(
            call.message.chat.id,
            "📱 Por favor envía tu número de teléfono (con código de país)\nEjemplo: +5491123456789",
            reply_markup=types.ForceReply(selective=True)
        )
    except Exception as e:
        logging.exception(f"Error starting deposit: {e}")

def start_withdraw(call):
    """Starts the withdrawal process."""
    try:
        user_id = call.from_user.id

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
            return

        # Retrieve balance (use Redis cache if available)
        balance_str = redis_client.get(f"user:{user_id}:balance")
        if balance_str:
            balance = float(balance_str.decode('utf-8'))  # decode from bytes
        else:
            balance = get_balance_task.result(user_id)  # Await from Celery
            redis_client.setex(f"user:{user_id}:balance", 60, balance)  # Cache

        # Requirements for withdrawal
        referidos = get_referidos_task.result(user_id) # Get referral list (async)
        if len(referidos) < 3:
            answer_callback(call, "❌ Debes referir al menos a 3 usuarios para retirar.", True)
            return

        cantidad_referidos_depositados = get_cantidad_referidos_depositados_task.result(user_id) # Async
        if cantidad_referidos_depositados < 1:
            answer_callback(call, "❌ Al menos 1 de tus referidos debe haber depositado para poder retirar.", True)
            return

        if balance < MIN_RETIRO:
            answer_callback(call, f"❌ El monto mínimo para retirar es de ${MIN_RETIRO}.", True)
            return

        user_states[user_id] = 'awaiting_withdrawal_phone'
        bot.send_message(
            call.message.chat.id,
            "📱 Por favor envía tu número de teléfono (con código de país) para recibir el pago\nEjemplo: +5491123456789",
            reply_markup=types.ForceReply(selective=True)
        )
    except Exception as e:
        logging.exception(f"Error starting withdrawal: {e}")

# ------ Information Display Handlers ------
def show_balance(call):
    """Displays the user's balance."""
    try:
        user_id = call.from_user.id

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
            return

        # Retrieve balance (use Redis cache if available)
        balance_str = redis_client.get(f"user:{user_id}:balance")
        if balance_str:
            balance = float(balance_str.decode('utf-8')) # decode from bytes
        else:
            balance = get_balance_task.result(user_id) # Await from Celery
            redis_client.setex(f"user:{user_id}:balance", 60, balance) # Cache

        edit_message(
            call,
            f"💰 Tu balance actual es: ${balance:.2f}",
            types.InlineKeyboardMarkup().row(
                types.InlineKeyboardButton("🔄 Actualizar", callback_data='refresh')
            )
        )
    except Exception as e:
        logging.exception(f"Error showing balance: {e}")

def show_stats(call):
    """Displays the user's statistics."""
    try:
        user_id = call.from_user.id

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
            return

        with Session() as session:
            estadistica = session.query(Estadistica).filter_by(id_telegram=user_id).first()
            if estadistica:
                edit_message(
                    call,
                    f"""
📊 **TUS ESTADÍSTICAS**
━━━━━━━━━━━━━━━━━━
🕹️ Apuestas realizadas: `{estadistica.bets_made}`
🏆 Apuestas ganadas: `{estadistica.bets_won}`
❌ Apuestas perdidas: `{estadistica.bets_lost}`
💰 Total ganado: `${estadistica.total_won:.2f}`
💸 Total perdido: `${estadistica.total_lost:.2f}`
""",
                    types.InlineKeyboardMarkup().row(
                        types.InlineKeyboardButton("🔙 Menú", callback_data='menu')
                    )
                )
            else:
                edit_message(
                    call,
                    "❌ No se encontraron estadísticas para este usuario.",
                    types.InlineKeyboardMarkup().row(
                        types.InlineKeyboardButton("🔙 Menú", callback_data='menu')
                    )
                )
    except Exception as e:
        logging.exception(f"Error showing stats: {e}")

def show_leaders(call):
    """Displays the leaderboard."""
    try:

        # Check if the user is blocked
        #if is_user_blocked_task.result(user_id): #Leaderboard is global - everyone should see it
        #    answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
        #    return

        with Session() as session:
            # Query top 10 users based on total winnings
            top_users = session.query(
                Usuario.nombre,
                Estadistica.total_won
            ).join(
                Estadistica, Usuario.id_telegram == Estadistica.id_telegram
            ).order_by(
                Estadistica.total_won.desc()
            ).limit(10).all()

            if top_users:
                leaderboard_text = "🏆 **TABLA DE LÍDERES** 🏆\n━━━━━━━━━━━━━━━━━━\n"
                for i, (nombre, total_won) in enumerate(top_users, 1):
                    leaderboard_text += f"{i}. {nombre}: `${total_won:.2f}`\n"
            else:
                leaderboard_text = "❌ No hay datos para mostrar en la tabla de líderes."

            edit_message(
                call,
                leaderboard_text,
                types.InlineKeyboardMarkup().row(
                    types.InlineKeyboardButton("🔙 Menú", callback_data='menu')
                )
            )
    except Exception as e:
        logging.exception(f"Error showing leaderboard: {e}")

def show_referrals(call):
    """Displays referral information."""
    try:
        user_id = call.from_user.id

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
            return

        with Session() as session:
            usuario = session.query(Usuario).filter_by(id_telegram=user_id).first()
            if usuario:
                referral_link = f"https://t.me/{bot.get_me().username}?start={usuario.referral_link}"
            else:
                referral_link = "Error al generar el enlace."

        referidos = get_referidos_task.result(user_id) # Async

        edit_message(
            call,
            f"""
👥 **REFERIDOS**
━━━━━━━━━━━━━━━━━━
🔗 Tu enlace de referido:
`{referral_link}`

👤 Referidos totales: `{len(referidos)}`
💰 Bono por referido: `{REFERRAL_BONUS * 100:.0f}%`
""",
            reply_markup=types.InlineKeyboardMarkup().row(
                types.InlineKeyboardButton("🔙 Menú", callback_data='menu')
            )
        )
    except Exception as e:
        logging.exception(f"Error showing referrals: {e}")

# ------ Admin Handlers ------

def show_admin_statistics(call):
    """Displays bot statistics to the admin."""
    try:
        user_id = call.from_user.id
        if user_id in ADMINS:
            stats = get_bot_statistics_task.result()  # Get statistics (wait for result)

            message_text = f"""
📊 **ESTADÍSTICAS DEL BOT** 📊
━━━━━━━━━━━━━━━━━━━━━━
👥 Usuarios totales: `{stats.get('total_users', 0)}`
🕹️ Apuestas totales: `{stats.get('total_bets', 0)}`
💳 Depósitos totales: `{stats.get('total_deposits', 0)}`
📤 Retiros totales: `{stats.get('total_withdrawals', 0)}`
💰 Total ganado: `${stats.get('total_won', 0):.2f}`
💸 Total perdido: `${stats.get('total_lost', 0):.2f}`
"""

            edit_message(
                call,
                message_text,
                types.InlineKeyboardMarkup().row(
                    types.InlineKeyboardButton("🔙 Panel Admin", callback_data='admin')
                )
            )
            logging.info(f"Admin {user_id} viewed bot statistics.")
        else:
            answer_callback(call, "❌ No tienes permisos de administrador.", True)
            logging.warning(f"Unauthorized access attempt to bot statistics by user {user_id}")
    except Exception as e:
        logging.exception(f"Error showing admin statistics: {e}")

def ask_admin_for_user_to_block(call):
    """Asks the admin for the user ID to block."""
    try:
        user_id = call.from_user.id
        if user_id in ADMINS:
            user_states[user_id] = 'awaiting_user_id_to_block'
            bot.send_message(
                call.message.chat.id,
                "🔒 Ingresa el ID del usuario que deseas bloquear:",
                reply_markup=types.ForceReply(selective=True)
            )
            logging.info(f"Admin {user_id} initiated user blocking process.")
        else:
            answer_callback(call, "❌ No tienes permisos de administrador.", True)
            logging.warning(f"Unauthorized access attempt to block user by user {user_id}")
    except Exception as e:
        logging.exception(f"Error asking for user ID to block: {e}")

def ask_admin_for_user_to_unblock(call):
    """Asks the admin for the user ID to unblock."""
    try:
        user_id = call.from_user.id
        if user_id in ADMINS:
            user_states[user_id] = 'awaiting_user_id_to_unblock'
            bot.send_message(
                call.message.chat.id,
                "🔓 Ingresa el ID del usuario que deseas desbloquear:",
                reply_markup=types.ForceReply(selective=True)
            )
            logging.info(f"Admin {user_id} initiated user unblocking process.")
        else:
            answer_callback(call, "❌ No tienes permisos de administrador.", True)
            logging.warning(f"Unauthorized access attempt to unblock user by user {user_id}")
    except Exception as e:
        logging.exception(f"Error asking for user ID to unblock: {e}")

def handle_admin_decision(call):
    """Handles admin decisions on deposit and withdrawal requests."""
    try:
        user_id = call.from_user.id
        if user_id not in ADMINS:
            answer_callback(call, "❌ No tienes permisos de administrador.", True)
            return

        action, request_id = call.data.split('_', 1)
        request_id = int(request_id)

        if action == 'confirm': # Process deposit
            if request_id in deposit_requests:
                deposit_info = deposit_requests[request_id]
                amount = deposit_info['amount']
                user_id = deposit_info['user_id']
                username = deposit_info['username']

                # Update user balance (using celery task)
                balance = get_balance_task.result(user_id) # Await celery result
                update_balance_task.delay(user_id, balance + amount)

                # Notify the user
                bot.send_message(
                    user_id,
                    f"🎉 ¡Tu depósito de ${amount:.2f} ha sido confirmado!\n"
                    f"👤 Admin: @{call.from_user.username}"
                )
                del deposit_requests[request_id] # Delete the request
                edit_message(call, f"✅ Depósito #${request_id} confirmado.")

                logging.info(f"Deposit #{request_id} confirmed by admin {user_id}")

            else:
                answer_callback(call, "❌ Solicitud de depósito no encontrada.", True)

        elif action == 'approve': # Process withdrawal
            if request_id in withdraw_requests:
                withdraw_info = withdraw_requests[request_id]
                amount = withdraw_info['amount']
                user_id = withdraw_info['user_id']
                username = withdraw_info['username']

                # Update user balance (using celery task)
                balance = get_balance_task.result(user_id) # Await celery result

                if balance < amount:
                    bot.send_message(ADMINS[0], f"❌ Saldo insuficiente para retiro de ${amount} para @{username}")
                    return

                update_balance_task.delay(user_id, balance - amount)

                # Notify the user
                bot.send_message(
                    user_id,
                    f"🎉 ¡Tu retiro de ${amount:.2f} ha sido aprobado y procesado!\n"
                    f"👤 Admin: @{call.from_user.username}"
                )
                del withdraw_requests[request_id] # Delete the request
                edit_message(call, f"✅ Retiro #${request_id} aprobado.")
                logging.info(f"Withdrawal #{request_id} approved by admin {user_id}")
            else:
                answer_callback(call, "❌ Solicitud de retiro no encontrada.", True)

        elif action in ('reject', 'reject'): # Reject a request (deposit or withdrawal)
            if action == 'reject' and request_id in deposit_requests:
                del deposit_requests[request_id]
                edit_message(call, f"❌ Depósito #{request_id} rechazado.")
            elif action == 'reject' and request_id in withdraw_requests:
                 del withdraw_requests[request_id]
                 edit_message(call, f"❌ Retiro #{request_id} rechazado.")

            logging.info(f"Request #{request_id} rejected by admin {user_id}")

        else:
            logging.warning(f"Unknown admin action: {action}")

    except Exception as e:
        logging.exception(f"Error handling admin decision: {e}")

# ------ Message Handlers ------
@bot.message_handler(content_types=['text'])
def handle_text(message):
    """Handles text messages from users, primarily for deposit/withdrawal and custom bet amounts."""
    try:
        user_id = message.from_user.id
        text = message.text

        if user_id in user_states:
            state = user_states[user_id]

            if state == 'awaiting_deposit_phone':
                try:
                    # Validate phone number format (very basic)
                    if not text.startswith('+'):
                        bot.reply_to(message, "❌ El número de teléfono debe comenzar con '+' y el código de país.")
                        return

                    deposit_id = random.randint(100000, 999999)
                    deposit_requests[deposit_id] = {
                        'user_id': user_id,
                        'username': message.from_user.username,
                        'phone': text,
                        'amount': 0.0 # Placeholder, admin will set actual amount
                    }
                    del user_states[user_id] # Clear state

                    # Send to admin for confirmation
                    markup = types.InlineKeyboardMarkup()
                    markup.row(
                        types.InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{deposit_id}"),
                        types.InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{deposit_id}")
                    )
                    bot.send_message(
                        ADMINS[0],
                        f"""
💸 **NUEVO DEPÓSITO** #${deposit_id}
━━━━━━━━━━━━━━━━━━
👤 Usuario: @{message.from_user.username}
🆔 ID: `{user_id}`
📱 Teléfono: `{text}`
💰 Monto: _Pendiente_

⚠️ _Confirma el depósito y ajusta el monto._
""",
                        reply_markup=markup
                    )

                    bot.reply_to(
                        message,
                        "✅ ¡Solicitud de depósito enviada!\nEspera la confirmación de un administrador."
                    )

                    logging.info(f"Deposit request #{deposit_id} created by user {user_id}")

                except ValueError:
                    bot.reply_to(message, "❌ Formato de número de teléfono inválido. Intenta de nuevo.")
                except Exception as e:
                    bot.reply_to(message, "❌ Ocurrió un error al procesar la solicitud. Intenta de nuevo.")

            elif state == 'awaiting_withdrawal_phone':
                 try:
                    # Validate phone number format (very basic)
                    if not text.startswith('+'):
                        bot.reply_to(message, "❌ El número de teléfono debe comenzar con '+' y el código de país.")
                        return
                    withdraw_id = random.randint(100000, 999999)
                    withdraw_requests[withdraw_id] = {
                        'user_id': user_id,
                        'username': message.from_user.username,
                        'phone': text,
                        'amount': 0.0 # Placeholder, admin will set actual amount
                    }
                    del user_states[user_id]

                    # Send to admin for approval
                    markup = types.InlineKeyboardMarkup()
                    markup.row(
                        types.InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{withdraw_id}"),
                        types.InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{withdraw_id}")
                    )
                    bot.send_message(
                        ADMINS[0],
                        f"""
📤 **NUEVO RETIRO** #${withdraw_id}
━━━━━━━━━━━━━━━━━━
👤 Usuario: @{message.from_user.username}
🆔 ID: `{user_id}`
📱 Teléfono: `{text}`
💰 Monto: _Pendiente_

⚠️ _Aprueba el retiro y ajusta el monto._
""",
                        reply_markup=markup
                    )

                    bot.reply_to(
                        message,
                        "✅ ¡Solicitud de retiro enviada!\nEspera la aprobación de un administrador."
                    )

                    logging.info(f"Withdrawal request #{withdraw_id} created by user {user_id}")

                 except ValueError:
                    bot.reply_to(message, "❌ Formato de número de teléfono inválido. Intenta de nuevo.")
                 except Exception as e:
                    bot.reply_to(message, "❌ Ocurrió un error al procesar la solicitud. Intenta de nuevo.")

            elif state == 'awaiting_bet_amount':
                try:

                    # Check if the user is blocked
                    if is_user_blocked_task.result(user_id):
                        bot.reply_to(message, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.")
                        del user_states[user_id]
                        return

                    amount = float(text)
                    if not (MIN_BET <= amount <= MAX_BET):
                        bot.reply_to(message, f"❌ El monto debe estar entre ${MIN_BET} y ${MAX_BET}.")
                        return

                    # Get cached balance or load from db
                    balance_str = redis_client.get(f"user:{user_id}:balance")
                    if balance_str:
                        balance = float(balance_str.decode('utf-8'))
                    else:
                        balance = get_balance_task.result(user_id)
                        redis_client.setex(f"user:{user_id}:balance", 60, balance)  # cache it

                    if balance < amount:
                        bot.reply_to(message, f"❌ Saldo insuficiente! Necesitas ${amount}")
                        return

                    # Register the bet asynchronously
                    apuesta_id = register_apuesta_task.result(user_id, amount)

                    if apuesta_id is None:
                        bot.reply_to(message, "❌ Error al registrar la apuesta.")
                        return

                    nuevo_balance = balance - amount

                    # Update the balance asynchronously
                    update_balance_task.delay(user_id, nuevo_balance)
                    redis_client.setex(f"user:{user_id}:balance", 60, nuevo_balance) # Cache


                    # Update statistics
                    update_statistics_task.delay(user_id, False, amount)

                    # Process referral bonus (using celery task)
                    process_referral_bonus_task.delay(user_id, amount, message.from_user.username)


                    # Start the game
                    with game.lock:
                        game.participants[user_id] = {'apuesta_id': apuesta_id, 'amount': amount}

                    if not game.round_active:
                        game.start_round()
                    else:
                        try:
                            msg = bot.send_message(
                                user_id,
                                game.generate_game_text(user_id),
                                reply_markup=game.generate_game_buttons()
                            )
                            with game.lock:
                                game.message_ids[user_id] = msg.message_id
                        except Exception as e:
                            logging.exception(f"Error joining round: {e}")

                    bot.reply_to(
                        message,
                        f"""
🎰 **APUESTA CONFIRMADA!** ✅
━━━━━━━━━━━━━━━━━━
💰 Monto apostado: `${amount}`
📈 Multiplicador actual: `1.0x`
🏆 Ganancia potencial: `${amount * 1.0:.2f}`

🚀 El juego está comenzando...
""",
                        reply_markup=types.InlineKeyboardMarkup().row(
                            types.InlineKeyboardButton("🔄 Actualizar", callback_data='refresh')
                        )
                    )

                except ValueError:
                    bot.reply_to(message, "❌ Monto inválido. Ingresa un número.")
                except Exception as e:
                    logging.exception(f"Error handling custom bet amount: {e}")

                finally:
                    del user_states[user_id]  # Clear state
            elif state == 'awaiting_user_id_to_block':
                try:
                    user_to_block = int(text)
                    if block_user_task.result(user_to_block):
                        bot.reply_to(message, f"✅ Usuario {user_to_block} bloqueado correctamente.")
                        logging.info(f"Admin {user_id} blocked user {user_to_block}.")
                    else:
                        bot.reply_to(message, f"❌ No se pudo bloquear al usuario {user_to_block}.")
                        logging.warning(f"Admin {user_id} failed to block user {user_to_block}.")
                except ValueError:
                    bot.reply_to(message, "❌ ID de usuario inválido. Ingresa un número entero.")
                except Exception as e:
                    logging.exception(f"Error blocking user: {e}")
                finally:
                    del user_states[user_id]

            elif state == 'awaiting_user_id_to_unblock':
                try:
                    user_to_unblock = int(text)
                    if unblock_user_task.result(user_to_unblock):
                        bot.reply_to(message, f"✅ Usuario {user_to_unblock} desbloqueado correctamente.")
                        logging.info(f"Admin {user_id} unblocked user {user_to_unblock}.")
                    else:
                        bot.reply_to(message, f"❌ No se pudo desbloquear al usuario {user_to_unblock}.")
                        logging.warning(f"Admin {user_id} failed to unblock user {user_to_unblock}.")
                except ValueError:
                    bot.reply_to(message, "❌ ID de usuario inválido. Ingresa un número entero.")
                except Exception as e:
                    logging.exception(f"Error unblocking user: {e}")
                finally:
                    del user_states[user_id]

            else:
                logging.warning(f"Unknown user state: {state}")
        else:
            if message.chat.type == 'private': # Only respond to direct messages
                # Check if the user is blocked
                if is_user_blocked_task.result(user_id):
                    bot.reply_to(message, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.")
                    return
                bot.reply_to(message, "🤔 Comando desconocido. Usa /start para ver las opciones.")
            else:
                logging.info(f"Ignoring message in group chat {message.chat.id}.") # Ignore group messages

    except Exception as e:
        logging.exception(f"Error handling text message: {e}")

# ------ Game Actions ------
def cash_out(call):
    """Handles the cash out action for the user."""
    try:
        user_id = call.from_user.id

        # Check if the user is blocked
        if is_user_blocked_task.result(user_id):
            answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
            return

        with game.lock:
            if user_id not in game.participants:
                answer_callback(call, "❌ No estás participando en esta ronda.", True)
                return

            apuesta_id = game.participants[user_id]['apuesta_id']
            multiplier = game.multiplier

            update_apuesta_task.delay(apuesta_id, multiplier)

            with Session() as session:
                apuesta = session.query(Apuesta).filter_by(id=apuesta_id).first()
                amount = apuesta.amount * multiplier

            # Update user balance (using celery task)
            balance = get_balance_task.result(user_id) # Await celery result
            update_balance_task.delay(user_id, balance + amount)

            # Update statistics (won)
            update_statistics_task.delay(user_id, True, amount) # Using celery task

            bot.send_message(
                user_id,
                f"🎉 **RETIRADO!**\n"
                f"💰 Ganaste: `${amount:.2f}` en `{multiplier}x`"
            )

            game.remove_participant(user_id)

            edit_message(
                call,
                f"🎉 **RETIRADO!** Ganaste: `${amount:.2f}`",
                types.InlineKeyboardMarkup().row(
                    types.InlineKeyboardButton("🔄 Nueva Apuesta", callback_data='newbet')
                )
            )
    except Exception as e:
        logging.exception(f"Error handling cashout: {e}")

# ------ Utility Functions ------
def answer_callback(call, text: str, show_alert: bool = False):
    """Answers a callback query with a notification."""
    try:
        bot.answer_callback_query(call.id, text, show_alert=show_alert)
    except Exception as e:
        logging.error(f"Error answering callback: {e}")

def edit_message(call, text: str, reply_markup=None, parse_mode='Markdown'):
    """Edits the message associated with the callback query."""
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logging.error(f"Error editing message: {e}")

def handle_refresh(call):
    """Refreshes the current message."""
    try:
        if call.data == 'refresh':
            if call.message:
                user_id = call.from_user.id

                # Check if the user is blocked
                if is_user_blocked_task.result(user_id):
                    answer_callback(call, "❌ Lo siento, has sido bloqueado y no puedes usar este bot.", True)
                    return

                # Retrieve balance (use Redis cache if available)
                balance_str = redis_client.get(f"user:{user_id}:balance")
                if balance_str:
                    balance = float(balance_str.decode('utf-8'))  # decode from bytes
                else:
                    balance = get_balance_task.result(user_id)  # Await from Celery
                    redis_client.setex(f"user:{user_id}:balance", 60, balance)  # Cache

                markup = types.InlineKeyboardMarkup()
                markup.row(types.InlineKeyboardButton("🎮 JUGAR AHORA", callback_data='play'))
                markup.row(types.InlineKeyboardButton("📚 TUTORIAL", callback_data='tutorial'))
                markup.row(types.InlineKeyboardButton("💳 DEPOSITAR", callback_data='deposit'))
        markup.row(types.InlineKeyboardButton("📤 RETIRAR", callback_data='withdraw'))
        markup.row(types.InlineKeyboardButton("💎 MIS ESTADÍSTICAS", callback_data='stats'))
        markup.row(types.InlineKeyboardButton("🏆 LÍDERES", callback_data='leaders'))
        markup.row(types.InlineKeyboardButton("👥 REFERIDOS", callback_data='referrals'))

        bot.edit_message_text(
          chat_id=call.message.chat.id,
          message_id=call.message.message_id,
          text=f"""
✨ BIENVENIDO A AVIASTAR BOT ✨
━━━━━━━━━━━━━━━━━━━━━━
✅ El bot OFICIAL del juego Aviator con:
➼ Retiros instantáneos
➼ Soporte 24/7
➼ Máxima seguridad

💰 Balance: ${balance:.2f}
🚀 ¡Comienza a ganar ahora mismo!
""",
          parse_mode='Markdown',
          reply_markup=markup
        )
    except Exception as e:
        logging.exception(f"Error handling refresh: {e}")

# ------ Polling ------
if __name__ == '__main__':
  try:
    logging.info("Starting bot...")
    bot.infinity_polling()
  except Exception as e:
    logging.critical(f"Bot failed to start: {e}")
