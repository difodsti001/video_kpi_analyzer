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
import re

from services.transversal.llm.client import llamar_llm_con_uso, DEBUG_LLM_PROMPTS
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

def _seleccionar_evidencias_temporales(ficha_evidencias: dict | None,
                                       limite: int = 24) -> list[dict]:
    """Prepara una muestra breve de ventanas fechadas para la retroalimentación.

    La ficha completa se conserva en la extracción. Al LLM se le entrega una
    muestra acotada para evitar que un video largo convierta el prompt en un
    duplicado de toda la transcripción.
    """
    ventanas = (ficha_evidencias or {}).get("transcripcion_multimodal", [])
    candidatas = [v for v in ventanas if v.get("audio") or v.get("visual")]
    if len(candidatas) <= limite:
        seleccion = candidatas
    else:
        paso = (len(candidatas) - 1) / (limite - 1)
        indices = sorted({round(i * paso) for i in range(limite)})
        seleccion = [candidatas[i] for i in indices]

    return [
        {
            "id": f"E{index:02d}",
            "tiempo": f"{v.get('inicio', '00:00:00')}–{v.get('fin', '00:00:00')}",
            "audio": v.get("audio"),
            "visual": v.get("visual"),
        }
        for index, v in enumerate(seleccion, start=1)
    ]


