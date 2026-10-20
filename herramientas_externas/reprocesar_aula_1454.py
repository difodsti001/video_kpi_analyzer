"""Regenera en sitio las evaluaciones de un aula Moodle sin repetir extracción.

Uso:
    .\\venv\\Scripts\\python.exe herramientas_externas\\reprocesar_aula_1454.py --dry-run
    .\\venv\\Scripts\\python.exe herramientas_externas\\reprocesar_aula_1454.py --workers 2
    .\\venv\\Scripts\\python.exe herramientas_externas\\reprocesar_aula_1454.py --analista-id benchmark --curso-id video_en_clase_2026 --workers 2

Actualiza las filas existentes de ``evaluaciones``: no crea evaluaciones nuevas
ni modifica extracciones, videos ni resultados de Whisper/YOLO/MediaPipe.
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.database import SessionLocal
from shared.models import Extraction, Evaluation
from jobs import _run_evaluation

DEPENDENCIA_POR_DEFECTO = "curso_moodle_1454_assign_31418"
CURSO_ID_POR_DEFECTO = "aula_1454"


def preparar_reproceso(
    dependencia: str | None,
    analista_id: str | None,
    curso_id: str,
    dry_run: bool,
) -> list[tuple[str, dict]]:
    db = SessionLocal()
    try:
        query = db.query(Extraction).filter_by(status="done")
        if dependencia:
            query = query.filter_by(dependencia=dependencia)
        if analista_id:
            query = query.filter_by(analista_id=analista_id)
        extracciones = query.order_by(Extraction.created_at).all()
        tareas = []
        faltantes = []
        for extraccion in extracciones:
            evaluacion = (
                db.query(Evaluation)
                .filter_by(extraction_id=extraccion.id, curso_id=curso_id)
                .order_by(Evaluation.created_at.desc())
                .first()
            )
            if evaluacion is None:
                faltantes.append(extraccion.id)
                continue
            tareas.append((evaluacion.id, extraccion.result))

        if faltantes:
            raise RuntimeError(
                f"Hay {len(faltantes)} extracciones sin evaluación {curso_id}; "
                "se cancela para no crear filas nuevas."
            )
        if not tareas:
            raise RuntimeError("No se encontraron extracciones terminadas para reprocesar.")

        filtro = f"dependencia: {dependencia}" if dependencia else f"analista_id: {analista_id}"
        print(f"Extracciones listas: {len(tareas)} | curso: {curso_id} | {filtro}")
        if dry_run:
            print("Dry run: no se modificó ninguna evaluación.")
            return []

        for evaluation_id, _ in tareas:
            evaluacion = db.query(Evaluation).filter_by(id=evaluation_id).one()
            evaluacion.status = "pending"
            evaluacion.result = None
            evaluacion.error = None
        db.commit()
        return tareas
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dependencia", default=None)
    parser.add_argument("--analista-id", default=None)
    parser.add_argument("--curso-id", default=CURSO_ID_POR_DEFECTO)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers debe ser mayor o igual a 1")
    if not args.dependencia and not args.analista_id:
        args.dependencia = DEPENDENCIA_POR_DEFECTO

    tareas = preparar_reproceso(args.dependencia, args.analista_id, args.curso_id, args.dry_run)
    if args.dry_run:
        return

    exitosas = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(_run_evaluation, evaluation_id, resultado, args.curso_id)
            for evaluation_id, resultado in tareas
        ]
        for numero, future in enumerate(as_completed(futures), start=1):
            future.result()
            exitosas = numero
            print(f"Completadas: {exitosas}/{len(tareas)}")
    print(f"Reproceso finalizado: {exitosas}/{len(tareas)} evaluaciones actualizadas en sitio.")


if __name__ == "__main__":
    main()
