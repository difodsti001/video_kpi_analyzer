"""Construye una ficha de evidencias temporal y sin medios persistentes.

La ficha describe señales observables extraídas del video. No asigna una
calificación pedagógica ni infiere intención del docente. El video, audio y
frames temporales pueden eliminarse una vez que este resultado se guarda.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone


WINDOW_SECONDS = max(10, int(os.getenv("EVIDENCE_WINDOW_SECONDS", "30")))
MAX_QUOTE_CHARS = 360


def _timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _confidence(value: float | None) -> str:
    if value is None:
        return "no disponible"
    if value >= 0.75:
        return "alta"
    if value >= 0.45:
        return "media"
    return "baja"


def _quote(words: list[dict], start: float, end: float) -> str:
    text = " ".join(
        str(word.get("word", "")).strip()
        for word in words
        if start <= float(word.get("start", 0)) < end and str(word.get("word", "")).strip()
    )
    if len(text) > MAX_QUOTE_CHARS:
        return text[: MAX_QUOTE_CHARS - 1].rstrip() + "…"
    return text


def _has_interrogative(text: str) -> bool:
    return bool(re.search(
        r"[?¿]|\b(?:por que|por qué|como|cómo|que|qué|cual|cuál|cuáles|quien|quién|para que|para qué)\b",
        text.lower(),
    ))


def _samples_in_window(posture: dict, start: float, end: float) -> list[dict]:
    timeline = posture.get("tracking_timeline") or posture.get("timeline") or []
    return [sample for sample in timeline if start <= float(sample.get("second", -1)) < end]


def _resource_labels(objects: dict, start: float, end: float) -> list[str]:
    labels = []
    for obj in objects.get("objetos", []):
        first = obj.get("primera_aparicion")
        last = obj.get("ultima_aparicion")
        if first is None or last is None:
            continue
        if float(first) < end and float(last) >= start:
            labels.append(str(obj.get("label", "recurso")))
    return labels


def _people_max(objects: dict, start: float, end: float) -> int:
    series = objects.get("personas_por_segundo") or []
    first, last = int(start), min(int(end), len(series))
    values = series[first:last]
    return max(values) if values else 0


def _vision_in_window(vision: dict, start: float, end: float) -> list[dict]:
    return [
        item for item in (vision or {}).get("descripciones", [])
        if start <= float(item.get("second", -1)) < end
    ]


def _visual_observation(posture: dict, objects: dict, vision: dict,
                        start: float, end: float) -> dict:
    samples = _samples_in_window(posture, start, end)
    resources = _resource_labels(objects, start, end)
    people_max = _people_max(objects, start, end)
    vision_descriptions = _vision_in_window(vision, start, end)
    statements: list[str] = []
    sources: list[str] = []
    limitations: list[str] = []

    if vision_descriptions:
        sources.append("modelo_vision")
        statements.extend(item["descripcion"] for item in vision_descriptions)
        limitations.append("La descripción visual es una evidencia orientativa y requiere validación humana.")

    if samples:
        sources.append("mediapipe_pose")
        xs = [float(sample.get("nose_x", 0.5)) for sample in samples if sample.get("nose_x") is not None]
        if xs:
            range_x = max(xs) - min(xs)
            avg_x = sum(xs) / len(xs)
            if range_x >= 0.15:
                statements.append("Una pose de persona detectada presenta desplazamiento lateral en el encuadre.")
            else:
                zone = "centro" if 0.34 <= avg_x <= 0.66 else ("lado izquierdo" if avg_x < 0.34 else "lado derecho")
                statements.append(f"Una pose de persona detectada permanece principalmente en el {zone} del encuadre.")
        coverage = len(samples) / max(1, end - start)
        if coverage < 0.5:
            limitations.append("La pose de una persona se detectó en menos de la mitad de las muestras de esta ventana.")
        limitations.append("La detección visual no identifica el rol de la persona como docente o estudiante.")
    else:
        statements.append("No se detectó una pose de persona utilizable en esta ventana.")
        limitations.append("La ausencia de pose no prueba ausencia de personas; puede deberse al encuadre u oclusiones.")

    if resources:
        sources.append("yolo_objetos")
        statements.append("Se detectaron recursos u objetos en escena: " + ", ".join(sorted(set(resources))) + ".")
        limitations.append("La detección indica presencia visual del recurso, no confirma su uso pedagógico.")
    if people_max:
        sources.append("yolo_personas")
        statements.append(f"Se detectaron hasta {people_max} persona(s) en una muestra de la ventana.")
        limitations.append("El conteo de personas no identifica roles ni confirma interacción.")

    return {
        "descripcion": " ".join(statements),
        "fuentes": sorted(set(sources)),
        "confianza": _confidence(0.70 if samples else (0.55 if resources else None)),
        "limitaciones": sorted(set(limitations)),
    }


def build_evidence_ficha(
    *,
    duration_seconds: float,
    words: list[dict],
    transcription_quality: dict,
    posture: dict,
    objects: dict,
    vision: dict | None = None,
    video_info: dict,
    window_seconds: int = WINDOW_SECONDS,
) -> dict:
    """Devuelve evidencia factual por ventanas, lista para persistirse en JSON."""
    duration = max(0.0, float(duration_seconds or 0.0))
    quality_ok = transcription_quality.get("confiable")
    audio_confidence = "alta" if quality_ok is True else ("baja" if quality_ok is False else "no disponible")
    windows = []
    evidences = []
    evidence_number = 1

    for start in range(0, max(1, int(duration)), window_seconds):
        end = min(float(start + window_seconds), duration)
        if end <= start:
            break
        quote = _quote(words, start, end)
        visual = _visual_observation(posture or {}, objects or {}, vision or {}, start, end)
        window = {
            "inicio_segundos": start,
            "fin_segundos": round(end, 3),
            "inicio": _timestamp(start),
            "fin": _timestamp(end),
            "audio": quote or None,
            "visual": visual["descripcion"],
            "confianza_audio": audio_confidence if quote else "no disponible",
            "confianza_visual": visual["confianza"],
            "fuentes_visual": visual["fuentes"],
            "limitaciones": visual["limitaciones"],
        }
        windows.append(window)

        if quote:
            evidence = {
                "id": f"ev_{evidence_number:04d}",
                "tipo": "fragmento_hablado",
                "descripcion": "Se registró habla transcrita en esta ventana.",
                "inicio": window["inicio"],
                "fin": window["fin"],
                "inicio_segundos": start,
                "fin_segundos": round(end, 3),
                "fuentes": ["whisper"],
                "texto_evidencia": quote,
                "confianza": audio_confidence,
                "limitaciones": (
                    [] if quality_ok is True else
                    ["La calidad agregada de la transcripción requiere revisión humana."]
                ),
            }
            evidences.append(evidence)
            evidence_number += 1

            if _has_interrogative(quote):
                evidences.append({
                    "id": f"ev_{evidence_number:04d}",
                    "tipo": "interrogante_detectada",
                    "descripcion": "La transcripción contiene al menos un interrogante; su intención pedagógica debe ser validada por una persona evaluadora.",
                    "inicio": window["inicio"],
                    "fin": window["fin"],
                    "inicio_segundos": start,
                    "fin_segundos": round(end, 3),
                    "fuentes": ["whisper", *visual["fuentes"]],
                    "texto_evidencia": quote,
                    "descripcion_visual": visual["descripcion"],
                    "confianza": audio_confidence,
                    "limitaciones": visual["limitaciones"],
                })
                evidence_number += 1

        if visual["fuentes"]:
            evidences.append({
                "id": f"ev_{evidence_number:04d}",
                "tipo": "observacion_visual",
                "descripcion": visual["descripcion"],
                "inicio": window["inicio"],
                "fin": window["fin"],
                "inicio_segundos": start,
                "fin_segundos": round(end, 3),
                "fuentes": visual["fuentes"],
                "confianza": visual["confianza"],
                "limitaciones": visual["limitaciones"],
            })
            evidence_number += 1

    return {
        "version": "1.0",
        "tipo": "ficha_evidencias_temporal",
        "generada_en_utc": datetime.now(timezone.utc).isoformat(),
        "politica_retencion": {
            "video_fuente": "El video fuente no forma parte de la ficha y puede eliminarse tras una extracción exitosa.",
            "clips_y_frames": "No se conservan clips, audio temporal ni frames temporales.",
        },
        "identificacion_docente": {
            "estado": "no_identificado",
            "metodo": "No se realiza identificación biométrica ni se infiere automáticamente el rol docente a partir de una detección de persona o pose.",
            "uso_de_presentador": "El metadato de presentador identifica el registro, pero no se usa para atribuir una persona dentro de la imagen.",
            "limitaciones": [
                "Las observaciones visuales describen personas o poses detectadas, no al docente como identidad confirmada.",
                "Para atribuir evidencia a un docente se requeriría una calibración explícita y validada por quien carga el video.",
            ],
        },
        "metadatos_video": {
            "duracion_segundos": round(duration, 3),
            "resolucion": video_info.get("resolucion"),
            "fps": video_info.get("fps"),
        },
        "configuracion": {
            "ventana_segundos": window_seconds,
            "fuentes": ["whisper", "mediapipe_pose", "yolo_objetos", "modelo_vision"],
        },
        "resumen_limitaciones": [
            "La ficha describe señales extraídas; no emite una calificación pedagógica.",
            "La ausencia de evidencia no equivale a ausencia del hecho en el video.",
            "La identidad del docente y la atribución de voces no se resuelven en esta versión.",
        ],
        "transcripcion_multimodal": windows,
        "evidencias": evidences,
    }
