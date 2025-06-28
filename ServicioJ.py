import telebot
from telebot import types
import os
import sqlite3
import logging
from dotenv import load_dotenv
from datetime import datetime, date, timedelta
import calendar

# --- Configuración ---
load_dotenv("config.env")
TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
DATABASE_NAME = "servicej.db"
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "YOUR_ADMIN_CHAT_ID")  # Add admin chat ID to .env
LOG_GROUP_ID = os.environ.get("LOG_GROUP_ID", "YOUR_LOG_GROUP_ID")  # Add log group chat ID to .env

# --- Datos Iniciales ---
USUARIOS_INICIALES = [
    ("Pauly", "Pauly", "Pauly"),
    ("Enrique", "Enrique", "Enrique"),
    ("Quiosco", "Quiosco", "Quiosco"),
    ("Admin", "Admin", "Admin")
]

PRODUCTOS_INICIALES = [
    ("Pasta Dental", 360, 500),
    ("Desodorante Kewell", 320, 500),
    ("Desodorante Rexona", 540, 750),
    ("Detergente STB 500g", 430, 540),
    ("Jabon 110g", 130, 180),
    ("Champú + Acondicionador", 1100, 1500),
    ("Toallitas Humedas 120u", 900, 1100),
]

INVENTARIO_INICIAL = [
    (1, 1, 50),
    (1, 2, 50),
    (1, 3, 50),
    (1, 4, 50),
    (1, 5, 50),
    (1, 6, 50),
    (1, 7, 50),

    (2, 1, 30),
    (2, 2, 30),
    (2, 3, 30),
    (2, 4, 30),
    (2, 5, 30),
    (2, 6, 30),
    (2, 7, 30),

    (3, 1, 5),
    (3, 2, 5),
    (3, 3, 4),
    (3, 5, 5),
    (3, 6, 2),
    (3, 7, 5),
]

# --- Configuración del Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Funciones de la Base de Datos ---
def create_database():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vendedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                contrasena TEXT NOT NULL,
                nombre TEXT NOT NULL,
                es_admin INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                precio_compra REAL NOT NULL,
                precio_venta REAL NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventario (
                vendedor_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                cantidad_entregada INTEGER NOT NULL,
                FOREIGN KEY (vendedor_id) REFERENCES vendedores (id),
                FOREIGN KEY (producto_id) REFERENCES productos (id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendedor_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                cantidad_vendida INTEGER NOT NULL,
                comision REAL NOT NULL,
                fecha TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
                FOREIGN KEY (vendedor_id) REFERENCES vendedores (id),
                FOREIGN KEY (producto_id) REFERENCES productos (id)
            )
        """)


        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sesiones (
                chat_id INTEGER PRIMARY KEY,
                vendedor_id INTEGER NOT NULL,
                fecha_inicio DATE NOT NULL
            )
        """)

        conn.commit()
        log_message = "Base de datos y tablas creadas o ya existentes."
        logging.info(log_message)
        send_log_to_group(log_message)
        conn.close()

    except sqlite3.Error as e:
        log_message = f"Error al crear la base de datos: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        raise

def insertar_datos_iniciales():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        for usuario, contrasena, nombre in USUARIOS_INICIALES:
            try:
                es_admin = 1 if usuario == "Admin" else 0
                cursor.execute("INSERT INTO vendedores (usuario, contrasena, nombre, es_admin) VALUES (?, ?, ?, ?)", (usuario, contrasena, nombre, es_admin))
            except sqlite3.IntegrityError:
                log_message = f"El vendedor {usuario} ya existe."
                logging.warning(log_message)
                send_log_to_group(log_message)

        for nombre, precio_compra, precio_venta in PRODUCTOS_INICIALES:
             try:
                cursor.execute("INSERT INTO productos (nombre, precio_compra, precio_venta) VALUES (?, ?, ?)", (nombre, precio_compra, precio_venta))
             except sqlite3.IntegrityError:
                log_message = f"El producto {nombre} ya existe."
                logging.warning(log_message)
                send_log_to_group(log_message)

        for vendedor_id, producto_id, cantidad_entregada in INVENTARIO_INICIAL:
             try:
                cursor.execute("INSERT INTO inventario (vendedor_id, producto_id, cantidad_entregada) VALUES (?, ?, ?)", (vendedor_id, producto_id, cantidad_entregada))
             except sqlite3.IntegrityError:
                log_message = f"El inventario para el vendedor {vendedor_id} y producto {producto_id} ya existe."
                logging.warning(log_message)
                send_log_to_group(log_message)


        conn.commit()
        log_message = "Datos iniciales insertados en la base de datos."
        logging.info(log_message)
        send_log_to_group(log_message)
        conn.close()

    except sqlite3.Error as e:
        log_message = f"Error al insertar datos iniciales: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        conn.rollback()
        conn.close()

def get_vendedor(usuario):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre, contrasena, es_admin FROM vendedores WHERE usuario = ?", (usuario,))
        result = cursor.fetchone()
        conn.close()
        return result
    except sqlite3.Error as e:
        log_message = f"Error al obtener vendedor: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return None

def get_productos():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre FROM productos")
        result = cursor.fetchall()
        conn.close()
        return result
    except sqlite3.Error as e:
        log_message = f"Error al obtener productos: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return []

