import sqlite3
import logging
import os
from dotenv import load_dotenv

load_dotenv("config.env")

DATABASE_NAME = os.getenv("DATABASE_NAME")

def crear_conexion():
    """Crea una conexión a la base de datos SQLite."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        print(f"Conexión a la base de datos {DATABASE_NAME} establecida.")
    except sqlite3.Error as e:
        logging.error(f"Error al conectar a la base de datos: {e}")
    return conn

def crear_tablas():
    """Crea las tablas necesarias en la base de datos."""
    conn = crear_conexion()
    if conn is not None:
        try:
            cursor = conn.cursor()

            # Tabla de usuarios
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    sorteos_ganados INTEGER DEFAULT 0,
                    dinero_ganado REAL DEFAULT 0.0,
                    sorteos_participados INTEGER DEFAULT 0,
                    mayor_ganancia REAL DEFAULT 0.0
                )
            """)

            # Tabla de sorteos
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sorteos (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT,
                    premio TEXT,
                    valor_numero REAL,
                    cantidad_numeros INTEGER,
                    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Tabla de numeros (para cada sorteo)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS numeros (
                    id INTEGER PRIMARY KEY,
                    sorteo_id INTEGER,
                    numero INTEGER,
                    disponible INTEGER DEFAULT 1,  -- 1 = disponible, 0 = reservado
                    FOREIGN KEY (sorteo_id) REFERENCES sorteos(id)
                )
            """)

            # Tabla de reservas
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reservas (
                    id INTEGER PRIMARY KEY,
                    usuario_id INTEGER,
                    sorteo_id INTEGER,
                    numero INTEGER,
                    fecha_reserva DATETIME DEFAULT CURRENT_TIMESTAMP,
                    estado TEXT DEFAULT 'pendiente',  -- 'pendiente', 'confirmada', 'rechazada'
                    captura_url TEXT,  -- URL o path de la captura de pantalla
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
                    FOREIGN KEY (sorteo_id) REFERENCES sorteos(id)
                )
            """)

            conn.commit()
            print("Tablas creadas exitosamente.")
        except sqlite3.Error as e:
            logging.error(f"Error al crear tablas: {e}")
        finally:
            conn.close()
    else:
        logging.error("No se pudo crear la conexión para crear tablas.")

def ejecutar_consulta(query, params=()):
    """Ejecuta una consulta SQL y devuelve los resultados."""
    conn = crear_conexion()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.fetchall()  # Devuelve los resultados
        except sqlite3.Error as e:
            logging.error(f"Error al ejecutar la consulta '{query}': {e}")
        finally:
            conn.close()
    else:
        logging.error(f"No se pudo crear la conexión para ejecutar la consulta '{query}'.")
    return None  # En caso de error, devuelve None

def obtener_conexion():
    """Devuelve una conexión a la base de datos."""
    return crear_conexion()

if __name__ == '__main__':
    # Ejemplo de uso
    crear_tablas()