import os
import threading
import pickle
import cv2
import numpy as np
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

YOLO_MODEL      = os.getenv("YOLO_MODEL", "yolo26n.pt")
YOLO_CONF       = float(os.getenv("YOLO_CONF", "0.35"))
YOLO_SAMPLE_FPS = float(os.getenv("YOLO_SAMPLE_FPS", "1"))
YOLO_TRUSTED_CHECKPOINT = os.getenv("YOLO_TRUSTED_CHECKPOINT", "false").strip().lower() in ("1", "true", "yes")
YOLO_FALLBACK_MODEL = os.getenv("YOLO_FALLBACK_MODEL", "sifods_v1_best.onnx")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

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
# Sección de detección de objetos con YOLOv8
#------------------------------------------------------------

_yolo_model = None
_yolo_lock = threading.Lock()


def _es_checkpoint_local_confiable(path: str) -> bool:
    """Restringe la compatibilidad de PyTorch a pesos .pt del proyecto."""
    absolute_path = os.path.abspath(path)
    try:
        dentro_del_proyecto = os.path.commonpath([PROJECT_ROOT, absolute_path]) == PROJECT_ROOT
    except ValueError:
        dentro_del_proyecto = False
    return (
        YOLO_TRUSTED_CHECKPOINT
        and dentro_del_proyecto
        and absolute_path.lower().endswith(".pt")
        and os.path.isfile(absolute_path)
    )


def _cargar_yolo_compatible(YOLO, model_path: str):
    """Carga pesos YOLO anteriores a Torch 2.6, solo si fueron autorizados.

    Torch 2.6 cambió `weights_only` a True. Ultralytics 8.2.18 aún invoca
    torch.load sin ese argumento. El parche es temporal, queda dentro del
    lock de carga y solo se habilita para un checkpoint local confiable.
    """
    try:
        return YOLO(model_path, task="detect")
    except pickle.UnpicklingError:
        if not _es_checkpoint_local_confiable(model_path):
            raise

        import torch
        original_load = torch.load

        def load_trusted_checkpoint(*args, **kwargs):
            kwargs["weights_only"] = False
            return original_load(*args, **kwargs)

        torch.load = load_trusted_checkpoint
        try:
            return YOLO(model_path, task="detect")
        finally:
            torch.load = original_load

def _load_yolo():
    """
    Carga el modelo YOLO una sola vez por proceso y lo cachea (mismo patrón
    que get_model() en services/transcription/analyzer.py para Whisper).
    Sin esto, cada análisis recargaba el modelo desde disco desde cero.
    Lock: con MAX_CONCURRENT_ANALYSIS > 1, dos extracciones concurrentes
    podrían cargar el modelo en paralelo sin esto (mismo riesgo que Whisper).
    """
    global _yolo_model
    if _yolo_model is None:
        with _yolo_lock:
            if _yolo_model is None:
                from ultralytics import YOLO
                try:
                    _yolo_model = _cargar_yolo_compatible(YOLO, YOLO_MODEL)
                except Exception as primary_error:
                    fallback_path = os.path.abspath(YOLO_FALLBACK_MODEL)
                    if (
                        fallback_path == os.path.abspath(YOLO_MODEL)
                        or not os.path.isfile(fallback_path)
                    ):
                        raise primary_error
                    print(
                        f"[objects] No se pudo cargar '{YOLO_MODEL}' ({primary_error}). "
                        f"Se usará el modelo ONNX de respaldo '{YOLO_FALLBACK_MODEL}'."
                    )
                    _yolo_model = YOLO(YOLO_FALLBACK_MODEL, task="detect")
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