def get_producto(producto_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT precio_compra, precio_venta, nombre FROM productos WHERE id = ?", (producto_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    except sqlite3.Error as e:
        log_message = f"Error al obtener producto: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return None

def get_inventario(vendedor_id, producto_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT cantidad_entregada FROM inventario WHERE vendedor_id = ? AND producto_id = ?", (vendedor_id, producto_id))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    except sqlite3.Error as e:
        log_message = f"Error al obtener inventario: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return 0

def registrar_venta(vendedor_id, producto_id, cantidad_vendida):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        cursor.execute("SELECT precio_compra, precio_venta, nombre FROM productos WHERE id = ?", (producto_id,))
        producto = cursor.fetchone()

        if producto:
            precio_compra = producto[0]
            precio_venta = producto[1]
            nombre_producto = producto[2]  # Get product name
            ganancia_por_unidad = precio_venta - precio_compra
            comision_vendedor = 0.20 * ganancia_por_unidad * cantidad_vendida

            cursor.execute("INSERT INTO ventas (vendedor_id, producto_id, cantidad_vendida, comision) VALUES (?, ?, ?, ?)",
                           (vendedor_id, producto_id, cantidad_vendida, comision_vendedor))

            cursor.execute("UPDATE inventario SET cantidad_entregada = cantidad_entregada - ? WHERE vendedor_id = ? AND producto_id = ?",
                           (cantidad_vendida, vendedor_id, producto_id))

            conn.commit()
            log_message = f"Venta registrada: Vendedor {vendedor_id}, Producto {nombre_producto}, Cantidad {cantidad_vendida}, Comisión: ${comision_vendedor:.2f}"
            logging.info(log_message)
            send_log_to_group(log_message)

            # Notify admin
            vendedor_info = get_vendedor_by_id(vendedor_id)
            vendedor_nombre = vendedor_info[1] if vendedor_info else "Unknown"
            notification_message = (f"Nueva venta registrada:\n"
                                    f"Vendedor: {vendedor_nombre} (ID: {vendedor_id})\n"
                                    f"Producto: {nombre_producto} (ID: {producto_id})\n"
                                    f"Cantidad: {cantidad_vendida}\n"
                                    f"Comisión del vendedor: ${comision_vendedor:.2f}")
            try:
                bot.send_message(ADMIN_CHAT_ID, notification_message)
            except telebot.apihelper.ApiTelegramException as e:
                log_message = f"Error sending message to admin: {e}"
                logging.error(log_message)
                send_log_to_group(log_message)
            
            # Notificar al vendedor
            try:
                mensaje_vendedor = (f"✅ Venta registrada:\n"
                                    f"Producto: {nombre_producto}\n"
                                    f"Cantidad: {cantidad_vendida}\n"
                                    f"Comisión: ${comision_vendedor:.2f}\n\n"
                                    f"¡Buen trabajo {vendedor_nombre}! 💪")
                bot.send_message(LOG_GROUP_ID, mensaje_vendedor)  # Enviar al grupo de log
            except Exception as e:
                log_message = f"Error notificando al vendedor: {e}"
                logging.error(log_message)
                send_log_to_group(log_message)

            return True
        else:
            log_message = f"Producto con ID {producto_id} no encontrado."
            logging.error(log_message)
            send_log_to_group(log_message)
            conn.close()
            return False

    except sqlite3.Error as e:
        log_message = f"Error al registrar venta: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        conn.rollback()
        conn.close()
        return False

def obtener_ventas_diarias(vendedor_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.nombre, SUM(v.cantidad_vendida), SUM(p.precio_venta * v.cantidad_vendida), SUM(v.comision), p.id
            FROM ventas v
            JOIN productos p ON v.producto_id = p.id
            WHERE v.vendedor_id = ? AND DATE(v.fecha) = DATE('now')
            GROUP BY p.nombre
        """, (vendedor_id,))
        result = cursor.fetchall()
        conn.close()
        return result
    except sqlite3.Error as e:
        log_message = f"Error al obtener ventas diarias: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return []

def obtener_cantidad_disponible(vendedor_id, producto_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT cantidad_entregada FROM inventario WHERE vendedor_id = ? AND producto_id = ?", (vendedor_id, producto_id))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    except sqlite3.Error as e:
        log_message = f"Error al obtener cantidad disponible: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return 0

def crear_sesion(chat_id, vendedor_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sesiones (chat_id, vendedor_id, fecha_inicio) VALUES (?, ?, ?)",
                       (chat_id, vendedor_id, date.today()))
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        log_message = f"Error al crear la sesión: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        conn.rollback()
        conn.close()
        return False

def verificar_sesion_activa(chat_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        # Elimina la restricción de fecha para mantener la sesión activa indefinidamente
        cursor.execute("SELECT vendedor_id FROM sesiones WHERE chat_id = ?", (chat_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except sqlite3.Error as e:
        log_message = f"Error al verificar la sesión: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return None

def cerrar_sesion(chat_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sesiones WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        log_message = f"Error al cerrar la sesión: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        conn.rollback()
        conn.close()
        return False

def get_vendedor_by_id(vendedor_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre, es_admin FROM vendedores WHERE id = ?", (vendedor_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    except sqlite3.Error as e:
        log_message = f"Error al obtener vendedor por ID: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return None

def get_all_vendedores():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre FROM vendedores WHERE es_admin = 0")
        vendedores = cursor.fetchall()
        conn.close()
        return vendedores
    except sqlite3.Error as e:
        log_message = f"Error al obtener todos los vendedores: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return []

def get_total_daily_sales():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(p.precio_venta * v.cantidad_vendida)
            FROM ventas v
            JOIN productos p ON v.producto_id = p.id
            WHERE DATE(v.fecha) = DATE('now')
        """)
        total = cursor.fetchone()[0] or 0
        conn.close()
        return total
    except sqlite3.Error as e:
        log_message = f"Error al obtener el total de ventas diarias: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return 0

def get_daily_sales_and_profit(vendedor_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                SUM(p.precio_venta * v.cantidad_vendida) AS ventas_diarias,
                SUM((p.precio_venta - p.precio_compra) * v.cantidad_vendida) AS ganancias_diarias,
                SUM(v.comision) AS comisiones_totales
            FROM ventas v
            JOIN productos p ON v.producto_id = p.id
            WHERE v.vendedor_id = ? AND DATE(v.fecha) = DATE('now')
        """, (vendedor_id,))

        result = cursor.fetchone()
        conn.close()

        ventas_diarias = result[0] if result and result[0] is not None else 0
        ganancias_diarias = result[1] if result and result[1] is not None else 0
        comisiones_totales = result[2] if result and result[2] is not None else 0

        return ventas_diarias, ganancias_diarias, comisiones_totales

    except sqlite3.Error as e:
        log_message = f"Error al obtener ventas diarias y ganancias: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return 0, 0, 0


def get_inventory_data():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                v.nombre AS vendedor,
                p.nombre AS producto,
                i.cantidad_entregada AS cantidad_disponible
            FROM inventario i
            JOIN vendedores v ON i.vendedor_id = v.id
            JOIN productos p ON i.producto_id = p.id
        """)

        inventory_data = cursor.fetchall()
        conn.close()
        return inventory_data
    except sqlite3.Error as e:
        log_message = f"Error al obtener datos del inventario: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return []

def get_all_sales_data():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                v.fecha,
                p.nombre AS producto,
                s.nombre AS vendedor,
                v.cantidad_vendida,
                p.precio_venta,
                (p.precio_venta * v.cantidad_vendida) AS total,
                v.comision
            FROM ventas v
            JOIN productos p ON v.producto_id = p.id
            JOIN vendedores s ON v.vendedor_id = s.id
            ORDER BY v.fecha DESC
        """)

        sales_data = cursor.fetchall()
        conn.close()
        return sales_data
    except sqlite3.Error as e:
        log_message = f"Error al obtener datos de todas las ventas: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return []

def get_sales_summary(vendedor_id, time_period):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        if time_period == 'daily':
            date_condition = "DATE(v.fecha) = DATE('now')"
        elif time_period == 'weekly':
            # Considerar la semana como de lunes a domingo
            date_condition = "DATE(v.fecha) BETWEEN DATE('now', 'weekday 0', '-7 days') AND DATE('now', 'weekday 0', '-1 days')"
        elif time_period == 'monthly':
            date_condition = "STRFTIME('%Y-%m', v.fecha) = STRFTIME('%Y-%m', 'now')"
        else:
            log_message = "Invalid time period provided to get_sales_summary"
            logging.warning(log_message)
            send_log_to_group(log_message)
            return 0, 0, 0  # Invalid time period

        cursor.execute(f"""
            SELECT
                SUM(p.precio_venta * v.cantidad_vendida) AS total_sales,
                SUM((p.precio_venta - p.precio_compra) * v.cantidad_vendida) AS total_profit,
                SUM(v.comision) AS total_commission
            FROM ventas v
            JOIN productos p ON v.producto_id = p.id
            WHERE v.vendedor_id = ? AND {date_condition}
        """, (vendedor_id,))

        result = cursor.fetchone()
        conn.close()

        if result:
            total_sales = result[0] if result[0] is not None else 0
            total_profit = result[1] if result[1] is not None else 0
            total_commission = result[2] if result[2] is not None else 0
        else:
            total_sales, total_profit, total_commission = 0, 0, 0

        return total_sales, total_profit, total_commission

    except sqlite3.Error as e:
        log_message = f"Error al obtener el resumen de ventas ({time_period}): {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return 0, 0, 0

# Nueva función para obtener el inventario de un vendedor
def obtener_inventario_vendedor(vendedor_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.nombre, i.cantidad_entregada
            FROM inventario i
            JOIN productos p ON i.producto_id = p.id
            WHERE i.vendedor_id = ?
        """, (vendedor_id,))
        inventario = cursor.fetchall()
        conn.close()
        return inventario
    except sqlite3.Error as e:
        log_message = f"Error al obtener inventario del vendedor: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return []

# Nueva función para actualizar inventario (sumar)
def actualizar_inventario(vendedor_id, producto_id, cantidad):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        # Verificar si existe el registro
        cursor.execute("SELECT cantidad_entregada FROM inventario WHERE vendedor_id = ? AND producto_id = ?", (vendedor_id, producto_id))
        result = cursor.fetchone()
        if result:
            nueva_cantidad = result[0] + cantidad
            cursor.execute("UPDATE inventario SET cantidad_entregada = ? WHERE vendedor_id = ? AND producto_id = ?", 
                           (nueva_cantidad, vendedor_id, producto_id))
        else:
            cursor.execute("INSERT INTO inventario (vendedor_id, producto_id, cantidad_entregada) VALUES (?, ?, ?)", 
                           (vendedor_id, producto_id, cantidad))
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        log_message = f"Error al actualizar inventario: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        return False

# --- Funciones de Log ---
def send_log_to_group(message):
    try:
        bot.send_message(LOG_GROUP_ID, message)
    except telebot.apihelper.ApiTelegramException as e:
        logging.error(f"Error al enviar el mensaje de log al grupo: {e}")

# --- Inicialización del Bot ---
bot = telebot.TeleBot(TOKEN)

# --- Estados ---
USUARIO = {}
VENTA = {}
MENSAJES = {}
GESTION_INVENTARIO = {}  # Nuevo estado para gestionar el flujo de inventario

# --- Textos de Bienvenida Personalizados ---
MENSAJES_BIENVENIDA = {
    1: """
    ¡Hola Pauly! 👋\n
    ¡Listo para un día de ventas exitosas? 🚀\n
    ¡Vamos a superar esos objetivos! 💪
    """,
    2: """
    ¡Hola Enrique! 👋\n
    ¡A brillar hoy! ✨\n
    ¡Cada venta te acerca a tus sueños! 🌟
    """,
    3: """
    ¡Hola Quiosco! 👋\n
    Aquí podrás anotar todas tus ventas 📝\n
    y llevar un mejor control. 📊
    """,
}

# --- Handlers ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    vendedor_id_sesion = verificar_sesion_activa(chat_id)

    if vendedor_id_sesion:
        vendedor_info = get_vendedor_by_id(vendedor_id_sesion)
        if vendedor_info:
            nombre_vendedor = vendedor_info[1]
            es_admin = vendedor_info[2]
            USUARIO[chat_id] = {"estado": "logeado", "vendedor_id": vendedor_id_sesion, "nombre": nombre_vendedor, "es_admin": es_admin}
            mostrar_menu_principal(message)
            return

    markup = types.InlineKeyboardMarkup()
    boton_inicio_sesion = types.InlineKeyboardButton("¡Inicia Sesión y Comienza a Ganar! 🔑", callback_data='inicio_sesion')
    markup.add(boton_inicio_sesion)

    mensaje_bienvenida = """
    ¡Bienvenido a ServiceJ Bot! 👋\n
    Aquí puedes registrar tus ventas diarias. 📝\n
    ¡Impulsa tus ganancias, cada venta cuenta! 🚀
    """
    # Usar send_message y guardar el message_id
    try:
        msg = bot.send_message(chat_id, mensaje_bienvenida, reply_markup=markup)
        MENSAJES[chat_id] = msg.message_id
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Error sending start message: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)


