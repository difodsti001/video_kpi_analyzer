"""
Script de testeo aparte para la detección de objetos (YOLO) y la ficha técnica
del video, sin correr todo el pipeline pesado (transcripción, sentimiento, etc.).

Uso:
    python test_objects.py "video/mi_video.mp4"                    # resumen agregado
    python test_objects.py "video/mi_video.mp4" 40                 # + dump de los primeros 40 frames muestreados
    python test_objects.py "video/mi_video.mp4" 0 10                # + guarda debug_frame_10s.jpg con las cajas dibujadas
"""
import sys
import cv2
from dotenv import load_dotenv
load_dotenv()

from services.video.analyzer import (
    get_video_info, analyze_objects, _load_yolo, detect_objects_in_frame,
    YOLO_SAMPLE_FPS, YOLO_CONF,
)

VIDEO_FILE = sys.argv[1] if len(sys.argv) > 1 else "video/video sesion.mp4"
MAX_FRAMES_DUMP = int(sys.argv[2]) if len(sys.argv) > 2 else 0
SNAPSHOT_AT_SECOND = int(sys.argv[3]) if len(sys.argv) > 3 else None


def main():
    print(f"Video: {VIDEO_FILE}")
    print(f"YOLO_SAMPLE_FPS={YOLO_SAMPLE_FPS}  YOLO_CONF={YOLO_CONF}\n")

    print("[1] Ficha técnica del video")
    info = get_video_info(VIDEO_FILE)
    for k, v in info.items():
        print(f"    {k}: {v}")

    duracion = info.get("duracion_segundos", 0)

    print("\n[2] Detección de objetos — resumen agregado")
    result = analyze_objects(VIDEO_FILE, duration_seconds=duracion)
    if "error" in result:
        print("    ERROR:", result["error"])
        return

    print(f"    frames_procesados: {result['frames_procesados']}")
    print(f"    fps_video:         {result['fps_video']}")
    print(f"    duracion_segundos: {result['duracion_segundos']}")
    print()
    for o in result.get("objetos", []):
        pct = o["presencia_segundos"] / duracion * 100 if duracion else 0
        print(f"    - {o['label']:22s} presencia={o['presencia_segundos']:>7.1f}s ({pct:5.1f}%)  "
              f"max_simult={o['max_simultaneo']:2d}  conf_avg={o['confianza_promedio']:.2f}  "
              f"frames_detectado={o['frames_detectado']}/{result['frames_procesados']}")

    if MAX_FRAMES_DUMP <= 0:
        print("\n(pasa un segundo argumento, ej. 'python test_objects.py video.mp4 40', "
              "para ver el detalle frame por frame)")
        if SNAPSHOT_AT_SECOND is not None:
            save_snapshot(VIDEO_FILE, SNAPSHOT_AT_SECOND)
        return

    print(f"\n[3] Dump frame por frame (primeros {MAX_FRAMES_DUMP} frames muestreados)")
    model = _load_yolo()
    cap = cv2.VideoCapture(VIDEO_FILE)
    fps_video  = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_skip = max(1, round(fps_video / YOLO_SAMPLE_FPS))

    frame_idx, shown = 0, 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        if frame_idx % frame_skip != 0:
            continue

        timestamp  = frame_idx / fps_video
        detections = detect_objects_in_frame(model, frame)
        conteo = {}
        for d in detections:
            conteo[d["label"]] = conteo.get(d["label"], 0) + 1
        detalle = ", ".join(f"{lbl}x{n}" for lbl, n in conteo.items()) or "—"
        print(f"    t={timestamp:6.1f}s  frame#{frame_idx:5d}  {detalle}")

        shown += 1
        if shown >= MAX_FRAMES_DUMP:
            break

    cap.release()

    if SNAPSHOT_AT_SECOND is not None:
        save_snapshot(VIDEO_FILE, SNAPSHOT_AT_SECOND)


def _color_for_label(label: str) -> tuple:
    """Color BGR determinístico por etiqueta, para dibujar cajas consistentes."""
    h = sum(ord(c) for c in label)
    return (int(37 + (h * 53) % 200), int(37 + (h * 97) % 200), int(37 + (h * 151) % 200))


def save_snapshot(video_path: str, second: int):
    """Guarda debug_frame_<second>s.jpg con las cajas de YOLO dibujadas, para
    inspeccionar visualmente si son detecciones duplicadas/solapadas del mismo
    objeto físico o instancias realmente distintas."""
    print(f"\n[4] Guardando snapshot con cajas en t={second}s...")
    model = _load_yolo()
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("    No se pudo leer el frame en ese segundo.")
        return

    detections = detect_objects_in_frame(model, frame)
    for det in detections:
        x1, y1, x2, y2 = det["bbox"]
        color = _color_for_label(det["label"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        texto = f"{det['label']} {det['confianza']:.2f}"
        cv2.putText(frame, texto, (x1, max(0, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    out_path = f"debug_frame_{second}s.jpg"
    cv2.imwrite(out_path, frame)
    print(f"    {len(detections)} cajas dibujadas -> {out_path}")


if __name__ == "__main__":
    main()