def construir_evidencia(transcript: str, interpretaciones: dict, objetos: dict,
                        ficha_evidencias: dict | None = None) -> dict:
    """Condensa texto, señales y una muestra de evidencia fechada."""
    objetos_detectados = [
        f"{o['label']} (presente {o['presencia_segundos']}s, confianza promedio {o['confianza_promedio']})"
        for o in (objetos or {}).get("objetos", [])
    ]

    return {
        "transcript":         transcript or "",
        "resumen_kpis":       {k: v["resumen"] for k, v in interpretaciones.items()},
        "objetos_detectados": objetos_detectados,
        "evidencias_temporales": _seleccionar_evidencias_temporales(ficha_evidencias),
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


def construir_prompt_evaluacion(evidencia: dict, score_oratoria: float,
                                criterios_rubrica: list[dict],
                                peso_contenido: float = 0.70,
                                peso_forma: float = 0.30) -> str:
    criterios_txt = "\n\n".join(_bloque_criterio(c) for c in criterios_rubrica)
    kpis_txt      = "\n".join(f"- {k}: {v}" for k, v in evidencia["resumen_kpis"].items())
    objetos_txt   = "; ".join(evidencia["objetos_detectados"]) or "no se detectaron objetos relevantes"
    temporales_txt = "\n".join(
        f"- [{item['id']}] {item['tiempo']} | Audio: {item.get('audio') or 'sin habla transcrita'} | "
        f"Visual: {item.get('visual') or 'sin observación visual'}"
        for item in evidencia.get("evidencias_temporales", [])
    ) or "No hay ventanas temporales disponibles."

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

    return f"""Eres un asistente de análisis de evidencias pedagógicas. Organizas la evidencia de una
grabación de clase usando la rúbrica como referencia para orientar una conversación pedagógica humana.
No emites una valoración final automática. Da prioridad al contenido pedagógico ({peso_contenido:.0%}) y
usa la forma u oratoria ({peso_forma:.0%}) solo como complemento.

PASO 1 — Evalúa cada criterio de la rúbrica usando ÚNICAMENTE la evidencia de la transcripción, \
eligiendo el nivel que mejor describe el desempeño según los niveles definidos en cada criterio, y \
justificando con datos concretos.{instruccion_puntaje}

{criterios_txt}

PASO 2 — Para la salida pública NO redactes texto libre. Por cada criterio devuelve una orientación
estructurada que seleccione uno o dos IDs de las ventanas [E##] entregadas abajo. Solo puedes seleccionar
IDs existentes. La aplicación insertará literalmente el tiempo y el fragmento de evidencia asociado.

Para cada criterio devuelve: (1) `evidencia_ids`, con uno o dos IDs; (2) `lectura_pedagogica`, una
interpretación prudente de máximo 45 palabras basada EXCLUSIVAMENTE en esos IDs; y (3) `sugerencia`, una
estrategia específica, realizable en la próxima sesión, de máximo 70 palabras. Explica cómo implementarla:
qué pregunta formular, cuánto tiempo de espera dar, qué producto pedir o cómo recoger respuestas. No uses
recomendaciones genéricas como "hacer actividades más dinámicas".

Esta narrativa pública NO debe incluir puntajes, niveles, calificaciones, verbos como "cumple/no cumple",
ni una valoración global. No menciones modelos, cobertura, calidad técnica ni limitaciones de extracción.
No atribuyas una pose o una persona detectada al docente. No agregues personas, acciones, materiales,
actividades o hechos que no aparezcan literalmente en los IDs seleccionados. Si no hay evidencia suficiente,
devuelve una lista vacía de IDs y una lectura que empiece por "La evidencia disponible permite profundizar
en..."; nunca afirmes que algo no ocurrió ni que no se brindó una práctica.

── EVIDENCIA ──
Transcripción:
\"\"\"
{evidencia['transcript']}
\"\"\"

KPIs de oratoria (score de forma: {score_oratoria}/10):
{kpis_txt}

Objetos/recursos detectados en el video:
{objetos_txt}

Ventanas temporales de evidencia (la descripción visual no identifica el rol de una persona):
{temporales_txt}

── FORMATO DE RESPUESTA ──
Responde ÚNICAMENTE con un JSON válido, sin texto adicional antes ni después, con esta forma exacta:
{{
  "criterios": {{
    {ids_json}
  }},
  "orientacion_por_criterio": {{
    "id_del_criterio": {{
      "evidencia_ids": ["E01"],
      "lectura_pedagogica": "...",
      "sugerencia": "..."
    }}
  }}
}}"""


# ── 3. PARSEO DEFENSIVO ──────────────────────────────────────────
# extraer_json() vive en services/transversal/llm/json_response.py

def _limpiar_texto_publico(texto: object) -> str:
    if not isinstance(texto, str):
        return ""
    # Algunos proveedores devuelven saltos como barras literales.
    return re.sub(r"\\+(?:n|\s*)", "\n", texto).strip()


def _fragmento_evidencia(evidencia: dict) -> str:
    texto = evidencia.get("audio") or evidencia.get("visual") or "sin detalle textual"
    texto = " ".join(str(texto).split())
    return texto[:300].rstrip() + ("…" if len(texto) > 300 else "")


def _construir_retroalimentacion_controlada(data: dict, criterios_rubrica: list[dict],
                                            evidencia: dict | None) -> str | None:
    orientaciones = data.get("orientacion_por_criterio")
    evidencias = (evidencia or {}).get("evidencias_temporales", [])
    if not isinstance(orientaciones, dict) or not evidencias:
        return None

    por_id = {item.get("id"): item for item in evidencias if item.get("id")}
    parrafos = []
    for criterio in criterios_rubrica:
        orientacion = orientaciones.get(criterio["id"], {})
        if not isinstance(orientacion, dict):
            orientacion = {}
        ids = orientacion.get("evidencia_ids", [])
        ids = ids if isinstance(ids, list) else []
        seleccionadas = [por_id[item] for item in ids[:2] if item in por_id]
        if seleccionadas:
            citas = " ".join(
                f"En {item['tiempo']}, la ficha registra: “{_fragmento_evidencia(item)}”."
                for item in seleccionadas
            )
        else:
            citas = "La evidencia disponible permite profundizar en este criterio."
        lectura = _limpiar_texto_publico(orientacion.get("lectura_pedagogica"))
        sugerencia = _limpiar_texto_publico(orientacion.get("sugerencia"))
        if not lectura:
            lectura = "La evidencia disponible permite profundizar en este aspecto de la práctica."
        if not sugerencia:
            sugerencia = "En la próxima sesión, defina una acción observable vinculada con este criterio y regístrela en la ficha."
        parrafos.append(f"{criterio['nombre']}: {citas} {lectura} Para la próxima sesión, {sugerencia}")
    return "\n\n".join(parrafos)


def parsear_respuesta(raw: str | None, criterios_rubrica: list[dict],
                      evidencia: dict | None = None) -> tuple[dict, str]:
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

    retroalimentacion = _construir_retroalimentacion_controlada(
        data, criterios_rubrica, evidencia
    ) if isinstance(data, dict) else None
    retroalimentacion = retroalimentacion or (
        data.get("retroalimentacion_pedagogica") if isinstance(data, dict) else None
    )
    # Compatibilidad con resultados generados antes de la ficha narrativa.
    retroalimentacion = retroalimentacion or (
        data.get("resumen_ejecutivo") if isinstance(data, dict) else None
    )
    if not retroalimentacion:
        retroalimentacion = (
            "No fue posible generar la retroalimentación pedagógica. "
            "Puede revisar la ficha de evidencias para orientar la conversación pedagógica."
        )

    return criterios, _limpiar_texto_publico(retroalimentacion)


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
                    peso_contenido: float = 0.70, peso_forma: float = 0.30,
                    ficha_evidencias: dict | None = None) -> dict:
    interpretaciones = construir_interpretaciones(speech, rhythm, sentiment, clarity, audio)
    score_oratoria   = calcular_score_global(interpretaciones)

    evidencia = construir_evidencia(transcript, interpretaciones, objetos, ficha_evidencias)
    prompt    = construir_prompt_evaluacion(
        evidencia, score_oratoria, criterios_rubrica, peso_contenido, peso_forma
    )
    raw, uso  = llamar_llm_con_uso(prompt, max_tokens=3000)

    criterios, retroalimentacion = parsear_respuesta(raw, criterios_rubrica, evidencia)
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
        # Se conserva el alias para consumidores anteriores; la interfaz usa
        # retroalimentacion_pedagogica y nunca muestra la calificación.
        "resumen_ejecutivo":         retroalimentacion,
        "retroalimentacion_pedagogica": retroalimentacion,
        "consumo_ia": [dict(uso, capa_ia="analisis_pedagogico")] if uso else [],
    }
    if DEBUG_LLM_PROMPTS:
        resultado["prompt_usado"] = prompt
    return resultado
