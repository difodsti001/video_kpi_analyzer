import os
import asyncio
import hashlib
import uuid as uuid_lib
import shutil
import logging
import warnings
from datetime import datetime, timedelta

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
from core            import Extractor, evaluar_extraccion
from services.cursos.registro import CURSO_POR_DEFECTO

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

# ── control de acceso a los endpoints de análisis ──────────────────
# Clave compartida simple (no hay sistema de usuarios): protege contra uso
# público no autorizado de los endpoints que disparan cómputo pesado y
# llamadas facturables al LLM. Falla cerrado: si no se configura API_KEY,
# se rechazan todas las peticiones a esos endpoints.
API_KEY = os.getenv("API_KEY", "")

def require_api_key(x_api_key: str = Header(default="")):
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(401, "API key inválida o faltante (header X-API-Key)")

# ── límite de análisis concurrentes ─────────────────────────────────
# Cada extracción carga Whisper + YOLO + MediaPipe; sin límite, N uploads
# simultáneos disparan N extracciones pesadas a la vez. El semáforo deja
# correr como máximo MAX_CONCURRENT_ANALYSIS a la vez; los demás esperan su
# turno en orden (cola FIFO implícita de asyncio). La evaluación (LLM) no
# pasa por este semáforo — es barata comparada con la extracción.
MAX_CONCURRENT_ANALYSIS = int(os.getenv("MAX_CONCURRENT_ANALYSIS", "2"))
analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSIS)

# ── limpieza de jobs atascados ──────────────────────────────────────
# Si el proceso muere a mitad de una extracción/evaluación (crash, redeploy,
# OOM), el registro se queda en "running" para siempre porque el
# except/finally correspondiente nunca llega a ejecutarse. Este loop revisa
# periódicamente y marca como "failed" lo que lleva "running" sin actividad.
JOB_STALE_TIMEOUT_MIN    = int(os.getenv("JOB_STALE_TIMEOUT_MIN", "120"))
JOB_CLEANUP_INTERVAL_SEC = int(os.getenv("JOB_CLEANUP_INTERVAL_SEC", "300"))

def _cleanup_stale_jobs():
    from shared.database import SessionLocal
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=JOB_STALE_TIMEOUT_MIN)
        mensaje = (
            f"Marcado como fallido automáticamente: sin actividad por más de "
            f"{JOB_STALE_TIMEOUT_MIN} minutos (probable caída del proceso)."
        )
        for Modelo in (Extraction, Evaluation):
            stale = db.query(Modelo).filter(
                Modelo.status == "running",
                Modelo.updated_at < cutoff,
            ).all()
            for row in stale:
                row.status = "failed"
                row.error  = mensaje
                logger.warning(f"[{row.id}] {Modelo.__tablename__} atascado en 'running' marcado como 'failed'")
            if stale:
                db.commit()
    finally:
        db.close()

async def _cleanup_stale_jobs_loop():
    while True:
        await asyncio.sleep(JOB_CLEANUP_INTERVAL_SEC)
        try:
            _cleanup_stale_jobs()
        except Exception as e:
            logger.error(f"Error en limpieza de jobs atascados: {e}")

@app.on_event("startup")
async def _start_background_jobs():
    asyncio.create_task(_cleanup_stale_jobs_loop())


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


def _run_evaluation(evaluation_id: str, extraction_result: dict, curso_id: str):
    """Corre evaluar_extraccion() y guarda el resultado en la fila Evaluation
    correspondiente. Se usa tanto en el encadenamiento automático tras una
    extracción exitosa, como en el endpoint para evaluar de nuevo."""
    from shared.database import SessionLocal
    db = SessionLocal()
    try:
        evaluacion = db.query(Evaluation).filter_by(id=evaluation_id).first()
        evaluacion.status = "running"
        db.commit()

        resultado = evaluar_extraccion(extraction_result, curso_id)

        evaluacion.status = "done"
        evaluacion.result = resultado

    except Exception as e:
        logger.exception(f"[{evaluation_id}] Error evaluando")
        evaluacion.status = "failed"
        evaluacion.error  = str(e)

    finally:
        db.commit()
        db.close()


