import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/videokpi")

# pool_size/max_overflow por defecto (5+10=15) se agota con lotes grandes:
# cada video en cola consulta su estado (GET /status) cada pocos segundos,
# y con el servidor ocupado por Whisper (más lento en soltar conexiones),
# ráfagas de ~15+ consultas simultáneas superan el límite y tiran
# "QueuePool limit ... connection timed out" (confirmado en un lote real
# de 43 videos). 30/20 da margen para varias decenas en vuelo a la vez.
engine = create_engine(DATABASE_URL, pool_size=30, max_overflow=20, pool_timeout=60)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()