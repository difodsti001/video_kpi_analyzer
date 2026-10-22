import os
import subprocess
from dotenv import load_dotenv
load_dotenv()

FFMPEG_PATH   = os.getenv("FFMPEG_PATH", "ffmpeg")
CHUNK_SECONDS = 600
VIDEO_FILE    = "video/test.mp4"

from services.transcription.analyzer import transcribe_audio, parse_words, get_duration
from services.speech_time.analyzer   import analyze_speech_time
from services.rhythm.analyzer import analyze_rhythm
from services.sentiment.analyzer import analyze_sentiment
from services.clarity.analyzer import analyze_clarity
from services.rhythm.audio_analyzer import analyze_audio
from services.feedback.analyzer import analyze_feedback

def extract_audio(input_video):
    output_wav = "temp_audio.wav"
    subprocess.run([
        FFMPEG_PATH, "-y", "-i", input_video,
        "-ac", "1", "-ar", "16000", "-vn", output_wav
    ], check=True)
    return output_wav


def split_audio(input_wav, chunk_seconds):
    output_pattern = "chunk_%03d.wav"
    subprocess.run([
        FFMPEG_PATH, "-i", input_wav,
        "-f", "segment", "-segment_time", str(chunk_seconds),
        "-c", "copy", output_pattern
    ], check=True)
    return sorted([f for f in os.listdir() if f.startswith("chunk_")])


def transcribe_with_offset(chunk_file, offset):
    result = transcribe_audio(chunk_file, model_size="base")
    words  = parse_words(result["segments"])
    for w in words:
        w["start"] += offset
        w["end"]   += offset
    return words, result["text"]


def main():
    print("\n[1] Extrayendo audio...")
    wav      = extract_audio(VIDEO_FILE)
    duration = get_duration(wav)
    print(f"    Duración: {duration:.1f}s")

    print("[2] Fragmentando audio...")
    chunks = split_audio(wav, CHUNK_SECONDS)
    print(f"    Total chunks: {len(chunks)}")

    print("[3] Transcribiendo chunks...")
    all_words      = []
    all_text_parts = []

    for i, chunk in enumerate(chunks):
        offset = i * CHUNK_SECONDS
        print(f"    Procesando {chunk} (offset {offset}s)...")
        words, text = transcribe_with_offset(chunk, offset)
        all_words.extend(words)
        all_text_parts.append(text.strip())

    transcript = " ".join(all_text_parts)

    print(f"\n[4] Total palabras: {len(all_words)}")
    print(f"    Primeras 5:")
    for w in all_words[:5]:
        print(f"      {w}")

    # ── KPI 1: Speech Time ──────────────────────────────────────
    print("\n[5] Speech Time...")
    speech = analyze_speech_time(all_words, duration)
    for k, v in speech.items():
        print(f"    {k}: {v}")

    # ── KPI 2: Rhythm  ───────────────────────────────────────────
    print("\n[6] Rhythm...")
    rhythm = analyze_rhythm(all_words)
    print(f"    avg_wpm:          {rhythm['avg_wpm']}")
    print(f"    wpm_score:        {rhythm['wpm_score']}")
    print(f"    strategic_pauses: {rhythm['strategic_pauses']}")
    print(f"    wpm_timeline:     {rhythm['wpm_timeline'][:3]}...")

    # ── KPI 3: Sentiment ─────────────────────────────────────────
    print("\n[7] Sentiment...")
    sentiment = analyze_sentiment(transcript, all_words)
    print(f"    overall_score:    {sentiment['overall_score']}")
    print(f"    label:            {sentiment['label']}")
    print(f"    positive_ratio:   {sentiment['positive_ratio']}")
    print(f"    negative_ratio:   {sentiment['negative_ratio']}")
    print(f"    neutral_ratio:    {sentiment['neutral_ratio']}")
    print(f"    timeline:         {sentiment['timeline'][:3]}...")

    # ── KPI 4: Clarity ───────────────────────────────────────────
    print("\n[8] Clarity...")
    clarity = analyze_clarity(all_words, transcript)
    print(f"    clarity_score:      {clarity['clarity_score']}")
    print(f"    filler_count:       {clarity['filler_count']}")
    print(f"    vocab_diversity:    {clarity['vocab_diversity']}")
    s = clarity.get('structure', {})
    print(f"    structure_score:    {s.get('structure_score')}")
    print(f"    has_intro:          {s.get('has_intro')}")
    print(f"    has_cierre:         {s.get('has_cierre')}")
    print(f"    preguntas_retoricas:{s.get('preguntas_retoricas')}")
    print(f"    preguntas_por_min:  {s.get('preguntas_por_min')}")
    print(f"    conectores:         {list(s.get('conectores', {}).keys())}")
    print(f"    palabras_repetidas: {s.get('palabras_repetidas', [])[:5]}")
    print(f"    ej. preguntas:      {s.get('ejemplos_preguntas', [])}")

    # ── KPI audio: necesita el WAV ───────────────────────────────
    print("\n[9] Audio (pitch + energía)...")
    audio = analyze_audio(wav)
    print(f"    pitch_mean_hz:      {audio['pitch_mean_hz']}")
    print(f"    pitch_variation:    {audio['pitch_variation']}")
    print(f"    expresividad_score: {audio['expresividad_score']}")
    print(f"    energy_mean:        {audio['energy_mean']}")
    print(f"    energy_variation:   {audio['energy_variation']}")
    print(f"    proyeccion_score:   {audio['proyeccion_score']}")
    print(f"    timeline:           {audio['timeline'][:3]}...")

    # ── limpieza al final ────────────────────────────────────────
    print("\n[10] Limpiando temporales...")
    os.remove(wav)
    for c in chunks:
        if os.path.exists(c):
            os.remove(c)

    print("\n[11] Feedback...")
    feedback = analyze_feedback(speech, rhythm, sentiment, clarity, audio)
    print(f"    score_global: {feedback['score_global']}/10")
    print(f"\n--- NARRATIVA ---")
    print(feedback["narrativa"])

    print("\n OK TODO FUNCIONANDO")


if __name__ == "__main__":
    main()