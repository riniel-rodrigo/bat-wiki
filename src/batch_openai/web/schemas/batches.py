from __future__ import annotations

from typing import Optional, Dict, Any
from pydantic import BaseModel


class SubmitRequest(BaseModel):
    input_path: str
    job_name: Optional[str] = None
    completion_window: str = "24h"


class WaitRequest(BaseModel):
    poll_interval: int = 10


class BatchStatusResponse(BaseModel):
    status: Optional[str] = None
    batch: Dict[str, Any]


class SubmitResponse(BaseModel):
    batch_id: str
    output_dir: str


class DownloadResponse(BaseModel):
    output_dir: str
    output_file: Optional[str] = None
    error_file: Optional[str] = None


class RunPayloadFileResponse(BaseModel):
    batch_id: str
    download: DownloadResponse
    parse_docs_dir: Optional[str] = None
    parse_processed: int = 0
    parse_skipped: int = 0
    parse_index_file: Optional[str] = None
