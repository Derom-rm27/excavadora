import time
import datetime
import os
import sys
from picamera2 import Picamera2

# --- CONFIGURACIÓN Y RUTAS ---
# Usando el usuario confirmado: trazmape
USUARIO_LINUX = "trazmape"
LOG_FILE = f"/home/{USUARIO_LINUX}/proyecto/camera_log.txt"
OUTPUT_FOLDER = f"/home/{USUARIO_LINUX}/proyecto/capturas"
RESOLUTION = (640, 480)
TIEMPO_ENTRE_CAPTURAS_SEGUNDOS = 30  # Capturar una imagen cada 30 segundos


# --- FUNCIONES DE SOPORTE ---

def log_message(message):
    """Función simple para registrar eventos en el archivo de log."""
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.datetime.now()}: {message}\n")
        print(f"LOG: {message}", file=sys.stdout)  # Imprimir en stdout/journalctl
    except Exception as e:
        # Fallo al escribir el log (posiblemente problemas de permisos)
        print(f"FALLO CRÍTICO DE LOG: {e}", file=sys.stderr)


def initialize_camera():
    """Inicializa la cámara Picamera2 una sola vez."""
    log_message("Intentando inicializar la cámara...")
    try:
        picam2 = Picamera2()
        camera_config = picam2.create_still_configuration(main={"size": RESOLUTION})
        picam2.configure(camera_config)
        picam2.start()
        # Tiempo para que la cámara se ajuste
        time.sleep(2)
        log_message("Cámara inicializada, lista para el bucle de captura.")
        return picam2
    except Exception as e:
        log_message(f"ERROR FATAL al inicializar la cámara: {e}")
        # Systemd intentará reiniciar
        sys.exit(1)


def run_capture_loop(picam2):
    """Bucle infinito para capturar imágenes periódicamente."""
    log_message(f"Iniciando bucle de captura (Intervalo: {TIEMPO_ENTRE_CAPTURAS_SEGUNDOS}s).")

    while True:
        try:
            # Genera nombre del archivo con timestamp
            filename = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".jpg"
            filepath = os.path.join(OUTPUT_FOLDER, filename)

            # Captura la imagen
            picam2.capture_file(filepath)
            log_message(f"Imagen capturada exitosamente: {filepath}")

        except Exception as e:
            # Error durante la captura, no es necesariamente fatal
            log_message(f"ERROR durante la captura: {e}")

        # Esperar el tiempo configurado antes de la próxima captura
        time.sleep(TIEMPO_ENTRE_CAPTURAS_SEGUNDOS)


# --- EJECUCIÓN PRINCIPAL ---

if __name__ == "__main__":
    # 1. Asegurarse de que el directorio de salida exista
    if not os.path.exists(OUTPUT_FOLDER):
        try:
            os.makedirs(OUTPUT_FOLDER)
            log_message(f"Carpeta de salida creada: {OUTPUT_FOLDER}")
        except Exception as e:
            log_message(f"ERROR: No se pudo crear la carpeta de salida {OUTPUT_FOLDER}. {e}")
            sys.exit(1)

    # 2. Inicializar la cámara (solo una vez)
    camara = initialize_camera()

    # 3. Iniciar el bucle de captura
    run_capture_loop(camara)