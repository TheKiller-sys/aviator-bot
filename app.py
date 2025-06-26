import threading
import logging
import os
import sqlite3
from datetime import date
from io import BytesIO
import csv
import codecs

from flask import Flask, render_template, send_file
import telebot
from telebot import types
from dotenv import load_dotenv

# --- Carga configuración ---
load_dotenv("config.env")
TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
DATABASE_NAME = "servicej.db"
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "YOUR_ADMIN_CHAT_ID")

# --- Configuración logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Flask app ---
app = Flask(__name__)

# --- Funciones comunes de base de datos (unificadas) ---

def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    # Para que devuelva filas como diccionarios (más cómodo)
    conn.row_factory = sqlite3.Row
    return conn

# --- Funciones para Flask (adaptadas) ---

def get_vendedores():
    conn = get_db_connection()
    vendedores = conn.execute("SELECT id, nombre FROM vendedores").fetchall()
    conn.close()
    return vendedores

def get_ventas_diarias(vendedor_id):
    conn = get_db_connection()
    ventas = conn.execute("""
        SELECT p.nombre, v.cantidad_vendida, p.precio_venta, v.comision
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE v.vendedor_id = ? AND DATE(v.fecha) = DATE('now')
    """, (vendedor_id,)).fetchall()
    conn.close()
    return ventas

def get_ganancias_diarias(vendedor_id):
    conn = get_db_connection()
    ganancia = conn.execute("""
        SELECT SUM((p.precio_venta - p.precio_compra) * v.cantidad_vendida)
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE v.vendedor_id = ? AND DATE(v.fecha) = DATE('now')
    """, (vendedor_id,)).fetchone()[0] or 0
    conn.close()
    return ganancia

def get_comisiones_totales(vendedor_id):
    conn = get_db_connection()
    comision = conn.execute("""
        SELECT SUM(v.comision)
        FROM ventas v
        WHERE v.vendedor_id = ? AND DATE(v.fecha) = DATE('now')
    """, (vendedor_id,)).fetchone()[0] or 0
    conn.close()
    return comision

