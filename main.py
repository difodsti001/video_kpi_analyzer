import os
import hashlib
import uuid as uuid_lib
import shutil
import logging
import warnings

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

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
def _create_job(filename: str, video_path: str, db,
                nombre_analisis: str = None,
                presentador: str = None,
                tipo: str = None,
                dependencia: str = None,
                analista_id: str = None,
                file_hash: str = None):
    job = AnalysisJob(
        id=str(uuid_lib.uuid4()),
        filename=filename,
        video_path=video_path,
        status="pending",
        nombre_analisis=nombre_analisis or filename,
        presentador=presentador or None,
        tipo=tipo or None,
        dependencia=dependencia or None,
        analista_id=analista_id or None,
        file_hash=file_hash,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _run_analysis(job_id: str, video_path: str):
    from shared.database import SessionLocal
    db = SessionLocal()

    try:
        print("=== RUN ANALYSIS ===")
        print("VIDEO PATH:", video_path)

        job = db.query(AnalysisJob).filter_by(id=job_id).first()
        job.status = "running"
        db.commit()

        analyzer = VideoAnalyzer(video_path)

        print("ANTES DE RUN()")
        result = analyzer.run()
        print("DESPUÉS DE RUN()")

        job.status = "done"
        job.result = result

    except Exception as e:
        print("ERROR REAL:", str(e))
        job.status = "failed"
        job.error  = str(e)

    finally:
        db.commit()
        db.close()

def compute_file_hash(file_path: str) -> str:
    """UUID5 basado en hash SHA256 del contenido del archivo."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    # UUID5 con namespace DNS y el hex del sha256
    return str(uuid_lib.uuid5(uuid_lib.NAMESPACE_DNS, sha.hexdigest()))

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
    nombre_analisis: str = Form(""),
    presentador:     str = Form(""),
    tipo:            str = Form(""),
    dependencia:     str = Form(""),
    analista_id:     str = Form(""),
    db: Session = Depends(get_db),
):
    dest = os.path.join(VIDEO_FOLDER, file.filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_hash = compute_file_hash(dest)

    # duplicado: mismo video Y mismo usuario
    existing = db.query(AnalysisJob).filter(
        AnalysisJob.file_hash   == file_hash,
        AnalysisJob.analista_id == (analista_id or None),
        AnalysisJob.status      == "done"
    ).first()

    if existing:
        logger.info(f"Duplicado detectado: job={existing.id} analista={analista_id}")
        return {
            "duplicate":       True,
            "job_id":          existing.id,
            "status":          existing.status,
            "filename":        existing.filename,
            "nombre_analisis": existing.nombre_analisis or existing.filename,
            "message":         "Este video ya fue analizado anteriormente."
        }

    job = _create_job(
        filename        = file.filename,
        video_path      = dest,
        db              = db,
        nombre_analisis = nombre_analisis or file.filename,
        presentador     = presentador or None,
        tipo            = tipo or None,
        dependencia     = dependencia or None,
        analista_id     = analista_id or None,
        file_hash       = file_hash,
    )
    logger.info(f"[{job.id}] Job creado — nombre='{nombre_analisis}' presentador='{presentador}' analista='{analista_id}' hash={file_hash[:12]}...")
    background_tasks.add_task(_run_analysis, job.id, dest)
    return {
        "duplicate": False,
        "job_id":    job.id,
        "status":    "pending"
    }

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
def list_jobs(analista_id: str = "", db: Session = Depends(get_db)):
    """Lista jobs filtrados por analista. Sin filtro devuelve todos (para admin)."""
    query = db.query(AnalysisJob)
    if analista_id:
        query = query.filter(AnalysisJob.analista_id == analista_id)
    jobs = query.order_by(AnalysisJob.created_at.desc()).all()
    return [
        {
            "job_id":          j.id,
            "filename":        j.filename,
            "nombre_analisis": j.nombre_analisis or j.filename,
            "presentador":     j.presentador or "—",
            "tipo":            j.tipo or "—",
            "dependencia":     j.dependencia or "—",
            "analista_id":     j.analista_id,
            "status":          j.status,
            "created_at":      j.created_at.isoformat() if j.created_at else None,
            "score":           j.result.get("evaluacion", {}).get("score_final") if j.result else None,
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

    evaluacion = result.get("evaluacion", {})
    interpretaciones = evaluacion.get("interpretaciones_oratoria", {})

    def get_nivel(kpi):
        return interpretaciones.get(kpi, {}).get("nivel", "desconocido")

    return {
        "job_id": job.id,
        "status": job.status,

        "summary": {
            "score_final":    evaluacion.get("score_final", 0),
            "score_rubrica":  evaluacion.get("score_rubrica"),
            "score_oratoria": evaluacion.get("score_oratoria"),
            "duracion_min":   round(result.get("duration_seconds", 0) / 60, 2),
            "palabras":       result.get("total_words", 0),
        },

        "video_info": result.get("video_info", {}),

        "resumen_ejecutivo": evaluacion.get("resumen_ejecutivo", "No se pudo generar la evaluación"),

        "criterios_rubrica": evaluacion.get("criterios", {}),

        "kpis": {
            "speech_time": get_nivel("speech_time"),
            "rhythm":      get_nivel("rhythm"),
            "sentiment":   get_nivel("sentiment"),
            "clarity":     get_nivel("clarity"),
            "audio":       get_nivel("audio"),
        },

        "details": result.get("kpis", {}),
    }
