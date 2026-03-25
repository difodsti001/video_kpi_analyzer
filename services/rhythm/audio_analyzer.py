# services/rhythm/audio_analyzer.py
import librosa
import numpy as np


def analyze_audio(wav_path: str) -> dict:
    """
    Analiza características prosódicas del audio:
    pitch (F0), energía vocal (RMS) y variación.
    """
    y, sr = librosa.load(wav_path, sr=16000)

    # ── Pitch (F0) ───────────────────────────────────────────────
    f0, voiced_flag, _ = librosa.pyin(
        y, sr=sr,
        fmin=librosa.note_to_hz("C2"),   # ~65 Hz
        fmax=librosa.note_to_hz("C7"),   # ~2093 Hz
    )
    f0_voiced = f0[voiced_flag & ~np.isnan(f0)]

    pitch_mean    = round(float(np.mean(f0_voiced)), 2)   if len(f0_voiced) else 0
    pitch_std     = round(float(np.std(f0_voiced)), 2)    if len(f0_voiced) else 0
    pitch_range   = round(float(np.ptp(f0_voiced)), 2)    if len(f0_voiced) else 0

    # variación normalizada: std/mean — indica expresividad vocal
    pitch_variation = round(pitch_std / pitch_mean, 4) if pitch_mean else 0

    # ── Energía vocal (RMS) ──────────────────────────────────────
    rms        = librosa.feature.rms(y=y)[0]
    rms_mean   = round(float(np.mean(rms)), 5)
    rms_std    = round(float(np.std(rms)), 5)
    rms_max    = round(float(np.max(rms)), 5)

    # variación de energía: indica dinamismo, evita tono plano
    energy_variation = round(rms_std / rms_mean, 4) if rms_mean else 0

    # ── Timeline de pitch y energía por 60s ─────────────────────
    duration     = librosa.get_duration(y=y, sr=sr)
    hop_length   = 512
    frame_time   = hop_length / sr       # segundos por frame
    window_frames = int(60 / frame_time) # frames en 60s

    rms_full  = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    timeline  = []
    for i in range(0, len(rms_full) - window_frames, window_frames):
        segment_rms   = rms_full[i:i + window_frames]
        second        = round(i * frame_time)
        timeline.append({
            "second":         second,
            "energy_mean":    round(float(np.mean(segment_rms)), 5),
            "energy_variation": round(float(np.std(segment_rms) / np.mean(segment_rms)), 4)
                              if np.mean(segment_rms) > 0 else 0,
        })

    # ── Scores ───────────────────────────────────────────────────
    # expresividad vocal: pitch_variation > 0.15 es bueno
    expresividad_score = round(min(pitch_variation / 0.20, 1.0), 3)

    # proyección: rms_mean > 0.05 es audible y seguro
    proyeccion_score = round(min(rms_mean / 0.05, 1.0), 3)

    return {
        "pitch_mean_hz":      pitch_mean,
        "pitch_std_hz":       pitch_std,
        "pitch_range_hz":     pitch_range,
        "pitch_variation":    pitch_variation,
        "expresividad_score": expresividad_score,
        "energy_mean":        rms_mean,
        "energy_std":         rms_std,
        "energy_max":         rms_max,
        "energy_variation":   energy_variation,
        "proyeccion_score":   proyeccion_score,
        "duration_seconds":   round(duration, 2),
        "timeline":           timeline,
    }