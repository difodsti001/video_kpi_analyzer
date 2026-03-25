import re

FILLERS = {
    # clásicos
    "eh", "ehh", "eeh", "eeeh", "mmm", "mhm", "emmm",

    # muletillas comunes
    "este", "esto", "o sea", "osea", "bueno", "pues",
    "entonces", "digamos", "a ver",

    # muletillas modernas
    "básicamente", "literalmente", "obviamente", "claramente",
    "prácticamente", "simplemente", "realmente",

    # redundantes
    "de alguna manera", "de alguna forma", "por así decirlo",
    "más o menos", "en cierto modo",

    # inseguridad / relleno cognitivo
    "creo que", "pienso que", "podríamos decir",
    "no sé", "no estoy seguro",

    # repetición oral típica
    "sí sí", "no no", "vale", "ok", "okay",
}

CONECTORES = {
    "causalidad": {
        "porque", "ya que", "debido a", "puesto que",
        "a causa de", "gracias a", "por eso", "por tanto",
        "por lo cual", "de ahí que"
    },

    "contraste": {
        "pero", "sin embargo", "aunque", "no obstante",
        "a pesar de", "en cambio", "por el contrario",
        "mientras que"
    },

    "secuencia": {
        "primero", "segundo", "tercero",
        "luego", "después", "más tarde",
        "finalmente", "por último", "a continuación"
    },

    "adición": {
        "además", "también", "asimismo",
        "incluso", "de igual manera", "de la misma forma"
    },

    "ejemplos": {
        "por ejemplo", "como", "tal como",
        "es decir", "o sea", "en otras palabras",
        "por caso"
    },

    "énfasis": {
        "de hecho", "en realidad", "sin duda",
        "ciertamente", "claramente", "efectivamente"
    },

    "condición": {
        "si", "si no", "siempre que", "en caso de",
        "a menos que"
    },

    "comparación": {
        "como", "igual que", "similar a",
        "de la misma manera", "así como"
    },

    "conclusión": {
        "en conclusión", "en resumen",
        "para concluir", "en definitiva",
        "por lo tanto", "por consiguiente",
        "en síntesis"
    },

    "transición": {
        "bien", "ahora", "dicho esto",
        "por otro lado", "en otro orden de ideas"
    }
}

INTRO_MARKERS = {
    # apertura clásica
    "hoy", "vamos a", "voy a", "el tema", "hablaremos",

    # contexto educativo
    "en esta clase", "en este video", "en esta sesión",
    "el objetivo es", "aprenderemos", "veremos",

    # engagement
    "bienvenidos", "hola", "qué tal",
    "comencemos", "empezamos",

    # framing
    "antes de empezar", "para comenzar",
    "primero vamos a ver"
}
CIERRE_MARKERS = {
    # cierre directo
    "gracias", "eso es todo", "hemos terminado",

    # resumen
    "en conclusión", "en resumen", "resumiendo",
    "para cerrar", "en definitiva", "en síntesis",

    # cierre pedagógico
    "para recordar", "lo importante es",
    "nos quedamos con", "como vimos",

    # call to action
    "practiquen", "intenten", "apliquen",
    "nos vemos", "hasta la próxima"
}

PREGUNTAS_KEYWORDS = {
    "qué", "por qué", "cómo", "cuándo", "dónde",
    "se han preguntado", "alguna vez", "qué pasaría"
}

STRUCTURE_SIGNALS = {
    "definición": {"es", "se define como", "consiste en"},
    "explicación": {"esto significa", "es decir", "en otras palabras"},
    "causa_efecto": {"provoca", "genera", "resulta en"},
    "ejemplo": {"por ejemplo", "imaginemos", "supongamos"},
}

STOPWORDS = {"de", "la", "el", "en", "y", "a", "que", "los", "las", "un", "una",
                 "es", "se", "con", "por", "su", "para", "como", "más", "pero", "o"}

def _split_sentences(text: str) -> list[str]:
    return re.split(r'(?<=[.!?])\s+', text)


