# services/evaluacion/analyzer.py
# Evaluación integral del docente en acción: una sola llamada LLM que juzga
# la rúbrica de contenido del curso y redacta el resumen ejecutivo, cruzando
# esa lectura con los KPIs de oratoria (calculados por reglas) y los
# recursos/objetos detectados en el video.
#
# La rúbrica (criterios/niveles/pesos) y la ponderación contenido/forma ya
# NO son fijas acá — las define el curso (ver shared.models.RubricaCurso /
# services.cursos.registro) y se reciben como parámetro, para que distintos
# cursos puedan evaluar con criterios distintos sin tocar este archivo.
from services.transversal.llm.client import llamar_llm, DEBUG_LLM_PROMPTS
from services.transversal.llm.json_response import extraer_json
from services.transversal.feedback.analyzer import construir_interpretaciones, calcular_score_global

# I-ED-L-D → 1-4. Esto sí es fijo: es la escala de niveles del proyecto, no
# algo que varíe por curso (lo que varía es QUÉ describe cada nivel).
NIVEL_VALOR = {"inicio": 1, "en desarrollo": 2, "logrado": 3, "destacado": 4}
ORDEN_NIVELES = ("Inicio", "En desarrollo", "Logrado", "Destacado")


def _usa_puntaje_directo(criterio: dict) -> bool:
    """Una rúbrica puede definir puntos por criterio (en vez de pesos 0-1)."""
    return "max_puntos" in criterio


# ── 1. EVIDENCIA ──────────────────────────────────────────────────

def construir_evidencia(transcript: str, interpretaciones: dict, objetos: dict) -> dict:
    """Condensa transcript + interpretaciones de KPIs + objetos detectados."""
    objetos_detectados = [
        f"{o['label']} (presente {o['presencia_segundos']}s, confianza promedio {o['confianza_promedio']})"
        for o in (objetos or {}).get("objetos", [])
    ]

    return {
        "transcript":         transcript or "",
        "resumen_kpis":       {k: v["resumen"] for k, v in interpretaciones.items()},
        "objetos_detectados": objetos_detectados,
    }


# ── 2. PROMPT ─────────────────────────────────────────────────────

def _bloque_criterio(c: dict) -> str:
    niveles = c["niveles"]
    escala = (
        f"({c['max_puntos']} puntos máximos)"
        if _usa_puntaje_directo(c)
        else f"(peso {c['peso']:.0%})"
    )
    niveles_txt = "\n".join(
        f"- {nombre}: {niveles[nombre]}"
        for nombre in ORDEN_NIVELES
        if nombre in niveles
    )
    return (
        f"### {c['id']} — {c['nombre']} {escala}\n"
        f"Qué evalúa: {c['que_evalua']}\n"
        f"{niveles_txt}"
    )


def construir_prompt_evaluacion(evidencia: dict, score_oratoria: float, criterios_rubrica: list[dict]) -> str:
    criterios_txt = "\n\n".join(_bloque_criterio(c) for c in criterios_rubrica)
    kpis_txt      = "\n".join(f"- {k}: {v}" for k, v in evidencia["resumen_kpis"].items())
    objetos_txt   = "; ".join(evidencia["objetos_detectados"]) or "no se detectaron objetos relevantes"

    ids_json = ",\n  ".join(
        (
            f'"{c["id"]}": {{"nivel": "Inicio|En desarrollo|Logrado|Destacado", '
            f'"puntaje": 0, "justificacion": "..."}}'
            if _usa_puntaje_directo(c) else
            f'"{c["id"]}": {{"nivel": "Inicio|En desarrollo|Logrado|Destacado", "justificacion": "..."}}'
        )
        for c in criterios_rubrica
    )

    instruccion_puntaje = ""
    if any(_usa_puntaje_directo(c) for c in criterios_rubrica):
        instruccion_puntaje = (
            " Para cada criterio que indique puntos máximos, incluye también `puntaje` "
            "como un número entero dentro del rango descrito por el nivel elegido."
        )

    return f"""Eres un evaluador pedagógico. Tu tarea es evaluar a un docente en acción a partir de la \
grabación de su clase, considerando tanto el CONTENIDO de lo que enseña (rúbrica) como la FORMA en que \
lo comunica (oratoria) y los recursos que usa en el video.

PASO 1 — Evalúa cada criterio de la rúbrica usando ÚNICAMENTE la evidencia de la transcripción, \
eligiendo el nivel que mejor describe el desempeño según los niveles definidos en cada criterio, y \
justificando con datos concretos.{instruccion_puntaje}

{criterios_txt}

PASO 2 — Redacta un resumen ejecutivo amplio y detallado en español (7-9 párrafos, prosa fluida, sin \
listas ni viñetas) que desarrolle en profundidad:
(1) si el docente cumple con los lineamientos y el propósito de la clase, con contexto de qué se enseñó;
(2) un repaso criterio por criterio de la rúbrica, explicando el porqué de cada nivel asignado y no solo \
   repitiendo la justificación breve;
(3) fortalezas de contenido pedagógico con ejemplos concretos citados o parafraseados de la transcripción;
(4) debilidades de contenido pedagógico, igualmente con ejemplos concretos;
(5) análisis de la oratoria (ritmo, tiempo de habla, claridad, tono emocional, expresividad vocal) y qué \
   tanto ayuda o perjudica la comprensión del contenido;
(6) análisis de la composición del video (recursos/objetos detectados, uso de pizarra, tecnología, \
   mobiliario) y su pertinencia pedagógica;
(7) una síntesis integradora de cómo se combinan contenido y forma en el desempeño general;
(8) recomendaciones concretas y accionables, priorizadas de mayor a menor impacto;
(9) un cierre breve con la valoración global del docente en acción.
Sé específico y evita generalidades vacías: cada afirmación debe apoyarse en un dato concreto de la \
evidencia (una cita de la transcripción, un valor de KPI, o un objeto detectado).

── EVIDENCIA ──
Transcripción:
\"\"\"
{evidencia['transcript']}
\"\"\"

KPIs de oratoria (score de forma: {score_oratoria}/10):
{kpis_txt}

Objetos/recursos detectados en el video:
{objetos_txt}

── FORMATO DE RESPUESTA ──
Responde ÚNICAMENTE con un JSON válido, sin texto adicional antes ni después, con esta forma exacta:
{{
  "criterios": {{
    {ids_json}
  }},
  "resumen_ejecutivo": "..."
}}"""


