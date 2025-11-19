import io
import time
import picamera2
from http import server
import threading
import socketserver
import sys

# --- CONFIGURACIÓN ---
# Puerto por el cual se transmitirá el video.
PORT = 8080
# Resolución del stream.
RESOLUTION = (640, 480)


# Clase para capturar los fotogramas y guardarlos en un buffer en memoria.
class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.lock = threading.Lock()

    def write(self, buf):
        # Bloqueamos el acceso para asegurar que la escritura del frame sea atómica.
        with self.lock:
            self.frame = buf
            return len(buf)


# Clase para manejar las peticiones HTTP y enviar el stream MJPEG.
class StreamingHandler(server.BaseHTTPRequestHandler):

    # Maneja las peticiones GET de los clientes.
    def do_GET(self):

        # Ruta principal para un navegador (opcional, muestra el stream incrustado).
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            # HTML simple para mostrar el video.feed en una etiqueta <img>
            content = b'<html><head><title>Picamera2 MJPEG Stream</title></head><body><h1>MJPEG Stream</h1><img src="/video.feed" width="%d" height="%d" /></body></html>' % RESOLUTION
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        # RUTA CLAVE: Envía el stream continuo de JPEG.
        elif self.path == '/video.feed':
            self.send_response(200)
            self.send_header('Age', '0')
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            # Establece el tipo de contenido como Multipart/x-mixed-replace (MJPEG).
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()

            try:
                while True:
                    # Leemos el frame del buffer compartido.
                    with output.lock:
                        frame = output.frame

                    if frame:
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(frame)))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.01)  # Pequeña pausa para evitar sobrecarga.
            except Exception as e:
                # Se lanza al desconectarse el cliente (es normal).
                print(f"Streaming client disconnected: {e}", file=sys.stderr)
        else:
            self.send_error(404)
            self.end_headers()


# Servidor multihilo para manejar múltiples clientes de streaming.
class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


# --- INICIO DEL PROGRAMA ---

if __name__ == '__main__':
    # Inicialización de la cámara
    picam2 = picamera2.Picamera2()
    picam2.configure(picam2.create_video_configuration(main={"size": RESOLUTION}))
    output = StreamingOutput()

    try:
        # Iniciamos la grabación. Usamos argumentos nombrados (encoder=encoder, output=output)
        # para evitar el error "Must pass Output".
        encoder = picamera2.encoders.MJPEGEncoder()
        picam2.start_recording(encoder=encoder, output=output)

        # Iniciamos el servidor HTTP
        address = ('0.0.0.0', PORT)
        server_obj = StreamingServer(address, StreamingHandler)
        print(f"Servidor MJPEG iniciado. Accede a http://[TU_IP_TAILSCALE]:{PORT}/video.feed")
        server_obj.serve_forever()

    except KeyboardInterrupt:
        print("Servidor detenido por el usuario.")
    except Exception as e:
        print(f"Error fatal del servidor: {e}", file=sys.stderr)
    finally:
        # Detenemos la cámara y limpiamos.
        if 'picam2' in locals() and picam2.started:
            picam2.stop_recording()
            picam2.stop()