import time
import datetime
import io
import threading
from http import server
import sys
import os

# Dependencias cruciales para streaming y arrays
from picamera2 import Picamera2
import numpy as np
import cv2  # Importado para cv2.imencode

# --- CONFIGURACIÓN DE LA CÁMARA Y SERVIDOR ---
USUARIO_LINUX = "trazmape"
PORT = 8000
RESOLUTION = (640, 480)
FPS = 15  # Tasa de frames por segundo

# Objetos de comunicación entre hilos
output = io.BytesIO()
lock = threading.Lock()
picam2 = None


# --- CLASE DE STREAMING (Manejador HTTP) ---

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/stream':
            self.send_response(200)
            self.send_header('Age', '0')
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()

            try:
                while True:
                    with lock:
                        frame = output.getvalue()

                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(frame)))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
                    time.sleep(1 / FPS)  # Controla la velocidad de envío
            except Exception as e:
                print(f'Cliente desconectado: {e}')
        else:
            self.send_error(404)


class StreamingServer(server.HTTPServer):
    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.output = output
        self.lock = lock


# --- FUNCIÓN DE CÁMARA ---

def start_camera_thread():
    """Configura e inicializa la cámara en un hilo."""
    global picam2
    try:
        picam2 = Picamera2()

        # Usar la configuración de video para streaming continuo
        video_config = picam2.create_video_configuration(main={"size": RESOLUTION, "format": "RGB888"})
        picam2.configure(video_config)
        picam2.start()
        print("Cámara inicializada, comenzando captura continua.")

        # Bucle de captura continua
        while True:
            # Captura el frame como un array (NumPy)
            buffer = picam2.capture_array()

            # Codifica el array a JPEG
            is_success, im_buf_arr = cv2.imencode(".jpg", buffer)

            if is_success:
                with lock:
                    output.seek(0)
                    output.truncate()
                    output.write(im_buf_arr.tobytes())

            # No se necesita 'sleep' aquí; el flujo es continuo.

    except Exception as e:
        print(f"ERROR en el hilo de cámara: {e}", file=sys.stderr)
    finally:
        if picam2:
            picam2.stop()
            print("Cámara detenida.")


# --- EJECUCIÓN PRINCIPAL ---

if __name__ == '__main__':
    # 1. Iniciar el hilo de la cámara
    camera_thread = threading.Thread(target=start_camera_thread)
    camera_thread.daemon = True
    camera_thread.start()

    # 2. Iniciar el servidor web en el hilo principal
    try:
        address = ('0.0.0.0', PORT)
        server = StreamingServer(address, StreamingHandler)
        print(f'Iniciando streaming en http://[IP_DE_LINUX]:{PORT}/stream')
        server.serve_forever()
    except Exception as e:
        print(f"ERROR FATAL al iniciar el servidor: {e}", file=sys.stderr)