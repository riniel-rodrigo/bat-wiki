import json
import sys
from typing import Optional, Iterable, Dict, Any

from ..utils.files import ensure_output_dir


def _safe_id(cid: str) -> str:
    return (
        cid.replace("/", "__")
        .replace("\\", "__")
        .replace(" ", "_")
        .replace(":", "_")
        .replace("|", "_")
    )


def _extract_meta_from_custom_id(custom_id: str) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"custom_id": custom_id}
    # tipo
    if "m3type_business" in custom_id:
        meta["type"] = "business"
    elif "m3type_tech_resume" in custom_id:
        meta["type"] = "tech_resume"
    else:
        meta["type"] = "unknown"

    # tentativa simples de extrair class/method do trecho entre m3id_ e _m3type
    try:
        start = custom_id.index("m3id_") + len("m3id_")
        end = custom_id.index("_m3type", start)
        core = custom_id[start:end]
        if "." in core:
            cls, method = core.rsplit(".", 1)
            meta["class_path"] = cls
            meta["method"] = method
        else:
            meta["class_path"] = core
            meta["method"] = None
    except ValueError:
        meta["class_path"] = None
        meta["method"] = None

    return meta


def parse(batch_id: str, *, force: bool = False, only: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """
    Converte output.jsonl em arquivos Markdown em outputs/<batch_id>/docs.

    - force: quando False, não reescreve arquivos já existentes (idempotente).
    - only: iterável de custom_ids a processar; quando None, processa todos.

    Retorna resumo com contagens e caminho da pasta.
    """
    out_dir = ensure_output_dir(batch_id)
    output_path = out_dir / "output.jsonl"
    if not output_path.exists():
        print(f"ERRO: {output_path} não existe.", file=sys.stderr)
        sys.exit(3)

    docs_dir = out_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    selected: Optional[set[str]] = set(only) if only else None
    processed = 0
    skipped = 0
    items_index = []

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
            if selected is not None and cid not in selected:
                continue

            resp = obj.get("response", {})
            body = resp.get("body", {})
            choices = body.get("choices", [])
            content = (
                choices[0]["message"]["content"] if choices and "message" in choices[0] else "(Sem conteúdo)"
            )

            safe_id = _safe_id(cid)

            if "m3type_business" in cid:
                fname = f"{safe_id}.business.md"
            elif "m3type_tech_resume" in cid:
                fname = f"{safe_id}.tech.md"
            else:
                fname = f"{safe_id}.md"

            target = docs_dir / fname

            if target.exists() and not force:
                skipped += 1
                items_index.append({
                    "custom_id": cid,
                    "file": str(target),
                    "status": "skipped",
                })
                continue

            # Não escrever front matter no Markdown final.
            # Metadados continuam disponíveis em index.json (abaixo) e via nome do arquivo/custom_id.
            target.write_text(content, encoding="utf-8")
            processed += 1
            items_index.append({
                "custom_id": cid,
                "file": str(target),
                "status": "ok",
            })

    index = {
        "batch_id": batch_id,
        "docs_dir": str(docs_dir),
        "processed": processed,
        "skipped": skipped,
        "items": items_index,
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Arquivos gerados: {processed} (pasta {docs_dir}) | pulados: {skipped}")
    return index
