import os
import subprocess
import cv2
from dotenv import load_dotenv

load_dotenv()
FFPROBE_PATH = os.getenv("FFPROBE_PATH", "ffprobe")

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


def _duration_with_ffprobe(video_path: str) -> float | None:
    """Obtiene la duración real del contenedor, incluso en videos con FPS variable."""
    try:
        result = subprocess.run(
            [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, check=True,
        )
        duration = float(result.stdout.strip())
        return round(duration, 2) if duration > 0 else None
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


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
    # OpenCV puede reportar conteos incorrectos en MP4 con FPS variable.
    # ffprobe lee la duración declarada por el contenedor y es la fuente primaria.
    duracion_segundos = _duration_with_ffprobe(video_path)
    if duracion_segundos is None:
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
