import os
import subprocess
import uuid
import cv2
import mediapipe as mp
import numpy as np
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
mp_pose     = mp.solutions.pose

YOLO_MODEL      = os.getenv("YOLO_MODEL", "yolo26n.pt")
YOLO_CONF       = float(os.getenv("YOLO_CONF", "0.35"))

YOLO_SAMPLE_FPS = float(os.getenv("YOLO_SAMPLE_FPS", "1"))

OBJECT_CLASS_MAP: dict[int, dict] = {
    61: {"label": "Pizarra / Pantalla",    "categoria": "Recursos didácticos"},
    62: {"label": "Laptop / Computadora",  "categoria": "Tecnología educativa"},
    63: {"label": "Mouse",                 "categoria": "Tecnología educativa"},
    65: {"label": "Teclado",               "categoria": "Tecnología educativa"},
    66: {"label": "Celular",               "categoria": "Tecnología educativa"},
    55: {"label": "Silla",                 "categoria": "Mobiliario"},
    56: {"label": "Sofá / Asiento",        "categoria": "Mobiliario"},
    57: {"label": "Planta / Objeto mesa",  "categoria": "Mobiliario"},
    59: {"label": "Mesa / Escritorio",     "categoria": "Mobiliario"},
    67: {"label": "Proyector / Microondas","categoria": "Tecnología educativa"},
    0:  {"label": "Persona",               "categoria": "Personas"},
}

CATEGORIA_POR_LABEL: dict[str, str] = {
    "Persona":                  "Personas",
    "Pizarra":                  "Recursos didácticos",
    "Celular":                  "Tecnología educativa",
    "Proyector / Pantalla":     "Tecnología educativa",
    "Mesa":                     "Mobiliario",
    "Silla":                    "Mobiliario",
    "Computadora / Laptop":     "Tecnología educativa",
    "Puntero físico":           "Recursos didácticos",
    "Marcador / Tiza / Plumón": "Recursos didácticos",
    "Mota / Borrador":          "Recursos didácticos",
}

def _es_modelo_custom() -> bool:
    return YOLO_MODEL.lower().endswith(".onnx")

#------------------------------------------------------------
# Ficha técnica del archivo de video
#------------------------------------------------------------

def _calidad_label(height: int) -> str:
    if height >= 2160:
        return "4K"
    if height >= 1080:
        return "Full HD"
    if height >= 720:
        return "HD"
    if height >= 480:
        return "SD"
    return "Baja resolución"


def get_video_info(video_path: str) -> dict:
    """Metadata básica del archivo: duración, resolución/calidad, fps y peso."""
    size_bytes = os.path.getsize(video_path) if os.path.exists(video_path) else 0

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            "error": f"No se pudo abrir el video: {video_path}",
            "tamano_mb": round(size_bytes / (1024 * 1024), 2),
        }

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 0.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duracion_segundos = round(total_frames / fps, 2) if fps else 0.0
    cap.release()

    return {
        "ancho":             width,
        "alto":              height,
        "resolucion":        f"{width}x{height}",
        "calidad":           _calidad_label(height),
        "fps":               round(fps, 2),
        "duracion_segundos": duracion_segundos,
        "tamano_mb":         round(size_bytes / (1024 * 1024), 2),
    }


#------------------------------------------------------------
# Sección de análisis de postura y gestos con MediaPipe Pose
#------------------------------------------------------------

def extract_frames(video_path: str, output_folder: str, fps: int = 1) -> list[str]:
    """Extrae 1 frame por segundo como JPG usando ffmpeg."""
    os.makedirs(output_folder, exist_ok=True)
    pattern = os.path.join(output_folder, "frame_%04d.jpg")
    subprocess.run([
        FFMPEG_PATH, "-y", "-i", video_path,
        "-vf", f"fps={fps}", pattern
    ], check=True, capture_output=True)
    return sorted([
        os.path.join(output_folder, f)
        for f in os.listdir(output_folder)
        if f.endswith(".jpg")
    ])


