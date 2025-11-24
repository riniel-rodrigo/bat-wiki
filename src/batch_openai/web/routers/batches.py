from __future__ import annotations

from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from ...services.openai_client import get_client
from ...services.batch_service import submit as svc_submit, TERMINAL_STATES
from ...utils.files import ensure_output_dir
from ...utils.payloads import decode_payload_bytes
from ...parsers.output_parser import parse as parse_outputs
from ..errors import as_http_error
from ..schemas.batches import (
    SubmitRequest,
    WaitRequest,
    SubmitResponse,
    BatchStatusResponse,
    DownloadResponse,
    RunPayloadFileResponse,
)
from ...tools.input_builder import build_inputs_from_payload, normalize_payload_sada


router = APIRouter(tags=["Batches"])

# Flag opcional via env para habilitar/desabilitar logs de status (default: ON)
import os
LOG_STATUS = os.getenv("BATCH_LOG_STATUS", "1") not in ("0", "false", "False")


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
    last_status: Optional[str] = None
    if LOG_STATUS:
        print(f"Aguardando batch {batch_id} terminar... (poll={poll_interval}s)")
    while True:
        batch = client.batches.retrieve(batch_id)
        status = getattr(batch, "status", None)
        if LOG_STATUS and status != last_status:
            print(f"status={status}")
            last_status = status
        if status in TERMINAL_STATES:
            out_dir = ensure_output_dir(batch_id)
            data = _batch_to_dict(batch)
            (out_dir / "batch.json").write_text(
                __import__("json").dumps(data, indent=2, ensure_ascii=False)
            )
            if LOG_STATUS:
                print(f"Status final: {status}")
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


def _parse_outputs(batch_id: str, force: bool = False, only: Optional[list[str]] = None) -> Dict[str, Any]:
    out_dir = ensure_output_dir(batch_id)
    output_path = out_dir / "output.jsonl"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail=f"{output_path} not found; download first")
    result = parse_outputs(batch_id, force=force, only=only)
    return {
        "docs_dir": result.get("docs_dir"),
        "processed": result.get("processed", 0),
        "skipped": result.get("skipped", 0),
        "index_file": str(out_dir / "index.json"),
    }


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
        batch_id = svc_submit(req.input_path, req.job_name, req.completion_window, verbose=True)
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


# Removidos endpoints antigos: parse, run, run-file, run-payload (refatoração de escopo solicitado)


@router.post(
    "/batches/run-payload-file",
    summary="Upload de payload JSON → (build .jsonl) → submit → wait → download → (parse)",
    description=(
        "Recebe um arquivo JSON (payload do processo) via multipart/form-data, gera um .jsonl modular (5 tópicos), "
        "e executa todo o fluxo. Campos: file (obrigatório), job_name, completion_window, poll_interval, do_parse, persist_context."
    ),
    response_model=RunPayloadFileResponse,
)
async def run_payload_file(
    file: UploadFile = File(...),
    job_name: Optional[str] = Form(default=None),
    completion_window: str = Form(default="24h"),
    poll_interval: int = Form(default=10),
    do_parse: bool = Form(default=True),
    persist_context: bool = Form(default=False),
) -> RunPayloadFileResponse:
    try:
        if not (file.filename or "").lower().endswith((".json", ".payload", ".txt")):
            # Aceita também .txt para facilitar, mas valida conteúdo abaixo
            pass
        raw = await file.read()
        try:
            payload = decode_payload_bytes(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        from pathlib import Path
        payload_norm = normalize_payload_sada(payload or {})
        proc = (payload_norm.get("entry_point") or {}).get("name") or (file.filename or "processo")
        sanitized = proc.replace(" ", "").replace("/", "_")
        proc_root = Path("inputs/by_process") / sanitized
        jsonl_dir = proc_root / "payloads"
        jsonl_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = jsonl_dir / f"{sanitized}.jsonl"
        # agrupar context packs sob inputs/by_process/<proc>/...
        ctx_dir = Path("inputs/by_process") if persist_context else None
        templates_dir = Path("prompts")
        build_inputs_from_payload(payload_norm, templates_dir, jsonl_path, persist_context=ctx_dir)

        # Submit
        batch_id = svc_submit(str(jsonl_path), job_name, completion_window, verbose=True)
        # Wait
        _ = _wait_blocking(batch_id, poll_interval=poll_interval)
        # Download
        d = _download_files(batch_id)
        # Parse (sempre porque faz parte do fluxo solicitado implícito)
        parse_result = None
        if do_parse:
            pr = _parse_outputs(batch_id, force=False, only=None)
            parse_result = pr
        return RunPayloadFileResponse(
            batch_id=batch_id,
            download=d,
            parse_docs_dir=(parse_result.get("docs_dir") if parse_result else None),
            parse_processed=(parse_result.get("processed") if parse_result else 0),
            parse_skipped=(parse_result.get("skipped") if parse_result else 0),
            parse_index_file=(str(ensure_output_dir(batch_id) / "index.json") if parse_result else None),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise as_http_error(e)
