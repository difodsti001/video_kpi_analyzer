# services/feedback/analyzer.py
# Interpretación determinista (por reglas) de los KPIs de oratoria.
# Es el insumo que consume services/evaluacion/analyzer.py para la evaluación final.

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


# ── 3. INTERPRETACIÓN AGRUPADA ───────────────────────────────────

def construir_interpretaciones(speech: dict, rhythm: dict, sentiment: dict,
                               clarity: dict, audio: dict) -> dict:
    return {
        "speech_time": interpretar_speech_time(speech),
        "rhythm":      interpretar_rhythm(rhythm),
        "sentiment":   interpretar_sentiment(sentiment),
        "clarity":     interpretar_clarity(clarity),
        "audio":       interpretar_audio(audio),
    }
