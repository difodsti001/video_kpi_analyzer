from transformers import pipeline

_sentiment_pipeline = None

def get_pipeline():
    global _sentiment_pipeline
    if _sentiment_pipeline is None:
        _sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model="nlptown/bert-base-multilingual-uncased-sentiment"
        )
    return _sentiment_pipeline

def analyze_sentiment(transcript: str, words: list[dict]) -> dict:
    """
    Analiza sentimiento del transcript por segmentos.
    Devuelve score general y evolución a lo largo del video.
    """
    if not transcript or not words:
        return {}

    nlp = get_pipeline()
    total_duration = words[-1]["end"] - words[0]["start"]

    # dividir transcript en segmentos de ~200 caracteres
    # (límite del modelo)
    segments = _split_text(transcript, max_chars=200)

    scores = []
    for seg in segments:
        try:
            result = nlp(seg[:512])[0]
            # modelo devuelve 1-5 estrellas → convertir a -1.0/1.0
            stars = int(result["label"][0])
            score = round((stars - 3) / 2, 3)   # 1★=-1.0, 3★=0.0, 5★=1.0
            scores.append(score)
        except Exception:
            continue

    if not scores:
        return {}

    avg_score = round(sum(scores) / len(scores), 3)

    # timeline: sentimiento por cada 60s del video
    timeline = _sentiment_timeline(words, nlp, window=60)

    return {
        "overall_score": avg_score,
        "label":         _score_to_label(avg_score),
        "segments_analyzed": len(scores),
        "positive_ratio": round(sum(1 for s in scores if s > 0.2) / len(scores), 3),
        "negative_ratio": round(sum(1 for s in scores if s < -0.2) / len(scores), 3),
        "neutral_ratio":  round(sum(1 for s in scores if -0.2 <= s <= 0.2) / len(scores), 3),
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


def _sentiment_timeline(words: list[dict], nlp, window: int = 60) -> list[dict]:
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
                result = nlp(text[:512])[0]
                stars  = int(result["label"][0])
                score  = round((stars - 3) / 2, 3)
                timeline.append({"second": round(t), "score": score,
                                  "label": _score_to_label(score)})
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