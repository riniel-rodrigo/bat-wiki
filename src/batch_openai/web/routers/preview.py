from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from ...services.preview_service import run_preview
from ..schemas.preview import (
    PreviewFullResponse,
    PreviewItem,
)
from ...parsers.output_parser import parse as parse_output
from ...utils.files import ensure_output_dir
from ...utils.payloads import decode_payload_bytes
import uuid, json
from ..errors import as_http_error

router = APIRouter(tags=["Preview"], prefix="/preview")


def _parse_max_tokens_override(raw_val: str | None, topics_list: list[str] | None) -> dict | None:
    if not raw_val:
        return None
    raw_val = raw_val.strip()
    # Se for só número -> aplicar a todos tópicos
    if raw_val.isdigit():
        val = int(raw_val)
        tlist = topics_list or ["resumo", "fluxo_execucao", "regras_negocio", "diagram_activity", "diagram_sequence"]
        return {t: val for t in tlist}
    import json as _json
    try:
        parsed = _json.loads(raw_val)
    except Exception:
        raise HTTPException(status_code=400, detail="max_tokens_override inválido: usar número ou JSON {""topic"":n}")
    if isinstance(parsed, int):
        tlist = topics_list or ["resumo", "fluxo_execucao", "regras_negocio", "diagram_activity", "diagram_sequence"]
        return {t: parsed for t in tlist}
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="max_tokens_override inválido: deve ser objeto JSON ou inteiro")
    # validar valores inteiros
    for k, v in parsed.items():
        if not isinstance(v, int):
            raise HTTPException(status_code=400, detail=f"max_tokens_override[{k}] deve ser inteiro")
    return parsed


@router.post(
    "/payload-file/full",
    summary="Preview completo via upload de arquivo JSON",
    description="Upload multipart de payload JSON (arquivo) e simulação completa (gera output.jsonl + parser).",
    response_model=PreviewFullResponse,
)
async def preview_payload_file_full(
    file: UploadFile = File(...),
    topics: str | None = Form(default=None),
    max_tokens_override: str | None = Form(default=None),
    do_parse: bool = Form(default=True),
):
    try:
        raw = await file.read()
        try:
            payload = decode_payload_bytes(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        topics_list = [t.strip() for t in topics.split(",") if t.strip()] if topics else None
        mto = _parse_max_tokens_override(max_tokens_override, topics_list)
        results = run_preview(payload, topics=topics_list, max_tokens_override=mto)
        batch_id = f"preview-{uuid.uuid4().hex[:8]}"
        out_dir = ensure_output_dir(batch_id)
        lines = []
        for r in results:
            cid = r.get("custom_id") or "no_custom_id"
            content = r.get("output_text") or r.get("error") or ""
            obj = {
                "id": f"preview_req_{uuid.uuid4().hex[:12]}",
                "custom_id": cid,
                "response": {
                    "status_code": 200 if r.get("error") is None else 500,
                    "request_id": uuid.uuid4().hex,
                    "body": {"choices": [{"message": {"content": content}}]},
                },
                "error": None if r.get("error") is None else {"message": r.get("error")},
            }
            lines.append(json.dumps(obj, ensure_ascii=False))
        (out_dir / "output.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        parse_result = parse_output(batch_id, force=True) if do_parse else None
        return PreviewFullResponse(
            items=[PreviewItem(**r) for r in results],
            total=len(results),
            batch_id=batch_id,
            output_dir=str(out_dir),
            parse=parse_result,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise as_http_error(e)
