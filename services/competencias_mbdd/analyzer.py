# services/competencias_mbdd/analyzer.py
# Detección (no calificación) de qué competencias del MBDD se evidencian en la
# sesión, a partir de la transcripción y la evidencia ya disponible en el
# pipeline. Pensado como una pieza que refuerza la retroalimentación al
# docente: le muestra en qué competencias del marco se reconoce su práctica.
import json
import re

from services.llm.client import llamar_llm, DEBUG_LLM_PROMPTS
from services.competencias_mbdd.mbdd_data import (
    COMPETENCIAS_MBDD, DOMINIOS, NIVELES_EVIDENCIA, NIVELES_FUERZA, FUERZA_NO_APLICA,
)

_DOMINIO_NOMBRE = {d["id"]: d["nombre"] for d in DOMINIOS}


# ── 1. EVIDENCIA ──────────────────────────────────────────────────

def construir_evidencia(transcript: str, resumen_kpis: dict, objetos: dict) -> dict:
    objetos_detectados = [
        f"{o['label']} (presente {o['presencia_segundos']}s, confianza promedio {o['confianza_promedio']})"
        for o in (objetos or {}).get("objetos", [])
    ]
    return {
        "transcript":         transcript or "",
        "resumen_kpis":       resumen_kpis or {},
        "objetos_detectados": objetos_detectados,
    }


# ── 2. PROMPT ─────────────────────────────────────────────────────

def _bloque_competencia(c: dict) -> str:
    return f"### {c['id']} — {c['nombre']} ({_DOMINIO_NOMBRE[c['dominio']]})\n{c['descripcion']}"


def construir_prompt(evidencia: dict) -> str:
    bloques   = "\n\n".join(_bloque_competencia(c) for c in COMPETENCIAS_MBDD)
    kpis_txt  = "\n".join(f"- {k}: {v}" for k, v in evidencia["resumen_kpis"].items()) or "no disponible"
    objetos_txt = "; ".join(evidencia["objetos_detectados"]) or "no se detectaron objetos relevantes"

    ids_json = ",\n  ".join(
        f'"{c["id"]}": {{"evidencia": "sí|evidencia parcial|sin evidencia en esta sesión", '
        f'"fuerza": "alto|medio|bajo|no aplica", "justificacion": "..."}}'
        for c in COMPETENCIAS_MBDD
    )

    return f"""Eres un especialista en el Marco del Buen Desempeño Docente (MBDD) de MINEDU. Tu tarea \
es identificar, a partir de la evidencia de UNA sesión de clase grabada en video, en cuáles de las 9 \
competencias del marco se observa evidencia — NO calificar qué tan bien se desempeña el docente, solo \
detectar presencia o ausencia de evidencia.

Ten en cuenta que un solo video de una sesión permite observar con claridad el Dominio II (enseñanza en \
el aula). Los Dominios I, III y IV describen aspectos que ocurren mayormente fuera del aula (planificación \
colegiada, gestión escolar, relación con familias, reflexión institucional, ética profesional) y rara vez \
son plenamente observables en una grabación de clase: es válido y esperado que en varias de esas \
competencias la respuesta sea "sin evidencia en esta sesión" — no fuerces evidencia donde no la hay. Si \
aparece algo indirecto (una mención, una referencia), repórtalo como "evidencia parcial" y cita la frase \
exacta o el dato que lo sustenta.

Cuando "evidencia" sea "sí", indica además "fuerza": qué tan densa/recurrente es la evidencia encontrada \
en la sesión — NO qué tan bien ejecutada está. "bajo" = aparece una sola vez o de forma aislada; "medio" \
= aparece un par de veces con claridad; "alto" = es un elemento recurrente y central a lo largo de la \
sesión. Si "evidencia" es "evidencia parcial" o "sin evidencia en esta sesión", usa "fuerza": "no aplica".

{bloques}

── EVIDENCIA DE LA SESIÓN ──
Transcripción:
\"\"\"
{evidencia['transcript']}
\"\"\"

KPIs de oratoria:
{kpis_txt}

Objetos/recursos detectados en el video:
{objetos_txt}

── FORMATO DE RESPUESTA ──
Responde ÚNICAMENTE con un JSON válido, sin texto adicional antes ni después, con esta forma exacta:
{{
  {ids_json}
}}"""


# ── 3. PARSEO DEFENSIVO ──────────────────────────────────────────

def _extraer_json(texto: str) -> dict:
    match = re.search(r"\{.*\}", texto or "", re.S)
    if not match:
        raise ValueError("No se encontró JSON en la respuesta del LLM")
    return json.loads(match.group(0))


def parsear_respuesta(raw: str | None) -> dict:
    try:
        data = _extraer_json(raw)
    except Exception:
        data = {}

    resultado = {}
    for c in COMPETENCIAS_MBDD:
        entry = data.get(c["id"], {}) if isinstance(data, dict) else {}
        evidencia = entry.get("evidencia") if isinstance(entry, dict) else None
        if evidencia not in NIVELES_EVIDENCIA:
            evidencia = "no evaluado"

        # "fuerza" solo tiene sentido cuando hay evidencia confirmada ("sí").
        fuerza = entry.get("fuerza") if isinstance(entry, dict) else None
        if evidencia != "sí" or fuerza not in NIVELES_FUERZA:
            fuerza = FUERZA_NO_APLICA

        resultado[c["id"]] = {
            "nombre":        c["nombre"],
            "dominio":       c["dominio"],
            "dominio_nombre": _DOMINIO_NOMBRE[c["dominio"]],
            "evidencia":     evidencia,
            "fuerza":        fuerza,
            "justificacion": entry.get("justificacion", "") if isinstance(entry, dict) else "",
        }
    return resultado


# ── 4. FUNCIÓN PRINCIPAL ─────────────────────────────────────────

def detectar_competencias(transcript: str, resumen_kpis: dict, objetos: dict) -> dict:
    evidencia = construir_evidencia(transcript, resumen_kpis, objetos)
    prompt    = construir_prompt(evidencia)
    raw       = llamar_llm(prompt, max_tokens=1800)

    competencias = parsear_respuesta(raw)

    resultado = {"competencias": competencias}
    if DEBUG_LLM_PROMPTS:
        resultado["prompt_usado"] = prompt
    return resultado
