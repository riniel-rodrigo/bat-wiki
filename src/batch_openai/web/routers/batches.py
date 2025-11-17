from __future__ import annotations

from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from ...services.openai_client import get_client
from ...services.batch_service import submit as svc_submit
from ...utils.files import ensure_output_dir
from ...parsers.output_parser import parse as parse_outputs
from ..errors import as_http_error
from ..schemas.batches import (
    SubmitRequest,
    RunRequest,
    WaitRequest,
    ParseRequest,
    SubmitResponse,
    BatchStatusResponse,
    DownloadResponse,
    ParseResponse,
    RunResponse,
)


router = APIRouter(tags=["Batches"])

TERMINAL_STATES = {"completed", "failed", "cancelled", "expired"}


def _batch_to_dict(batch: Any) -> Dict[str, Any]:
    try:
        return batch.model_dump()
    except Exception:
        try:
            return batch.dict()
        except Exception:
            import json as _json

            try:
                return _json.loads(batch.json())
            except Exception:
                return {"id": getattr(batch, "id", None), "status": getattr(batch, "status", None)}


def _wait_blocking(batch_id: str, poll_interval: int) -> Dict[str, Any]:
    import time as _time

    client = get_client()
    while True:
        batch = client.batches.retrieve(batch_id)
        status = getattr(batch, "status", None)
        if status in TERMINAL_STATES:
            out_dir = ensure_output_dir(batch_id)
            data = _batch_to_dict(batch)
            (out_dir / "batch.json").write_text(
                __import__("json").dumps(data, indent=2, ensure_ascii=False)
            )
            return {"final_status": status, "batch": data}
        _time.sleep(max(1, poll_interval))


def _download_files(batch_id: str) -> DownloadResponse:
    client = get_client()
    batch = client.batches.retrieve(batch_id)
    status = getattr(batch, "status", None)
    if status != "completed":
        raise HTTPException(status_code=409, detail=f"batch {batch_id} not completed (status={status})")

    out_dir = ensure_output_dir(batch_id)
    if getattr(batch, "output_file_id", None):
        out = client.files.content(batch.output_file_id)
        (out_dir / "output.jsonl").write_text(out.text)
    if getattr(batch, "error_file_id", None):
        err = client.files.content(batch.error_file_id)
        (out_dir / "errors.jsonl").write_text(err.text)

    resp: Dict[str, Any] = {"output_dir": str(out_dir)}
    if (out_dir / "output.jsonl").exists():
        resp["output_file"] = str(out_dir / "output.jsonl")
    if (out_dir / "errors.jsonl").exists():
        resp["error_file"] = str(out_dir / "errors.jsonl")
    return DownloadResponse(**resp)


def _parse_outputs(batch_id: str, force: bool = False, only: Optional[list[str]] = None) -> ParseResponse:
    out_dir = ensure_output_dir(batch_id)
    output_path = out_dir / "output.jsonl"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail=f"{output_path} not found; download first")
    result = parse_outputs(batch_id, force=force, only=only)
    return ParseResponse(
        docs_dir=result.get("docs_dir"),
        processed=result.get("processed", 0),
        skipped=result.get("skipped", 0),
        index_file=str(out_dir / "index.json"),
    )


@router.post(
    "/batches",
    summary="Criar batch (submit)",
    description=(
        "Cria um batch a partir de um arquivo .jsonl local. "
        "Campos: input_path (obrigatório), job_name (opcional), completion_window (ex.: '24h'). "
        "Retorna o batch_id e o diretório onde os artefatos serão gravados."
    ),
    response_model=SubmitResponse,
)
def submit(req: SubmitRequest) -> SubmitResponse:
    try:
        batch_id = svc_submit(req.input_path, req.job_name, req.completion_window)
        out_dir = str(ensure_output_dir(batch_id))
        return SubmitResponse(batch_id=batch_id, output_dir=out_dir)
    except SystemExit as e:
        raise HTTPException(status_code=400, detail=f"submit failed with code {e.code}")
    except Exception as e:
        raise as_http_error(e)


@router.get(
    "/batches/{batch_id}/status",
    summary="Consultar status do batch",
    description="Retorna o status atual e o objeto completo do batch.",
    response_model=BatchStatusResponse,
)
def get_status(batch_id: str) -> BatchStatusResponse:
    try:
        client = get_client()
        batch = client.batches.retrieve(batch_id)
        data = _batch_to_dict(batch)
        return BatchStatusResponse(status=data.get("status"), batch=data)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"batch {batch_id} not found or inaccessible: {e}")


