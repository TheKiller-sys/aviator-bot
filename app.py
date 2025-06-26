from flask import Flask, render_template, request, send_file
import sqlite3
from datetime import date
from io import BytesIO
import csv
import codecs
import os  # Importa el módulo 'os'
import telebot  # Importa la librería de Telebot
from telebot import types
from dotenv import load_dotenv # Importa la librería dotenv


load_dotenv() # Carga las variables de entorno desde el archivo .env

app = Flask(__name__)

DATABASE_NAME = "servicej.db"

# --- Configuración para Render ---
# Intenta obtener el puerto de las variables de entorno, si no, usa el puerto 5000
port = int(os.environ.get('PORT', 5000))

# --- Configuración del Bot de Telegram ---
# Obtén el token del bot de las variables de entorno
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # Obtén el ID del chat del administrador

if not BOT_TOKEN:
    raise ValueError("El token del bot de Telegram no está configurado en las variables de entorno.")

bot = telebot.TeleBot(BOT_TOKEN)

# --- Funciones de la Base de Datos ---

def get_vendedores():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre FROM vendedores")
    vendedores = cursor.fetchall()
    conn.close()
    return vendedores

def get_ventas_diarias(vendedor_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.nombre, v.cantidad_vendida, p.precio_venta, v.comision
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE v.vendedor_id = ? AND DATE(v.fecha) = DATE('now')
    """, (vendedor_id,))
    ventas = cursor.fetchall()
    conn.close()
    return ventas

def get_ganancias_diarias(vendedor_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM((p.precio_venta - p.precio_compra) * v.cantidad_vendida)
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE v.vendedor_id = ? AND DATE(v.fecha) = DATE('now')
    """, (vendedor_id,))
    ganancia = cursor.fetchone()[0] or 0
    conn.close()
    return ganancia

def get_comisiones_totales(vendedor_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM(v.comision)
        FROM ventas v
        WHERE v.vendedor_id = ? AND DATE(v.fecha) = DATE('now')
    """, (vendedor_id,))
    comision = cursor.fetchone()[0] or 0
    conn.close()
    return comision

def get_inventario_por_vendedor():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.id, v.nombre AS vendedor, p.nombre AS producto, i.cantidad_entregada
        FROM inventario i
        JOIN vendedores v ON i.vendedor_id = v.id
        JOIN productos p ON i.producto_id = p.id
        ORDER BY v.id
    """)
    rows = cursor.fetchall()
    conn.close()

    inventario_por_vendedor = {}
    for vendedor_id, vendedor_nombre, producto, cantidad in rows:
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
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.fecha, p.nombre AS producto, v.cantidad_vendida, p.precio_venta, 
               (v.cantidad_vendida * p.precio_venta) AS total, v.comision, ve.nombre as vendedor
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        JOIN vendedores ve ON v.vendedor_id = ve.id
    """)
    ventas = cursor.fetchall()
    conn.close()
    return ventas

def get_total_ventas_diarias():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM(p.precio_venta * v.cantidad_vendida)
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE DATE(v.fecha) = DATE('now')
    """)
    total_ventas = cursor.fetchone()[0] or 0
    conn.close()
    return total_ventas

# Ventas semanales y mensuales usando semanas y meses ISO (semana inicia lunes)
def get_ventas_semanales(vendedor_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM((p.precio_venta - p.precio_compra) * v.cantidad_vendida), SUM(v.comision)
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE v.vendedor_id = ?
          AND strftime('%W', v.fecha) = strftime('%W', DATE('now'))
          AND strftime('%Y', v.fecha) = strftime('%Y', DATE('now'))
    """, (vendedor_id,))
    resultado = cursor.fetchone()
    ganancia_semanal = resultado[0] or 0
    comision_semanal = resultado[1] or 0
    conn.close()
    return ganancia_semanal, comision_semanal

def get_ventas_mensuales(vendedor_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM((p.precio_venta - p.precio_compra) * v.cantidad_vendida), SUM(v.comision)
        FROM ventas v
        JOIN productos p ON v.producto_id = p.id
        WHERE v.vendedor_id = ?
          AND strftime('%m', v.fecha) = strftime('%m', DATE('now'))
          AND strftime('%Y', v.fecha) = strftime('%Y', DATE('now'))
    """, (vendedor_id,))
    resultado = cursor.fetchone()
    ganancia_mensual = resultado[0] or 0
    comision_mensual = resultado[1] or 0
    conn.close()
    return ganancia_mensual, comision_mensual

# --- Rutas de la aplicación ---

