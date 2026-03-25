import os
import subprocess
from dotenv import load_dotenv
load_dotenv()

FFMPEG_PATH   = os.getenv("FFMPEG_PATH", "ffmpeg")
CHUNK_SECONDS = int(os.getenv("CHUNK_SECONDS", 600))

from services.transcription.analyzer import transcribe_audio, parse_words, get_duration
from services.speech_time.analyzer   import analyze_speech_time
from services.rhythm.analyzer        import analyze_rhythm
from services.rhythm.audio_analyzer  import analyze_audio
from services.sentiment.analyzer     import analyze_sentiment
from services.clarity.analyzer       import analyze_clarity
from services.feedback.analyzer      import analyze_feedback


class VideoAnalyzer:

    def __init__(self, video_path: str):
        self.video_path = video_path
        self.wav_path   = None
        self.chunks     = []

        # resultados intermedios
        self.all_words  = []
        self.transcript = ""
        self.duration   = 0.0

        # KPIs
        self.speech   = {}
        self.rhythm   = {}
        self.sentiment = {}
        self.clarity  = {}
        self.audio    = {}
        self.feedback = {}

    # ── audio ────────────────────────────────────────────────────

    def extract_audio(self) -> str:
        output_wav = "temp_audio.wav"
        subprocess.run([
            FFMPEG_PATH, "-y", "-i", self.video_path,
            "-ac", "1", "-ar", "16000", "-vn", output_wav
        ], 
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, check=True)
        self.wav_path = output_wav
        self.duration = get_duration(self.wav_path)
        return self.wav_path

    def split_audio(self) -> list[str]:
        output_pattern = "chunk_%03d.wav"
        subprocess.run([
            FFMPEG_PATH, "-i", self.wav_path,
            "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
            "-c", "copy", output_pattern
        ], check=True)
        self.chunks = sorted([f for f in os.listdir() if f.startswith("chunk_")])
        return self.chunks

    def transcribe(self) -> tuple[list, str]:
        all_words      = []
        all_text_parts = []
        for i, chunk in enumerate(self.chunks):
            offset = i * CHUNK_SECONDS
            result = transcribe_audio(chunk, model_size=os.getenv("WHISPER_MODEL", "base"))
            words  = parse_words(result["segments"])
            for w in words:
                w["start"] += offset
                w["end"]   += offset
            all_words.extend(words)
            all_text_parts.append(result["text"].strip())
        self.all_words  = all_words
        self.transcript = " ".join(all_text_parts)
        return self.all_words, self.transcript

    # ── KPIs ─────────────────────────────────────────────────────

    def run_speech_time(self) -> dict:
        self.speech = analyze_speech_time(self.all_words, self.duration)
        return self.speech

    def run_rhythm(self) -> dict:
        self.rhythm = analyze_rhythm(self.all_words)
        return self.rhythm

    def run_sentiment(self) -> dict:
        self.sentiment = analyze_sentiment(self.transcript, self.all_words)
        return self.sentiment

    def run_clarity(self) -> dict:
        self.clarity = analyze_clarity(self.all_words, self.transcript)
        return self.clarity

    def run_audio(self) -> dict:
        self.audio = analyze_audio(self.wav_path)
        return self.audio

    def run_feedback(self) -> dict:
        self.feedback = analyze_feedback(
            self.speech, self.rhythm, self.sentiment,
            self.clarity, self.audio
        )
        return self.feedback

    # ── limpieza ─────────────────────────────────────────────────

    def cleanup(self):
        if self.wav_path and os.path.exists(self.wav_path):
            os.remove(self.wav_path)
        for c in self.chunks:
            if os.path.exists(c):
                os.remove(c)

    # ── pipeline completo ─────────────────────────────────────────

    def run(self) -> dict:
        try:
            self.extract_audio()
            self.split_audio()
            self.transcribe()
            self.run_speech_time()
            self.run_rhythm()
            self.run_sentiment()
            self.run_clarity()
            self.run_audio()
            self.run_feedback()
        finally:
            self.cleanup()

        return self.result()

    def result(self) -> dict:
        return {
            "duration_seconds": self.duration,
            "total_words":      len(self.all_words),
            "transcript":       self.transcript,
            "kpis": {
                "speech_time": self.speech,
                "rhythm":      self.rhythm,
                "sentiment":   self.sentiment,
                "clarity":     self.clarity,
                "audio":       self.audio,
            },
            "feedback": self.feedback,
        }