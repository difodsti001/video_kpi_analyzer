import subprocess
import tempfile
import os
from dotenv import load_dotenv

load_dotenv()

FFMPEG_PATH  = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE_PATH = os.getenv("FFPROBE_PATH", "ffprobe")

_model = None

def get_model(model_size: str = "small"):
    global _model
    if _model is None:
        import whisper
        _model = whisper.load_model(model_size)
    return _model


def extract_audio(video_path: str) -> str:
    """Extrae audio WAV 16kHz mono. Devuelve path al WAV temporal."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()

    subprocess.run([
        FFMPEG_PATH,
        "-y",
        "-i", video_path,
        "-ar", "16000",
        "-ac", "1",
        "-vn",
        tmp.name
    ], 
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, check=True, capture_output=True)

    return tmp.name


def transcribe_audio(wav_path: str, model_size: str = "small") -> dict:
    """Transcribe con Whisper. Devuelve dict con text, segments, language."""
    model = get_model(model_size)

    result = model.transcribe(
        wav_path,
        word_timestamps=True,
        language="es"
    )

    return result


def parse_words(segments: list) -> list[dict]:
    """Extrae lista plana de {word, start, end} desde segments de Whisper."""
    words = []

    for seg in segments:
        for w in seg.get("words", []):
            words.append({
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            })

    return words


def get_duration(wav_path: str) -> float:
    """Duración del audio en segundos via ffprobe."""
    result = subprocess.run([
        FFPROBE_PATH,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        wav_path
    ], capture_output=True, text=True, check=True)

    return float(result.stdout.strip())

def split_audio(wav_path: str, chunk_seconds: int = 600) -> list[str]:
    """Divide el WAV en chunks. Devuelve lista de paths."""
    output_pattern = wav_path.replace(".wav", "_chunk_%03d.wav")
    subprocess.run([
        FFMPEG_PATH, "-i", wav_path,
        "-f", "segment",
        "-segment_time", str(chunk_seconds),
        "-c", "copy",
        output_pattern
    ], 
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, check=True, capture_output=True)

    folder = os.path.dirname(wav_path) or "."
    prefix = os.path.basename(wav_path).replace(".wav", "_chunk_")
    chunks = sorted([
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.startswith(prefix)
    ])
    return chunks

def transcribe_with_chunks(wav_path: str, model_size: str = "small",
                            chunk_seconds: int = 600) -> dict:
    """
    Si el audio es corto lo transcribe directo.
    Si es largo lo parte en chunks y ajusta los timestamps.
    Devuelve el mismo formato que transcribe_audio().
    """
    duration = get_duration(wav_path)

    if duration <= chunk_seconds:
        return transcribe_audio(wav_path, model_size)

    chunks = split_audio(wav_path, chunk_seconds)
    all_words = []
    full_text_parts = []

    try:
        for i, chunk in enumerate(chunks):
            offset = i * chunk_seconds
            result = transcribe_audio(chunk, model_size)
            words = parse_words(result["segments"])
            for w in words:
                w["start"] += offset
                w["end"]   += offset
            all_words.extend(words)
            full_text_parts.append(result["text"].strip())
    finally:
        for chunk in chunks:
            try:
                os.remove(chunk)
            except OSError:
                pass

    return {
        "text": " ".join(full_text_parts),
        "segments": [], 
        "language": result.get("language"),
        "_words_flat": all_words, 
    }