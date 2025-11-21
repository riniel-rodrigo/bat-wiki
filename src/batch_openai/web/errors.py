from __future__ import annotations

from fastapi import HTTPException

def as_http_error(e: Exception) -> HTTPException:
    msg = str(e)
    lowered = msg.lower()
    if "unauthorized" in lowered or "invalid api key" in lowered or "401" in lowered:
        return HTTPException(status_code=401, detail=msg)
    if "forbidden" in lowered or "403" in lowered:
        return HTTPException(status_code=403, detail=msg)
    if "not found" in lowered or "404" in lowered:
        return HTTPException(status_code=404, detail=msg)
    if "conflict" in lowered or "409" in lowered:
        return HTTPException(status_code=409, detail=msg)
    if "unprocessable" in lowered or "422" in lowered:
        return HTTPException(status_code=422, detail=msg)
    if "error code: 400" in lowered or "invalid file format" in lowered or "bad request" in lowered:
        return HTTPException(status_code=400, detail=msg)
    return HTTPException(status_code=500, detail=msg)
