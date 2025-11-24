from __future__ import annotations

from typing import Dict, Any, List, Optional
from pydantic import BaseModel



class PreviewItem(BaseModel):
    custom_id: str
    output_text: Optional[str] = None
    error: Optional[str] = None
    request_body: Dict[str, Any]
    usage: Optional[Dict[str, Any]] = None


class PreviewFullResponse(BaseModel):
    items: List[PreviewItem]
    total: int
    batch_id: str
    output_dir: str
    parse: Optional[Dict[str, Any]] = None
