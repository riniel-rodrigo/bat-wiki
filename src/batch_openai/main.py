import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):  # fallback silencioso se python-dotenv não estiver instalado
        return False

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: pacote 'openai' não instalado. Execute 'pip install -r requirements.txt'.", file=sys.stderr)
    sys.exit(1)

load_dotenv()

TERMINAL_STATES = {"completed", "failed", "cancelled", "expired"}

def get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: variável de ambiente OPENAI_API_KEY não definida. Crie um .env com OPENAI_API_KEY=...", file=sys.stderr)
        sys.exit(1)
    return OpenAI()
 
def ensure_output_dir(batch_id: str) -> Path:
    out_dir = Path("outputs") / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir

def safe_copy_input(input_path: Path, out_dir: Path):
    dst = out_dir / "input.jsonl"
    if input_path.resolve() != dst.resolve():
        dst.write_bytes(input_path.read_bytes())

def submit(input_path: str, job_name: Optional[str], completion_window: str) -> str:
    p = Path(input_path)
    if not p.exists():
        print(f"ERROR: arquivo de entrada não encontrado: {input_path}", file=sys.stderr)
        sys.exit(1)

    # obtem cliente openai
    client = get_client()

    # abre o arquivo de entrada e o envia para a API
    with p.open("rb") as f:
        file_resp = client.files.create(file=f, purpose="batch")
 
    # metadata opcional; se job_name foi fornecido, adiciona ao metadata
    metadata = {}
    if job_name:
        metadata["job_name"] = job_name

    # cria o batch chamando client.batches.create(...) com os parâmetros necessarios
    batch = client.batches.create(
        input_file_id=file_resp.id,
        endpoint="/v1/chat/completions",
        completion_window=completion_window,
        metadata=metadata or None,
    )

    batch_id = batch.id

    # Garante/cria o diretório outputs/<batch_id> para armazenar artefatos (batch.json, input copy, etc).
    out_dir = ensure_output_dir(batch_id)

    # Serialização do objeto batch
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
    # Escreve o batch_data serializado em outputs/<batch_id>/batch.json
    (out_dir / "batch.json").write_text(json.dumps(batch_data, indent=2, ensure_ascii=False))
    safe_copy_input(p, out_dir)
    print(f"Batch criado. batch_id={batch_id}")
    return batch_id

def wait(batch_id: str, poll_interval: int):
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

def download(batch_id: str):
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

def parse(batch_id: str):
    out_dir = ensure_output_dir(batch_id)
    output_path = out_dir / "output.jsonl"
    if not output_path.exists():
        print(f"ERRO: {output_path} não existe.", file=sys.stderr)
        sys.exit(3)

    docs_dir = out_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    with output_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print(f"Linha inválida ignorada: {line[:120]}", file=sys.stderr)
                continue

            cid = obj.get("custom_id", "sem_custom_id")
            resp = obj.get("response", {})
            body = resp.get("body", {})
            choices = body.get("choices", [])
            content = choices[0]["message"]["content"] if choices and "message" in choices[0] else "(Sem conteúdo)"

            safe_id = (cid.replace("/", "__")
                          .replace("\\", "__")
                          .replace(" ", "_")
                          .replace(":", "_")
                          .replace("|", "_"))

            if "m3type_business" in cid:
                fname = f"{safe_id}.business.md"
            elif "m3type_tech_resume" in cid:
                fname = f"{safe_id}.tech.md"
            else:
                fname = f"{safe_id}.md"

            (docs_dir / fname).write_text(content, encoding="utf-8")
            count += 1

    print(f"Arquivos gerados: {count} (pasta {docs_dir})")

def run(input_path: str, job_name: Optional[str], completion_window: str, poll_interval: int, do_parse: bool):
    batch_id = submit(input_path, job_name, completion_window)
    wait(batch_id, poll_interval=poll_interval)
    download(batch_id)
    if do_parse:
        parse(batch_id)

def build_parser():
    parser = argparse.ArgumentParser(prog="batch_openai", description="Batch API (OpenAI)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_submit = sub.add_parser("submit")
    p_submit.add_argument("input_path")
    p_submit.add_argument("--job-name", default=None)
    p_submit.add_argument("--completion-window", default="24h")
    p_submit.set_defaults(func=lambda a: print(submit(a.input_path, a.job_name, a.completion_window)))

    p_wait = sub.add_parser("wait")
    p_wait.add_argument("batch_id")
    p_wait.add_argument("--poll-interval", type=int, default=10)
    p_wait.set_defaults(func=lambda a: wait(a.batch_id, a.poll_interval))

    p_download = sub.add_parser("download")
    p_download.add_argument("batch_id")
    p_download.set_defaults(func=lambda a: download(a.batch_id))

    p_parse = sub.add_parser("parse")
    p_parse.add_argument("batch_id")
    p_parse.set_defaults(func=lambda a: parse(a.batch_id))

    p_run = sub.add_parser("run")
    p_run.add_argument("input_path")
    p_run.add_argument("--job-name", default=None)
    p_run.add_argument("--completion-window", default="24h")
    p_run.add_argument("--poll-interval", type=int, default=10)
    p_run.add_argument("--parse", action="store_true")
    p_run.set_defaults(func=lambda a: run(a.input_path, a.job_name, a.completion_window, a.poll_interval, a.parse))

    return parser

def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()