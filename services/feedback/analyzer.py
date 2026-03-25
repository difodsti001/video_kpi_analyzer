# services/feedback/analyzer.py
import os
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none")  # "openai" | "anthropic" | "gemini" | "none"
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")


# ── 1. REGLAS — etiquetas e interpretación por KPI ──────────────

def _nivel(score: float, umbrales: list) -> str:
    """umbrales = [(valor, etiqueta)] de mayor a menor."""
    for umbral, etiqueta in umbrales:
        if score >= umbral:
            return etiqueta
    return umbrales[-1][1]

def interpretar_speech_time(s: dict) -> dict:
    ratio = s.get("speech_ratio", 0)
    nivel = _nivel(ratio, [(0.75, "alto"), (0.60, "óptimo"), (0.40, "bajo")])
    return {
        "nivel":      nivel,
        "fortaleza":  nivel == "óptimo",
        "resumen":    f"Habla el {ratio:.0%} del tiempo ({nivel}). "
                      f"{s.get('silence_count',0)} pausas, promedio {s.get('avg_silence',0):.1f}s.",
    }

def interpretar_rhythm(r: dict) -> dict:
    wpm   = r.get("avg_wpm", 0)
    score = r.get("wpm_score", 0)
    nivel = _nivel(wpm, [(160, "rápido"), (120, "óptimo"), (0, "lento")])
    return {
        "nivel":     nivel,
        "fortaleza": nivel == "óptimo",
        "resumen":   f"{wpm:.0f} WPM ({nivel}), score {score:.2f}. "
                     f"{r.get('strategic_pauses',0)} pausas estratégicas.",
    }

def interpretar_sentiment(s: dict) -> dict:
    score = s.get("overall_score", 0)
    label = s.get("label", "neutral")
    pos   = s.get("positive_ratio", 0)
    neg   = s.get("negative_ratio", 0)
    return {
        "nivel":     label,
        "fortaleza": score > 0.1,
        "resumen":   f"Tono {label} (score {score:.2f}). "
                     f"Positivo {pos:.0%}, negativo {neg:.0%}. "
                     f"Arco narrativo con tensión y resolución.",
    }

def interpretar_clarity(c: dict) -> dict:
    score    = c.get("clarity_score", 0)
    fillers  = c.get("filler_count", 0)
    vocab    = c.get("vocab_diversity", 0)
    struct   = c.get("structure", {})
    nivel    = _nivel(score, [(0.80, "alto"), (0.60, "medio"), (0, "bajo")])
    return {
        "nivel":     nivel,
        "fortaleza": nivel in ("alto", "medio"),
        "resumen":   f"Claridad {nivel} (score {score:.2f}). "
                     f"{fillers} fillers, vocab diversity {vocab:.2f}. "
                     f"Estructura: intro={'sí' if struct.get('has_intro') else 'no'}, "
                     f"cierre={'sí' if struct.get('has_cierre') else 'no'}, "
                     f"{struct.get('preguntas_retoricas',0)} preguntas retóricas.",
    }

def interpretar_audio(a: dict) -> dict:
    var   = a.get("pitch_variation", 0)
    nivel = _nivel(var, [(0.25, "muy expresivo"), (0.15, "expresivo"), (0, "monótono")])
    return {
        "nivel":     nivel,
        "fortaleza": var >= 0.15,
        "resumen":   f"Pitch {a.get('pitch_mean_hz',0):.0f}Hz, variación {var:.2f} ({nivel}). "
                     f"Energía vocal {a.get('energy_mean',0):.3f} RMS, "
                     f"proyección {'sólida' if a.get('proyeccion_score',0) >= 0.8 else 'mejorable'}.",
    }


# ── 2. SCORE GLOBAL ─────────────────────────────────────────────

def calcular_score_global(interpretaciones: dict) -> float:
    pesos = {
        "speech_time": 0.15,
        "rhythm":      0.20,
        "sentiment":   0.15,
        "clarity":     0.25,
        "audio":       0.25,
    }
    scores_raw = {
        "speech_time": {"óptimo": 1.0, "alto": 0.7, "bajo": 0.4}.get(
                        interpretaciones["speech_time"]["nivel"], 0.5),
        "rhythm":      {"óptimo": 1.0, "rápido": 0.6, "lento": 0.5}.get(
                        interpretaciones["rhythm"]["nivel"], 0.5),
        "sentiment":   {"positive": 1.0, "neutral": 0.7, "negative": 0.4}.get(
                        interpretaciones["sentiment"]["nivel"], 0.5),
        "clarity":     {"alto": 1.0, "medio": 0.7, "bajo": 0.3}.get(
                        interpretaciones["clarity"]["nivel"], 0.5),
        "audio":       {"muy expresivo": 1.0, "expresivo": 0.75, "monótono": 0.3}.get(
                        interpretaciones["audio"]["nivel"], 0.5),
    }
    total = sum(scores_raw[k] * pesos[k] for k in pesos)
    return round(total * 10, 2)   # escala 0–10