def get_inventario_por_vendedor():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT v.id, v.nombre AS vendedor, p.nombre AS producto, i.cantidad_entregada
        FROM inventario i
        JOIN vendedores v ON i.vendedor_id = v.id
        JOIN productos p ON i.producto_id = p.id
        ORDER BY v.id
    """).fetchall()
    conn.close()

    inventario_por_vendedor = {}
    for row in rows:
        vendedor_id = row["id"]
        vendedor_nombre = row["vendedor"]
        producto = row["producto"]
        cantidad = row["cantidad_entregada"]
        if vendedor_id not in inventario_por_vendedor:
            inventario_por_vendedor[vendedor_id] = {
                'nombre': vendedor_nombre,
                'productos': []
            }
        inventario_por_vendedor[vendedor_id]['productos'].append({
            'producto': producto,
            'cantidad': cantidad
        })
    return inventario_por_vendedor

def get_all_ventas():
    conn = get_db_connection()
    ventas = conn.execute("""
        SELECT v.fecha, p.nombre AS producto, v.cantidad_vendida, p.precio_venta, 
               (v.cantidad_vendida * p.precio_venta) AS total, v.comision, ve.nombre as vendedor
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        JOIN vendedores ve ON v.vendedor_id = ve.id
    """).fetchall()
    conn.close()
    return ventas

def get_total_ventas_diarias():
    conn = get_db_connection()
    total_ventas = conn.execute("""
        SELECT SUM(p.precio_venta * v.cantidad_vendida)
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE DATE(v.fecha) = DATE('now')
    """).fetchone()[0] or 0
    conn.close()
    return total_ventas

def get_ventas_semanales(vendedor_id):
    conn = get_db_connection()
    resultado = conn.execute("""
        SELECT SUM((p.precio_venta - p.precio_compra) * v.cantidad_vendida), SUM(v.comision)
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE v.vendedor_id = ?
          AND strftime('%W', v.fecha) = strftime('%W', DATE('now'))
          AND strftime('%Y', v.fecha) = strftime('%Y', DATE('now'))
    """, (vendedor_id,)).fetchone()
    conn.close()
    ganancia_semanal = resultado[0] or 0
    comision_semanal = resultado[1] or 0
    return ganancia_semanal, comision_semanal

def get_ventas_mensuales(vendedor_id):
    conn = get_db_connection()
    resultado = conn.execute("""
        SELECT SUM((p.precio_venta - p.precio_compra) * v.cantidad_vendida), SUM(v.comision)
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE v.vendedor_id = ?
          AND strftime('%m', v.fecha) = strftime('%m', DATE('now'))
          AND strftime('%Y', v.fecha) = strftime('%Y', DATE('now'))
    """, (vendedor_id,)).fetchone()
    conn.close()
    ganancia_mensual = resultado[0] or 0
    comision_mensual = resultado[1] or 0
    return ganancia_mensual, comision_mensual

@app.route("/")
def index():
    vendedores = get_vendedores()
    total_ventas_diarias = get_total_ventas_diarias()
    inventario_por_vendedor = get_inventario_por_vendedor()
    all_ventas = get_all_ventas()

    vendedores_data = []
    for vendedor in vendedores:
        vendedor_id = vendedor["id"]
        nombre_vendedor = vendedor["nombre"]
        ventas_diarias = get_ventas_diarias(vendedor_id)
        ganancias_diarias = get_ganancias_diarias(vendedor_id)
        comisiones_totales = get_comisiones_totales(vendedor_id)
        ganancia_semanal, comision_semanal = get_ventas_semanales(vendedor_id)
        ganancia_mensual, comision_mensual = get_ventas_mensuales(vendedor_id)

        inventario_vendedor = inventario_por_vendedor.get(vendedor_id, {'productos': []})

        vendedores_data.append({
            'id': vendedor_id,
            'nombre': nombre_vendedor,
            'ventas_diarias': ventas_diarias,
            'ganancias_diarias': ganancias_diarias,
            'comisiones_totales': comisiones_totales,
            'ganancia_semanal': ganancia_semanal,
            'comision_semanal': comision_semanal,
            'ganancia_mensual': ganancia_mensual,
            'comision_mensual': comision_mensual,
            'inventario': inventario_vendedor['productos']
        })

    return render_template(
        "index.html",
        vendedores=vendedores_data,
        total_ventas_diarias=total_ventas_diarias,
        all_ventas=all_ventas,
        today=date.today()
    )

@app.route("/exportar_csv/<int:vendedor_id>")
def exportar_csv(vendedor_id):
    ventas = get_ventas_diarias(vendedor_id)
    vendedor_nombre = None
    for v in get_vendedores():
        if v["id"] == vendedor_id:
            vendedor_nombre = v["nombre"]
            break

    if not ventas:
        return "No hay ventas para este vendedor hoy.", 404

    csv_data = BytesIO()
    csv_writer = csv.writer(codecs.getwriter('utf-8')(csv_data))

    csv_writer.writerow(['Producto', 'Cantidad', 'Precio Unitario', 'Comisión'])
    for venta in ventas:
        csv_writer.writerow([venta["nombre"], venta["cantidad_vendida"], f"{venta['precio_venta']:.2f}", f"{venta['comision']:.2f}"])

    csv_data.seek(0)
    return send_file(
        csv_data,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"ventas_diarias_{vendedor_nombre}.csv"
    )

@app.route("/exportar_csv_all")
def exportar_csv_all():
    all_ventas_data = get_all_ventas()
    if not all_ventas_data:
        return "No hay ventas registradas.", 404

    csv_data = BytesIO()
    csv_writer = csv.writer(codecs.getwriter('utf-8')(csv_data))

    csv_writer.writerow(['Fecha', 'Producto', 'Cantidad', 'Precio', 'Total', 'Comisión', 'Vendedor'])
    for venta in all_ventas_data:
        csv_writer.writerow(venta)

    csv_data.seek(0)
    return send_file(
        csv_data,
        mimetype='text/csv',
        as_attachment=True,
        download_name="todas_las_ventas.csv"
    )


# --- Funciones y lógica del bot Telegram (unificadas) ---

bot = telebot.TeleBot(TOKEN)

USUARIOS_INICIALES = [
    ("Pauly", "Pauly", "Pauly"),
    ("Enrique", "Enrique", "Enrique"),
    ("Quiosco", "Quiosco", "Quiosco"),
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

USUARIO = {}
VENTA = {}
MENSAJES = {}

MENSAJES_BIENVENIDA = {
    1: """
    ¡Hola Pauly! 👋

    ¡Listo para un día de ventas exitosas? 🚀
    ¡Vamos a superar esos objetivos! 💪
    """,
    2: """
    ¡Hola Enrique! 👋

    ¡A brillar hoy! ✨
    ¡Cada venta te acerca a tus sueños! 🌟
    """,
    3: """
    ¡Hola Quiosco! 👋

    Aquí podrás anotar todas tus ventas 📝
    y llevar un mejor control. 📊
    """,
}

# --- Funciones base de datos bot ---

def create_database():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vendedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                contrasena TEXT NOT NULL,
                nombre TEXT NOT NULL
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
        logging.info("Base de datos y tablas creadas o ya existentes.")
        conn.close()

    except sqlite3.Error as e:
        logging.error(f"Error al crear la base de datos: {e}")
        raise

def insertar_datos_iniciales():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        for usuario, contrasena, nombre in USUARIOS_INICIALES:
            try:
                cursor.execute("INSERT INTO vendedores (usuario, contrasena, nombre) VALUES (?, ?, ?)", (usuario, contrasena, nombre))
            except sqlite3.IntegrityError:
                logging.warning(f"El vendedor {usuario} ya existe.")

        for nombre, precio_compra, precio_venta in PRODUCTOS_INICIALES:
             try:
                cursor.execute("INSERT INTO productos (nombre, precio_compra, precio_venta) VALUES (?, ?, ?)", (nombre, precio_compra, precio_venta))
             except sqlite3.IntegrityError:
                logging.warning(f"El producto {nombre} ya existe.")

        for vendedor_id, producto_id, cantidad_entregada in INVENTARIO_INICIAL:
             try:
                cursor.execute("INSERT INTO inventario (vendedor_id, producto_id, cantidad_entregada) VALUES (?, ?, ?)", (vendedor_id, producto_id, cantidad_entregada))
             except sqlite3.IntegrityError:
                logging.warning(f"El inventario para el vendedor {vendedor_id} y producto {producto_id} ya existe.")

        conn.commit()
        logging.info("Datos iniciales insertados en la base de datos.")
        conn.close()

    except sqlite3.Error as e:
        logging.error(f"Error al insertar datos iniciales: {e}")
        conn.rollback()
        conn.close()

def get_vendedor(usuario):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre, contrasena FROM vendedores WHERE usuario = ?", (usuario,))
        result = cursor.fetchone()
        conn.close()
        return result
    except sqlite3.Error as e:
        logging.error(f"Error al obtener vendedor: {e}")
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
        logging.error(f"Error al obtener productos: {e}")
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
        logging.error(f"Error al obtener producto: {e}")
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
        logging.error(f"Error al obtener inventario: {e}")
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
            nombre_producto = producto[2]
            ganancia_por_unidad = precio_venta - precio_compra
            comision_vendedor = 0.20 * ganancia_por_unidad * cantidad_vendida

            cursor.execute("INSERT INTO ventas (vendedor_id, producto_id, cantidad_vendida, comision) VALUES (?, ?, ?, ?)",
                           (vendedor_id, producto_id, cantidad_vendida, comision_vendedor))

            cursor.execute("UPDATE inventario SET cantidad_entregada = cantidad_entregada - ? WHERE vendedor_id = ? AND producto_id = ?",
                           (cantidad_vendida, vendedor_id, producto_id))

            conn.commit()
            logging.info(f"Venta registrada: Vendedor {vendedor_id}, Producto {producto_id}, Cantidad {cantidad_vendida}, Comisión: ${comision_vendedor:.2f}")
            conn.close()

            # Notificación admin
            vendedor_info = get_vendedor_by_id(vendedor_id)
            vendedor_nombre = vendedor_info[1] if vendedor_info else "Unknown"
            notification_message = (f"Nueva venta registrada:\n"
                                    f"Vendedor: {vendedor_nombre} (ID: {vendedor_id})\n"
                                    f"Producto: {nombre_producto} (ID: {producto_id})\n"
                                    f"Cantidad: {cantidad_vendida}\n"
                                    f"Comisión del vendedor: ${comision_vendedor:.2f}")
            bot.send_message(ADMIN_CHAT_ID, notification_message)
            return True
        else:
            logging.error(f"Producto con ID {producto_id} no encontrado.")
            conn.close()
            return False

    except sqlite3.Error as e:
        logging.error(f"Error al registrar venta: {e}")
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
        logging.error(f"Error al obtener ventas diarias: {e}")
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
        logging.error(f"Error al obtener cantidad disponible: {e}")
        return 0

def crear_sesion(chat_id, vendedor_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO sesiones (chat_id, vendedor_id, fecha_inicio) VALUES (?, ?, ?)",
                       (chat_id, vendedor_id, date.today()))
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        logging.error(f"Error al crear la sesión: {e}")
        conn.rollback()
        conn.close()
        return False

def verificar_sesion_activa(chat_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT vendedor_id FROM sesiones WHERE chat_id = ?", (chat_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except sqlite3.Error as e:
        logging.error(f"Error al verificar sesión: {e}")
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
        logging.error(f"Error al cerrar sesión: {e}")
        conn.rollback()
        conn.close()
        return False

def get_vendedor_by_id(vendedor_id):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre FROM vendedores WHERE id = ?", (vendedor_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    except sqlite3.Error as e:
        logging.error(f"Error al obtener vendedor por ID: {e}")
        return None

# --- Handlers del bot Telegram ---

@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    vendedor_id_sesion = verificar_sesion_activa(chat_id)

    if vendedor_id_sesion:
        vendedor_info = get_vendedor_by_id(vendedor_id_sesion)
        if vendedor_info:
            nombre_vendedor = vendedor_info[1]
            USUARIO[chat_id] = {"estado": "logeado", "vendedor_id": vendedor_id_sesion, "nombre": nombre_vendedor}
            mostrar_menu_principal(message)
            return

    markup = types.InlineKeyboardMarkup()
    boton_inicio_sesion = types.InlineKeyboardButton("¡Inicia Sesión y Comienza a Ganar! 🔑", callback_data='inicio_sesion')
    markup.add(boton_inicio_sesion)

    mensaje_bienvenida = """
    ¡Bienvenido a ServiceJ Bot! 👋

    Aquí puedes registrar tus ventas diarias. 📝
    ¡Impulsa tus ganancias, cada venta cuenta! 🚀
    """
    MENSAJES[chat_id] = bot.send_message(chat_id, mensaje_bienvenida, reply_markup=markup).message_id

@bot.callback_query_handler(func=lambda call: call.data == 'inicio_sesion')
def inicio_sesion(call):
    chat_id = call.message.chat.id
    USUARIO[chat_id] = {"estado": "esperando_usuario", "vendedor_id": None, "nombre": None}
    markup = types.InlineKeyboardMarkup()
    bot.edit_message_text("Por favor, ingresa tu usuario 👤:", chat_id, MENSAJES.get(chat_id), reply_markup=markup)

@bot.message_handler(func=lambda message: USUARIO.get(message.chat.id, {}).get("estado") == "esperando_usuario")
def recibir_usuario(message):
    chat_id = message.chat.id
    usuario = message.text
    vendedor = get_vendedor(usuario)
    if vendedor:
        USUARIO[chat_id]["vendedor_id"] = vendedor[0]
        USUARIO[chat_id]["nombre"] = vendedor[1]
        USUARIO[chat_id]["contrasena"] = vendedor[2]
        USUARIO[chat_id]["estado"] = "esperando_contrasena"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_inicio'))
        msg = bot.send_message(chat_id, "Usuario correcto ✅. ¡Ingresa tu contraseña para acceder! 🔒:", reply_markup=markup)
        MENSAJES[chat_id] = msg.message_id
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_inicio'))
        msg = bot.send_message(chat_id, "Usuario incorrecto ❌. Intenta de nuevo o contacta al administrador.", reply_markup=markup)
        MENSAJES[chat_id] = msg.message_id
    bot.delete_message(chat_id=chat_id, message_id=message.message_id)

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
        msg = bot.send_message(chat_id, "Contraseña incorrecta ❌. Intenta de nuevo.", reply_markup=markup)
        MENSAJES[chat_id] = msg.message_id
    bot.delete_message(chat_id=chat_id, message_id=message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == 'volver_inicio')
def volver_inicio(call):
    chat_id = call.message.chat.id
    USUARIO[chat_id] = {}
    cmd_start(call.message)

def mostrar_menu_principal(message):
    chat_id = message.chat.id
    vendedor_id = USUARIO[chat_id]["vendedor_id"]
    nombre_vendedor = USUARIO[chat_id]["nombre"]

    mensaje_bienvenida = MENSAJES_BIENVENIDA.get(vendedor_id, f"""
    ¡Hola {nombre_vendedor}! 👋

    ¡Listo para superar tus objetivos de hoy? 💪
    """)

    markup = types.InlineKeyboardMarkup()
    boton_venta = types.InlineKeyboardButton("Registrar Venta 💰", callback_data='venta')
    boton_historial = types.InlineKeyboardButton("Ver Historial Diario 📊", callback_data='historial')
    boton_cerrar_sesion = types.InlineKeyboardButton("Cerrar Sesión 🚪", callback_data='cerrar_sesion')
    markup.add(boton_venta, boton_historial)
    markup.add(boton_cerrar_sesion)

    try:
        bot.edit_message_text(mensaje_bienvenida + "\nSelecciona una opción para continuar:", chat_id, MENSAJES.get(chat_id), reply_markup=markup)
    except telebot.apihelper.ApiTelegramException as e:
        logging.error(f"Error al editar mensaje: {e}")
        bot.send_message(chat_id, mensaje_bienvenida + "\nSelecciona una opción para continuar:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'cerrar_sesion')
def cerrar_sesion_handler(call):
    chat_id = call.message.chat.id
    cerrar_sesion(chat_id)
    USUARIO[chat_id] = {}
    cmd_start(call.message)

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
        bot.edit_message_text("¿Qué producto vendiste? 📦\n¡Elige el producto para registrar tu venta! 🚀", chat_id, MENSAJES.get(chat_id), reply_markup=markup)
    else:
        bot.edit_message_text("No hay productos disponibles. Contacta al administrador.", chat_id, MENSAJES.get(chat_id))

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
    msg = bot.send_message(chat_id, f"¡Excelente! Has seleccionado {nombre_producto} ✅ ¿Cuántas unidades vendiste? 🔢\n¡Ingresa la cantidad para registrar tus ganancias! 💰", reply_markup=markup)
    MENSAJES[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'cancelar_venta' and VENTA.get(call.message.chat.id, {}).get("estado") == "esperando_producto")
def cancelar_venta(call):
    chat_id = call.message.chat.id
    del VENTA[chat_id]
    mostrar_menu_principal(call.message)

@bot.callback_query_handler(func=lambda call: call.data == 'volver_productos')
def volver_productos(call):
    iniciar_venta(call)

@bot.callback_query_handler(func=lambda call: call.data == 'volver_menu')
def volver_menu(call):
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
        msg = bot.send_message(chat_id, "Cantidad inválida ❌. Debe ser un número entero positivo.", reply_markup=markup)
        MENSAJES[chat_id] = msg.message_id
        bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        return

    vendedor_id = USUARIO[chat_id]["vendedor_id"]
    producto_id = VENTA[chat_id]["producto_id"]
    inventario_actual = get_inventario(vendedor_id, producto_id)

    if inventario_actual < cantidad:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_productos'))
        msg = bot.send_message(chat_id, f"No hay suficiente inventario 😞. Tienes {inventario_actual} unidades disponibles.", reply_markup=markup)
        MENSAJES[chat_id] = msg.message_id
        bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        return

    producto = get_producto(producto_id)
    nombre_producto = producto[2]

    if registrar_venta(vendedor_id, producto_id, cantidad):
        del VENTA[chat_id]
        mostrar_menu_principal(message)
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Volver", callback_data='volver_productos'))
        msg = bot.send_message(chat_id, "Error al registrar la venta ❌. Contacta al administrador.", reply_markup=markup)
        MENSAJES[chat_id] = msg.message_id
    bot.delete_message(chat_id=chat_id, message_id=message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == 'historial' and USUARIO.get(call.message.chat.id, {}).get("estado") == "logeado")
def mostrar_historial_diario(call):
    chat_id = call.message.chat.id
    vendedor_id = USUARIO[chat_id]["vendedor_id"]
    ventas_diarias = obtener_ventas_diarias(vendedor_id)

    mensaje = "🎉 ¡Aquí está tu resumen de ventas diarias! 📊\n"
    total_ganancias = 0
    total_comisiones = 0

    for nombre_producto, cantidad_vendida, total_venta, comision, producto_id in ventas_diarias:
        cantidad_disponible = obtener_cantidad_disponible(vendedor_id, producto_id)
        mensaje += f"- {nombre_producto}: {cantidad_vendida} unidades - Total: ${total_venta:.2f} - Comisión: ${comision:.2f} - Disponible: {cantidad_disponible}\n"
        total_ganancias += total_venta
        total_comisiones += comision

    mensaje += f"\n¡Venta Total del Día: ${total_ganancias:.2f} 🎉"
    mensaje += f"\n¡Comisión Total del Día: ${total_comisiones:.2f} 💰"
    mensaje += "\n¡Excelente trabajo! ¡Sigue así para alcanzar tus objetivos! 🚀"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Volver al menú principal", callback_data='volver_menu'))
    bot.edit_message_text(mensaje, chat_id, MENSAJES.get(chat_id), reply_markup=markup)

# --- Función para ejecutar bot en hilo separado ---

def run_bot():
    create_database()
    insertar_datos_iniciales()
    logging.info("Bot iniciado.")
    bot.infinity_polling()

# --- Punto de entrada principal ---

if __name__ == "__main__":
    # Ejecutar bot en hilo separado para no bloquear Flask
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Ejecutar Flask
    logging.info("Iniciando servidor Flask...")
    app.run(host='0.0.0.0', port=5000, debug=True)
