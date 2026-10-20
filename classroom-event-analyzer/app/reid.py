"""Reidentificación visual efímera y sin rostro dentro de un solo video."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


def _body_histogram(person_crop: np.ndarray) -> tuple[np.ndarray, str] | None:
    """Extrae color de ropa excluyendo el 28 % superior del recorte (rostro)."""
    if person_crop.size == 0:
        return None
    start_y = max(1, round(person_crop.shape[0] * 0.28))
    body = person_crop[start_y:]
    if body.size == 0:
        return None
    hsv = cv2.cvtColor(body, cv2.COLOR_BGR2HSV)
    # Se descartan píxeles casi blancos/negros para que el fondo pese menos.
    mask = cv2.inRange(hsv, (0, 35, 25), (179, 255, 235))
    if cv2.countNonZero(mask) < 40:
        mask = None
    hist = cv2.calcHist([hsv], [0, 1], mask, [12, 6], [0, 180, 0, 256]).flatten()
    norm = np.linalg.norm(hist)
    if norm == 0:
        return None
    hist /= norm
    pixels = hsv[mask > 0] if mask is not None else hsv.reshape(-1, 3)
    median_h, median_s, median_v = np.median(pixels, axis=0)
    return hist, _color_name(float(median_h), float(median_s), float(median_v))


def _color_name(hue: float, saturation: float, value: float) -> str:
    """Nombre amplio y observable; no intenta describir identidad o rasgos."""
    if saturation < 45:
        if value < 70:
            return "prenda oscura"
        if value > 185:
            return "prenda clara"
        return "prenda gris"
    if value < 70:
        return "prenda oscura"
    if hue < 10 or hue >= 170:
        return "prenda roja"
    if hue < 22:
        return "prenda marrón o anaranjada"
    if hue < 38:
        return "prenda amarilla"
    if hue < 85:
        return "prenda verde"
    if hue < 135:
        return "prenda azul"
    if hue < 170:
        return "prenda morada"
    return "prenda de color no determinado"


@dataclass
class _PersonMemory:
    person_id: str
    prototype: np.ndarray
    visible_descriptor: str
    last_second: float
    last_center: tuple[float, float]
    track_ids: set[int] = field(default_factory=set)
    match_scores: list[float] = field(default_factory=list)


class AppearanceReidentifier:
    """Une tracklets compatibles sin usar rostros ni persistir datos biométricos.

    La memoria vive exclusivamente durante la ejecución del proceso y debe
    descartarse al finalizar el análisis.
    """

    def __init__(self, threshold: float = 0.84) -> None:
        self.threshold = threshold
        self._track_to_person: dict[int, str] = {}
        self._people: dict[str, _PersonMemory] = {}
        self._next_id = 1

    def assign(
        self,
        track_id: int,
        crop: np.ndarray,
        second: float,
        center: tuple[float, float],
        active_track_ids: set[int],
    ) -> tuple[str, float, str]:
        """Asigna una persona temporal a un tracklet y devuelve su confianza."""
        existing = self._track_to_person.get(track_id)
        descriptor = _body_histogram(crop)
        if existing:
            memory = self._people[existing]
            memory.last_second = second
            memory.last_center = center
            if descriptor:
                memory.prototype = self._blend(memory.prototype, descriptor[0])
            return existing, 1.0, memory.visible_descriptor

        if descriptor is None:
            return self._create(track_id, np.zeros(72, dtype=np.float32), "prenda no determinada", second, center)
        vector, visible_descriptor = descriptor
        occupied_people = {self._track_to_person[tid] for tid in active_track_ids if tid in self._track_to_person}
        candidate, score = self._best_match(vector, second, center, occupied_people)
        if candidate and score >= self.threshold:
            memory = self._people[candidate]
            self._track_to_person[track_id] = candidate
            memory.track_ids.add(track_id)
            memory.match_scores.append(score)
            memory.prototype = self._blend(memory.prototype, vector)
            memory.last_second = second
            memory.last_center = center
            return candidate, round(score, 3), memory.visible_descriptor
        return self._create(track_id, vector, visible_descriptor, second, center)

    def _best_match(self, vector, second, center, occupied_people) -> tuple[str | None, float]:
        best_id, best_score = None, -1.0
        for person_id, memory in self._people.items():
            if person_id in occupied_people:
                continue
            appearance = float(np.clip(np.dot(vector, memory.prototype), 0, 1))
            gap = max(0, second - memory.last_second)
            temporal = max(0.0, 1.0 - gap / 180.0)
            distance = float(np.hypot(center[0] - memory.last_center[0], center[1] - memory.last_center[1]))
            spatial = max(0.0, 1.0 - distance / 1.2)
            score = 0.82 * appearance + 0.10 * temporal + 0.08 * spatial
            if score > best_score:
                best_id, best_score = person_id, score
        return best_id, best_score

    def _create(self, track_id, vector, descriptor, second, center) -> tuple[str, float, str]:
        person_id = f"persona_{self._next_id}"
        self._next_id += 1
        self._track_to_person[track_id] = person_id
        self._people[person_id] = _PersonMemory(
            person_id=person_id, prototype=vector, visible_descriptor=descriptor,
            last_second=second, last_center=center, track_ids={track_id}, match_scores=[1.0],
        )
        return person_id, 1.0, descriptor

    @staticmethod
    def _blend(previous: np.ndarray, current: np.ndarray) -> np.ndarray:
        mixed = previous * 0.8 + current * 0.2
        norm = np.linalg.norm(mixed)
        return mixed / norm if norm else current
