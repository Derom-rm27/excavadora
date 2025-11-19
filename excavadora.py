# --- EJECUTAR EN TU LAPTOP (Dentro del entorno detector_env) ---
import cv2
import time
# Importa aquí las librerías de tu modelo (YOLO, etc.)
from ultralytics import YOLO
import torch, time
import pandas as pd
from pathlib import Path
from collections import deque
import numpy as np  # Aseguramos la importación de numpy

# =========================================================
# CONFIGURACIÓN DE CONEXIÓN (TAILSCALE)
# =========================================================
# ⚠️ IMPORTANTE: Esta es la IP 100.x.x.x real de tu Pi Zero.
IP_TAILSCALE_PI = "100.84.202.90"
URL_STREAM = f"http://{IP_TAILSCALE_PI}:5000/video_feed"

# =========================================================
# CONFIGURACIÓN GENERAL DEL PROCESAMIENTO (Mantenido)
# =========================================================
# NOTA: Cambiamos RUTA_VIDEO a URL_STREAM para usar la cámara remota
RUTA_MODELO = r"best.pt"
DIRECTORIO_GUARDADO = Path(r"videos prueba")
DIRECTORIO_GUARDADO.mkdir(parents=True, exist_ok=True)
# RUTA_SALIDA se manejará de forma diferente para streaming si se quiere grabar

# Parámetros de ajuste
CONF_VOLQUETE = 0.35
CONF_CUCHARON = 0.35
SOLAPE_MINIMO = 0.02
PIXELES_DILATACION = 20
UMBRAL_CONF = 0.45

# --- UMBRALES DE MOVIMIENTO SEPARADOS ---
FPS_MIN_MOV_BRAZO_CUCHARON = 0.7
FPS_MIN_MOV_CABINA = 2.0

# --- LÓGICA DE TIEMPOS MODIFICADA ---
VENTANA_CICLO_ACTIVO = 25.0
TIEMPO_MUERTO = 6.0
MIN_DURACION_CARGUIO = 5.0
# =========================================================


# Inicialización del modelo y video
dispositivo = 'cuda' if torch.cuda.is_available() else 'cpu'
modelo = YOLO(RUTA_MODELO)
# *** CAMBIO CLAVE: Usamos URL_STREAM en lugar de RUTA_VIDEO ***
cap = cv2.VideoCapture(URL_STREAM)

# En el streaming, no podemos obtener FPS ni ancho/alto de inmediato.
# Usaremos valores por defecto o los ajustaremos en el bucle.
fps = 30  # Valor asumido; la Pi está enviando a 25 FPS
ancho, alto = 640, 480
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
# La grabación OUT se inicializa después de obtener el primer frame real.
out = None

# =========================================================
# VARIABLES DE ESTADO
# =========================================================
punta_y_prev = None
estado_actual = "INICIO"
tiempo_inicio = 0.0
tiempo_frame = 1.0 / fps
gris_prev = None
tiempo_ultimo_contacto = None
frames_sin_mov = 0
registros = []
# Se inicializan las variables para la grabación
grabacion_activa = False
tiempo_inicio_grabacion = time.time()


# =========================================================
# FUNCIONES AUXILIARES (Mantenidas)
# =========================================================
def crear_mascara(contorno_xy, h, w):
    """Crea una máscara binaria a partir de los puntos del contorno."""
    mask = np.zeros((h, w), dtype=np.uint8)
    if contorno_xy is not None and len(contorno_xy) > 0:
        cv2.fillPoly(mask, [np.array(contorno_xy, np.int32)], 1)
    return mask


def calcular_solape(a, b):
    """Calcula el índice de solape (Intersección / Área de A)."""
    inter = (a & b).sum()
    area = a.sum()
    return (inter / area) if area > 0 else 0.0


def obtener_bbox_de_mascara(contorno_xy, h, w):
    """Calcula el bounding box (x1, y1, x2, y2) a partir de un contorno."""
    if contorno_xy is None or len(contorno_xy) == 0:
        return None
    try:
        arr = np.array(contorno_xy, np.int32)
        x1, y1 = arr.min(axis=0)
        x2, y2 = arr.max(axis=0)
        return (max(x1, 0), max(y1, 0), min(x2, w - 1), min(y2, h - 1))
    except Exception as e:
        print(f"Error al calcular bbox de máscara: {e}")
        return None


