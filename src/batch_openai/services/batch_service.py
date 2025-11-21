import json
import sys
import time
from pathlib import Path
from typing import Optional

from .openai_client import get_client
from ..utils.files import ensure_output_dir, safe_copy_input


TERMINAL_STATES = {"completed", "failed", "cancelled", "expired"}


def submit(input_path: str, job_name: Optional[str], completion_window: str, *, verbose: bool = True) -> str:
    p = Path(input_path)
    if not p.exists():
        print(f"ERROR: arquivo de entrada não encontrado: {input_path}", file=sys.stderr)
        sys.exit(1)
    if p.suffix.lower() != ".jsonl":
        print(
            f"ERROR: arquivo de entrada deve ter extensão .jsonl (recebido: {p.name}).",
            file=sys.stderr,
        )
        sys.exit(1)

    client = get_client()

    # Enviar o Path diretamente para preservar o nome do arquivo (.jsonl) no multipart
    file_resp = client.files.create(file=p, purpose="batch")

    metadata = {}
    if job_name:
        metadata["job_name"] = job_name

    batch = client.batches.create(
        input_file_id=file_resp.id,
        endpoint="/v1/chat/completions",
        completion_window=completion_window,
        metadata=metadata or None,
    )

    batch_id = batch.id
    out_dir = ensure_output_dir(batch_id)

    # Serialização resiliente
    try:
        batch_data = batch.model_dump()
    except Exception:
        try:
            batch_data = batch.dict()
        except Exception:
            try:
                batch_data = json.loads(batch.json())
            except Exception:
                batch_data = {"id": getattr(batch, "id", None), "status": getattr(batch, "status", None)}

    (out_dir / "batch.json").write_text(json.dumps(batch_data, indent=2, ensure_ascii=False))
    safe_copy_input(p, out_dir)
    if verbose:
        print(f"Batch criado. batch_id={batch_id}")
    return batch_id


def wait(batch_id: str, poll_interval: int) -> None:
    client = get_client()
    print(f"Aguardando batch {batch_id} terminar...")
    last_status = None
    try:
        while True:
            batch = client.batches.retrieve(batch_id)
            status = batch.status
            if status != last_status:
                print(f"status={status}")
                last_status = status
            if status in TERMINAL_STATES:
                print(f"Status final: {status}")
                out_dir = ensure_output_dir(batch_id)
                try:
                    batch_data = batch.model_dump()
                except Exception:
                    try:
                        batch_data = batch.dict()
                    except Exception:
                        try:
                            batch_data = json.loads(batch.json())
                        except Exception:
                            batch_data = {"id": getattr(batch, "id", None), "status": getattr(batch, "status", None)}
                (out_dir / "batch.json").write_text(json.dumps(batch_data, indent=2, ensure_ascii=False))
                break
            time.sleep(max(1, poll_interval))
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário durante o 'wait'.", file=sys.stderr)
        sys.exit(130)


def download(batch_id: str) -> None:
    out_dir = ensure_output_dir(batch_id)
    client = get_client()
    batch = client.batches.retrieve(batch_id)
    if batch.status != "completed":
        print(f"ERRO: batch {batch_id} não está 'completed' (atual: {batch.status}).", file=sys.stderr)
        sys.exit(2)
    if getattr(batch, "output_file_id", None):
        out = client.files.content(batch.output_file_id)
        (out_dir / "output.jsonl").write_text(out.text)
        print(f"Output salvo em: {out_dir / 'output.jsonl'}")

    if getattr(batch, "error_file_id", None):
        err = client.files.content(batch.error_file_id)
        (out_dir / "errors.jsonl").write_text(err.text)
        print(f"Errors salvo em: {out_dir / 'errors.jsonl'}")


def status(batch_id: str, json_output: bool = False) -> None:
    """Mostra o status atual do batch sem bloquear.

    - Se json_output=True, imprime o objeto completo do batch como JSON (pretty).
    - Caso contrário, imprime apenas a string de status.
    """
    client = get_client()
    try:
        batch = client.batches.retrieve(batch_id)
    except Exception as e:
        print(f"ERRO ao recuperar batch {batch_id}: {e}", file=sys.stderr)
        sys.exit(4)

    if json_output:
        try:
            data = batch.model_dump()
        except Exception:
            try:
                data = batch.dict()
            except Exception:
                try:
                    import json as _json

                    data = _json.loads(batch.json())
                except Exception:
                    data = {"id": getattr(batch, "id", None), "status": getattr(batch, "status", None)}
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(getattr(batch, "status", "desconhecido"))