@app.route("/")
def index():
    vendedores = get_vendedores()
    total_ventas_diarias = get_total_ventas_diarias()
    inventario_por_vendedor = get_inventario_por_vendedor()
    all_ventas = get_all_ventas()

    vendedores_data = []
    for vendedor_id, nombre_vendedor in vendedores:
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
        if v[0] == vendedor_id:
            vendedor_nombre = v[1]
            break

    if not ventas:
        return "No hay ventas para este vendedor hoy.", 404

    csv_data = BytesIO()
    csv_writer = csv.writer(codecs.getwriter('utf-8')(csv_data))

    # Escribir la cabecera del CSV
    csv_writer.writerow(['Producto', 'Cantidad', 'Precio Unitario', 'Comisión'])

    # Escribir las filas de datos
    for producto, cantidad, precio, comision in ventas:
        csv_writer.writerow([producto, cantidad, f"{precio:.2f}", f"{comision:.2f}"])

    # Preparar la respuesta
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

    # Escribir la cabecera del CSV
    csv_writer.writerow(['Fecha', 'Producto', 'Cantidad', 'Precio', 'Total', 'Comisión', 'Vendedor'])

    # Escribir las filas de datos
    for venta in all_ventas_data:
        csv_writer.writerow(venta)

    # Preparar la respuesta
    csv_data.seek(0)
    return send_file(
        csv_data,
        mimetype='text/csv',
        as_attachment=True,
        download_name="todas_las_ventas.csv"
    )

# --- Funciones del Bot de Telegram ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """
    Maneja los comandos /start y /help.
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    item1 = types.KeyboardButton("/ventas_hoy")
    markup.add(item1)
    bot.send_message(message.chat.id, 
                     "Bienvenido! Este bot te permite obtener información sobre las ventas.\n"
                     "Usa /ventas_hoy para obtener un resumen de las ventas diarias.",
                     reply_markup=markup)


@bot.message_handler(commands=['ventas_hoy'])
def ventas_hoy(message):
    """
    Maneja el comando /ventas_hoy para mostrar un resumen de las ventas diarias.
    """
    total_ventas_diarias = get_total_ventas_diarias()
    vendedores = get_vendedores()
    inventario_por_vendedor = get_inventario_por_vendedor()

    # Construir el mensaje
    mensaje = f"📊 Resumen de Ventas Diarias ({date.today()}):\n\n"
    mensaje += f"💰 Total Ventas: ${total_ventas_diarias:.2f}\n\n"

    for vendedor_id, nombre_vendedor in vendedores:
        ganancias_diarias = get_ganancias_diarias(vendedor_id)
        comisiones_totales = get_comisiones_totales(vendedor_id)
        ganancia_semanal, comision_semanal = get_ventas_semanales(vendedor_id)
        ganancia_mensual, comision_mensual = get_ventas_mensuales(vendedor_id)
        inventario_vendedor = inventario_por_vendedor.get(vendedor_id, {'productos': []})

        mensaje += f"👤 Vendedor: {nombre_vendedor}\n"
        mensaje += f"   - 📈 Ganancias Diarias: ${ganancias_diarias:.2f}\n"
        mensaje += f"   - 💰 Comisiones Diarias: ${comisiones_totales:.2f}\n"
        mensaje += f"   - 🗓️ Ganancia Semanal: ${ganancia_semanal:.2f}\n"
        mensaje += f"   - 💸 Comisión Semanal: ${comision_semanal:.2f}\n"
        mensaje += f"   - 🗓️ Ganancia Mensual: ${ganancia_mensual:.2f}\n"
        mensaje += f"   - 💸 Comisión Mensual: ${comision_mensual:.2f}\n"

        # Agregar información del inventario
        if inventario_vendedor['productos']:
            mensaje += "   - 📦 Inventario:\n"
            for producto in inventario_vendedor['productos']:
                mensaje += f"      - {producto['producto']}: {producto['cantidad']}\n"
        else:
            mensaje += "   - 📦 Inventario: No hay inventario asignado\n"

        mensaje += "\n"

    bot.send_message(message.chat.id, mensaje)


# --- Iniciar el bot de Telegram ---
def start_telegram_bot():
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Error al iniciar el bot de Telegram: {e}")

# --- Manejo de errores del bot ---
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    """
    Responde a cualquier otro mensaje con un mensaje de error genérico.
    """
    bot.reply_to(message, "Lo siento, no entiendo ese comando. Usa /help para ver los comandos disponibles.")

# --- Ejecución principal ---
if __name__ == "__main__":
    # Importante: Ejecuta el bot de Telegram en un hilo separado
    import threading
    telegram_thread = threading.Thread(target=start_telegram_bot)
    telegram_thread.daemon = True  # Permite que el programa termine incluso si el hilo del bot está activo
    telegram_thread.start()

    # Ejecuta la aplicación Flask
    app.run(debug=False, host='0.0.0.0', port=port)  # Escucha en todas las interfaces en el puerto especificado