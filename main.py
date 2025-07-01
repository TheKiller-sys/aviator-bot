import telebot
from telebot import types
import os
import json
from dotenv import load_dotenv
from PIL import Image
import time
import requests
import logging
import re  # Para validación de números
from database import crear_conexion, crear_tablas, ejecutar_consulta, obtener_conexion
import sqlite3

load_dotenv("config.env")

# --- Configuración ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
COMMUNITY_GROUP_ID = int(os.getenv("COMMUNITY_GROUP_ID"))
RESULTS_GROUP_ID = int(os.getenv("RESULTS_GROUP_ID"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
CUP_CARD_NUMBER = os.getenv("CUP_CARD_NUMBER")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID"))
DATABASE_NAME = os.getenv("DATABASE_NAME")
ADMIN_PHONE_NUMBER = os.getenv("ADMIN_PHONE_NUMBER")

bot = telebot.TeleBot(TOKEN)

# --- Configuración de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def enviar_log(mensaje):
    """Envía un mensaje de log al grupo de Telegram."""
    try:
        bot.send_message(LOG_GROUP_ID, mensaje)
        logging.info(f"Log enviado a Telegram: {mensaje}")
    except Exception as e:
        logging.error(f"Error al enviar log a Telegram: {e}")

# --- Funciones de utilidad ---

def obtener_usuario(user_id):
    """Obtiene la información de un usuario de la base de datos."""
    query = "SELECT * FROM usuarios WHERE id = ?"
    resultado = ejecutar_consulta(query, (user_id,))
    if resultado:
        return resultado[0]
    else:
        return None

def crear_usuario(user_id, username, first_name):
    """Crea un nuevo usuario en la base de datos."""
    query = "INSERT INTO usuarios (id, username, first_name) VALUES (?, ?, ?)"
    ejecutar_consulta(query, (user_id, username, first_name))

def obtener_sorteo(sorteo_id):
    """Obtiene la información de un sorteo de la base de datos."""
    query = "SELECT * FROM sorteos WHERE id = ?"
    resultado = ejecutar_consulta(query, (sorteo_id,))
    if resultado:
        return resultado[0]
    else:
        return None

def obtener_numeros_disponibles(sorteo_id):
    """Obtiene los números disponibles para un sorteo."""
    query = "SELECT numero FROM numeros WHERE sorteo_id = ? AND disponible = 1"
    resultados = ejecutar_consulta(query, (sorteo_id,))
    return [resultado[0] for resultado in resultados]

def reservar_numero_db(usuario_id, sorteo_id, numero):
    """Reserva un número en la base de datos."""
    try:
        conn = obtener_conexion()
        cursor = conn.cursor()
        # Primero, verifica si el número está disponible
        cursor.execute("SELECT disponible FROM numeros WHERE sorteo_id = ? AND numero = ?", (sorteo_id, numero))
        resultado = cursor.fetchone()

        if resultado is None:
            logging.warning(f"Número {numero} no encontrado en el sorteo {sorteo_id}.")
            return False, "¡Ups! Parece que el número que intentas reservar no existe en este sorteo. Por favor, verifica nuevamente."  # El número no existe

        if resultado[0] == 0:  # Si disponible es 0, el número ya está reservado
            logging.warning(f"El número {numero} ya está reservado en el sorteo {sorteo_id}.")
            return False, "¡Lo sentimos! Alguien más ha sido más rápido y ya reservó este número. Por favor, elige otro."

        # Luego, crea la reserva
        cursor.execute("INSERT INTO reservas (usuario_id, sorteo_id, numero, estado) VALUES (?, ?, ?, ?)", (usuario_id, sorteo_id, numero, 'pendiente'))

        # Marca el número como no disponible
        cursor.execute("UPDATE numeros SET disponible = 0 WHERE sorteo_id = ? AND numero = ?", (sorteo_id, numero))

        conn.commit()
        logging.info(f"Número {numero} reservado para el usuario {usuario_id} en el sorteo {sorteo_id}.")
        return True, None  # Reserva exitosa
    except sqlite3.Error as e:
        logging.error(f"Error al reservar el número: {e}")
        conn.rollback()
        return False, "¡Oh no! Tuvimos un problema técnico al intentar reservar el número. Por favor, intenta de nuevo en unos minutos."  # Error en la base de datos
    finally:
        if conn:
            conn.close()

def confirmar_reserva_db(reserva_id):
    """Confirma una reserva en la base de datos."""
    query = "UPDATE reservas SET estado = 'confirmada' WHERE id = ?"
    ejecutar_consulta(query, (reserva_id,))

def rechazar_reserva_db(reserva_id):
    """Rechaza una reserva en la base de datos y libera el número."""
    try:
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Obtén la información de la reserva para liberar el número
        cursor.execute("SELECT sorteo_id, numero FROM reservas WHERE id = ?", (reserva_id,))
        reserva = cursor.fetchone()

        if reserva:
            sorteo_id, numero = reserva
            # Libera el número marcándolo como disponible
            cursor.execute("UPDATE numeros SET disponible = 1 WHERE sorteo_id = ? AND numero = ?", (sorteo_id, numero))
            # Actualiza el estado de la reserva
            cursor.execute("UPDATE reservas SET estado = 'rechazada' WHERE id = ?", (reserva_id,))
            conn.commit()
            logging.info(f"Reserva {reserva_id} rechazada y número {numero} liberado en el sorteo {sorteo_id}.")
        else:
            logging.warning(f"Reserva con ID {reserva_id} no encontrada.")
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error al rechazar la reserva: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def guardar_captura_reserva(reserva_id, file_path):
    """Guarda el path de la captura en la base de datos."""
    query = "UPDATE reservas SET captura_url = ? WHERE id = ?"
    ejecutar_consulta(query, (file_path, reserva_id))

# --- Manejadores de comandos ---

@bot.message_handler(commands=['start'])
def start(message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        first_name = message.from_user.first_name

        # Verificar si el usuario ya existe en la base de datos
        usuario = obtener_usuario(user_id)
        if not usuario:
            crear_usuario(user_id, username, first_name)
            enviar_log(f"Nuevo usuario registrado: ID {user_id}, Username {username}")

        # Verificar si el usuario está en los grupos requeridos
        try:
            community_status = bot.get_chat_member(COMMUNITY_GROUP_ID, user_id).status
            results_status = bot.get_chat_member(RESULTS_GROUP_ID, user_id).status
            if community_status in ("member", "administrator", "creator") and \
               results_status in ("member", "administrator", "creator"):
                markup = types.InlineKeyboardMarkup()
                item_sorteos = types.InlineKeyboardButton("🎟️ ¡Quiero Participar!", callback_data='ver_sorteos')
                item_cuenta = types.InlineKeyboardButton("👤 Mi Cuenta", callback_data='mi_cuenta')
                markup.add(item_sorteos)
                markup.add(item_cuenta)

                # Mensaje de bienvenida llamativo
                welcome_message = f"""
¡Hola, @{username or first_name}! 👋

¡Bienvenido/a a la plataforma de sorteos más emocionante! 🎉 Aquí, tus sueños pueden hacerse realidad con solo participar en nuestros increíbles sorteos.

¡Descubre las oportunidades de ganar premios asombrosos! 🎁 Únete a la diversión y participa para tener la oportunidad de cambiar tu vida. ¡Mucha suerte! 🍀
                """
                sent_msg = bot.send_message(message.chat.id, welcome_message, reply_markup=markup)
                bot.register_next_step_handler(message, lambda msg: start(msg))
            else:
                 # Mensaje de error llamativo
                error_message = """
🚫 ¡Oops! 🚫

Parece que aún no te has unido a nuestros canales de la comunidad y resultados. 🥺

Para poder participar en nuestros sorteos y disfrutar de todas las ventajas, es necesario que te unas a nuestros canales. ¡No te pierdas ninguna actualización importante! 🚀
"""
                bot.send_message(message.chat.id, error_message)
        except telebot.apihelper.ApiTelegramException as e:
            if "user not found" in str(e):
                 # Mensaje de error llamativo
                error_message = """
🚫 ¡Oops! 🚫

Parece que aún no te has unido a nuestros canales de la comunidad y resultados. 🥺

Para poder participar en nuestros sorteos y disfrutar de todas las ventajas, es necesario que te unas a nuestros canales. ¡No te pierdas ninguna actualización importante! 🚀
"""
                bot.send_message(message.chat.id, error_message)
            else:
                logging.error(f"Error al verificar la membresía del usuario: {e}")
                # Mensaje de error llamativo
                error_message = """
⚠️ ¡Algo salió mal! ⚠️

Tuvimos un pequeño problema al verificar tu membresía en nuestros canales. 😥

Por favor, inténtalo de nuevo más tarde. Si el problema persiste, contacta con nuestro equipo de soporte para que podamos ayudarte. ¡Gracias por tu paciencia! 🙏
"""
                bot.send_message(message.chat.id, error_message)
        except Exception as e:
            logging.exception("Error inesperado en el comando /start")
             # Mensaje de error llamativo
            error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error interno en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
            bot.send_message(message.chat.id, error_message)
    except Exception as e:
        logging.exception("Error general en el comando /start")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

# --- Manejadores de "callback_query" (botones inline) ---

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        user_id = call.from_user.id
        message = call.message  # Obtener el mensaje original

        if call.data == 'ver_sorteos':
            mostrar_sorteos(message)
        elif call.data == 'mi_cuenta':
            mostrar_mi_cuenta(message)
        elif call.data.startswith('reservar_sorteo_'):
            sorteo_id = int(call.data.split('_')[2])
            mostrar_numeros_disponibles(message, sorteo_id)
        elif call.data.startswith('seleccionar_numero_'):
            numero = int(call.data.split('_')[2])
            sorteo_id = int(call.data.split('_')[3])  # Nuevo: obtener sorteo_id
            seleccionar_numero(message, numero, sorteo_id) # Modificado
        elif call.data == 'volver_sorteos':
            mostrar_sorteos(message)
        elif call.data == 'volver_inicio':
            start(message)
        elif call.data.startswith('confirmar_reserva_'):
            reserva_id = int(call.data.split('_')[2])
            confirmar_reserva(call, reserva_id)  # Pasar el objeto call
        elif call.data.startswith('rechazar_reserva_'):
            reserva_id = int(call.data.split('_')[2])
            rechazar_reserva(call, reserva_id)  # Pasar el objeto call
        elif call.data == 'volver_admin_panel':
            admin_panel(message)
        else:
            logging.warning(f"Callback data no reconocida: {call.data}")
            # Mensaje de error llamativo
            error_message = """
🤔 ¡Ups! Parece que algo no está bien 🤔

No reconocemos la acción que intentas realizar. 😥

Por favor, verifica que estás utilizando las opciones correctas. Si el problema persiste, contacta con nuestro equipo de soporte. ¡Gracias! 🙏
"""
            bot.send_message(message.chat.id, error_message)

    except Exception as e:
        logging.exception(f"Error en el callback query: {call.data}")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

# --- Funciones para la lógica del bot ---

def mostrar_sorteos(message):
    """Muestra la lista de sorteos disponibles."""
    try:
        conn = crear_conexion()
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre, premio, valor_numero FROM sorteos")
        sorteos = cursor.fetchall()
        conn.close()

        if not sorteos:
            # Mensaje llamativo si no hay sorteos disponibles
            no_sorteos_message = """
¡Lo sentimos! 😔

En este momento no tenemos sorteos disponibles. ¡Pero no te preocupes! Estamos trabajando para traerte nuevas y emocionantes oportunidades de ganar. 🎁

¡Mantente atento a nuestras actualizaciones y sé el primero en participar cuando tengamos nuevos sorteos! 🚀
"""
            bot.send_message(message.chat.id, no_sorteos_message)
            return

        for sorteo in sorteos:
            sorteo_id, nombre, premio, valor_numero = sorteo
            numeros_disponibles = obtener_numeros_disponibles(sorteo_id)

            markup = types.InlineKeyboardMarkup()
            item_reservar = types.InlineKeyboardButton("🔢 ¡Quiero Reservar!", callback_data=f'reservar_sorteo_{sorteo_id}')
            item_volver = types.InlineKeyboardButton("🔙 Volver al Inicio", callback_data='volver_inicio')
            markup.add(item_reservar)
            markup.add(item_volver)

            sorteo_details = f"""
🎉 **¡Sorteo {nombre}!** 🎉

¡Prepárate para ganar este increíble premio! 🎁

*   💰 **Premio:** {premio}
*   💲 **Valor por número:** {valor_numero} CUP
*   🔢 **Números disponibles:** {len(numeros_disponibles)}

¡No pierdas la oportunidad de cambiar tu suerte! 🍀
            """
            bot.send_message(message.chat.id, sorteo_details, parse_mode="Markdown", reply_markup=markup)

    except sqlite3.Error as e:
         # Mensaje de error llamativo
        error_message = """
⚠️ ¡Ups! Tuvimos un problemita técnico ⚠️

No pudimos obtener la información de los sorteos en este momento. 😥

Por favor, inténtalo de nuevo más tarde. Si el problema persiste, contacta con nuestro equipo de soporte. ¡Gracias por tu paciencia! 🙏
"""
        logging.error(f"Error al mostrar sorteos: {e}")
        bot.send_message(message.chat.id, error_message)
    except Exception as e:
        logging.exception("Error inesperado al mostrar sorteos")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def mostrar_mi_cuenta(message):
    """Muestra la información de la cuenta del usuario."""
    try:
        user_id = message.from_user.id
        usuario = obtener_usuario(user_id)

        if not usuario:
             # Mensaje de error llamativo
            error_message = """
⚠️ ¡Ups! No pudimos cargar tu información ⚠️

Ocurrió un error al cargar tu información de usuario. 😥

Por favor, inténtalo de nuevo más tarde. Si el problema persiste, contacta con nuestro equipo de soporte. ¡Gracias por tu paciencia! 🙏
"""
            bot.send_message(message.chat.id, error_message)
            return

        _, username, first_name, sorteos_ganados, dinero_ganado, sorteos_participados, mayor_ganancia = usuario

        account_details = f"""
👤 **¡Tu Cuenta, @{username or first_name}!** 👤

¡Aquí tienes un resumen de tus logros y participaciones! 🎉

*   🏆 **Sorteos ganados:** {sorteos_ganados}
*   💰 **Dinero total ganado:** {dinero_ganado:.2f} CUP
*   🎟️ **Sorteos participados:** {sorteos_participados}
*   🥇 **Mayor ganancia:** {mayor_ganancia:.2f} CUP

¡Sigue participando y aumentando tus ganancias! 🍀
        """
        markup = types.InlineKeyboardMarkup()
        item_volver = types.InlineKeyboardButton("🔙 Volver al Inicio", callback_data='volver_inicio')
        markup.add(item_volver)

        bot.send_message(message.chat.id, account_details, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        logging.exception("Error al mostrar la cuenta del usuario")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def mostrar_numeros_disponibles(message, sorteo_id):
    """Muestra los números disponibles para un sorteo."""
    try:
        numeros_disponibles = obtener_numeros_disponibles(sorteo_id)

        if not numeros_disponibles:
             # Mensaje llamativo si no hay números disponibles
            no_numeros_message = """
¡Lo sentimos! 😔

En este momento no hay números disponibles para este sorteo. ¡Pero no te preocupes! Regularmente liberamos nuevos números. 🎁

¡Mantente atento a nuestras actualizaciones y sé el primero en reservar tu número! 🚀
"""
            bot.send_message(message.chat.id, no_numeros_message)
            return

        markup = types.InlineKeyboardMarkup(row_width=5)  # Muestra 5 botones por fila
        buttons = [types.InlineKeyboardButton(str(numero), callback_data=f'seleccionar_numero_{numero}_{sorteo_id}') for numero in numeros_disponibles]  # Incluir sorteo_id
        markup.add(*buttons)  # Desempaqueta la lista de botones
        item_volver = types.InlineKeyboardButton("🔙 Volver a los Sorteos", callback_data='volver_sorteos')
        markup.add(item_volver)

        # Mensaje llamativo al mostrar los números disponibles
        available_numbers_message = """
¡Elige tu número de la suerte! 🍀

Selecciona el número con el que quieres participar en este sorteo. ¡Cada número es una oportunidad de ganar! 🎁

¡Mucha suerte en tu elección! 🙏
"""
        bot.send_message(message.chat.id, available_numbers_message, reply_markup=markup)
    except Exception as e:
        logging.exception("Error al mostrar los números disponibles")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def seleccionar_numero(message, numero, sorteo_id):
    """Muestra la confirmación de selección de número y pide el depósito."""
    try:
        # Obtener información del sorteo
        sorteo = obtener_sorteo(sorteo_id)
        if not sorteo:
             # Mensaje de error llamativo
            error_message = """
⚠️ ¡Ups! No encontramos este sorteo ⚠️

Parece que el sorteo que intentas seleccionar no existe. 😥

Por favor, verifica que estás utilizando las opciones correctas. Si el problema persiste, contacta con nuestro equipo de soporte. ¡Gracias! 🙏
"""
            bot.send_message(message.chat.id, error_message)
            return

        _, nombre_sorteo, _, valor_numero, _, _ = sorteo  # Desempaquetar información del sorteo

        # Crear teclado inline para confirmar el depósito
        markup = types.InlineKeyboardMarkup()
        item_confirmar = types.InlineKeyboardButton("✅ ¡Ya deposité!", callback_data='confirmar_deposito')
        item_volver = types.InlineKeyboardButton("🔙 Volver a los Sorteos", callback_data='volver_sorteos')
        markup.add(item_confirmar)
        markup.add(item_volver)

        # Mensaje llamativo con instrucciones de pago
        payment_instructions = f"""
¡Felicidades! 🎉 Has elegido el número **{numero}** para el sorteo **{nombre_sorteo}**. 🍀

Para confirmar tu participación, por favor, realiza el depósito de **{valor_numero} CUP** a la siguiente tarjeta:

💳 **{CUP_CARD_NUMBER}**

📞 También puedes contactar al administrador al número: **{ADMIN_PHONE_NUMBER}** para confirmar.

Una vez realizado el depósito, presiona el botón "¡Ya deposité!" para completar tu reserva. ¡Mucha suerte! 🙏
"""
        sent_msg = bot.send_message(
            message.chat.id,
            payment_instructions,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        # Establecer el siguiente paso: pedir la captura
        bot.register_next_step_handler(message, lambda msg: confirmar_deposito(msg, numero, sorteo_id, sent_msg.message_id))

    except Exception as e:
        logging.exception("Error al seleccionar el número")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def confirmar_deposito(message, numero, sorteo_id, message_id):
    """Pide la captura de pantalla del depósito."""
    try:
         # Mensaje llamativo para pedir la captura
        ask_for_capture = """
📸 ¡Un último paso! 📸

Para completar tu reserva, por favor, envía una captura de pantalla del comprobante de depósito. 🧾

¡Gracias por tu participación! 🍀
"""
        bot.edit_message_text(ask_for_capture, chat_id=message.chat.id, message_id=message_id)
        # Establecer el siguiente paso: procesar la captura
        bot.register_next_step_handler(message, lambda msg: procesar_captura(msg, numero, sorteo_id, message_id))
    except Exception as e:
        logging.exception("Error al pedir la captura del depósito")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def procesar_captura(message, numero, sorteo_id, message_id):
    """Procesa la captura de pantalla del depósito."""
    try:
        if message.content_type != 'photo':
            # Mensaje llamativo si no se envía una foto
            not_a_photo_message = """
⚠️ ¡Ups! Necesitamos una imagen ⚠️

Por favor, asegúrate de enviar una captura de pantalla como imagen. 📸

¡Inténtalo de nuevo! 🙏
"""
            bot.send_message(message.chat.id, not_a_photo_message)
            # Si no es una imagen, reintenta pedir la captura
            bot.register_next_step_handler(message, lambda msg: procesar_captura(msg, numero, sorteo_id, message_id))  # Pide la imagen de nuevo
            return

        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        image_name = f"deposito_{message.from_user.id}_{int(time.time())}.jpg"
        file_path = os.path.join("./", image_name)

        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        # Reservar el número en la base de datos
        usuario_id = message.from_user.id
        success, error_message = reservar_numero_db(usuario_id, sorteo_id, numero)

        if success:
            # Obtener el ID de la reserva recién creada
            conn = obtener_conexion()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM reservas WHERE usuario_id = ? AND sorteo_id = ? AND numero = ? ORDER BY fecha_reserva DESC LIMIT 1", (usuario_id, sorteo_id, numero))
            reserva_id_result = cursor.fetchone()
            conn.close()

            if reserva_id_result:
                reserva_id = reserva_id_result[0]

                 # Guardar el path de la captura en la base de datos
                guardar_captura_reserva(reserva_id, file_path)

                # Enviar la captura al grupo de administración para su revisión
                markup = types.InlineKeyboardMarkup()
                item_confirmar = types.InlineKeyboardButton("✅ Confirmar", callback_data=f'confirmar_reserva_{reserva_id}')
                item_rechazar = types.InlineKeyboardButton("❌ Rechazar", callback_data=f'rechazar_reserva_{reserva_id}')
                markup.add(item_confirmar, item_rechazar)

                with open(file_path, 'rb') as photo:
                    bot.send_photo(ADMIN_GROUP_ID, photo, caption=f"Nueva solicitud de depósito de @{message.from_user.username} por el número {numero} en el sorteo {sorteo_id}", reply_markup=markup)

                # Mensaje llamativo de confirmación y espera
                confirmation_message = """
🎉 ¡Reserva en revisión! 🎉

¡Gracias por enviar tu comprobante! 🧾 Tu solicitud está siendo revisada por nuestro equipo.

Te notificaremos tan pronto como se confirme tu reserva. ¡Mucha suerte! 🍀
"""
                bot.edit_message_text(confirmation_message, chat_id=message.chat.id, message_id=message_id)
                enviar_log(f"Solicitud de depósito enviada al grupo de administración para el usuario {usuario_id}")
            else:
                 # En caso de error, liberar el número reservado
                conn = obtener_conexion()
                cursor = conn.cursor()
                cursor.execute("UPDATE numeros SET disponible = 1 WHERE sorteo_id = ? AND numero = ?", (sorteo_id, numero))
                conn.commit()
                conn.close()
                 # Mensaje de error llamativo
                error_message = """
⚠️ ¡Ups! Tuvimos un problema técnico ⚠️

Ocurrió un error al obtener el ID de tu reserva. 😥 No te preocupes, tu número ha sido liberado.

Por favor, inténtalo de nuevo más tarde. Si el problema persiste, contacta con nuestro equipo de soporte. ¡Gracias por tu paciencia! 🙏
"""
                bot.edit_message_text(error_message, chat_id=message.chat.id, message_id=message_id)

        else:
             # Mensaje de error llamativo
            error_message = f"""
⚠️ ¡Ups! No pudimos reservar tu número ⚠️

Ocurrió un error al intentar reservar el número: {error_message} 😥

Por favor, inténtalo de nuevo más tarde. Si el problema persiste, contacta con nuestro equipo de soporte. ¡Gracias por tu paciencia! 🙏
"""
            bot.edit_message_text(error_message, chat_id=message.chat.id, message_id=message_id)
    except Exception as e:
        logging.exception("Error al procesar la captura")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.edit_message_text(error_message, chat_id=message.chat.id, message_id=message_id)

def confirmar_reserva(call, reserva_id):
    """Confirma la reserva y notifica al usuario."""
    try:
        confirmar_reserva_db(reserva_id)
        bot.answer_callback_query(call.id, "Reserva confirmada.")
        bot.send_message(ADMIN_GROUP_ID, f"Reserva con ID {reserva_id} confirmada.")
        # Obtener información de la reserva
        conn = obtener_conexion()
        cursor = conn.cursor()
        cursor.execute("SELECT usuario_id, sorteo_id, numero FROM reservas WHERE id = ?", (reserva_id,))
        reserva = cursor.fetchone()
        conn.close()

        if reserva:
            usuario_id, sorteo_id, numero = reserva
             # Mensaje llamativo de reserva confirmada
            confirmation_message = f"""
¡Felicidades! 🎉 ¡Tu número **{numero}** ha sido reservado correctamente para el sorteo **{sorteo_id}**! 🍀

¡Mucha suerte! 🙏
"""
            bot.send_message(usuario_id, confirmation_message)
            enviar_log(f"Reserva {reserva_id} confirmada para el usuario {usuario_id}")
        else:
            bot.send_message(ADMIN_GROUP_ID, f"Error al obtener información de la reserva {reserva_id} al confirmar.")
            enviar_log(f"Error al obtener información de la reserva {reserva_id} al confirmar.")

    except Exception as e:
        logging.exception("Error al confirmar la reserva")
         # Mensaje de error llamativo
        error_message = """
⚠️ ¡Ups! No pudimos confirmar la reserva ⚠️

Ocurrió un error al intentar confirmar la reserva. 😥

Por favor, contacta con el usuario para verificar el estado de la reserva. ¡Gracias por tu paciencia! 🙏
"""
        bot.send_message(ADMIN_GROUP_ID, error_message)
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(call.message.chat.id, error_message)

def rechazar_reserva(call, reserva_id):
    """Rechaza la reserva y notifica al usuario."""
    try:
        rechazar_reserva_db(reserva_id)
        bot.answer_callback_query(call.id, "Reserva rechazada.")
        bot.send_message(ADMIN_GROUP_ID, f"Reserva con ID {reserva_id} rechazada.")

        # Obtener información de la reserva
        conn = obtener_conexion()
        cursor = conn.cursor()
        cursor.execute("SELECT usuario_id, sorteo_id, numero FROM reservas WHERE id = ?", (reserva_id,))
        reserva = cursor.fetchone()
        conn.close()

        if reserva:
            usuario_id, sorteo_id, numero = reserva
            # Mensaje llamativo de reserva rechazada
            rejection_message = """
¡Lo sentimos! 😔 Tu solicitud de reserva ha sido rechazada.

Por favor, contacta con el administrador para obtener más información. ¡Gracias! 🙏
"""
            bot.send_message(usuario_id, rejection_message)
            enviar_log(f"Reserva {reserva_id} rechazada para el usuario {usuario_id}")
        else:
            bot.send_message(ADMIN_GROUP_ID, f"Error al obtener información de la reserva {reserva_id} al rechazar.")
            enviar_log(f"Error al obtener información de la reserva {reserva_id} al rechazar.")

    except Exception as e:
        logging.exception("Error al rechazar la reserva")
         # Mensaje de error llamativo
        error_message = """
⚠️ ¡Ups! No pudimos rechazar la reserva ⚠️

Ocurrió un error al intentar rechazar la reserva. 😥

Por favor contacta con el usuario para informarle del estado de su reserva. ¡Gracias por tu paciencia! 🙏
"""
        bot.send_message(ADMIN_GROUP_ID, error_message)
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(call.message.chat.id, error_message)

# --- Comandos de administración ---

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """Muestra el panel de administración."""
    try:
        if message.from_user.id == ADMIN_USER_ID:
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            item_crear_sorteo = types.KeyboardButton("Crear Sorteo")
            item_editar_sorteo = types.KeyboardButton("Editar Sorteo")
            markup.add(item_crear_sorteo, item_editar_sorteo)
            # Mensaje llamativo del panel de administración
            admin_panel_message = """
⚙️ ¡Bienvenido al Panel de Administración! ⚙️

Selecciona la acción que deseas realizar:
"""
            bot.send_message(message.chat.id, admin_panel_message, reply_markup=markup)
            bot.register_next_step_handler(message, admin_actions)
        else:
            # Mensaje llamativo si no tiene permisos
            no_permission_message = """
🚫 ¡Acceso Denegado! 🚫

Lo sentimos, no tienes los permisos necesarios para acceder al panel de administración. 😥
"""
            bot.send_message(message.chat.id, no_permission_message)
    except Exception as e:
        logging.exception("Error al mostrar el panel de administración")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def admin_actions(message):
    """Realiza las acciones del panel de administración."""
    try:
        if message.text == "Crear Sorteo":
            # Mensaje llamativo para pedir el nombre del sorteo
            ask_sorteo_name = """
📝 ¡Vamos a crear un nuevo sorteo! 📝

Por favor, envia el nombre del sorteo:
"""
            bot.send_message(message.chat.id, ask_sorteo_name)
            bot.register_next_step_handler(message, crear_sorteo_nombre)
        elif message.text == "Editar Sorteo":
            # Implementar la lógica para editar un sorteo
            pass  #TODO: Implementar la logica para editar sorteos
        else:
            # Mensaje llamativo si la acción no es reconocida
            unrecognized_action_message = """
🤔 ¡Acción no reconocida! 🤔

La acción que intentas realizar no es válida. Por favor, selecciona una de las opciones disponibles. 🙏
"""
            bot.send_message(message.chat.id, unrecognized_action_message)
    except Exception as e:
        logging.exception("Error al realizar una acción del panel de administración")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def crear_sorteo_nombre(message):
    """Crea el nombre del sorteo y pide el premio."""
    try:
        nombre = message.text
        # Mensaje llamativo para pedir el premio del sorteo
        ask_sorteo_premio = """
🎁 ¡Ahora el premio! 🎁

Por favor, envia el premio del sorteo:
"""
        bot.send_message(message.chat.id, ask_sorteo_premio)
        bot.register_next_step_handler(message, lambda msg: crear_sorteo_premio(msg, nombre))
    except Exception as e:
        logging.exception("Error al crear el nombre del sorteo")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def crear_sorteo_premio(message, nombre):
    """Crea el premio del sorteo y pide el valor del número."""
    try:
        premio = message.text
        # Mensaje llamativo para pedir el valor del número
        ask_sorteo_valor = """
💲 ¡Valor del número! 💲

Por favor, envia el valor del número para este sorteo:
"""
        bot.send_message(message.chat.id, ask_sorteo_valor)
        bot.register_next_step_handler(message, lambda msg: crear_sorteo_valor(msg, nombre, premio))
    except Exception as e:
        logging.exception("Error al crear el premio del sorteo")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def crear_sorteo_valor(message, nombre, premio):
    """Crea el valor del número y pide la cantidad de números."""
    try:
        valor_numero = message.text
        # Validar que el valor del número sea un número
        if not re.match(r'^\d+(\.\d+)?$', valor_numero):
            # Mensaje llamativo si el valor no es un número
            invalid_value_message = """
⚠️ ¡Valor inválido! ⚠️

Por favor, envia un valor de número válido (ej: 10.50).
"""
            bot.send_message(message.chat.id, invalid_value_message)
            bot.register_next_step_handler(message, lambda msg: crear_sorteo_valor(msg, nombre, premio))
            return

        # Mensaje llamativo para pedir la cantidad de números
        ask_sorteo_cantidad = """
🔢 ¡Cantidad de números! 🔢

Por favor, envia la cantidad de números disponibles para este sorteo:
"""
        bot.send_message(message.chat.id, ask_sorteo_cantidad)
        bot.register_next_step_handler(message, lambda msg: crear_sorteo_cantidad(msg, nombre, premio, valor_numero))
    except Exception as e:
        logging.exception("Error al crear el valor del número")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

def crear_sorteo_cantidad(message, nombre, premio, valor_numero):
    """Crea la cantidad de números y guarda el sorteo en la base de datos."""
    try:
        cantidad_numeros = message.text
        # Validar que la cantidad de números sea un número entero
        if not re.match(r'^\d+$', cantidad_numeros):
             # Mensaje llamativo si la cantidad no es un número entero
            invalid_cantidad_message = """
⚠️ ¡Cantidad inválida! ⚠️

Por favor, envia una cantidad de números válida (ej: 100). Debe ser un número entero.
"""
            bot.send_message(message.chat.id, invalid_cantidad_message)
            bot.register_next_step_handler(message, lambda msg: crear_sorteo_cantidad(msg, nombre, premio, valor_numero))
            return

        cantidad_numeros = int(cantidad_numeros)

        # Guardar el sorteo en la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sorteos (nombre, premio, valor_numero, cantidad_numeros) VALUES (?, ?, ?, ?)", (nombre, premio, valor_numero, cantidad_numeros))
        sorteo_id = cursor.lastrowid  # Obtener el ID del sorteo recién creado
        conn.commit()

        # Crear los números para el sorteo y marcarlos como disponibles
        for numero in range(1, cantidad_numeros + 1):
            cursor.execute("INSERT INTO numeros (sorteo_id, numero, disponible) VALUES (?, ?, ?)", (sorteo_id, numero, 1))
        conn.commit()
        conn.close()

         # Mensaje llamativo de confirmación de creación de sorteo
        sorteo_creado_message = f"""
🎉 ¡Sorteo creado con éxito! 🎉

El sorteo **{nombre}** ha sido creado con los siguientes detalles:

*   🎁 Premio: {premio}
*   💲 Valor por número: {valor_numero}
*   🔢 Cantidad de números: {cantidad_numeros}

¡El sorteo ya está disponible para los usuarios! 🚀
"""
        bot.send_message(message.chat.id, sorteo_creado_message)
        enviar_log(f"Nuevo sorteo creado: {nombre} con ID {sorteo_id}")

    except Exception as e:
        logging.exception("Error al crear la cantidad de números")
         # Mensaje de error llamativo
        error_message = """
🤯 ¡Tenemos un problema! 🤯

Ocurrió un error inesperado en el bot. 🤖 Estamos trabajando para solucionarlo lo antes posible.

Por favor, inténtalo de nuevo más tarde. ¡Agradecemos tu comprensión! 😊
"""
        bot.send_message(message.chat.id, error_message)

# --- Funciones de manejo de errores ---

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    """Responde a cualquier mensaje no reconocido."""
     # Mensaje llamativo si el comando no es reconocido
    unknown_command_message = """
🤔 ¡Comando desconocido! 🤔

Lo sentimos, no reconocemos el comando que has enviado. 😥

Por favor, utiliza los comandos disponibles o contacta con nuestro equipo de soporte para obtener ayuda. ¡Gracias! 🙏
"""
    bot.send_message(message.chat.id, unknown_command_message)

# --- Inicialización ---

if __name__ == '__main__':
    crear_conexion()
    crear_tablas()
    print("Bot is running...")
    bot.infinity_polling()