def analyze_frame(pose, image_path: str) -> dict | None:
    """
    Analiza postura y gestos en un frame individual.
    Devuelve métricas o None si no detecta persona.
    """
    img = cv2.imread(image_path)
    if img is None:
        return None

    rgb     = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    results = pose.process(rgb)

    if not results.pose_landmarks:
        return None

    lm = results.pose_landmarks.landmark

    # ── Keypoints principales ─────────────────────────────────────
    nose       = lm[mp_pose.PoseLandmark.NOSE]
    l_shoulder = lm[mp_pose.PoseLandmark.LEFT_SHOULDER]
    r_shoulder = lm[mp_pose.PoseLandmark.RIGHT_SHOULDER]
    l_ear      = lm[mp_pose.PoseLandmark.LEFT_EAR]
    r_ear      = lm[mp_pose.PoseLandmark.RIGHT_EAR]
    l_hip      = lm[mp_pose.PoseLandmark.LEFT_HIP]
    r_hip      = lm[mp_pose.PoseLandmark.RIGHT_HIP]
    l_elbow    = lm[mp_pose.PoseLandmark.LEFT_ELBOW]
    r_elbow    = lm[mp_pose.PoseLandmark.RIGHT_ELBOW]
    l_wrist    = lm[mp_pose.PoseLandmark.LEFT_WRIST]
    r_wrist    = lm[mp_pose.PoseLandmark.RIGHT_WRIST]

    # Centro de hombros y caderas
    shoulder_cx = (l_shoulder.x + r_shoulder.x) / 2
    shoulder_cy = (l_shoulder.y + r_shoulder.y) / 2
    hip_cy      = (l_hip.y + r_hip.y) / 2

    # ── Métricas de postura ───────────────────────────────────────

    # Inclinación de hombros: diferencia vertical entre hombro izq y der
    # (en coordenadas normalizadas: 0 = arriba, 1 = abajo)
    shoulder_tilt = abs(l_shoulder.y - r_shoulder.y)

    # Inclinación de cabeza: diferencia vertical entre orejas
    head_tilt = abs(l_ear.y - r_ear.y)

    # Offset de cabeza: nariz vs centro horizontal de hombros
    # Indica si la cabeza está desplazada lateralmente
    head_offset = abs(nose.x - shoulder_cx)

    # Ancho de hombros: distancia horizontal entre hombros
    shoulder_width = abs(l_shoulder.x - r_shoulder.x)

    # ── Métricas de gestos ────────────────────────────────────────

    # Mano levantada: muñeca por encima del hombro ipsilateral
    # En MediaPipe, coordenada Y menor = más arriba en la imagen
    l_hand_up = l_wrist.y < l_shoulder.y
    r_hand_up = r_wrist.y < r_shoulder.y

    # Mano al centro: muñeca cerca del eje central del cuerpo
    l_hand_center = abs(l_wrist.x - 0.5) < 0.2
    r_hand_center = abs(r_wrist.x - 0.5) < 0.2

    # Mano baja: muñeca debajo de la cadera
    l_hand_low = l_wrist.y > hip_cy
    r_hand_low = r_wrist.y > hip_cy

    # Brazos abiertos: codo fuera del ancho de hombros
    shoulder_half_w = shoulder_width / 2
    l_arm_open = abs(l_elbow.x - shoulder_cx) > shoulder_half_w + 0.05
    r_arm_open = abs(r_elbow.x - shoulder_cx) > shoulder_half_w + 0.05

    return {
        # postura
        "shoulder_tilt":   round(float(shoulder_tilt), 4),
        "head_tilt":       round(float(head_tilt), 4),
        "head_offset":     round(float(head_offset), 4),
        "shoulder_width":  round(float(shoulder_width), 4),
        "nose_x":          round(float(nose.x), 4),
        "nose_y":          round(float(nose.y), 4),
        # gestos
        "hand_up":         bool(l_hand_up or r_hand_up),
        "hand_center":     bool(l_hand_center or r_hand_center),
        "hand_low":        bool(l_hand_low or r_hand_low),
        "arms_open":       bool(l_arm_open or r_arm_open),
        "both_hands_up":   bool(l_hand_up and r_hand_up),
    }