def analyze_structure(transcript: str, words: list[dict]) -> dict:
    """
    Analiza estructura discursiva: intro, cierre, conectores, preguntas retóricas.
    """
    if not transcript or not words:
        return {}

    text_lower = transcript.lower()
    sentences  = _split_sentences(transcript)
    duration   = words[-1]["end"] - words[0]["start"]

    # intro y cierre: busca en primer y último 10% del texto
    cutoff_intro = len(transcript) // 10
    cutoff_cierre = len(transcript) - len(transcript) // 10
    intro_text  = text_lower[:cutoff_intro]
    cierre_text = text_lower[cutoff_cierre:]

    has_intro  = any(m in intro_text  for m in INTRO_MARKERS)
    has_cierre = any(m in cierre_text for m in CIERRE_MARKERS)

    # preguntas retóricas
    preguntas = []
    for s in sentences:
        s_clean = s.strip().lower()
        if (
            s_clean.endswith("?") or
            s_clean.startswith("¿") or
            any(k in s_clean for k in PREGUNTAS_KEYWORDS)
        ):
            preguntas.append(s.strip())
    preguntas_por_min = round(len(preguntas) / (duration / 60), 2) if duration else 0

    # conectores por categoría
    conectores_encontrados = {}
    for categoria, terminos in CONECTORES.items():
        hits = [t for t in terminos if t in text_lower]
        if hits:
            conectores_encontrados[categoria] = hits

    total_conectores = sum(len(v) for v in conectores_encontrados.values())

    # estructura lógica: señales de definición, explicación, causa-efecto, ejemplos
    estructura_logica = {}
    for tipo, terminos in STRUCTURE_SIGNALS.items():
        hits = [t for t in terminos if t in text_lower]
        if hits:
            estructura_logica[tipo] = hits

    total_estructura = sum(len(v) for v in estructura_logica.values())

    # repeticiones: palabras que aparecen más del 1% del total (excluye stopwords)
    word_list  = [w["word"].lower().strip("¡!¿?.,;:\"'") for w in words]
    freq       = {}
    for w in word_list:
        if w not in STOPWORDS and len(w) > 3:
            freq[w] = freq.get(w, 0) + 1
    umbral     = max(3, len(word_list) * 0.01)
    repetidas  = {w: c for w, c in freq.items() if c >= umbral}
    top_repetidas = sorted(repetidas.items(), key=lambda x: x[1], reverse=True)[:8]

    # coherencia
    densidad_conectores = total_conectores / max(len(sentences), 1)
    categorias_usadas = len(conectores_encontrados.keys())

    # penalizaciones por falta de estructura y exceso de repeticiones
    penalizacion = 0

    if len(top_repetidas) > 5:
        penalizacion += 0.1
    if total_conectores < 2:
        penalizacion += 0.15
    if total_estructura == 0:
        penalizacion += 0.15

    # score de estructura
    score = 0.0

    if has_intro: score += 0.15
    if has_cierre: score += 0.15

    score += min(total_conectores / 10, 1) * 0.2
    score += min(len(preguntas) / 5, 1) * 0.15
    score += min(total_estructura / 5, 1) * 0.2
    score += min(densidad_conectores, 1) * 0.15

    score -= penalizacion
    score = round(max(0, min(score, 1)), 3)

    return {
        "structure_score": score,
        "has_intro": has_intro,
        "has_cierre": has_cierre,
        "preguntas_retoricas": len(preguntas),
        "preguntas_por_min": preguntas_por_min,
        "ejemplos_preguntas": preguntas[:3],
        "conectores": conectores_encontrados,
        "total_conectores": total_conectores,
        "estructura_logica": estructura_logica,
        "total_estructura": total_estructura,
        "densidad_conectores": round(densidad_conectores, 3),
        "categorias_conectores": categorias_usadas,
        "palabras_repetidas": top_repetidas,
        "penalizacion": penalizacion,
    }


def analyze_clarity(words: list[dict], transcript: str) -> dict:
    """
    Recibe words con timestamps y el transcript completo.
    Devuelve métricas de claridad del habla.
    """
    if not words or not transcript:
        return {}

    total_words = len(words)
    word_list   = [w["word"].lower().strip("¡!¿?.,;:\"'") for w in words]

    # fillers
    filler_hits   = [w for w in word_list if w in FILLERS]
    filler_count  = len(filler_hits)
    filler_ratio  = round(filler_count / total_words, 4) if total_words else 0

    # diversidad de vocabulario (type-token ratio)
    unique_words  = set(word_list)
    vocab_diversity = round(len(unique_words) / total_words, 4) if total_words else 0

    # palabras largas = +3 sílabas estimadas (proxy: +7 caracteres)
    long_words    = [w for w in word_list if len(w) >= 7]
    long_ratio    = round(len(long_words) / total_words, 4) if total_words else 0

    # velocidad de fillers: fillers por minuto
    duration_min  = (words[-1]["end"] - words[0]["start"]) / 60
    fillers_per_min = round(filler_count / duration_min, 2) if duration_min else 0

    # score claridad: penaliza fillers y premia diversidad
    # filler_ratio óptimo < 0.03 (menos del 3% de palabras)
    filler_penalty  = min(filler_ratio / 0.05, 1.0)
    clarity_score   = round(
        (vocab_diversity * 0.5) + ((1 - filler_penalty) * 0.5),
        3
    )

    # top fillers usados
    filler_freq = {}
    for f in filler_hits:
        filler_freq[f] = filler_freq.get(f, 0) + 1
    top_fillers = sorted(filler_freq.items(), key=lambda x: x[1], reverse=True)[:5]

    structure = analyze_structure(transcript, words)

    return {
        "clarity_score":    clarity_score,
        "filler_count":     filler_count,
        "filler_ratio":     filler_ratio,
        "fillers_per_min":  fillers_per_min,
        "top_fillers":      top_fillers,
        "vocab_diversity":  vocab_diversity,
        "unique_words":     len(unique_words),
        "total_words":      total_words,
        "long_word_ratio":  long_ratio,
        "structure": structure,
    }

