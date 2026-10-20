"""Reglas temporales sobre pistas anónimas, sin reconocimiento facial."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrackSample:
    second: float
    center_x: float
    center_y: float
    area_ratio: float
    # Caja normalizada, usada solo durante el análisis complementario de pose.
    # No representa identidad ni se extraen rostros.
    left: float | None = None
    top: float | None = None
    right: float | None = None
    bottom: float | None = None
    person_id: str | None = None
    reid_confidence: float | None = None
    visible_descriptor: str | None = None


@dataclass(frozen=True)
class PoseSample:
    second: float
    hand_up: bool


def select_presenter(tracks: dict[int, list[TrackSample]]) -> int | None:
    """Elige la pista más estable y visible; es una heurística, no identidad."""
    candidates = [(track_id, samples) for track_id, samples in tracks.items() if samples]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (len(item[1]), sum(s.area_ratio for s in item[1]) / len(item[1])),
    )[0]


def detect_movement_events(
    samples: list[TrackSample],
    track_id: int,
    min_duration_seconds: float = 3.0,
    min_horizontal_displacement: float = 0.18,
) -> list[dict]:
    """Detecta desplazamientos horizontales sostenidos de una pista anónima."""
    if len(samples) < 2:
        return []

    events = []
    start_index = 0
    for end_index in range(1, len(samples)):
        start = samples[start_index]
        end = samples[end_index]
        duration = end.second - start.second
        displacement = end.center_x - start.center_x
        if duration < min_duration_seconds or abs(displacement) < min_horizontal_displacement:
            continue

        confidence = min(0.95, round(0.55 + abs(displacement) + min(duration / 20, 0.2), 2))
        events.append({
            "type": "presentador_desplazamiento",
            "start_seconds": round(start.second, 2),
            "end_seconds": round(end.second, 2),
            "subject": "presentador",
            "confidence": confidence,
            "evidence": {
                "track_id": track_id,
                "horizontal_displacement": round(abs(displacement), 3),
                "direction": "derecha" if displacement > 0 else "izquierda",
            },
        })
        start_index = end_index
    return events


def detect_hand_raised_events(
    samples: list[PoseSample],
    track_id: int,
    min_duration_seconds: float = 2.0,
    max_gap_seconds: float = 1.5,
) -> list[dict]:
    """Confirma mano elevada solo si se sostiene en una pista anónima."""
    events = []
    start: PoseSample | None = None
    last_hand_up: PoseSample | None = None

    def close_event(first: PoseSample | None, last: PoseSample | None) -> None:
        if first is None or last is None:
            return
        duration = last.second - first.second
        if duration < min_duration_seconds:
            return
        confidence = min(0.95, round(0.65 + min(duration / 20, 0.25), 2))
        events.append({
            "type": "mano_levantada",
            "start_seconds": round(first.second, 2),
            "end_seconds": round(last.second, 2),
            "subject": "persona_no_identificada",
            "confidence": confidence,
            "evidence": {
                "pose_track_id": track_id,
                "duration_seconds": round(duration, 2),
                "rule": "muñeca sobre hombro en pose multipersona",
            },
        })

    for sample in samples:
        if sample.hand_up:
            if start is None:
                start = sample
            elif last_hand_up and sample.second - last_hand_up.second > max_gap_seconds:
                close_event(start, last_hand_up)
                start = sample
            last_hand_up = sample
        elif start is not None and last_hand_up and sample.second - last_hand_up.second > max_gap_seconds:
            # Una detección de pose puede fallar en un frame aislado. Solo se
            # cierra el evento cuando la ausencia supera la tolerancia definida.
            close_event(start, last_hand_up)
            start = None
            last_hand_up = None

    close_event(start, last_hand_up)
    return events


def fuse_visual_observations(visual_windows: list[dict], detector_events: list[dict]) -> list[dict]:
    """Expone observaciones de IA y señala cuáles tienen evidencia instrumental."""
    event_for_label = {
        "person_movement": "presentador_desplazamiento",
        "raised_hand": "mano_levantada",
    }
    fused: list[dict] = []
    for window in visual_windows:
        start, end = window["start_seconds"], window["end_seconds"]
        for observation in window.get("observations", []):
            expected = {event_for_label[label] for label in observation.get("labels", []) if label in event_for_label}
            supporting = [
                event["type"] for event in detector_events
                if event["type"] in expected
                and event["start_seconds"] <= end and event["end_seconds"] >= start
            ]
            fused.append({
                "type": "observacion_visual",
                "start_seconds": start,
                "end_seconds": end,
                "text": observation["text"],
                "labels": observation.get("labels", []),
                "vision_confidence": observation.get("confidence"),
                "verification": "corroborada_por_detector" if supporting else "observacion_sin_corrobacion_instrumental",
                "supporting_events": supporting,
            })
    return fused