def analyze_posture(video_path: str, frames_folder: str) -> dict:
    """
    Pipeline completo de análisis de postura y gestos.

    Extrae frames a 1 FPS, detecta 33 keypoints corporales con MediaPipe Pose
    y calcula scores de postura, estabilidad, centrado y distribución de gestos.

    Args:
        video_path:     Ruta al archivo de video original.
        frames_folder:  Carpeta temporal donde se guardan los JPG (se limpian al final).

    Returns:
        dict con scores, métricas agregadas, gestos y timeline.
    """
    frames = extract_frames(video_path, frames_folder, fps=1)
    if not frames:
        return {"error": "No se pudieron extraer frames del video"}

    frames_muestreados = len(frames)
    results = []

    with mp_pose.Pose(
        static_image_mode=True,
        model_complexity=1,
        min_detection_confidence=0.5
    ) as pose:
        for i, frame_path in enumerate(frames):
            data = analyze_frame(pose, frame_path)
            if data:
                data["second"] = i
                results.append(data)

    # limpiar frames temporales
    for f in frames:
        try:
            os.remove(f)
        except OSError:
            pass
    try:
        os.rmdir(frames_folder)
    except OSError:
        pass

    if not results:
        return {
            "error": "No se detectó persona en el video",
            "frames_muestreados":  frames_muestreados,
            "frames_con_persona":  0,
        }

    total = len(results)

    shoulder_tilts = [r["shoulder_tilt"] for r in results]
    nose_xs        = [r["nose_x"]        for r in results]
    head_offsets   = [r["head_offset"]   for r in results]

    # ── Scores de postura ─────────────────────────────────────────

    # postura_score: penaliza inclinación de hombros
    # umbral: tilt > 0.08 empieza a penalizar
    postura_score = round(max(0.0, 1.0 - float(np.mean(shoulder_tilts)) / 0.08), 3)

    # estabilidad_score: usa rango intercuartílico (Q75 - Q25) de la posición X de nariz
    # más robusto que std para videos con movimientos ocasionales legítimos
    mov_range = float(np.percentile(nose_xs, 75)) - float(np.percentile(nose_xs, 25))
    estabilidad_score = round(max(0.0, 1.0 - mov_range / 0.15), 3)

    # centrado_score: qué tan cerca del centro horizontal (0.5) está el orador en promedio
    centrado_score = round(max(0.0, 1.0 - abs(float(np.mean(nose_xs)) - 0.5) / 0.3), 3)

    # movimiento_excesivo: True si el rango intercuartílico supera 0.12
    movimiento_excesivo = bool(mov_range > 0.12)

    # ── Distribución de gestos ────────────────────────────────────
    hands_up_ratio     = round(sum(1 for r in results if r["hand_up"])     / total, 3)
    hands_center_ratio = round(sum(1 for r in results if r["hand_center"]) / total, 3)
    hands_low_ratio    = round(sum(1 for r in results if r["hand_low"])    / total, 3)
    arms_open_ratio    = round(sum(1 for r in results if r["arms_open"])   / total, 3)

    # gesto predominante: el de mayor proporción
    gesto_predominante = max(
        [
            ("manos al centro", hands_center_ratio),
            ("manos arriba",    hands_up_ratio),
            ("manos bajas",     hands_low_ratio),
            ("brazos abiertos", arms_open_ratio),
        ],
        key=lambda x: x[1]
    )[0]

    # ── Timeline (cada 5 frames para no saturar el JSON) ─────────
    timeline = [
        {
            "second":        r["second"],
            "shoulder_tilt": r["shoulder_tilt"],
            "head_offset":   r["head_offset"],
            "hand_up":       r["hand_up"],
            "arms_open":     r["arms_open"],
        }
        for r in results[::5]
    ]

    return {
        # frames_analizados se mantiene por compatibilidad con el frontend
        # (index.html lo usa tal cual); significa lo mismo que
        # frames_con_persona — frames donde MediaPipe detectó una persona.
        # frames_muestreados es el total de frames sacados a 1 FPS, SIN
        # importar si se detectó algo — permite calcular cuántos se
        # descartaron por no encontrar persona (frames_muestreados -
        # frames_con_persona), útil para pruebas de coherencia internas.
        "frames_analizados":   total,
        "frames_muestreados":  frames_muestreados,
        "frames_con_persona":  total,
        "tasa_deteccion":      round(total / frames_muestreados, 3) if frames_muestreados else 0.0,
        "postura_score":       postura_score,
        "estabilidad_score":   estabilidad_score,
        "centrado_score":      centrado_score,
        "shoulder_tilt_avg":   round(float(np.mean(shoulder_tilts)), 4),
        "head_offset_avg":     round(float(np.mean(head_offsets)), 4),
        "movimiento_excesivo": movimiento_excesivo,
        "gestos": {
            "manos_arriba_ratio":    hands_up_ratio,
            "manos_centro_ratio":    hands_center_ratio,
            "manos_bajas_ratio":     hands_low_ratio,
            "brazos_abiertos_ratio": arms_open_ratio,
            "gesto_predominante":    gesto_predominante,
        },
        "timeline": timeline,
    }