# ── 3. PARSEO DEFENSIVO ──────────────────────────────────────────
# extraer_json() vive en services/transversal/llm/json_response.py

def parsear_respuesta(raw: str | None, criterios_rubrica: list[dict]) -> tuple[dict, str]:
    try:
        data = extraer_json(raw)
    except Exception:
        data = {}

    criterios_raw = data.get("criterios", {}) if isinstance(data, dict) else {}
    criterios = {}
    for c in criterios_rubrica:
        entry = criterios_raw.get(c["id"], {}) if isinstance(criterios_raw, dict) else {}
        nivel = entry.get("nivel", "no evaluado") if isinstance(entry, dict) else "no evaluado"
        puntaje = entry.get("puntaje") if isinstance(entry, dict) else None
        if _usa_puntaje_directo(c):
            try:
                puntaje_decimal = float(puntaje)
                puntaje = int(puntaje_decimal)
                if puntaje_decimal != puntaje:
                    puntaje = None
            except (TypeError, ValueError):
                puntaje = None
            if puntaje is not None and not 0 <= puntaje <= c["max_puntos"]:
                puntaje = None
            rango = c.get("rangos_puntaje", {}).get(str(nivel))
            if puntaje is not None and rango and not rango[0] <= puntaje <= rango[1]:
                puntaje = None
        criterios[c["id"]] = {
            "nombre":        c["nombre"],
            "peso":          c["peso"],
            "nivel":         nivel,
            "justificacion": entry.get("justificacion", "") if isinstance(entry, dict) else "",
            "valor":         NIVEL_VALOR.get(str(nivel).strip().lower()),
            "puntaje":       puntaje,
            "max_puntos":    c.get("max_puntos"),
        }

    resumen_ejecutivo = data.get("resumen_ejecutivo") if isinstance(data, dict) else None
    if not resumen_ejecutivo:
        resumen_ejecutivo = "No se pudo generar el resumen ejecutivo (respuesta del LLM no disponible o inválida)."

    return criterios, resumen_ejecutivo


# ── 4. SCORES ─────────────────────────────────────────────────────

def calcular_score_rubrica(criterios: dict) -> float | None:
    criterios_con_puntos = [c for c in criterios.values() if c.get("max_puntos") is not None]
    if criterios_con_puntos:
        if len(criterios_con_puntos) != len(criterios) or any(c.get("puntaje") is None for c in criterios_con_puntos):
            return None
        maximo = sum(c["max_puntos"] for c in criterios_con_puntos)
        if maximo == 0:
            return None
        return round(sum(c["puntaje"] for c in criterios_con_puntos) / maximo * 20, 2)

    total_peso  = 0.0
    total_valor = 0.0
    for c in criterios.values():
        if c["valor"] is None:
            continue
        total_valor += (c["valor"] / 4) * c["peso"]
        total_peso  += c["peso"]

    if total_peso == 0:
        return None
    return round((total_valor / total_peso) * 20, 2)


def calcular_score_final(score_rubrica: float | None, score_oratoria: float,
                         peso_contenido: float, peso_forma: float) -> float:
    """Combina contenido (0-20) y forma (0-10 -> 0-20) en un score vigesimal final."""
    contenido = score_rubrica if score_rubrica is not None else 0.0
    forma     = score_oratoria * 2

    if score_rubrica is None:
        return round(forma, 2)

    return round(contenido * peso_contenido + forma * peso_forma, 2)


# ── 5. FUNCIÓN PRINCIPAL ─────────────────────────────────────────

def evaluar_docente(transcript: str, speech: dict, rhythm: dict, sentiment: dict,
                    clarity: dict, audio: dict, objetos: dict,
                    criterios_rubrica: list[dict],
                    peso_contenido: float = 0.70, peso_forma: float = 0.30) -> dict:
    interpretaciones = construir_interpretaciones(speech, rhythm, sentiment, clarity, audio)
    score_oratoria   = calcular_score_global(interpretaciones)

    evidencia = construir_evidencia(transcript, interpretaciones, objetos)
    prompt    = construir_prompt_evaluacion(evidencia, score_oratoria, criterios_rubrica)
    raw       = llamar_llm(prompt, max_tokens=3000)

    criterios, resumen_ejecutivo = parsear_respuesta(raw, criterios_rubrica)
    score_rubrica = calcular_score_rubrica(criterios)
    score_final   = calcular_score_final(score_rubrica, score_oratoria, peso_contenido, peso_forma)

    resultado = {
        "score_final":               score_final,
        "score_rubrica":             score_rubrica,
        "score_oratoria":            score_oratoria,
        "escala":                    "vigesimal (0-20)",
        "ponderacion":               {"contenido": peso_contenido, "forma": peso_forma},
        "criterios":                 criterios,
        "interpretaciones_oratoria": interpretaciones,
        "resumen_ejecutivo":         resumen_ejecutivo,
    }
    if DEBUG_LLM_PROMPTS:
        resultado["prompt_usado"] = prompt
    return resultado
