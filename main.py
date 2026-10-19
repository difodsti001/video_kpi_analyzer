import os
import asyncio
import hashlib
import uuid as uuid_lib
import shutil
import logging
import warnings

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, HTTPException, Depends, Header
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
from shared.models   import Extraction, Evaluation
from services.transversal.cursos.registro import CURSO_POR_DEFECTO
import jobs

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

# Clave compartida para los endpoints de análisis. Falla cerrado: sin
# API_KEY configurada, se rechazan todas las peticiones.
API_KEY = os.getenv("API_KEY", "")

def require_api_key(x_api_key: str = Header(default="")):
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(401, "API key inválida o faltante (header X-API-Key)")

@app.on_event("startup")
async def _start_background_jobs():
    asyncio.create_task(jobs.cleanup_stale_jobs_loop())


# ── extracción (pesada) ─────────────────────────────────────────────

def _create_extraction(filename: str, video_path: str, db,
                       nombre_analisis: str = None,
                       presentador: str = None,
                       tipo: str = None,
                       dependencia: str = None,
                       analista_id: str = None,
                       file_hash: str = None):
    extraccion = Extraction(
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
    db.add(extraccion)
    db.commit()
    db.refresh(extraccion)
    return extraccion


def compute_file_hash(file_path: str) -> str:
    """UUID5 basado en hash SHA256 del contenido del archivo."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    # UUID5 con namespace DNS y el hex del sha256
    return str(uuid_lib.uuid5(uuid_lib.NAMESPACE_DNS, sha.hexdigest()))


def _ultima_evaluacion(db: Session, extraction_id: str):
    return (
        db.query(Evaluation)
        .filter_by(extraction_id=extraction_id)
        .order_by(Evaluation.created_at.desc())
        .first()
    )


def _estado_combinado(extraccion, evaluacion) -> str:
    """Estado visible: extracción primero, luego espera a que la evaluación
    encadenada también termine (evita un hueco donde el frontend vería un
    informe vacío). Si la evaluación falla, igual se reporta 'done'."""
    if extraccion.status != "done":
        return extraccion.status
    if evaluacion is None or evaluacion.status in ("pending", "running"):
        return "running"
    return "done"


def _resultado_combinado(extraccion, evaluacion) -> dict:
    """Reconstruye la forma de resultado que ya conocía el frontend (todo en
    un solo dict), aunque por debajo ahora vivan en dos tablas separadas."""
    resultado = dict(extraccion.result or {})
    datos_evaluacion = (evaluacion.result or {}) if evaluacion else {}
    resultado["evaluacion"]        = datos_evaluacion.get("evaluacion", {})
    resultado["competencias_mbdd"] = datos_evaluacion.get("competencias_mbdd", {})
    resultado["curso_id"]          = datos_evaluacion.get("curso_id")
    return resultado


# ── Ruta raíz ─────────────────────────
@app.get("/")
def serve_index():
    return FileResponse("index.html")

# ── endpoints ─────────────────────────────────────────────────────

@app.post("/analyze/from-file", dependencies=[Depends(require_api_key)])
def analyze_from_file(
    filename: str,
    background_tasks: BackgroundTasks,
    curso_id: str = CURSO_POR_DEFECTO,
    db: Session = Depends(get_db),
):
    """v1 — video ya está en la carpeta video/"""
    path = os.path.join(VIDEO_FOLDER, filename)
    if not os.path.exists(path):
        raise HTTPException(404, f"Video no encontrado: {filename}")

    extraccion = _create_extraction(filename, path, db)
    logger.info(f"[{extraccion.id}] Extracción creada (from-file)")
    background_tasks.add_task(jobs.run_extraction_queued, extraccion.id, path, curso_id)
    return {"job_id": extraccion.id, "status": "pending"}


@app.post("/analyze/upload", dependencies=[Depends(require_api_key)])
def analyze_from_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    nombre_analisis: str = Form(""),
    presentador:     str = Form(""),
    tipo:            str = Form(""),
    dependencia:     str = Form(""),
    analista_id:     str = Form(""),
    curso_id:        str = Form(CURSO_POR_DEFECTO),
    db: Session = Depends(get_db),
):
    # Prefijo único: dos docentes pueden subir archivos con el mismo nombre
    # (ej. "VIDEO.mp4"); sin esto, el segundo pisa al primero en disco.
    nombre_unico = f"{uuid_lib.uuid4().hex[:12]}_{file.filename}"
    dest = os.path.join(VIDEO_FOLDER, nombre_unico)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_hash = compute_file_hash(dest)

    # duplicado: mismo video Y mismo usuario
    existing = db.query(Extraction).filter(
        Extraction.file_hash   == file_hash,
        Extraction.analista_id == (analista_id or None),
        Extraction.status      == "done"
    ).first()

    if existing:
        logger.info(f"Duplicado detectado: extraccion={existing.id} analista={analista_id}")
        return {
            "duplicate":       True,
            "job_id":          existing.id,
            "status":          existing.status,
            "filename":        existing.filename,
            "nombre_analisis": existing.nombre_analisis or existing.filename,
            "message":         "Este video ya fue analizado anteriormente."
        }

    extraccion = _create_extraction(
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
    logger.info(f"[{extraccion.id}] Extracción creada — nombre='{nombre_analisis}' presentador='{presentador}' analista='{analista_id}' curso='{curso_id}' hash={file_hash[:12]}...")
    background_tasks.add_task(jobs.run_extraction_queued, extraccion.id, dest, curso_id)
    return {
        "duplicate": False,
        "job_id":    extraccion.id,
        "status":    "pending"
    }


@app.post("/extracciones/{extraction_id}/evaluaciones", dependencies=[Depends(require_api_key)])
def crear_evaluacion(
    extraction_id: str,
    background_tasks: BackgroundTasks,
    curso_id: str = Form(CURSO_POR_DEFECTO),
    db: Session = Depends(get_db),
):
    """Evalúa una extracción YA HECHA contra un curso — sin repetir Whisper/
    YOLO/MediaPipe. Sirve tanto para re-evaluar con otro curso como para
    reintentar si la evaluación automática falló."""
    extraccion = db.query(Extraction).filter_by(id=extraction_id).first()
    if not extraccion:
        raise HTTPException(404, "Extracción no encontrada")
    if extraccion.status != "done":
        raise HTTPException(409, f"La extracción todavía no terminó (status={extraccion.status})")

    evaluacion = Evaluation(
        id=str(uuid_lib.uuid4()),
        extraction_id=extraction_id,
        curso_id=curso_id or CURSO_POR_DEFECTO,
        status="pending",
    )
    db.add(evaluacion)
    db.commit()
    db.refresh(evaluacion)

    background_tasks.add_task(jobs.run_evaluation_queued, evaluacion.id, extraccion.result, evaluacion.curso_id)
    return {"evaluation_id": evaluacion.id, "extraction_id": extraction_id, "curso_id": evaluacion.curso_id, "status": "pending"}


@app.get("/extracciones/{extraction_id}")
def get_extraction(extraction_id: str, db: Session = Depends(get_db)):
    extraccion = db.query(Extraction).filter_by(id=extraction_id).first()
    if not extraccion:
        raise HTTPException(404, "Extracción no encontrada")
    return {
        "id":     extraccion.id,
        "status": extraccion.status,
        "error":  extraccion.error,
        "result": extraccion.result,
    }


@app.get("/evaluaciones/{evaluation_id}")
def get_evaluation(evaluation_id: str, db: Session = Depends(get_db)):
    evaluacion = db.query(Evaluation).filter_by(id=evaluation_id).first()
    if not evaluacion:
        raise HTTPException(404, "Evaluación no encontrada")
    return {
        "id":             evaluacion.id,
        "extraction_id":  evaluacion.extraction_id,
        "curso_id":       evaluacion.curso_id,
        "status":         evaluacion.status,
        "error":          evaluacion.error,
        "result":         evaluacion.result,
    }


@app.get("/analyze/{job_id}/status")
def get_status(job_id: str, db: Session = Depends(get_db)):
    extraccion = db.query(Extraction).filter_by(id=job_id).first()

    if not extraccion:
        raise HTTPException(404, "Job no encontrado")

    evaluacion = _ultima_evaluacion(db, job_id)
    return {
        "job_id": extraccion.id,
        "status": _estado_combinado(extraccion, evaluacion),
    }


def _ocultar_calificacion(resultado: dict | None) -> dict | None:
    """Oculta puntajes de la respuesta pública, conservando solo el nivel de
    cada criterio como retroalimentación cualitativa."""
    if not resultado:
        return resultado
    evaluacion = resultado.get("evaluacion")
    if isinstance(evaluacion, dict):
        criterios_visibles = {}
        for criterio_id, criterio in evaluacion.get("criterios", {}).items():
            if isinstance(criterio, dict):
                criterios_visibles[criterio_id] = {
                    "nombre": criterio.get("nombre", criterio_id),
                    "nivel": criterio.get("nivel", "no evaluado"),
                }
        evaluacion = {k: v for k, v in evaluacion.items()
                      if k not in ("score_final", "score_rubrica", "score_oratoria", "criterios")}
        evaluacion["criterios"] = criterios_visibles
        resultado = {**resultado, "evaluacion": evaluacion}
    return resultado


@app.get("/analyze/{job_id}")
def get_result_raw(job_id: str, db: Session = Depends(get_db)):
    extraccion = db.query(Extraction).filter_by(id=job_id).first()

    if not extraccion:
        raise HTTPException(404, "Job no encontrado")

    evaluacion = _ultima_evaluacion(db, job_id)
    resultado  = _resultado_combinado(extraccion, evaluacion) if extraccion.status == "done" else None

    return {
        "job_id":   extraccion.id,
        "filename": extraccion.filename,
        "status":   _estado_combinado(extraccion, evaluacion),
        "result":   _ocultar_calificacion(resultado),
        "error":    extraccion.error or (evaluacion.error if evaluacion else None),
    }


@app.get("/analyze")
def list_jobs(analista_id: str = "", db: Session = Depends(get_db)):
    """Lista jobs (extracciones) filtrados por analista. Sin filtro devuelve todos (para admin)."""
    query = db.query(Extraction)
    if analista_id:
        query = query.filter(Extraction.analista_id == analista_id)
    extracciones = query.order_by(Extraction.created_at.desc()).all()

    filas = []
    # Sin score_final: ver _ocultar_calificacion.
    for ext in extracciones:
        evaluacion = _ultima_evaluacion(db, ext.id)
        filas.append({
            "job_id":          ext.id,
            "filename":        ext.filename,
            "nombre_analisis": ext.nombre_analisis or ext.filename,
            "presentador":     ext.presentador or "—",
            "tipo":            ext.tipo or "—",
            "dependencia":     ext.dependencia or "—",
            "analista_id":     ext.analista_id,
            "status":          _estado_combinado(ext, evaluacion),
            "created_at":      ext.created_at.isoformat() if ext.created_at else None,
        })
    return filas


@app.get("/videos")
def list_videos():
    """Lista los videos disponibles en la carpeta."""
    exts  = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    files = [f for f in os.listdir(VIDEO_FOLDER)
             if os.path.splitext(f)[1].lower() in exts]
    return {"videos": files}


@app.get("/analyze/{job_id}/result")
def get_result_clean(job_id: str, db: Session = Depends(get_db)):
    extraccion = db.query(Extraction).filter_by(id=job_id).first()

    if not extraccion:
        raise HTTPException(404, "Job no encontrado")

    evaluacion_row = _ultima_evaluacion(db, job_id)
    estado = _estado_combinado(extraccion, evaluacion_row)

    if estado != "done":
        return {
            "job_id": extraccion.id,
            "status": estado,
            "message": "El análisis aún no ha terminado"
        }

    result = _resultado_combinado(extraccion, evaluacion_row)

    evaluacion = result.get("evaluacion", {})
    interpretaciones = evaluacion.get("interpretaciones_oratoria", {})

    def get_nivel(kpi):
        return interpretaciones.get(kpi, {}).get("nivel", "desconocido")

    # Sin score/niveles acá tampoco: ver _ocultar_calificacion.
    return {
        "job_id": extraccion.id,
        "status": estado,

        "summary": {
            "duracion_min": round(result.get("duration_seconds", 0) / 60, 2),
            "palabras":     result.get("total_words", 0),
        },

        "video_info": result.get("video_info", {}),

        "transcription_calidad": result.get("transcription_calidad", {}),

        "resumen_ejecutivo": evaluacion.get("resumen_ejecutivo", "No se pudo generar la evaluación"),

        "competencias_mbdd": result.get("competencias_mbdd", {}).get("competencias", {}),

        "kpis": {
            "speech_time": get_nivel("speech_time"),
            "rhythm":      get_nivel("rhythm"),
            "sentiment":   get_nivel("sentiment"),
            "clarity":     get_nivel("clarity"),
            "audio":       get_nivel("audio"),
        },

        "details": result.get("kpis", {}),
    }