@bot.callback_query_handler(func=lambda call: call.data == 'inicio_sesion')
def inicio_sesion(call):
    chat_id = call.message.chat.id
    USUARIO[chat_id] = {"estado": "esperando_usuario", "vendedor_id": None, "nombre": None, "es_admin": 0}
    markup = types.InlineKeyboardMarkup()  # Keyboard markup
    #markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_inicio'))
    try:
        bot.edit_message_text("Por favor, ingresa tu usuario 👤:", chat_id, MENSAJES.get(chat_id), reply_markup = markup)
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Error editing message: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        bot.send_message(chat_id, "Por favor, ingresa tu usuario 👤:", reply_markup=markup) #Fallback

@bot.message_handler(func=lambda message: USUARIO.get(message.chat.id, {}).get("estado") == "esperando_usuario")
def recibir_usuario(message):
    chat_id = message.chat.id
    usuario = message.text
    vendedor = get_vendedor(usuario)
    if vendedor:
        USUARIO[chat_id]["vendedor_id"] = vendedor[0]
        USUARIO[chat_id]["nombre"] = vendedor[1]
        USUARIO[chat_id]["contrasena"] = vendedor[2]
        USUARIO[chat_id]["es_admin"] = vendedor[3]
        USUARIO[chat_id]["estado"] = "esperando_contrasena"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_inicio'))
        # Eliminar el mensaje anterior antes de enviar uno nuevo
        try:
            bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Failed to delete message: {e}"
            logging.warning(log_message)
            send_log_to_group(log_message)
        msg = bot.send_message(chat_id, "Usuario correcto ✅. ¡Ingresa tu contraseña para acceder! 🔒:", reply_markup = markup)
        MENSAJES[chat_id] = msg.message_id
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_inicio'))

        # Eliminar el mensaje anterior antes de enviar uno nuevo
        try:
            bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Failed to delete message: {e}"
            logging.warning(log_message)
            send_log_to_group(log_message)

        msg = bot.send_message(chat_id, "Usuario incorrecto ❌. Intenta de nuevo o contacta al administrador.", reply_markup = markup)
        MENSAJES[chat_id] = msg.message_id
    try:
        bot.delete_message(chat_id=message.chat.id, message_id=message.message_id) #Delete the message sent by the user
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Failed to delete message: {e}"
        logging.warning(log_message)
        send_log_to_group(log_message)