#------------------------------------------------------------
# Sección de detección de objetos con YOLOv8
#------------------------------------------------------------

_yolo_model = None

def _load_yolo():
    """
    Carga el modelo YOLO una sola vez por proceso y lo cachea (mismo patrón
    que get_model() en services/transcription/analyzer.py para Whisper).
    Sin esto, cada análisis recargaba el modelo desde disco desde cero.
    """
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO
        _yolo_model = YOLO(YOLO_MODEL, task="detect")
    return _yolo_model
 
 
def detect_objects_in_frame(model, frame: np.ndarray, conf: float = YOLO_CONF) -> list[dict]:
    """
    Corre inferencia YOLO sobre un frame (numpy BGR) y devuelve
    solo los objetos que están en OBJECT_CLASS_MAP.
 
    Args:
        model:  Instancia de ultralytics.YOLO ya cargada.
        frame:  Array BGR leído con cv2.
        conf:   Umbral de confianza mínimo.
 
    Returns:
        Lista de dicts con keys: label, categoria, confianza, bbox.
        bbox = [x1, y1, x2, y2] en píxeles (int).
    """
    results    = model(frame, conf=conf, verbose=False)
    es_custom  = _es_modelo_custom()
    detections = []

    for box in results[0].boxes:
        cls_id = int(box.cls[0])

        if es_custom:
            # Nombre real leído del propio modelo, no de un mapa por ID a mano.
            label     = model.names.get(cls_id, f"clase_{cls_id}")
            categoria = CATEGORIA_POR_LABEL.get(label, "Otros")
        else:
            info = OBJECT_CLASS_MAP.get(cls_id)
            if info is None:
                continue                      # clase COCO no relevante → ignorar
            label, categoria = info["label"], info["categoria"]

        conf_val = round(float(box.conf[0]), 3)
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

        detections.append({
            "label":     label,
            "categoria": categoria,
            "confianza": conf_val,
            "bbox":      [x1, y1, x2, y2],
        })

    return detections
 
 
