import os
import cv2

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