@bot.message_handler(func=lambda message: USUARIO.get(message.chat.id, {}).get("estado") == "esperando_contrasena")
def recibir_contrasena(message):
    chat_id = message.chat.id
    contrasena = message.text
    if USUARIO[chat_id]["contrasena"] == contrasena:
        vendedor_id = USUARIO[chat_id]["vendedor_id"]
        crear_sesion(chat_id, vendedor_id)
        del USUARIO[chat_id]["contrasena"]
        USUARIO[chat_id]["estado"] = "logeado"
        mostrar_menu_principal(message)
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_inicio'))

        # Eliminar el mensaje anterior antes de enviar uno nuevo
        try:
            bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Failed to delete message: {e}"
            logging.warning(log_message)
            send_log_to_group(log_message)

        msg = bot.send_message(chat_id, "Contraseña incorrecta ❌. Intenta de nuevo.", reply_markup = markup)
        MENSAJES[chat_id] = msg.message_id
    try:
        bot.delete_message(chat_id=message.chat.id, message_id=message.message_id) #Delete the message sent by the user
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Failed to delete message: {e}"
        logging.warning(log_message)
        send_log_to_group(log_message)

@bot.callback_query_handler(func=lambda call: call.data == 'volver_inicio')
def volver_inicio(call):
    chat_id = call.message.chat.id
    USUARIO[chat_id] = {}
    cmd_start(call.message)

