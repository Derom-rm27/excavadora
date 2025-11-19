import io
import time
import picamera2
from http import server
import threading
import socketserver

# --- CONFIGURACIÓN ---
PORT = 8080
RESOLUTION = (640, 480)


# Clase para capturar los fotogramas y guardarlos en la memoria (buffer)
class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.lock = threading.Lock()

    def write(self, buf):
        with self.lock:
            self.frame = buf
            return len(buf)


# Clase para manejar las peticiones HTTP
class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        # 404 NOT FOUND - Error que tenías
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = b'<html><head><title>Picamera2 MJPEG Stream</title></head><body><h1>MJPEG Stream</h1><img src="/video.feed" width="%d" height="%d" /></body></html>' % RESOLUTION
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        # 200 OK - Ruta correcta para el streaming
        elif self.path == '/video.feed':
            self.send_response(200)
            self.send_header('Age', '0')
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.lock:
                        frame = output.frame
                    if frame:
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(frame)))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.03)  # Pequeña pausa
            except Exception as e:
                # El cliente se desconectó
                print(f"Streaming client disconnected: {e}")
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


# --- INICIO DEL PROGRAMA ---

if __name__ == "__main__":
    picam2 = picamera2.Picamera2()
    picam2.configure(picam2.create_video_configuration(main={"size": RESOLUTION}))
    output = StreamingOutput()

    # El encoder (codificador) MJPEG envía los datos a la clase StreamingOutput
    picam2.start_recording(picamera2.encoders.MJPEGEncoder(), output)

    try:
        address = ('', PORT)
        server_obj = StreamingServer(address, StreamingHandler)
        print(f"Iniciando streaming en http://[IP_DE_TAILSCALE]:{PORT}")
        server_obj.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        picam2.stop_recording()
        picam2.stop()