@router.post(
    "/batches/{batch_id}/wait",
    summary="Aguardar conclusão do batch",
    description=(
        "Faz polling até o batch entrar em estado terminal (completed/failed/cancelled/expired). "
        "Opcional: poll_interval (segundos). Persiste outputs/<batch_id>/batch.json."
    ),
)
def wait(batch_id: str, req: WaitRequest) -> Dict[str, Any]:
    try:
        return _wait_blocking(batch_id, req.poll_interval)
    except Exception as e:
        raise as_http_error(e)


@router.post(
    "/batches/{batch_id}/download",
    summary="Baixar resultados do batch",
    description=(
        "Baixa e salva output.jsonl e errors.jsonl (quando houver) em outputs/<batch_id>/."
    ),
    response_model=DownloadResponse,
)
def download(batch_id: str) -> DownloadResponse:
    try:
        return _download_files(batch_id)
    except HTTPException:
        raise
    except SystemExit as e:
        raise HTTPException(status_code=400, detail=f"download failed with code {e.code}")
    except Exception as e:
        raise as_http_error(e)


@router.post(
    "/batches/{batch_id}/parse",
    summary="Gerar documentos a partir do output",
    description=(
        "Lê outputs/<batch_id>/output.jsonl e gera arquivos .md em outputs/<batch_id>/docs/. "
        "Use após o download. Parâmetros: 'force' (reescrever arquivos existentes) e 'only' (lista de custom_id)."
    ),
    response_model=ParseResponse,
)
def parse(batch_id: str, req: Optional[ParseRequest] = None) -> ParseResponse:
    try:
        force = req.force if req else False
        only = req.only if req else None
        return _parse_outputs(batch_id, force=force, only=only)
    except HTTPException:
        raise
    except SystemExit as e:
        raise HTTPException(status_code=400, detail=f"parse failed with code {e.code}")
    except Exception as e:
        raise as_http_error(e)


@router.post(
    "/batches/run",
    summary="Fluxo completo: submit → wait → download → (parse)",
    description=(
        "Executa o processo completo em uma única chamada. Campos: input_path, job_name, "
        "completion_window, poll_interval e do_parse. Retorna batch_id e caminhos gerados."
    ),
    response_model=RunResponse,
)
def run(req: RunRequest) -> RunResponse:
    try:
        batch_id = svc_submit(req.input_path, req.job_name, req.completion_window)
        _ = _wait_blocking(batch_id, req.poll_interval)
        d = _download_files(batch_id)
        parsed = None
        if req.do_parse:
            parsed = _parse_outputs(batch_id, force=False, only=None)
        return RunResponse(batch_id=batch_id, download=d, parse=parsed)
    except HTTPException:
        raise
    except Exception as e:
        raise as_http_error(e)


@router.post(
    "/batches/run-file",
    summary="Upload + fluxo completo",
    description=(
        "Faz upload de um .jsonl e executa o fluxo completo: submit → wait → download → (parse). "
        "Campos multipart: file (.jsonl), job_name, completion_window, poll_interval, do_parse."
    ),
    response_model=RunResponse,
)
async def run_file(
    file: UploadFile = File(...),
    job_name: Optional[str] = Form(default=None),
    completion_window: str = Form(default="24h"),
    poll_interval: int = Form(default=10),
    do_parse: bool = Form(default=True),
) -> RunResponse:
    try:
        filename = file.filename or "uploaded.jsonl"
        if not filename.lower().endswith(".jsonl"):
            raise HTTPException(status_code=400, detail="arquivo deve ter extensão .jsonl")

        from pathlib import Path
        import uuid

        inputs_dir = Path("inputs")
        inputs_dir.mkdir(parents=True, exist_ok=True)
        dest_path = inputs_dir / f"{uuid.uuid4().hex}__{filename}"

        total = 0
        with dest_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                out.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="arquivo vazio")

        batch_id = svc_submit(str(dest_path), job_name, completion_window)
        _ = _wait_blocking(batch_id, poll_interval=poll_interval)
        d = _download_files(batch_id)
        parsed = None
        if do_parse:
            parsed = _parse_outputs(batch_id, force=False, only=None)
        return RunResponse(batch_id=batch_id, download=d, parse=parsed)
    except HTTPException:
        raise
    except SystemExit as e:
        raise HTTPException(status_code=400, detail=f"run-file failed with code {e.code}")
    except Exception as e:
        raise as_http_error(e)