def mostrar_menu_principal(message):
    chat_id = message.chat.id
    vendedor_id = USUARIO[chat_id]["vendedor_id"]
    nombre_vendedor = USUARIO[chat_id]["nombre"]
    es_admin = USUARIO[chat_id]["es_admin"]

    mensaje_bienvenida = MENSAJES_BIENVENIDA.get(vendedor_id, f"""
    ¡Hola {nombre_vendedor}! 👋\n
    ¡Listo para superar tus objetivos de hoy? 💪
    """)

    markup = types.InlineKeyboardMarkup()
    boton_venta = types.InlineKeyboardButton("Registrar Venta 💰", callback_data='venta')
    boton_historial = types.InlineKeyboardButton("Ver Historial Diario 📊", callback_data='historial')
    boton_cerrar_sesion = types.InlineKeyboardButton("Cerrar Sesión 🚪", callback_data='cerrar_sesion') # Nuevo botón
    markup.add(boton_venta, boton_historial)
    markup.add(boton_cerrar_sesion) # Añade el botón de cerrar sesión al menú

    if es_admin:
        boton_admin = types.InlineKeyboardButton("Panel de Admin ⚙️", callback_data='admin_panel')
        markup.add(boton_admin)

    try:
        #bot.edit_message_text(mensaje_bienvenida + "\nSelecciona una opción para continuar:", chat_id, MENSAJES.get(chat_id), reply_markup=markup)
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Error al editar mensaje: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
        # Fallback: Enviar un nuevo mensaje si falla la edición
    msg = bot.send_message(chat_id, mensaje_bienvenida + "\nSelecciona una opción para continuar:", reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id


@bot.callback_query_handler(func=lambda call: call.data == 'admin_panel' and USUARIO.get(call.message.chat.id, {}).get("es_admin") == 1)
def mostrar_panel_admin(call):
    chat_id = call.message.chat.id

    # Total de ventas diarias de todos los vendedores
    total_ventas_diarias = get_total_daily_sales()

    # Botones para cada vendedor
    markup = types.InlineKeyboardMarkup()
    vendedores = get_all_vendedores()

    for vendedor_id, nombre_vendedor in vendedores:
        boton_vendedor = types.InlineKeyboardButton(nombre_vendedor, callback_data=f'vendedor_info_{vendedor_id}')
        markup.add(boton_vendedor)

    # Inventario disponible y tabla completa de ventas (inicialmente ocultos)
    boton_inventario = types.InlineKeyboardButton("Mostrar Inventario Disponible", callback_data='mostrar_inventario')
    boton_ventas = types.InlineKeyboardButton("Mostrar Tabla de Ventas", callback_data='mostrar_ventas')
    boton_gestion_inventario = types.InlineKeyboardButton("📦 Gestión de Inventario", callback_data='gestion_inventario')  # Nuevo botón

    # Botones de resumen de ventas diarias, semanales y mensuales
    boton_resumen_diario = types.InlineKeyboardButton("Resumen Diario", callback_data='resumen_diario')
    boton_resumen_semanal = types.InlineKeyboardButton("Resumen Semanal", callback_data='resumen_semanal')
    boton_resumen_mensual = types.InlineKeyboardButton("Resumen Mensual", callback_data='resumen_mensual')

    markup.add(boton_inventario)
    markup.add(boton_ventas)
    markup.add(boton_gestion_inventario)  # Añadido el botón de gestión de inventario
    markup.add(boton_resumen_diario, boton_resumen_semanal, boton_resumen_mensual)

    markup.add(types.InlineKeyboardButton("Volver al menú principal", callback_data='volver_menu'))

    mensaje = f"📊 Panel de Administración ⚙️\n\n"
    mensaje += f"💰 Total de Ventas Diarias (Todos los Vendedores): ${total_ventas_diarias:.2f}\n\n"
    mensaje += "Selecciona un vendedor para ver sus estadísticas:\n"

    try:
        #bot.edit_message_text(mensaje, chat_id, MENSAJES.get(chat_id), reply_markup=markup)
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Error editing message: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
    msg = bot.send_message(chat_id, mensaje, reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'gestion_inventario')
def gestion_inventario(call):
    chat_id = call.message.chat.id
    markup = types.InlineKeyboardMarkup()
    boton_anadir = types.InlineKeyboardButton("➕ Añadir Inventario", callback_data='anadir_inventario')
    boton_ver = types.InlineKeyboardButton("👀 Ver Inventario por Vendedor", callback_data='ver_inventario_vendedor')
    boton_volver = types.InlineKeyboardButton("🔙 Volver", callback_data='admin_panel')
    markup.add(boton_anadir, boton_ver)
    markup.add(boton_volver)
    
    try:
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except:
        pass
        
    msg = bot.send_message(chat_id, "📦 Gestión de Inventario\n\nSelecciona una opción:", reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'anadir_inventario')
def anadir_inventario(call):
    chat_id = call.message.chat.id
    GESTION_INVENTARIO[chat_id] = {"estado": "seleccion_vendedor"}
    markup = types.InlineKeyboardMarkup()
    vendedores = get_all_vendedores()
    
    for vendedor_id, nombre_vendedor in vendedores:
        boton_vendedor = types.InlineKeyboardButton(nombre_vendedor, callback_data=f'inv_vendedor_{vendedor_id}')
        markup.add(boton_vendedor)
        
    boton_volver = types.InlineKeyboardButton("🔙 Volver", callback_data='gestion_inventario')
    markup.add(boton_volver)
    
    try:
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except:
        pass
        
    msg = bot.send_message(chat_id, "Selecciona un vendedor para añadir inventario:", reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('inv_vendedor_'))
def seleccionar_vendedor_inventario(call):
    chat_id = call.message.chat.id
    vendedor_id = int(call.data.split('_')[2])
    GESTION_INVENTARIO[chat_id] = {
        "estado": "seleccion_producto",
        "vendedor_id": vendedor_id
    }
    
    markup = types.InlineKeyboardMarkup()
    productos = get_productos()
    
    for producto_id, nombre_producto in productos:
        boton_producto = types.InlineKeyboardButton(nombre_producto, callback_data=f'inv_producto_{producto_id}')
        markup.add(boton_producto)
        
    boton_volver = types.InlineKeyboardButton("🔙 Volver", callback_data='anadir_inventario')
    markup.add(boton_volver)
    
    try:
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except:
        pass
        
    msg = bot.send_message(chat_id, "Selecciona un producto:", reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('inv_producto_'))
def seleccionar_producto_inventario(call):
    chat_id = call.message.chat.id
    producto_id = int(call.data.split('_')[2])
    GESTION_INVENTARIO[chat_id]["producto_id"] = producto_id
    GESTION_INVENTARIO[chat_id]["estado"] = "esperando_cantidad"
    
    producto = get_producto(producto_id)
    nombre_producto = producto[2] if producto else "Producto"
    
    try:
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except:
        pass
        
    msg = bot.send_message(chat_id, f"Ingresa la cantidad de {nombre_producto} a añadir:")
    MENSAJES[chat_id] = msg.message_id

@bot.message_handler(func=lambda message: GESTION_INVENTARIO.get(message.chat.id, {}).get("estado") == "esperando_cantidad")
def recibir_cantidad_inventario(message):
    chat_id = message.chat.id
    cantidad = message.text
    
    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(chat_id, "❌ Cantidad inválida. Debe ser un número entero positivo.")
        return
    
    vendedor_id = GESTION_INVENTARIO[chat_id]["vendedor_id"]
    producto_id = GESTION_INVENTARIO[chat_id]["producto_id"]
    
    if actualizar_inventario(vendedor_id, producto_id, cantidad):
        vendedor_info = get_vendedor_by_id(vendedor_id)
        nombre_vendedor = vendedor_info[1] if vendedor_info else "Desconocido"
        producto = get_producto(producto_id)
        nombre_producto = producto[2] if producto else "Desconocido"
        
        bot.send_message(chat_id, f"✅ Se añadieron {cantidad} unidades de {nombre_producto} al inventario de {nombre_vendedor}.")
        # Notificar al grupo de log
        mensaje_log = f"📦 Inventario actualizado:\nVendedor: {nombre_vendedor}\nProducto: {nombre_producto}\nCantidad añadida: {cantidad}"
        send_log_to_group(mensaje_log)
    else:
        bot.send_message(chat_id, "❌ Error al actualizar el inventario.")
    
    # Limpiar estado
    del GESTION_INVENTARIO[chat_id]
    # Volver al panel de admin
    mostrar_panel_admin(call=None, chat_id=chat_id)

def mostrar_panel_admin(call, chat_id=None):
    if call:
        chat_id = call.message.chat.id
    else:
        # Si no hay call, se usa el chat_id proporcionado
        pass
        
    # Total de ventas diarias de todos los vendedores
    total_ventas_diarias = get_total_daily_sales()

    # Botones para cada vendedor
    markup = types.InlineKeyboardMarkup()
    vendedores = get_all_vendedores()

    for vendedor_id, nombre_vendedor in vendedores:
        boton_vendedor = types.InlineKeyboardButton(nombre_vendedor, callback_data=f'vendedor_info_{vendedor_id}')
        markup.add(boton_vendedor)

    # Inventario disponible y tabla completa de ventas
    boton_inventario = types.InlineKeyboardButton("Mostrar Inventario Disponible", callback_data='mostrar_inventario')
    boton_ventas = types.InlineKeyboardButton("Mostrar Tabla de Ventas", callback_data='mostrar_ventas')
    boton_gestion_inventario = types.InlineKeyboardButton("📦 Gestión de Inventario", callback_data='gestion_inventario')  # Nuevo botón

    # Botones de resumen
    boton_resumen_diario = types.InlineKeyboardButton("Resumen Diario", callback_data='resumen_diario')
    boton_resumen_semanal = types.InlineKeyboardButton("Resumen Semanal", callback_data='resumen_semanal')
    boton_resumen_mensual = types.InlineKeyboardButton("Resumen Mensual", callback_data='resumen_mensual')

    markup.add(boton_inventario)
    markup.add(boton_ventas)
    markup.add(boton_gestion_inventario)
    markup.add(boton_resumen_diario, boton_resumen_semanal, boton_resumen_mensual)

    markup.add(types.InlineKeyboardButton("Volver al menú principal", callback_data='volver_menu'))

    mensaje = f"📊 Panel de Administración ⚙️\n\n"
    mensaje += f"💰 Total de Ventas Diarias (Todos los Vendedores): ${total_ventas_diarias:.2f}\n\n"
    mensaje += "Selecciona un vendedor para ver sus estadísticas:\n"

    try:
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except:
        pass
        
    msg = bot.send_message(chat_id, mensaje, reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'ver_inventario_vendedor')
def ver_inventario_vendedor(call):
    chat_id = call.message.chat.id
    GESTION_INVENTARIO[chat_id] = {"estado": "seleccion_vendedor_ver"}
    markup = types.InlineKeyboardMarkup()
    vendedores = get_all_vendedores()
    
    for vendedor_id, nombre_vendedor in vendedores:
        boton_vendedor = types.InlineKeyboardButton(nombre_vendedor, callback_data=f'ver_inv_vendedor_{vendedor_id}')
        markup.add(boton_vendedor)
        
    boton_volver = types.InlineKeyboardButton("🔙 Volver", callback_data='gestion_inventario')
    markup.add(boton_volver)
    
    try:
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except:
        pass
        
    msg = bot.send_message(chat_id, "Selecciona un vendedor para ver su inventario:", reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('ver_inv_vendedor_'))
def mostrar_inventario_vendedor(call):
    chat_id = call.message.chat.id
    vendedor_id = int(call.data.split('_')[3])
    inventario = obtener_inventario_vendedor(vendedor_id)
    vendedor_info = get_vendedor_by_id(vendedor_id)
    nombre_vendedor = vendedor_info[1] if vendedor_info else "Desconocido"
    
    mensaje = f"📦 Inventario de {nombre_vendedor}:\n\n"
    if inventario:
        for nombre_producto, cantidad in inventario:
            mensaje += f"• {nombre_producto}: {cantidad} unidades\n"
    else:
        mensaje += "No hay productos en el inventario."
    
    markup = types.InlineKeyboardMarkup()
    boton_volver = types.InlineKeyboardButton("🔙 Volver", callback_data='ver_inventario_vendedor')
    markup.add(boton_volver)
    
    try:
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except:
        pass
        
    msg = bot.send_message(chat_id, mensaje, reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('vendedor_info_'))
def mostrar_info_vendedor(call):
    chat_id = call.message.chat.id
    vendedor_id = int(call.data.split('_')[2])

    # Obtener información del vendedor
    vendedor_info = get_vendedor_by_id(vendedor_id)
    nombre_vendedor = vendedor_info[1] if vendedor_info else "Desconocido"

    # Obtener ventas diarias, ganancias y comisiones
    ventas_diarias, ganancias_diarias, comisiones_totales = get_daily_sales_and_profit(vendedor_id)

    # Crear mensaje con la información
    mensaje = f"📊 Información del Vendedor: {nombre_vendedor} (ID: {vendedor_id})\n\n"
    mensaje += f"💰 Ventas Diarias: ${ventas_diarias:.2f}\n"
    mensaje += f"💸 Ganancias Diarias: ${ganancias_diarias:.2f}\n"
    mensaje += f"🤝 Comisiones Totales: ${comisiones_totales:.2f}\n"

    # Botón para volver al panel de administración
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Volver al Panel de Administración", callback_data='admin_panel'))
    try:
        #bot.edit_message_text(mensaje, chat_id, MENSAJES.get(chat_id), reply_markup=markup)
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Error editing message: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
    msg = bot.send_message(chat_id, mensaje, reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'mostrar_inventario')
def mostrar_inventario(call):
    chat_id = call.message.chat.id
    inventory_data = get_inventory_data()

    mensaje = "📦 Inventario Disponible 📦\n\n"

    if inventory_data:
        mensaje += "Vendedor          | Producto              | Cantidad Disponible\n"
        mensaje += "------------------|-----------------------|----------------------\n"
        for vendedor, producto, cantidad_disponible in inventory_data:
            mensaje += f"{vendedor:<17}| {producto:<21}| {cantidad_disponible:<20}\n"
    else:
        mensaje += "No hay datos de inventario disponibles."

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Volver al Panel de Administración", callback_data='admin_panel'))
    try:
        #bot.edit_message_text(mensaje, chat_id, MENSAJES.get(chat_id), reply_markup=markup)
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Error editing message: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
    msg = bot.send_message(chat_id, mensaje, reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'mostrar_ventas')
def mostrar_tabla_ventas(call):
    chat_id = call.message.chat.id
    sales_data = get_all_sales_data()

    mensaje = "📝 Tabla Completa de Ventas 📝\n\n"

    if sales_data:
        mensaje += "Fecha       | Vendedor          | Producto              | Cantidad | Precio Unitario | Total Venta | Comisión\n"
        mensaje += "------------|------------------|-----------------------|----------|-----------------|-------------|----------\n"
        for fecha, producto, vendedor, cantidad, precio, total, comision in sales_data:
             fecha_formateada = fecha[:10]  # Extraer solo la fecha (YYYY-MM-DD)
             mensaje += f"{fecha_formateada:<11}| {vendedor:<17}| {producto:<21}| {cantidad:<8}| {precio:<15.2f}| {total:<11.2f}| {comision:<8.2f}\n"
    else:
        mensaje += "No hay datos de ventas disponibles."

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Volver al Panel de Administración", callback_data='admin_panel'))
    try:
        #bot.edit_message_text(mensaje, chat_id, MENSAJES.get(chat_id), reply_markup=markup)
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Error editing message: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
    msg = bot.send_message(chat_id, mensaje, reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data in ['resumen_diario', 'resumen_semanal', 'resumen_mensual'])
def mostrar_resumen_ventas(call):
    chat_id = call.message.chat.id
    time_period = call.data.split('_')[1]  # Extract the time period ('diario', 'semanal', 'mensual')
    vendedores = get_all_vendedores()
    total_ventas_periodo = 0
    total_ganancias_periodo = 0
    total_comisiones_periodo = 0

    # Diccionario para traducir el período de tiempo
    period_translation = {
        'diario': 'Diario',
        'semanal': 'Semanal',
        'mensual': 'Mensual'
    }

    # Obtener la traducción del período de tiempo
    translated_period = period_translation.get(time_period, time_period.capitalize())

    mensaje = f"📊 Resumen de Ventas {translated_period} 📊\n\n"

    for vendedor_id, nombre_vendedor in vendedores:
        total_sales, total_profit, total_commission = get_sales_summary(vendedor_id, time_period)

        # Acumular totales
        total_ventas_periodo += total_sales
        total_ganancias_periodo += total_profit
        total_comisiones_periodo += total_commission

        mensaje += f"Vendedor: {nombre_vendedor}\n"
        mensaje += f"- Ventas Totales: ${total_sales:.2f}\n"
        mensaje += f"- Ganancias Totales: ${total_profit:.2f}\n"
        mensaje += f"- Comisiones Totales: ${total_commission:.2f}\n\n"

    # Agregar totales generales al final del mensaje
    mensaje += f"💰 Total de Ventas en el Período: ${total_ventas_periodo:.2f}\n"
    mensaje += f"💸 Total de Ganancias en el Período: ${total_ganancias_periodo:.2f}\n"
    mensaje += f"🤝 Total de Comisiones en el Período: ${total_comisiones_periodo:.2f}\n"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Volver al Panel de Administración", callback_data='admin_panel'))
    try:
        #bot.edit_message_text(mensaje, chat_id, MENSAJES.get(chat_id), reply_markup=markup)
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Error editing message: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
    msg = bot.send_message(chat_id, mensaje, reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id


@bot.callback_query_handler(func=lambda call: call.data == 'cerrar_sesion')
def cerrar_sesion_handler(call):
    chat_id = call.message.chat.id
    cerrar_sesion(chat_id)
    USUARIO[chat_id] = {} # Limpia el estado del usuario
    cmd_start(call.message) # Vuelve al inicio

@bot.callback_query_handler(func=lambda call: call.data == 'venta' and USUARIO.get(call.message.chat.id, {}).get("estado") == "logeado")
def iniciar_venta(call):
    chat_id = call.message.chat.id
    VENTA[chat_id] = {"estado": "esperando_producto"}
    markup = types.InlineKeyboardMarkup()
    productos = get_productos()
    if productos:
        for producto_id, nombre_producto in productos:
            boton_producto = types.InlineKeyboardButton(nombre_producto, callback_data=f'producto_{producto_id}')
            markup.add(boton_producto)
        boton_volver = types.InlineKeyboardButton("Volver al menú principal", callback_data='volver_menu')
        boton_cancelar = types.InlineKeyboardButton("Cancelar 🚫", callback_data='cancelar_venta')
        markup.add(boton_cancelar, boton_volver)
        try:
            #bot.edit_message_text("¿Qué producto vendiste? 📦\n¡Elige el producto para registrar tu venta! 🚀", chat_id, MENSAJES.get(chat_id), reply_markup=markup)
            bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Error editing message: {e}"
            logging.error(log_message)
            send_log_to_group(log_message)
        msg = bot.send_message(chat_id, "¿Qué producto vendiste? 📦\n¡Elige el producto para registrar tu venta! 🚀", reply_markup=markup)
        MENSAJES[chat_id] = msg.message_id
    else:
        try:
            #bot.edit_message_text("No hay productos disponibles. Contacta al administrador.", chat_id, MENSAJES.get(chat_id))
            bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Error editing message: {e}"
            logging.error(log_message)
            send_log_to_group(log_message)
        bot.send_message(chat_id, "No hay productos disponibles. Contacta al administrador.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('producto_') and VENTA.get(call.message.chat.id, {}).get("estado") == "esperando_producto")
def seleccionar_producto(call):
    chat_id = call.message.chat.id
    producto_id = int(call.data.split('_')[1])
    VENTA[chat_id]["producto_id"] = producto_id
    VENTA[chat_id]["estado"] = "esperando_cantidad"
    producto = get_producto(producto_id)
    nombre_producto = producto[2]

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_productos'))

    # Eliminar el mensaje anterior antes de enviar uno nuevo
    try:
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Failed to delete message: {e}"
        logging.warning(log_message)
        send_log_to_group(log_message)

    msg = bot.send_message(chat_id, f"¡Excelente! Has seleccionado {nombre_producto} ✅ ¿Cuántas unidades vendiste? 🔢\n¡Ingresa la cantidad para registrar tus ganancias! 💰", reply_markup = markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'cancelar_venta' and VENTA.get(call.message.chat.id, {}).get("estado") == "esperando_producto")
def cancelar_venta(call):
    chat_id = call.message.chat.id
    del VENTA[chat_id]
    mostrar_menu_principal(call.message)
    #bot.edit_message_text("Venta cancelada. ❌ ¡No te rindas, la próxima será mejor! 💪", chat_id, MENSAJES.get(chat_id))

@bot.callback_query_handler(func=lambda call: call.data == 'volver_productos')
def volver_productos(call):
    iniciar_venta(call)

@bot.callback_query_handler(func=lambda call: call.data == 'volver_menu')
def volver_menu(call):
    chat_id = call.message.chat.id
    es_admin = USUARIO[chat_id]["es_admin"]
    if es_admin:
        mostrar_panel_admin(call)
    else:
        mostrar_menu_principal(call.message)

@bot.message_handler(func=lambda message: VENTA.get(message.chat.id, {}).get("estado") == "esperando_cantidad")
def registrar_cantidad(message):
    chat_id = message.chat.id
    cantidad = message.text
    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError
    except ValueError:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_productos'))

        # Eliminar el mensaje anterior antes de enviar uno nuevo
        try:
            bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Failed to delete message: {e}"
            logging.warning(log_message)
            send_log_to_group(log_message)

        msg = bot.send_message(chat_id, "Cantidad inválida ❌. Debe ser un número entero positivo.", reply_markup = markup)
        MENSAJES[chat_id] = msg.message_id
        try:
            bot.delete_message(chat_id=message.chat.id, message_id=message.message_id) #Delete the message sent by the user
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Failed to delete message: {e}"
            logging.warning(log_message)
            send_log_to_group(log_message)
        return

    vendedor_id = USUARIO[chat_id]["vendedor_id"]
    producto_id = VENTA[chat_id]["producto_id"]
    inventario_actual = get_inventario(vendedor_id, producto_id)

    if inventario_actual < cantidad:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_productos'))

        # Eliminar el mensaje anterior antes de enviar uno nuevo
        try:
            bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Failed to delete message: {e}"
            logging.warning(log_message)
            send_log_to_group(log_message)

        msg = bot.send_message(chat_id, f"No hay suficiente inventario 😞. Tienes {inventario_actual} unidades disponibles.", reply_markup = markup)
        MENSAJES[chat_id] = msg.message_id
        try:
            bot.delete_message(chat_id=message.chat.id, message_id=message.message_id) #Delete the message sent by the user
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Failed to delete message: {e}"
            logging.warning(log_message)
            send_log_to_group(log_message)
        return

    producto = get_producto(producto_id)
    nombre_producto = producto[2]

    if registrar_venta(vendedor_id, producto_id, cantidad):
        del VENTA[chat_id]
        mostrar_menu_principal(message)
        #bot.edit_message_text(f"¡Venta de {cantidad} unidades de {nombre_producto} registrada con éxito! ✅ ¡Sigue así y alcanzarás tus metas! 🚀", chat_id, MENSAJES.get(chat_id))
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_productos'))

        # Eliminar el mensaje anterior antes de enviar uno nuevo
        try:
            bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
        except telebot.apihelper.ApiTelegramException as e:
            log_message = f"Failed to delete message: {e}"
            logging.warning(log_message)
            send_log_to_group(log_message)

        msg = bot.send_message(chat_id, "Error al registrar la venta ❌. Contacta al administrador.", reply_markup = markup)
        MENSAJES[chat_id] = msg.message_id
    try:
        bot.delete_message(chat_id=message.chat.id, message_id=message.message_id) #Delete the message sent by the user
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Failed to delete message: {e}"
        logging.warning(log_message)
        send_log_to_group(log_message)

@bot.callback_query_handler(func=lambda call: call.data == 'historial' and USUARIO.get(call.message.chat.id, {}).get("estado") == "logeado")
def mostrar_historial_diario(call):
    chat_id = call.message.chat.id
    vendedor_id = USUARIO[chat_id]["vendedor_id"]
    ventas_diarias = obtener_ventas_diarias(vendedor_id)

    mensaje = "🎉 ¡Aquí está tu resumen de ventas diarias! 📊\n"
    total_ganancias = 0
    total_comisiones = 0

    if ventas_diarias:
        for nombre_producto, cantidad_vendida, total_venta, comision, producto_id in ventas_diarias:
            cantidad_disponible = obtener_cantidad_disponible(vendedor_id, producto_id)
            mensaje += f"- {nombre_producto}: {cantidad_vendida} unidades - Total: ${total_venta:.2f} - Comisión: ${comision:.2f} - Disponible: {cantidad_disponible}\n"
            total_ganancias += total_venta
            total_comisiones += comision

        mensaje += f"\n¡Venta Total del Día: ${total_ganancias:.2f} 🎉"
        mensaje += f"\n¡Comisión Total del Día: ${total_comisiones:.2f} 💰"
        mensaje += "\n¡Excelente trabajo! ¡Sigue así para alcanzar tus objetivos! 🚀"
    else:
         mensaje += "\n¡No hay ventas registradas para hoy!"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Volver al menú principal", callback_data='volver_menu'))
    try:
        #bot.edit_message_text(mensaje, chat_id, MENSAJES.get(chat_id), reply_markup=markup)
        bot.delete_message(chat_id=chat_id, message_id=MENSAJES.get(chat_id))
    except telebot.apihelper.ApiTelegramException as e:
        log_message = f"Error editing message: {e}"
        logging.error(log_message)
        send_log_to_group(log_message)
    msg = bot.send_message(chat_id, mensaje, reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

# --- Main ---
if __name__ == '__main__':
    # Crea la base de datos si no existe
    create_database()

    # Inserta datos iniciales (¡SOLO PARA PRUEBAS!)
    insertar_datos_iniciales()

    try:
        log_message = "Bot is running..."
        logging.info(log_message)
        send_log_to_group(log_message)
        bot.infinity_polling()
    except Exception as e:
        log_message = f"Error inesperado: {e}"
        logging.exception(log_message)
        send_log_to_group(log_message)
    finally:
        log_message = "Bot detenido."
        logging.info(log_message)
        send_log_to_group(log_message)