from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

class JobStatus(str, Enum):
    pending   = "pending"
    running   = "running"
    done      = "done"
    failed    = "failed"

class JobCreate(BaseModel):
    video_path: str           # ruta absoluta en disco
    filename: str             # nombre legible

class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    filename: str
    created_at: datetime

class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float

class TranscriptResult(BaseModel):
    job_id: str
    transcript: str
    words: list[WordTimestamp]
    duration_seconds: float
    language: Optional[str] = None