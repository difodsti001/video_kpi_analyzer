import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from shared.database import Base

class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id:         Mapped[str]      = mapped_column(String, primary_key=True,
                                    default=lambda: str(uuid.uuid4()))
    filename:   Mapped[str]      = mapped_column(String)
    video_path: Mapped[str]      = mapped_column(String)
    status:     Mapped[str]      = mapped_column(String, default="pending")
    result:     Mapped[dict|None]= mapped_column(JSON, nullable=True)
    error:      Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                    onupdate=datetime.utcnow)