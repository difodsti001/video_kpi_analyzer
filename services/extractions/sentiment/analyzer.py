from pysentimiento import create_analyzer

_sentiment_analyzer = None

_LABEL_MAP = {"POS": "positive", "NEG": "negative", "NEU": "neutral"}


def get_analyzer():
    global _sentiment_analyzer
    if _sentiment_analyzer is None:
        _sentiment_analyzer = create_analyzer(task="sentiment", lang="es")
    return _sentiment_analyzer


def _predict(analyzer, text: str) -> tuple[float, str]:
    """Devuelve (score -1..1, label positive/negative/neutral) para un texto."""
    result = analyzer.predict(text[:512])
    probas = result.probas
    score  = round(probas.get("POS", 0.0) - probas.get("NEG", 0.0), 3)
    label  = _LABEL_MAP.get(result.output, "neutral")
    return score, label


def analyze_sentiment(transcript: str, words: list[dict]) -> dict:
    """
    Analiza sentimiento del transcript por segmentos usando un modelo entrenado
    en español (pysentimiento/robertuito-sentiment-analysis), con salida directa
    positive/negative/neutral en vez de inferirlo de un rating de estrellas.
    Devuelve score general y evolución a lo largo del video.
    """
    if not transcript or not words:
        return {}

    analyzer = get_analyzer()

    # dividir transcript en segmentos de ~200 caracteres
    # (evita textos demasiado largos por inferencia)
    segments = _split_text(transcript, max_chars=200)

    scores = []
    labels = []
    for seg in segments:
        try:
            score, label = _predict(analyzer, seg)
            scores.append(score)
            labels.append(label)
        except Exception:
            continue

    if not scores:
        return {}

    avg_score = round(sum(scores) / len(scores), 3)

    # timeline: sentimiento por cada 60s del video
    timeline = _sentiment_timeline(words, analyzer, window=60)

    total = len(labels)
    return {
        "overall_score": avg_score,
        "label":         _score_to_label(avg_score),
        "segments_analyzed": total,
        "positive_ratio": round(labels.count("positive") / total, 3),
        "negative_ratio": round(labels.count("negative") / total, 3),
        "neutral_ratio":  round(labels.count("neutral")  / total, 3),
        "timeline":       timeline,
    }


def _split_text(text: str, max_chars: int = 200) -> list[str]:
    """Divide texto en segmentos respetando palabras completas."""
    words   = text.split()
    chunks  = []
    current = []
    length  = 0

    for word in words:
        if length + len(word) + 1 > max_chars and current:
            chunks.append(" ".join(current))
            current = [word]
            length  = len(word)
        else:
            current.append(word)
            length += len(word) + 1

    if current:
        chunks.append(" ".join(current))

    return chunks


def _sentiment_timeline(words: list[dict], analyzer, window: int = 60) -> list[dict]:
    """Sentimiento por ventana de tiempo."""
    if not words:
        return []

    timeline = []
    start    = words[0]["start"]
    end      = words[-1]["end"]
    t        = start

    while t + window <= end:
        bucket_words = [w["word"] for w in words if t <= w["start"] < t + window]
        text = " ".join(bucket_words)
        if text.strip():
            try:
                score, label = _predict(analyzer, text)
                timeline.append({"second": round(t), "score": score, "label": label})
            except Exception:
                pass
        t += window

    return timeline


def _score_to_label(score: float) -> str:
    if score > 0.2:
        return "positive"
    elif score < -0.2:
        return "negative"
    return "neutral"
