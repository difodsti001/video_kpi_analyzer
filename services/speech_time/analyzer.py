def analyze_speech_time(words: list[dict], total_duration: float) -> dict:
    """
    Recibe la lista de words con timestamps y la duración total.
    Devuelve métricas de tiempo de habla.
    """
    if not words or total_duration == 0:
        return {}

    # tiempo hablado = suma de duración de cada palabra
    speech_seconds = sum(w["end"] - w["start"] for w in words)

    # silencios = gaps entre palabras mayores a 0.5s
    silences = []
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap > 0.5:
            silences.append(round(gap, 3))

    silence_seconds = total_duration - speech_seconds

    return {
        "speech_seconds":   round(speech_seconds, 2),
        "silence_seconds":  round(max(silence_seconds, 0), 2),
        "speech_ratio":     round(speech_seconds / total_duration, 4),
        "silence_count":    len(silences),
        "longest_silence":  round(max(silences, default=0), 2),
        "avg_silence":      round(sum(silences) / len(silences), 2) if silences else 0,
    }