def _run_extraction(extraction_id: str, video_path: str):
    from shared.database import SessionLocal
    db = SessionLocal()

    try:
        logger.info(f"[{extraction_id}] Iniciando extracción — video: {video_path}")

        extraccion = db.query(Extraction).filter_by(id=extraction_id).first()
        extraccion.status = "running"
        db.commit()

        extractor = Extractor(video_path)
        resultado = extractor.run()

        extraccion.status = "done"
        extraccion.result = resultado
        db.commit()
        logger.info(f"[{extraction_id}] Extracción completa")

        # Auditoría interna de calidad de transcripción: queda en logs (y en
        # transcription_calidad dentro del resultado, para quien arme una
        # vista de auditoría más adelante), no se muestra en la interfaz —
        # no es información que el docente/evaluador necesite ver de entrada.
        calidad = resultado.get("transcription_calidad", {})
        if calidad.get("confiable") is False:
            logger.warning(
                f"[{extraction_id}] Transcripción de baja confianza: "
                f"{calidad.get('pct_problema')}% de segmentos problema "
                f"({calidad.get('segmentos_problema')}/{calidad.get('total_segmentos')}), "
                f"umbral={calidad.get('umbral_pct')}%"
            )
        elif calidad.get("confiable") is True:
            logger.info(
                f"[{extraction_id}] Transcripción confiable: "
                f"{calidad.get('pct_problema')}% de segmentos problema "
                f"({calidad.get('segmentos_problema')}/{calidad.get('total_segmentos')})"
            )

        # Política de retención: el video fuente ya no se necesita una vez que
        # la extracción terminó (todo lo relevante quedó en extraccion.result).
        # Borrarlo evita que el disco se llene indefinidamente. Solo se borra
        # tras éxito — si la extracción falla, se conserva para depurar o
        # reintentar manualmente.
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                logger.info(f"[{extraction_id}] Video fuente eliminado tras extracción exitosa: {video_path}")
        except OSError as e:
            logger.warning(f"[{extraction_id}] No se pudo eliminar el video fuente ({video_path}): {e}")

        # Encadena automáticamente una evaluación con el curso por defecto,
        # para mantener la experiencia de "subir → ver informe completo" del
        # piloto. Queda igual de válido evaluar de nuevo después contra otro
        # curso via POST /extracciones/{id}/evaluaciones, sin repetir esto.
        evaluacion = Evaluation(
            id=str(uuid_lib.uuid4()),
            extraction_id=extraction_id,
            curso_id=CURSO_POR_DEFECTO,
            status="pending",
        )
        db.add(evaluacion)
        db.commit()
        db.refresh(evaluacion)

        _run_evaluation(evaluacion.id, resultado, CURSO_POR_DEFECTO)

    except Exception as e:
        logger.exception(f"[{extraction_id}] Error en extracción")
        extraccion = db.query(Extraction).filter_by(id=extraction_id).first()
        extraccion.status = "failed"
        extraccion.error  = str(e)
        db.commit()

    finally:
        db.close()


async def _run_extraction_queued(extraction_id: str, video_path: str):
    """Espera un cupo libre del semáforo antes de correr la extracción
    (bloqueante) en un hilo aparte, sin bloquear el event loop."""
    async with analysis_semaphore:
        await asyncio.to_thread(_run_extraction, extraction_id, video_path)


async def _run_evaluation_queued(evaluation_id: str, extraction_result: dict, curso_id: str):
    """La evaluación no pasa por el semáforo de CPU — es solo un par de
    llamadas al LLM, no compite por los mismos recursos que Whisper/YOLO."""
    await asyncio.to_thread(_run_evaluation, evaluation_id, extraction_result, curso_id)


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
    """El estado que ve el frontend: mientras la extracción no termine, es el
    de la extracción. Una vez lista, hay que esperar a que la evaluación
    encadenada automáticamente también llegue a un estado final (done o
    failed) — si se reportara 'done' apenas termina la extracción, el
    frontend podría consultar justo en el hueco antes de que la evaluación
    exista o termine, y ver un informe vacío. Si la evaluación falla, se
    sigue reportando 'done' igual: la extracción es la parte valiosa/costosa,
    y evaluacion.py ya tiene sus propios respaldos defensivos para no dejar
    campos vacíos ante un fallo del LLM."""
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
    db: Session = Depends(get_db),
):
    """v1 — video ya está en la carpeta video/"""
    path = os.path.join(VIDEO_FOLDER, filename)
    if not os.path.exists(path):
        raise HTTPException(404, f"Video no encontrado: {filename}")

    extraccion = _create_extraction(filename, path, db)
    logger.info(f"[{extraccion.id}] Extracción creada (from-file)")
    background_tasks.add_task(_run_extraction_queued, extraccion.id, path)
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
    db: Session = Depends(get_db),
):
    dest = os.path.join(VIDEO_FOLDER, file.filename)
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
    logger.info(f"[{extraccion.id}] Extracción creada — nombre='{nombre_analisis}' presentador='{presentador}' analista='{analista_id}' hash={file_hash[:12]}...")
    background_tasks.add_task(_run_extraction_queued, extraccion.id, dest)
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

    background_tasks.add_task(_run_evaluation_queued, evaluacion.id, extraccion.result, evaluacion.curso_id)
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
        "result":   resultado,
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
    for ext in extracciones:
        evaluacion = _ultima_evaluacion(db, ext.id)
        score = None
        if evaluacion and evaluacion.result:
            score = evaluacion.result.get("evaluacion", {}).get("score_final")
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
            "score":           score,
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

    return {
        "job_id": extraccion.id,
        "status": estado,

        "summary": {
            "score_final":    evaluacion.get("score_final", 0),
            "score_rubrica":  evaluacion.get("score_rubrica"),
            "score_oratoria": evaluacion.get("score_oratoria"),
            "duracion_min":   round(result.get("duration_seconds", 0) / 60, 2),
            "palabras":       result.get("total_words", 0),
        },

        "video_info": result.get("video_info", {}),

        "transcription_calidad": result.get("transcription_calidad", {}),

        "resumen_ejecutivo": evaluacion.get("resumen_ejecutivo", "No se pudo generar la evaluación"),

        "criterios_rubrica": evaluacion.get("criterios", {}),

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
