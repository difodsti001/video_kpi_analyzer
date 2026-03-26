import os
import uuid
import shutil
import logging
import warnings

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from fastapi import Depends
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

from shared.database import engine, get_db, Base
from shared.models   import AnalysisJob
from core           import VideoAnalyzer

Base.metadata.create_all(bind=engine)

VIDEO_FOLDER = os.getenv("VIDEO_FOLDER", "./video")
os.makedirs(VIDEO_FOLDER, exist_ok=True)

app = FastAPI(title="Video KPI Analyzer", version="1.0.0")

# ── CORS (por si se consume desde otro origen) ────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── background task ───────────────────────────────────────────────

def _create_job(filename: str, video_path: str, db):
    job = AnalysisJob(
        id=str(uuid.uuid4()),
        filename=filename,
        video_path=video_path,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _run_analysis(job_id: str, video_path: str):
    from shared.database import SessionLocal
    db = SessionLocal()
    try:
        job = db.query(AnalysisJob).filter_by(id=job_id).first()
        job.status = "running"
        db.commit()

        analyzer = VideoAnalyzer(video_path)
        result   = analyzer.run()

        job.status = "done"
        job.result = result
    except Exception as e:
        job.status = "failed"
        job.error  = str(e)
    finally:
        db.commit()
        db.close()


# ── Ruta raíz ─────────────────────────
@app.get("/")
def serve_index():
    return FileResponse("index.html")

# ── endpoints ─────────────────────────────────────────────────────

@app.post("/analyze/from-file")
def analyze_from_file(
    filename: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """v1 — video ya está en la carpeta video/"""
    path = os.path.join(VIDEO_FOLDER, filename)
    if not os.path.exists(path):
        raise HTTPException(404, f"Video no encontrado: {filename}")

    job = _create_job(filename, path, db)
    logger.info(f"[{job.id}] Job creado (from-file)")
    background_tasks.add_task(_run_analysis, job.id, path)
    return {"job_id": job.id, "status": "pending"}


@app.post("/analyze/upload")
def analyze_from_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """v2 — sube el video por la API"""
    dest = os.path.join(VIDEO_FOLDER, file.filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job = _create_job(file.filename, dest, db)
    logger.info(f"[{job.id}] Job creado (upload: {file.filename})")
    background_tasks.add_task(_run_analysis, job.id, dest)
    return {"job_id": job.id, "status": "pending"}


@app.get("/analyze/{job_id}/status")
def get_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(AnalysisJob).filter_by(id=job_id).first()

    if not job:
        raise HTTPException(404, "Job no encontrado")

    return {
        "job_id": job.id,
        "status": job.status,
    }


@app.get("/analyze/{job_id}")
def get_result_raw(job_id: str, db: Session = Depends(get_db)):
    job = db.query(AnalysisJob).filter_by(id=job_id).first()

    if not job:
        raise HTTPException(404, "Job no encontrado")

    return {
        "job_id":   job.id,
        "filename": job.filename,
        "status":   job.status,
        "result":   job.result,
        "error":    job.error,
    }


@app.get("/analyze")
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.query(AnalysisJob).all()

    return [
        {
            "job_id": j.id,
            "filename": j.filename,
            "status": j.status,
        }
        for j in jobs
    ]

@app.get("/videos")
def list_videos():
    """Lista los videos disponibles en la carpeta."""
    exts  = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    files = [f for f in os.listdir(VIDEO_FOLDER)
             if os.path.splitext(f)[1].lower() in exts]
    return {"videos": files}


@app.get("/analyze/{job_id}/result")
def get_result_clean(job_id: str, db: Session = Depends(get_db)):
    job = db.query(AnalysisJob).filter_by(id=job_id).first()

    if not job:
        raise HTTPException(404, "Job no encontrado")

    if job.status != "done":
        return {
            "job_id": job.id,
            "status": job.status,
            "message": "El análisis aún no ha terminado"
        }

    result = job.result or {}

    feedback = result.get("feedback", {})
    interpretaciones = feedback.get("interpretaciones", {})

    def get_nivel(kpi):
        return interpretaciones.get(kpi, {}).get("nivel", "desconocido")

    return {
        "job_id": job.id,
        "status": job.status,

        "summary": {
            "score_global": feedback.get("score_global", 0),
            "duracion_min": round(result.get("duration_seconds", 0) / 60, 2),
            "palabras": result.get("total_words", 0),
        },

        "feedback": feedback.get("narrativa", "No se pudo generar feedback"),

        "kpis": {
            "speech_time": get_nivel("speech_time"),
            "rhythm":      get_nivel("rhythm"),
            "sentiment":   get_nivel("sentiment"),
            "clarity":     get_nivel("clarity"),
            "audio":       get_nivel("audio"),
        },

        "details": result.get("kpis", {}),
    }


# ── helper ────────────────────────────────────────────────────────

def _create_job(filename: str, video_path: str, db):
    from shared.models import AnalysisJob
    job = AnalysisJob(
        id=str(uuid.uuid4()),
        filename=filename,
        video_path=video_path,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job