def analyze_objects(video_path: str, duration_seconds: float = 0.0) -> dict:
    """
    Analiza un video y detecta objetos educativos usando YOLOv8.
    """
    model = _load_yolo()
 
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"error": f"No se pudo abrir el video: {video_path}"}
 
    fps_video   = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Frames nativos a saltar para muestrear a YOLO_SAMPLE_FPS reales,
    # sin importar el fps nativo del video (25, 30, 60...).
    frame_skip = max(1, round(fps_video / YOLO_SAMPLE_FPS))

    # Acumuladores por etiqueta institucional
    # Cada entrada: {frames, confianzas, primera_aparicion, ultima_aparicion, max_sim}
    stats: dict[str, dict] = defaultdict(lambda: {
        "frames_detectado":  0,
        "confianzas":        [],
        "primera_aparicion": None,   # segundos
        "ultima_aparicion":  None,
        "max_simultaneo":    0,
        "categoria":         "",
    })
 
    # Timeline de personas por segundo (para integrar con speech_time)
    personas_por_segundo: list[int] = []
    current_second        = -1
    personas_en_segundo   = 0
 
    frame_idx    = 0
    frames_proc  = 0
 
    while True:
        ret, frame = cap.read()
        if not ret:
            break
 
        frame_idx += 1
 
        # Saltar frames según configuración
        if frame_idx % frame_skip != 0:
            continue
 
        frames_proc  += 1
        timestamp_s   = frame_idx / fps_video
 
        # Actualizar contador de personas por segundo
        segundo_actual = int(timestamp_s)
        if segundo_actual != current_second:
            if current_second >= 0:
                personas_por_segundo.append(personas_en_segundo)
            current_second      = segundo_actual
            personas_en_segundo = 0
 
        detections = detect_objects_in_frame(model, frame)

        # Contar cuántas instancias hay de cada etiqueta en este frame, y quedarnos
        # con la mejor confianza de cada una (puede haber varias cajas de la misma
        # clase en un mismo frame, ej. varios celulares a la vez).
        conteo_frame: dict[str, int] = defaultdict(int)
        mejor_conf_frame: dict[str, float] = {}
        categoria_frame: dict[str, str] = {}
        for det in detections:
            lbl = det["label"]
            conteo_frame[lbl] += 1
            categoria_frame[lbl] = det["categoria"]
            mejor_conf_frame[lbl] = max(mejor_conf_frame.get(lbl, 0.0), det["confianza"])

        # Personas para el timeline
        personas_en_segundo = max(
            personas_en_segundo,
            conteo_frame.get("Persona", 0)
        )

        # Actualizar stats por objeto: una sola vez por etiqueta presente en el
        # frame, sin importar cuántas instancias simultáneas haya (eso ya lo
        # captura max_simultaneo). Contar por detección individual inflaba
        # "frames_detectado" muy por encima del total de frames procesados,
        # produciendo presencias imposibles (mayores a la duración del video).
        for lbl, count in conteo_frame.items():
            s = stats[lbl]
            s["frames_detectado"]  += 1
            s["confianzas"].append(mejor_conf_frame[lbl])
            s["categoria"]          = categoria_frame[lbl]
            s["max_simultaneo"]     = max(s["max_simultaneo"], count)

            if s["primera_aparicion"] is None:
                s["primera_aparicion"] = round(timestamp_s, 2)
            s["ultima_aparicion"] = round(timestamp_s, 2)
 
    # Agregar último segundo
    if current_second >= 0:
        personas_por_segundo.append(personas_en_segundo)
 
    cap.release()
 
    if frames_proc == 0:
        return {"error": "No se procesaron frames del video"}
 
    # Segundos que representa cada frame procesado. Se ancla a la duración real
    # del video (medida por audio, confiable) en vez de solo a fps_video reportado
    # por el contenedor: algunos archivos (variable frame rate, metadata mal escrita)
    # hacen que cv2 devuelva un fps incorrecto y eso antes producía presencias
    # imposibles (ej. "37:35" en un video de 7 minutos).
    if duration_seconds and frames_proc:
        segundos_por_frame = duration_seconds / frames_proc
    else:
        segundos_por_frame = frame_skip / fps_video
 
    # ── Construir resultado por objeto ────────────────────────────
    objetos: list[dict] = []
    for label, s in sorted(stats.items(), key=lambda x: x[1]["frames_detectado"], reverse=True):
        if label == "Persona":
            continue    # personas van en su propio bloque
 
        presencia_s = round(s["frames_detectado"] * segundos_por_frame, 2)
        conf_avg    = round(float(np.mean(s["confianzas"])), 3) if s["confianzas"] else 0.0
 
        objetos.append({
            "label":             label,
            "categoria":         s["categoria"],
            "frames_detectado":  s["frames_detectado"],
            "presencia_segundos": presencia_s,
            "primera_aparicion": s["primera_aparicion"],
            "ultima_aparicion":  s["ultima_aparicion"],
            "confianza_promedio": conf_avg,
            "max_simultaneo":    s["max_simultaneo"],
        })
 
    # ── Stats de personas ─────────────────────────────────────────
    p = stats.get("Persona", {})
    personas_info = {
        "frames_detectado":   p.get("frames_detectado", 0),
        "presencia_segundos": round(p.get("frames_detectado", 0) * segundos_por_frame, 2),
        "primera_aparicion":  p.get("primera_aparicion"),
        "ultima_aparicion":   p.get("ultima_aparicion"),
        "max_simultaneo":     p.get("max_simultaneo", 0),
    }
 
    # ── Distribución por categoría ────────────────────────────────
    categoria_frames: dict[str, int] = defaultdict(int)
    for label, s in stats.items():
        if label != "Persona":
            categoria_frames[s["categoria"]] += s["frames_detectado"]
 
    total_obj_frames = sum(categoria_frames.values()) or 1
    distribucion_categoria = {
        cat: round(frames / total_obj_frames * 100, 1)
        for cat, frames in sorted(categoria_frames.items(), key=lambda x: x[1], reverse=True)
    }
 
    # ── Resumen global ────────────────────────────────────────────
    dur = duration_seconds or (total_frames / fps_video)
 
    return {
        "frames_procesados":     frames_proc,
        "fps_video":             round(fps_video, 2),
        "duracion_segundos":     round(dur, 2),
        "objetos_unicos":        len(objetos),
        "objetos":               objetos,
        "personas":              personas_info,
        "personas_por_segundo":  personas_por_segundo,
        "distribucion_categoria": distribucion_categoria,
    }