"""
clonar_rubrica.py — Clona la rúbrica 'default' (tabla rubricas_curso) bajo un
nuevo curso_id, para evaluar un aula específica con los mismos criterios sin
tocar la rúbrica por defecto (y poder ajustarla después sin afectar al resto).

Accede directo a la base (no pasa por la API) — se corre una sola vez por
aula nueva, no es parte del flujo de procesamiento de videos.

EJECUCIÓN (desde la raíz del proyecto, con el venv activado)
    python herramientas_externas/clonar_rubrica.py --curso-id aula_1454 \
        --nombre "Aula 1454 — Metodologías activas"
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import SessionLocal
from shared.models import RubricaCurso


def clonar(curso_id_nuevo: str, nombre_nuevo: str, curso_id_origen: str = "default") -> None:
    db = SessionLocal()
    try:
        origen = db.query(RubricaCurso).filter_by(curso_id=curso_id_origen).first()
        if origen is None:
            print(f"No existe la rúbrica de origen '{curso_id_origen}' en rubricas_curso.", file=sys.stderr)
            sys.exit(1)

        existente = db.query(RubricaCurso).filter_by(curso_id=curso_id_nuevo).first()
        if existente is not None:
            print(f"Ya existe una rúbrica con curso_id='{curso_id_nuevo}' — no se sobreescribe.", file=sys.stderr)
            sys.exit(1)

        clon = RubricaCurso(
            curso_id=curso_id_nuevo,
            nombre=nombre_nuevo,
            criterios=origen.criterios,
            peso_contenido=origen.peso_contenido,
            peso_forma=origen.peso_forma,
            activo=True,
        )
        db.add(clon)
        db.commit()
        print(f"Rúbrica clonada: '{curso_id_origen}' -> '{curso_id_nuevo}' ({nombre_nuevo})")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Clona una rúbrica existente bajo un nuevo curso_id.")
    parser.add_argument("--curso-id", required=True, help="curso_id nuevo (el que se pasará como --curso-id al procesar videos)")
    parser.add_argument("--nombre", required=True, help="Nombre descriptivo de la rúbrica clonada")
    parser.add_argument("--desde", default="default", help="curso_id de origen a clonar (default: 'default')")
    args = parser.parse_args()
    clonar(args.curso_id, args.nombre, args.desde)


if __name__ == "__main__":
    main()
