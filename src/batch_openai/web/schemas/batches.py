from __future__ import annotations

from typing import Optional, Dict, Any, List
from pydantic import BaseModel


class SubmitRequest(BaseModel):
    input_path: str
    job_name: Optional[str] = None
    completion_window: str = "24h"


class RunRequest(SubmitRequest):
    poll_interval: int = 10
    do_parse: bool = True


class RunPayloadRequest(BaseModel):
    payload: Dict[str, Any]
    job_name: Optional[str] = None
    completion_window: str = "24h"
    poll_interval: int = 10
    do_parse: bool = True
    persist_context: bool = False


class WaitRequest(BaseModel):
    poll_interval: int = 10


class ParseRequest(BaseModel):
    force: bool = False
    only: Optional[List[str]] = None


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


class ParseResponse(BaseModel):
    docs_dir: Optional[str] = None
    processed: int = 0
    skipped: int = 0
    index_file: Optional[str] = None


class RunResponse(BaseModel):
    batch_id: str
    download: DownloadResponse
    parse: Optional[ParseResponse] = None