def calcular_flujo_optico_en_bbox(gris_prev, gris_actual, bbox):
    """Calcula la mediana del flujo óptico dentro de un bounding box."""
    if gris_prev is None or bbox is None:
        return 0.0

    # Nos aseguramos de que el bounding box tenga 4 elementos antes de desempacar
    if len(bbox) != 4:
        return 0.0

    x1, y1, x2, y2 = map(int, bbox)
    if x2 > x1 and y2 > y1:
        region_prev = gris_prev[y1:y2, x1:x2]
        region_actual = gris_actual[y1:y2, x1:x2]

        if region_prev.shape[0] == 0 or region_prev.shape[1] == 0:
            return 0.0

        # Asegurarse de que las regiones tengan el mismo tamaño antes de calcOpticalFlowFarneback
        if region_prev.shape != region_actual.shape:
            return 0.0

        flow = cv2.calcOpticalFlowFarneback(region_prev, region_actual, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        return float(np.median(mag))
    return 0.0


# =========================================================
# BUCLE PRINCIPAL
# =========================================================
indice = 0
tiempo_inicial_abs = time.time()

while True:
    ret, frame = cap.read()

    if not ret:
        print("⚠️ Señal perdida. Reintentando...")
        time.sleep(1)
        cap.open(URL_STREAM)  # Intenta reconectar
        continue

    # --- Inicialización después del primer frame exitoso ---
    if indice == 0:
        ancho, alto = frame.shape[1], frame.shape[0]
        # Creamos el grabador una vez que tenemos el tamaño del frame
        RUTA_SALIDA = DIRECTORIO_GUARDADO / (f"stream_{int(time.time())}_prueba_8.mp4")
        out = cv2.VideoWriter(str(RUTA_SALIDA), fourcc, fps, (ancho, alto))
        print(f"🎥 Grabador inicializado: {RUTA_SALIDA}")
        grabacion_activa = True

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    tiempo_actual = time.time() - tiempo_inicial_abs  # Usamos tiempo absoluto para la duración

    # --- Inferencia YOLO ---
    r = modelo.predict(frame, conf=UMBRAL_CONF, verbose=False, device=dispositivo)[0]

    cucharon_xy = volquete_xy = brazo_caja = cabina_caja = None
    for i, b in enumerate(r.boxes):
        nombre = r.names[int(b.cls)]
        c = b.conf.item()
        # Verificamos si hay máscaras disponibles (requerido para contornos)
        cont = r.masks.xy[i] if r.masks is not None and r.masks.xy is not None and i < len(r.masks.xy) else None

        if "cucharon" in nombre.lower() and c >= CONF_CUCHARON:
            cucharon_xy = cont
        if ("tolva" in nombre.lower() or "volquete" in nombre.lower()) and c >= CONF_VOLQUETE:
            volquete_xy = cont
        if "brazo" in nombre.lower():
            brazo_caja = b.xyxy[0].cpu().numpy()
        if "cabina" in nombre.lower():
            cabina_caja = b.xyxy[0].cpu().numpy()

    # --- Solape y Máscaras ---
    cucharon_bbox = obtener_bbox_de_mascara(cucharon_xy, alto, ancho)

    mask_c = crear_mascara(cucharon_xy, alto, ancho)
    mask_v = crear_mascara(volquete_xy, alto, ancho)

    if mask_v.sum() > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (PIXELES_DILATACION, PIXELES_DILATACION))
        mask_v = cv2.dilate(mask_v, kernel, 1)
    solape = calcular_solape(mask_c, mask_v)

    # --- Movimiento ---
    mov_brazo = 0.0
    mov_cucharon = 0.0
    mov_cabina = 0.0

    if gris_prev is not None and cucharon_bbox is not None and cabina_caja is not None:
        # Usamos cucharon_bbox para el flujo óptico
        mov_cucharon = calcular_flujo_optico_en_bbox(gris_prev, gray, cucharon_bbox)
        # Usamos cabina_caja para el flujo óptico
        mov_cabina = calcular_flujo_optico_en_bbox(gris_prev, gray, cabina_caja)
        # Reutilizamos cabina_caja para brazo si no hay brazo_caja explícito
        if brazo_caja is not None:
            mov_brazo = calcular_flujo_optico_en_bbox(gris_prev, gray, brazo_caja)
        else:
            mov_brazo = 0.0  # No detectado, no hay movimiento específico

    # Lógica de movimiento booleana separada
    mov_brazo_cucharon_bool = max(mov_brazo, mov_cucharon) > FPS_MIN_MOV_BRAZO_CUCHARON
    mov_cabina_bool = mov_cabina > FPS_MIN_MOV_CABINA
    movimiento = mov_brazo_cucharon_bool or mov_cabina_bool
    movimiento_total_display = max(mov_brazo, mov_cucharon, mov_cabina)

    # --- Altura y velocidad del cucharón (Simplificado para streaming) ---
    punta_y = None
    if cucharon_xy is not None and len(cucharon_xy) > 0:
        punta_y = float(np.max(np.array(cucharon_xy)[:, 1]))
    vel_y = (punta_y - punta_y_prev) if (punta_y is not None and punta_y_prev is not None) else 0.0
    punta_y_prev = punta_y

    # =========================================================
    # LÓGICA DE ESTADOS
    # =========================================================
    contacto_tolva = solape >= SOLAPE_MINIMO

    if tiempo_ultimo_contacto is not None:
        t_desde = tiempo_actual - tiempo_ultimo_contacto
    else:
        t_desde = 1e9

    if contacto_tolva:
        tiempo_ultimo_contacto = tiempo_actual
        t_desde = 0.0

    frames_sin_mov = frames_sin_mov + 1 if not movimiento else 0

    nuevo_estado = "PREPARACION"  # Default

    # 1. MUERTO
    if (frames_sin_mov * tiempo_frame >= TIEMPO_MUERTO):
        nuevo_estado = "MUERTO"

    # 2. CARGUÍO
    elif (tiempo_ultimo_contacto is not None and
          t_desde <= VENTANA_CICLO_ACTIVO and
          volquete_xy is not None):
        nuevo_estado = "CARGUIO"

    # 3. PREPARACION (Default)
    # Ya está implícito si no cae en 1 o 2

    # --- Registro de transiciones ---
    if nuevo_estado != estado_actual:
        if estado_actual != "INICIO":
            tiempo_fin_anterior = tiempo_actual
            tiempo_inicio_nuevo = tiempo_actual

            if nuevo_estado == "MUERTO":
                tiempo_fin_anterior = tiempo_actual - TIEMPO_MUERTO
                if tiempo_fin_anterior < tiempo_inicio:
                    tiempo_fin_anterior = tiempo_inicio
                tiempo_inicio_nuevo = tiempo_fin_anterior

            registros.append({
                "Estado": estado_actual,
                "Inicio_s": tiempo_inicio,
                "Fin_s": tiempo_fin_anterior
            })

            tiempo_inicio = tiempo_inicio_nuevo
        else:
            if nuevo_estado == "MUERTO":
                tiempo_inicio = max(0.0, tiempo_actual - TIEMPO_MUERTO)
            else:
                tiempo_inicio = tiempo_actual

        estado_actual = nuevo_estado

    # --- Dibujo y Output ---
    color = (0, 255, 0) if estado_actual == "CARGUIO" else (0, 255, 255) if estado_actual == "PREPARACION" else (0, 0,
                                                                                                                 255)
    cv2.putText(frame, f"Estado: {estado_actual}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, color, 3)
    cv2.putText(frame, f"Solape:{solape:.2f} Mov:{movimiento_total_display:.2f} t_desde:{t_desde:.1f}s",
                (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 255, 255), 2)
    cv2.putText(frame, f"Ventana Carguio:{VENTANA_CICLO_ACTIVO:.1f}s Muerto:{TIEMPO_MUERTO:.1f}s", (30, 130),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 255, 255), 2)

    if out is not None:
        out.write(frame)

    cv2.imshow("Monitor de Excavadora Remoto", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):  # Usamos 'q' para salir, más estándar
        break

    gris_prev = gray
    indice += 1

    if indice % 100 == 0:
        print(f"Procesando frame {indice} ({tiempo_actual:.1f}s)... Estado: {estado_actual}")