# ── 3. PROMPT COMPACTO para el LLM ──────────────────────────────

def construir_prompt(interpretaciones: dict, score_global: float) -> str:
    i = interpretaciones
    fortalezas = [k for k, v in i.items() if v.get("fortaleza")]
    mejoras    = [k for k, v in i.items() if not v.get("fortaleza")]

    resumen_kpis = "\n".join(f"- {v['resumen']}" for v in i.values())

    prompt = f"""Eres un analista de oratoria en la enseñanza de docentes. Analiza esta presentación y escribe un feedback 
profesional en español, en 3 párrafos cortos: fortalezas, áreas de mejora y recomendación final.
Sé específico con los datos. No uses listas, solo prosa fluida.

Score general: {score_global}/10
Fortalezas detectadas: {', '.join(fortalezas) if fortalezas else 'ninguna destacada'}
Áreas a mejorar: {', '.join(mejoras) if mejoras else 'ninguna crítica'}

Datos:
{resumen_kpis}

Feedback:"""

    return prompt


# ── 4. LLAMADA AL LLM ────────────────────────────────────────────

def llamar_llm(prompt: str, interpretaciones: dict, score_global: float) -> str:
    if LLM_PROVIDER == "anthropic":
        return _llamar_anthropic(prompt)
    elif LLM_PROVIDER == "openai":
        return _llamar_openai(prompt)
    elif LLM_PROVIDER == "gemini":
        return _llamar_gemini(prompt)
    return _generar_narrativa_reglas(interpretaciones, score_global)

def _llamar_anthropic(prompt: str) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=LLM_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"[Error LLM: {e}]"

def _llamar_openai(prompt: str) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=LLM_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Error LLM: {e}]"
    
def _llamar_gemini(prompt: str) -> str:
    try:
        from google import genai
        client = genai.Client(api_key=LLM_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "max_output_tokens": 400,
                "temperature": 0.4
            }
        )

        return response.text.strip()
    except Exception as e:
        return f"[Error LLM Gemini: {e}]"

def _generar_narrativa_reglas(interpretaciones: dict, score_global: float) -> str:
    i = interpretaciones
    fortalezas = [k for k, v in i.items() if v.get("fortaleza")]
    mejoras    = [k for k, v in i.items() if not v.get("fortaleza")]

    nombres = {
        "speech_time": "el tiempo de habla",
        "rhythm":      "el ritmo",
        "sentiment":   "el tono emocional",
        "clarity":     "la claridad y estructura",
        "audio":       "la expresividad vocal",
    }

    # párrafo 1 — score y fortalezas
    p1 = f"La presentación obtuvo un score de {score_global}/10. "
    if fortalezas:
        lista = ", ".join(nombres[f] for f in fortalezas)
        p1 += f"Los puntos más sólidos son {lista}, que muestran un desempeño destacado."
    else:
        p1 += "Hay oportunidades de mejora en varias dimensiones."

    # párrafo 2 — detalle de cada KPI
    detalles = " ".join(v["resumen"] for v in i.values())
    p2 = detalles

    # párrafo 3 — recomendación
    if mejoras:
        lista_mejoras = ", ".join(nombres[m] for m in mejoras)
        p3 = f"Para seguir mejorando, se recomienda trabajar en {lista_mejoras}."
    else:
        p3 = "El desempeño es consistente en todas las dimensiones analizadas."

    return f"{p1}\n\n{p2}\n\n{p3}"

# ── 5. FUNCIÓN PRINCIPAL ─────────────────────────────────────────

def analyze_feedback(speech: dict, rhythm: dict, sentiment: dict,
                     clarity: dict, audio: dict) -> dict:
    interpretaciones = {
        "speech_time": interpretar_speech_time(speech),
        "rhythm":      interpretar_rhythm(rhythm),
        "sentiment":   interpretar_sentiment(sentiment),
        "clarity":     interpretar_clarity(clarity),
        "audio":       interpretar_audio(audio),
    }

    score_global = calcular_score_global(interpretaciones)
    prompt       = construir_prompt(interpretaciones, score_global)
    narrativa = llamar_llm(prompt, interpretaciones, score_global)

    return {
        "score_global":      score_global,
        "interpretaciones":  interpretaciones,
        "prompt_usado":      prompt,
        "narrativa":         narrativa,
    }
