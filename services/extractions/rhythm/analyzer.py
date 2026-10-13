# services/rhythm/analyzer.py

def analyze_rhythm(words: list[dict]) -> dict:
    """
    Recibe words con timestamps.
    Devuelve métricas de ritmo y velocidad de habla.
    """
    if not words:
        return {}

    total_words    = len(words)
    total_duration = words[-1]["end"] - words[0]["start"]

    if total_duration == 0:
        return {}

    avg_wpm = round((total_words / total_duration) * 60, 2)

    # WPM por ventana de 60 segundos deslizante
    timeline = []
    window   = 60
    start    = words[0]["start"]
    end      = words[-1]["end"]
    t        = start

    while t + window <= end:
        bucket = [w for w in words if t <= w["start"] < t + window]
        timeline.append({
            "second": round(t),
            "wpm":    round(len(bucket) / window * 60, 1),
        })
        t += window

    # pausas estratégicas = silencios > 1.5s entre palabras
    strategic_pauses = []
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap > 1.5:
            strategic_pauses.append({
                "at_second": round(words[i - 1]["end"], 1),
                "duration":  round(gap, 2),
            })

    # score WPM: óptimo entre 120-160 WPM para español
    if 120 <= avg_wpm <= 160:
        wpm_score = 1.0
    elif avg_wpm < 120:
        wpm_score = round(avg_wpm / 120, 3)
    else:
        wpm_score = round(max(0, 1 - (avg_wpm - 160) / 100), 3)

    return {
        "avg_wpm":          avg_wpm,
        "wpm_score":        wpm_score,
        "total_words":      total_words,
        "strategic_pauses": len(strategic_pauses),
        "pauses_detail":    strategic_pauses[:5],
        "wpm_timeline":     timeline,
    }