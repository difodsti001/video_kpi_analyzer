# services/cursos/registro.py

CURSO_POR_DEFECTO = "default"


def obtener_curso(curso_id: str | None, db=None) -> dict:
    """
    Devuelve la config del curso (criterios, pesos) desde la base de datos.
    Si curso_id no viene, no existe, o está inactivo, cae a 'default'.

    db: sesión de SQLAlchemy ya abierta (reutilizada si se pasa, para no
    abrir una conexión nueva en medio de una transacción existente). Si no
    se pasa, abre y cierra una propia.
    """
    from shared.models import RubricaCurso

    cerrar_al_final = False
    if db is None:
        from shared.database import SessionLocal
        db = SessionLocal()
        cerrar_al_final = True

    try:
        fila = None
        if curso_id:
            fila = db.query(RubricaCurso).filter_by(curso_id=curso_id, activo=True).first()

        if fila is None:
            fila = db.query(RubricaCurso).filter_by(curso_id=CURSO_POR_DEFECTO).first()

        if fila is None:
            raise RuntimeError(
                "No existe el curso 'default' en rubricas_curso — falta correr la migración "
                "que carga la configuración inicial (ver scripts de seed)."
            )

        return {
            "id":             fila.curso_id,
            "nombre":         fila.nombre,
            "criterios":      fila.criterios,
            "peso_contenido": fila.peso_contenido,
            "peso_forma":     fila.peso_forma,
        }
    finally:
        if cerrar_al_final:
            db.close()