# =========================================================
# CIERRE Y EXPORTACIÓN
# =========================================================
if estado_actual != "INICIO":
    registros.append({"Estado": estado_actual, "Inicio_s": tiempo_inicio, "Fin_s": time.time() - tiempo_inicial_abs})

cap.release()
if out is not None:
    out.release()

cv2.destroyAllWindows()
print("Procesamiento de stream finalizado.")

# Postproceso (El mismo que tenías)
if not registros:
    print("No se generaron registros. Terminando.")
    exit()

df = pd.DataFrame(registros)
df["Duracion_s"] = df["Fin_s"] - df["Inicio_s"]

filtro_cortos = (df["Estado"] == "CARGUIO") & (df["Duracion_s"] < MIN_DURACION_CARGUIO)
df.loc[filtro_cortos, "Estado"] = "PREPARACION"

df['grupo'] = (df['Estado'] != df['Estado'].shift()).cumsum()

df_agrupado = df.groupby(['grupo', 'Estado']).agg(
    Inicio_s=('Inicio_s', 'min'),
    Fin_s=('Fin_s', 'max')
).reset_index()

df_agrupado["Duracion_s"] = df_agrupado["Fin_s"] - df_agrupado["Inicio_s"]
df = df_agrupado.drop(columns=['grupo'])

df = df[df["Duracion_s"] > 0].copy()

df_resumen = df.groupby("Estado")["Duracion_s"].sum().reset_index()
total = df_resumen["Duracion_s"].sum()
if total > 0:
    df_resumen["Porcentaje_%"] = (df_resumen["Duracion_s"] / total * 100).round(1)
else:
    df_resumen["Porcentaje_%"] = 0.0

ruta_xlsx = DIRECTORIO_GUARDADO / (Path(RUTA_SALIDA).stem + "_resumen.xlsx")
with pd.ExcelWriter(ruta_xlsx, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="Cronología")
    df_resumen.to_excel(writer, index=False, sheet_name="Resumen")

print("\n=== RESULTADOS DE OPERACIÓN ===")
print(df_resumen)
print(f"\n✅ Archivo Excel guardado en: {ruta_xlsx}")
print(f"🎥 Video anotado guardado en: {RUTA_SALIDA}")