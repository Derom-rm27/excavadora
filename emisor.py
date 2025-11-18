# --- EJECUTAR EN LA RASPBERRY PI ZERO 2 W (Dentro del entorno vision_env) ---
from flask import Flask, Response
import cv2
import time

app = Flask(__name__)

# Configuración de la Astra Pro. Prueba con 0, 1, 2 si 0 no funciona.
INDICE_CAMARA = 0
ANCHO = 640
ALTO = 480
FPS = 25

try:
    camera = cv2.VideoCapture(INDICE_CAMARA)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)
    camera.set(cv2.CAP_PROP_FPS, FPS)
    time.sleep(1)  # Pequeña espera para que la cámara inicialice
    if not camera.isOpened():
        print(f"❌ ERROR: No se pudo abrir la cámara en el índice {INDICE_CAMARA}.")
        print("Intenta cambiar INDICE_CAMARA a 1 o 2.")
except Exception as e:
    print(f"Error al inicializar cámara: {e}")
    exit()


def generar_stream():
    """Genera frames de la cámara y los codifica en JPEG."""
    while True:
        ret, frame = camera.read()
        if not ret:
            print("⚠️ Error de lectura de frame. Reintentando...")
            time.sleep(0.5)
            continue

        # Codificación rápida a JPEG para la transmisión por red
        ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        frame_bytes = buffer.tobytes()

        # Retorna el frame en formato MJPEG (multipart)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')


@app.route('/video_feed')
def video_feed():
    """Ruta HTTP que sirve el video."""
    return Response(generar_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    print(f"🚀 Iniciando emisor en http://[IP_PI_ZERO]:5000/video_feed")
    # 0.0.0.0 permite que Tailscale pueda acceder al puerto 5000
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)