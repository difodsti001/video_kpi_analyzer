from datetime import datetime
from sqlalchemy import String, DateTime, Text, JSON, ForeignKey, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from shared.database import Base


class Extraction(Base):
    """
    La parte cara del análisis: todo lo que se calcula directamente del video
    (Whisper, KPIs de oratoria, postura, objetos, ficha técnica) — se corre
    una sola vez por video, sin depender de ningún curso/rúbrica específica.
    """
    __tablename__ = "extracciones"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str] = mapped_column(String)
    video_path: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    presentador: Mapped[str | None] = mapped_column(String, nullable=True)
    tipo: Mapped[str | None] = mapped_column(String, nullable=True)
    dependencia: Mapped[str | None] = mapped_column(String, nullable=True)
    analista_id: Mapped[str | None] = mapped_column(String, nullable=True)
    nombre_analisis: Mapped[str | None] = mapped_column(String, nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)


class RubricaCurso(Base):
    """
    Configuración de evaluación por curso: qué criterios de contenido se
    evalúan (y sus niveles/pesos), y cómo se pondera contenido vs. forma en
    el score final. Reemplaza al registro fijo de services/cursos/registro.py
    — cada curso es una fila acá, cargada directamente en la base (sin UI de
    administración por ahora).
    """
    __tablename__ = "rubricas_curso"

    curso_id: Mapped[str] = mapped_column(String, primary_key=True)
    nombre: Mapped[str] = mapped_column(String)
    # Lista de criterios: [{id, nombre, que_evalua, peso, niveles: {Inicio,
    # En desarrollo, Logrado, Destacado}}, ...] — mismo formato que tenía
    # services/evaluacion/rubrica_data.py antes de migrarse acá.
    criterios: Mapped[list] = mapped_column(JSON)
    peso_contenido: Mapped[float] = mapped_column(Float, default=0.70)
    peso_forma: Mapped[float] = mapped_column(Float, default=0.30)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Evaluation(Base):
    """
    La parte barata: rúbrica de contenido + competencias MBDD, evaluadas con
    el LLM contra la configuración de UN curso. Varias evaluaciones pueden
    apuntar a la misma extracción (distintos cursos, o reintentos) sin pagar
    de nuevo el costo de Whisper/YOLO/MediaPipe.
    """
    __tablename__ = "evaluaciones"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    extraction_id: Mapped[str] = mapped_column(String, ForeignKey("extracciones.id"), index=True)
    curso_id: Mapped[str] = mapped_column(String, default="default")
    status: Mapped[str] = mapped_column(String, default="pending")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
