"""Capa opcional de observación visual con un modelo multimodal.

No identifica rostros ni asigna nombres. Sus respuestas son observaciones que
después se contrastan con la evidencia de tracking/pose del analizador.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from dotenv import load_dotenv


SYSTEM_PROMPT = """Eres un observador objetivo de un video de aula.
Las imágenes pertenecen a una sola ventana temporal y están ordenadas. Produce
UNA única síntesis breve de los elementos visibles y de los cambios visibles
entre ellas. Describe exclusivamente hechos que puedan verse.

No identifiques personas ni las llames docente, estudiante o participante. No
describas rasgos físicos. No atribuyas voz, habla, explicaciones, atención,
intenciones, emociones, aprendizaje ni roles. No uses 'parece', 'la misma
persona' ni afirmes continuidad de identidad. Usa 'persona no identificada' o
'grupo de personas' cuando corresponda. No inventes información fuera de las
imágenes.

Devuelve solamente JSON válido con esta forma:
{
  "observations": [{"text": "descripción objetiva breve", "labels": ["..."], "confidence": 0.0}]
}
Devuelve cero o UNA observación, nunca una por cada imagen.
Las etiquetas permitidas son solo: person_movement, raised_hand,
person_at_front, group_visible, board_or_screen_visible, object_interaction.
Incluye una etiqueta solo si es visible. confidence debe estar entre 0 y 1.
"""

_FORBIDDEN_OBSERVATION = re.compile(
    r"\b(habla|hablando|dijo|dice|explica|explicando|presentaci[oó]n|parece|"
    r"estudiante|docente|participante|misma persona|observa|observando|atenci[oó]n)\b",
    re.IGNORECASE,
)


def _parse_response(content: str) -> list[dict[str, Any]]:
    """Valida y limita la estructura recibida de la IA."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("La IA de visión no devolvió JSON válido") from exc

    allowed_labels = {
        "person_movement", "raised_hand", "person_at_front", "group_visible",
        "board_or_screen_visible", "object_interaction",
    }
    observations = payload.get("observations", []) if isinstance(payload, dict) else []
    if not isinstance(observations, list):
        return []

    clean: list[dict[str, Any]] = []
    for observation in observations[:1]:
        if not isinstance(observation, dict) or not isinstance(observation.get("text"), str):
            continue
        observation_text = observation["text"].strip()
        # Si el modelo se sale del alcance objetivo, es preferible omitir esa
        # afirmación antes que conservar una inferencia como si fuera evidencia.
        if not observation_text or _FORBIDDEN_OBSERVATION.search(observation_text):
            continue
        labels = observation.get("labels", [])
        if not isinstance(labels, list):
            labels = []
        try:
            confidence = float(observation.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        clean.append({
            "text": observation_text[:400],
            "labels": [label for label in labels if label in allowed_labels],
            "confidence": max(0.0, min(1.0, round(confidence, 2))),
        })
    return clean


class VisionDescriber:
    """Cliente deliberadamente pequeño para OpenAI o Azure OpenAI."""

    def __init__(self, provider: str, model: str | None = None) -> None:
        load_dotenv()
        self.provider = provider
        if provider == "azure":
            from openai import AzureOpenAI
            self.model = model or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
            api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
            if not self.model or not endpoint or not api_key:
                raise RuntimeError(
                    "Para --vision-provider azure faltan AZURE_OPENAI_ENDPOINT, "
                    "AZURE_OPENAI_API_KEY o AZURE_OPENAI_DEPLOYMENT/--vision-model"
                )
            self.client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            )
        elif provider == "openai":
            from openai import OpenAI
            self.model = model or os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key:
                raise RuntimeError("Para --vision-provider openai falta OPENAI_API_KEY")
            self.client = OpenAI(api_key=api_key)
        else:
            raise ValueError("provider debe ser 'azure' u 'openai'")

    def describe_window(self, images_jpeg: list[bytes], start_seconds: float, end_seconds: float) -> dict:
        if not images_jpeg:
            return {"start_seconds": start_seconds, "end_seconds": end_seconds, "observations": []}

        content: list[dict] = [{
            "type": "text",
            "text": f"Ventana temporal aproximada [{start_seconds:.1f}, {end_seconds:.1f}] segundos. "
                    "Las imágenes están ordenadas de forma cronológica.",
        }]
        for image in images_jpeg:
            content.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"), "detail": "low"},
            })
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=220,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        )
        response_text = response.choices[0].message.content or "{}"
        return {
            "start_seconds": round(start_seconds, 2),
            "end_seconds": round(end_seconds, 2),
            "observations": _parse_response(response_text),
            "source": f"vision_{self.provider}",
        }
