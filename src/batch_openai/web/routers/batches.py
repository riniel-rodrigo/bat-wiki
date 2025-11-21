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
    RunPayloadRequest,
    WaitRequest,
    ParseRequest,
    SubmitResponse,
    BatchStatusResponse,
    DownloadResponse,
    ParseResponse,
    RunResponse,
)
from ...tools.input_builder import build_inputs_from_payload, normalize_payload_sada


router = APIRouter(tags=["Batches"])

TERMINAL_STATES = {"completed", "failed", "cancelled", "expired"}

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
        batch_id = svc_submit(req.input_path, req.job_name, req.completion_window, verbose=True)
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

        batch_id = svc_submit(str(dest_path), job_name, completion_window, verbose=True)
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


@router.post(
    "/batches/run-payload",
    summary="Payload JSON → (build .jsonl) → submit → wait → download → (parse)",
    description=(
        "Recebe o payload JSON do processo, gera um .jsonl modular (5 tópicos), "
        "e executa todo o fluxo. Opcional: persistir context packs para auditoria."
    ),
    response_model=RunResponse,
)
def run_payload(req: RunPayloadRequest) -> RunResponse:
    try:
        from pathlib import Path
        payload_norm = normalize_payload_sada(req.payload or {})
        proc = (payload_norm.get("entry_point") or {}).get("name") or "processo"
        sanitized = proc.replace(" ", "").replace("/", "_")
        proc_root = Path("inputs/by_process") / sanitized
        jsonl_dir = proc_root / "payloads"
        jsonl_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = jsonl_dir / f"{sanitized}.jsonl"
        # para agrupar por processo, passamos a raiz dos processos; o builder criará <proc>/<topic>/...
        ctx_dir = Path("inputs/by_process") if req.persist_context else None
        templates_dir = Path("prompts")
        build_inputs_from_payload(payload_norm, templates_dir, jsonl_path, persist_context=ctx_dir)

        run_req = RunRequest(
            input_path=str(jsonl_path),
            job_name=req.job_name,
            completion_window=req.completion_window,
            poll_interval=req.poll_interval,
            do_parse=req.do_parse,
        )
        return run(run_req)
    except HTTPException:
        raise
    except Exception as e:
        raise as_http_error(e)


@router.post(
    "/batches/run-payload-file",
    summary="Upload de payload JSON → (build .jsonl) → submit → wait → download → (parse)",
    description=(
        "Recebe um arquivo JSON (payload do processo) via multipart/form-data, gera um .jsonl modular (5 tópicos), "
        "e executa todo o fluxo. Campos: file (obrigatório), job_name, completion_window, poll_interval, do_parse, persist_context."
    ),
    response_model=RunResponse,
)
async def run_payload_file(
    file: UploadFile = File(...),
    job_name: Optional[str] = Form(default=None),
    completion_window: str = Form(default="24h"),
    poll_interval: int = Form(default=10),
    do_parse: bool = Form(default=True),
    persist_context: bool = Form(default=False),
) -> RunResponse:
    try:
        if not (file.filename or "").lower().endswith((".json", ".payload", ".txt")):
            # Aceita também .txt para facilitar, mas valida conteúdo abaixo
            pass
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="arquivo vazio")
        # tentativa de detecção de encoding comum (utf-8/utf-8-sig/utf-16)
        text = None
        for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "latin-1", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            # tentar chardet
            try:
                import chardet  # type: ignore
                det = chardet.detect(raw)
                enc = (det or {}).get("encoding") or "utf-8"
                text = raw.decode(enc, errors="replace")
            except Exception:
                # último recurso
                text = raw.decode("utf-8", errors="replace")
        import json as _json
        def _try_parse(s: str):
            try:
                return _json.loads(s)
            except Exception:
                return None
        # normalizar caracteres de aspas "inteligentes" e remover controles
        def _normalize_chars(s: str) -> str:
            s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u201e", '"').replace("\u201f", '"')
            s = s.replace("\u2018", "'").replace("\u2019", "'")
            # remover controles exceto \t, \n, \r
            s = "".join(ch for ch in s if ch >= " " or ch in "\t\n\r")
            return s
        text = _normalize_chars(text)
        payload = _try_parse(text)
        if payload is None:
            # tentar com BOM removido
            if text.startswith("\ufeff"):
                payload = _try_parse(text.lstrip("\ufeff"))
        if payload is None:
            # tentar json5 se instalado
            try:
                import json5  # type: ignore
                payload = json5.loads(text)
            except Exception:
                payload = None
        if payload is None:
            # sanitização leve: remove comentários /* */ e //, linhas iniciadas com #, e vírgulas finais antes de }]
            import re as _re
            s = _re.sub(r"/\*.*?\*/", "", text, flags=_re.S)
            s = _re.sub(r"(^|\s)//.*$", "", s, flags=_re.M)
            s = _re.sub(r"^\s*#.*$", "", s, flags=_re.M)
            s = _re.sub(r",\s*([}\]])", r"\1", s)
            # remover asteriscos fora de strings (padrões vistos em amostras)
            def _drop_unquoted(st: str, drop_chars: str = "*") -> str:
                res = []
                in_str = False
                esc = False
                for ch in st:
                    if in_str:
                        if esc:
                            res.append(ch)
                            esc = False
                        else:
                            if ch == "\\":
                                res.append(ch)
                                esc = True
                            elif ch == '"':
                                res.append(ch)
                                in_str = False
                            else:
                                res.append(ch)
                    else:
                        if ch == '"':
                            res.append(ch)
                            in_str = True
                        else:
                            if ch in drop_chars:
                                continue
                            res.append(ch)
                return "".join(res)
            s = _drop_unquoted(s)
            payload = _try_parse(s)
            if payload is None:
                # tentar extrair primeiro objeto/array balanceado
                def _extract_first_json_block(txt: str) -> list[str]:
                    blocks: list[str] = []
                    for opener, closer in (("{", "}"), ("[", "]")):
                        i = txt.find(opener)
                        while i != -1:
                            depth = 0
                            in_str = False
                            esc = False
                            for j in range(i, len(txt)):
                                ch = txt[j]
                                if in_str:
                                    if esc:
                                        esc = False
                                    else:
                                        if ch == "\\":
                                            esc = True
                                        elif ch == '"':
                                            in_str = False
                                else:
                                    if ch == '"':
                                        in_str = True
                                    elif ch == opener:
                                        depth += 1
                                    elif ch == closer:
                                        depth -= 1
                                        if depth == 0:
                                            blocks.append(txt[i:j+1])
                                            break
                            i = txt.find(opener, i + 1)
                    return blocks
                candidates = _extract_first_json_block(s)
                # tentar json5 e json padrão em cada bloco
                for cand in candidates:
                    try:
                        import json5  # type: ignore
                        payload = json5.loads(cand)
                        break
                    except Exception:
                        pass
                    obj = _try_parse(cand)
                    if obj is not None:
                        payload = obj
                        break
        if payload is None:
            raise HTTPException(status_code=400, detail="conteúdo inválido: não é JSON")

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

        run_req = RunRequest(
            input_path=str(jsonl_path),
            job_name=job_name,
            completion_window=completion_window,
            poll_interval=poll_interval,
            do_parse=do_parse,
        )
        return run(run_req)
    except HTTPException:
        raise
    except Exception as e:
        raise as_http_error(e)
