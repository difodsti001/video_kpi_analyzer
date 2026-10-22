# jobs.py — orquestación en segundo plano: cola/semáforo, reintentos y
# limpieza. Separado de main.py (que solo tiene rutas) y de core.py (que es
# puro, sin BD ni FastAPI, para poder llamarlo desde scripts sueltos).
import os
import asyncio
import logging
import time
import uuid as uuid_lib
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

from shared.database import SessionLocal
from shared.models    import Extraction, Evaluation, AIUsage
from core              import Extractor, evaluar_extraccion
from services.transversal.cursos.registro import CURSO_POR_DEFECTO

# Máximo de extracciones corriendo a la vez (Whisper+YOLO+MediaPipe pesan);
# el resto espera en cola. La evaluación (LLM) no pasa por este semáforo.
MAX_CONCURRENT_ANALYSIS = int(os.getenv("MAX_CONCURRENT_ANALYSIS", "2"))
analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSIS)

# Reintento de la evaluación completa si el LLM "respondió" pero sin
# contenido usable (score_rubrica=None) — distinto del reintento de la
# llamada HTTP en sí, que ya existe en services/transversal/llm/client.py.
EVALUACION_MAX_REINTENTOS = int(os.getenv("EVALUACION_MAX_REINTENTOS", "3"))
EVALUACION_ESPERA_REINTENTO_SEG = float(os.getenv("EVALUACION_ESPERA_REINTENTO_SEG", "3"))


def _guardar_consumos_ia(db, extraction_id: str, evaluation_id: str | None, consumos: list[dict]):
    for consumo in consumos or []:
        db.add(AIUsage(
            id=str(uuid_lib.uuid4()), extraction_id=extraction_id, evaluation_id=evaluation_id,
            capa_ia=consumo.get("capa_ia", "desconocida"), proveedor=consumo.get("proveedor", "desconocido"),
            modelo=consumo.get("modelo") or "desconocido", solicitudes=int(consumo.get("solicitudes") or 1),
            imagenes_enviadas=int(consumo.get("imagenes_enviadas") or 0),
            tokens_entrada=consumo.get("tokens_entrada"), tokens_salida=consumo.get("tokens_salida"),
            tokens_totales=consumo.get("tokens_totales"), estado=consumo.get("estado", "exitoso"),
        ))

# Si el proceso muere a mitad de un job, queda en "running" para siempre.
# Este loop marca como "failed" lo que lleva mucho tiempo sin actividad.
JOB_STALE_TIMEOUT_MIN    = int(os.getenv("JOB_STALE_TIMEOUT_MIN", "120"))
JOB_CLEANUP_INTERVAL_SEC = int(os.getenv("JOB_CLEANUP_INTERVAL_SEC", "300"))


def _cleanup_stale_jobs():
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


async def cleanup_stale_jobs_loop():
    while True:
        await asyncio.sleep(JOB_CLEANUP_INTERVAL_SEC)
        try:
            _cleanup_stale_jobs()
        except Exception as e:
            logger.error(f"Error en limpieza de jobs atascados: {e}")


# ── evaluación ───────────────────────────────────────────────────────

def _run_evaluation(evaluation_id: str, extraction_result: dict, curso_id: str):
    """Corre evaluar_extraccion() y guarda el resultado en Evaluation.
    Reintenta mientras score_rubrica venga en None — ver EVALUACION_MAX_REINTENTOS."""
    db = SessionLocal()
    try:
        evaluacion = db.query(Evaluation).filter_by(id=evaluation_id).first()
        evaluacion.status = "running"
        db.commit()

        resultado = None
        for intento in range(1, EVALUACION_MAX_REINTENTOS + 1):
            resultado = evaluar_extraccion(extraction_result, curso_id)
            score_rubrica = resultado.get("evaluacion", {}).get("score_rubrica")
            if score_rubrica is not None:
                break
            logger.warning(
                f"[{evaluation_id}] Intento {intento}/{EVALUACION_MAX_REINTENTOS}: "
                f"la evaluación terminó sin contenido útil del LLM (score_rubrica=None)"
                + (" — reintentando" if intento < EVALUACION_MAX_REINTENTOS else " — se agotaron los reintentos")
            )
            if intento < EVALUACION_MAX_REINTENTOS:
                time.sleep(EVALUACION_ESPERA_REINTENTO_SEG)

        evaluacion.status = "done"
        evaluacion.result = resultado
        _guardar_consumos_ia(db, evaluacion.extraction_id, evaluation_id, resultado.get("consumo_ia", []))

    except Exception as e:
        logger.exception(f"[{evaluation_id}] Error evaluando")
        evaluacion.status = "failed"
        evaluacion.error  = str(e)

    finally:
        db.commit()
        db.close()


async def run_evaluation_queued(evaluation_id: str, extraction_result: dict, curso_id: str):
    """Sin semáforo: la evaluación es barata, no compite por CPU con Whisper/YOLO."""
    await asyncio.to_thread(_run_evaluation, evaluation_id, extraction_result, curso_id)


# ── extracción (pesada) ───────────────────────────────────────────────

def _run_extraction(extraction_id: str, video_path: str, curso_id: str = CURSO_POR_DEFECTO):
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
        _guardar_consumos_ia(db, extraction_id, None, resultado.get("consumo_ia", []))
        db.commit()
        logger.info(f"[{extraction_id}] Extracción completa")

        # Auditoría de calidad de transcripción: solo logs, no va a la interfaz.
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

        # Retención: el video fuente ya no se necesita tras extraer con éxito.
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                logger.info(f"[{extraction_id}] Video fuente eliminado tras extracción exitosa: {video_path}")
        except OSError as e:
            logger.warning(f"[{extraction_id}] No se pudo eliminar el video fuente ({video_path}): {e}")

        # Encadena la evaluación automáticamente con el curso indicado.
        evaluacion = Evaluation(
            id=str(uuid_lib.uuid4()),
            extraction_id=extraction_id,
            curso_id=curso_id,
            status="pending",
        )
        db.add(evaluacion)
        db.commit()
        db.refresh(evaluacion)

        _run_evaluation(evaluacion.id, resultado, curso_id)

    except Exception as e:
        logger.exception(f"[{extraction_id}] Error en extracción")
        extraccion = db.query(Extraction).filter_by(id=extraction_id).first()
        extraccion.status = "failed"
        extraccion.error  = str(e)
        db.commit()

    finally:
        db.close()


async def run_extraction_queued(extraction_id: str, video_path: str, curso_id: str = CURSO_POR_DEFECTO):
    """Espera un cupo libre del semáforo antes de correr la extracción
    (bloqueante) en un hilo aparte, sin bloquear el event loop."""
    async with analysis_semaphore:
        await asyncio.to_thread(_run_extraction, extraction_id, video_path, curso_id)
