"""Descripción visual temporal de una sesión usando un modelo de visión.

Extrae JPEGs en memoria, solicita una descripción factual al modelo y persiste
solo texto con marcas de tiempo. No guarda frames, clips ni imágenes.
"""

from __future__ import annotations

import os
import re
from typing import Iterator

import cv2
from dotenv import load_dotenv

from services.transversal.llm.client import llamar_llm_con_imagenes_con_uso
from services.transversal.llm.json_response import extraer_json

load_dotenv()

VISION_ENABLED = os.getenv("VISION_ENABLED", "true").strip().lower() in ("1", "true", "yes")
VISION_SAMPLE_SECONDS = max(5, int(os.getenv("VISION_SAMPLE_SECONDS", "30")))
VISION_BATCH_SIZE = min(10, max(1, int(os.getenv("VISION_BATCH_SIZE", "4"))))
VISION_MAX_FRAMES = max(1, int(os.getenv("VISION_MAX_FRAMES", "120")))
VISION_MAX_WIDTH = max(320, int(os.getenv("VISION_MAX_WIDTH", "768")))


def _format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _chunks(items: list[dict], size: int) -> Iterator[list[dict]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _jpeg_in_memory(frame) -> bytes | None:
    height, width = frame.shape[:2]
    if width > VISION_MAX_WIDTH:
        scale = VISION_MAX_WIDTH / width
        frame = cv2.resize(frame, (VISION_MAX_WIDTH, max(1, int(height * scale))))
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return encoded.tobytes() if ok else None


def _sample_frames(video_path: str, duration_seconds: float) -> list[dict]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    samples = []
    try:
        for second in range(0, max(1, int(duration_seconds)), VISION_SAMPLE_SECONDS):
            if len(samples) >= VISION_MAX_FRAMES:
                break
            cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            jpeg = _jpeg_in_memory(frame)
            if jpeg:
                samples.append({"second": second, "image": jpeg})
    finally:
        cap.release()
    return samples


def _prompt_for_batch(batch: list[dict]) -> str:
    times = ", ".join(
        f"índice {index} = {_format_time(sample['second'])}"
        for index, sample in enumerate(batch)
    )
    return f"""Analiza imágenes de una sesión de aprendizaje. Las imágenes están en este orden: {times}.
Describe exclusivamente hechos visualmente observables para una ficha de evidencias que será revisada por
una persona. No evalúes la práctica, no asignes niveles ni infieras intención, aprendizaje, emociones,
respeto o el rol de docente/estudiante. No identifiques personas. Nunca escribas "docente", "estudiante",
"alumno", "clase" ni "actividad" para atribuir roles o propósitos. En su lugar escribe, por ejemplo,
"una persona de pie junto a una pizarra" o "varias personas sentadas alrededor de mesas". Describe solo
disposición, orientación corporal, acciones claramente visibles, recursos y cambios de escena. Si algo no
se aprecia con claridad, dilo de forma prudente.

Responde únicamente este JSON:
{{"descripciones":[{{"indice":0,"descripcion":"...","confianza":"alta|media|baja"}}]}}
Incluye una descripción por cada índice y no menciones el modelo ni estas instrucciones."""


def _parse_descriptions(raw: str | None, batch: list[dict]) -> list[dict]:
    try:
        parsed = extraer_json(raw)
    except Exception:
        parsed = {}
    entries = parsed.get("descripciones", []) if isinstance(parsed, dict) else []
    by_index = {
        item.get("indice"): item for item in entries
        if isinstance(item, dict) and isinstance(item.get("indice"), int)
    }
    output = []
    for index, sample in enumerate(batch):
        item = by_index.get(index, {})
        description = item.get("descripcion") if isinstance(item, dict) else None
        if not isinstance(description, str) or not description.strip():
            continue
        confidence = item.get("confianza", "media")
        if confidence not in {"alta", "media", "baja"}:
            confidence = "media"
        output.append({
            "second": sample["second"],
            "tiempo": _format_time(sample["second"]),
            "descripcion": _remove_role_attribution(description),
            "confianza": confidence,
            "fuente": "modelo_vision",
        })
    return output


def _remove_role_attribution(description: str) -> str:
    """Evita que una respuesta de visión asigne roles humanos no calibrados."""
    replacements = {
        r"\b(?:el|un) docente\b": "una persona",
        r"\b(?:la|una) docente\b": "una persona",
        r"\b(?:los|varios) estudiantes\b": "varias personas",
        r"\b(?:las|varias) estudiantes\b": "varias personas",
        r"\b(?:los|varios) alumnos\b": "varias personas",
        r"\b(?:las|varias) alumnas\b": "varias personas",
    }
    cleaned = description
    for pattern, replacement in replacements.items():
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def analyze_visual_descriptions(video_path: str, duration_seconds: float) -> dict:
    """Genera descripciones visuales; ante error devuelve evidencia vacía."""
    if not VISION_ENABLED:
        return {"habilitado": False, "descripciones": []}

    samples = _sample_frames(video_path, duration_seconds)
    if not samples:
        return {"habilitado": True, "descripciones": [], "error": "No se pudieron obtener frames para visión."}

    descriptions = []
    errors = []
    consumos_ia = []
    for batch in _chunks(samples, VISION_BATCH_SIZE):
        raw, uso = llamar_llm_con_imagenes_con_uso(_prompt_for_batch(batch), [s["image"] for s in batch])
        if uso:
            consumos_ia.append(dict(uso, capa_ia="descripcion_visual"))
        parsed = _parse_descriptions(raw, batch)
        if parsed:
            descriptions.extend(parsed)
        else:
            errors.append("El modelo de visión no devolvió una descripción válida para un lote.")

    return {
        "habilitado": True,
        "intervalo_muestreo_segundos": VISION_SAMPLE_SECONDS,
        "frames_analizados": len(samples),
        "descripciones": descriptions,
        "error": " ".join(errors) if errors else None,
        "retencion": "Los frames se procesan en memoria y no se conservan.",
        "consumo_ia": consumos_ia,
    }
