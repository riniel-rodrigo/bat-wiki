import json
import sys
from typing import Optional, Iterable, Dict, Any, List

from ..utils.files import ensure_output_dir
from pathlib import Path
from collections import defaultdict


def _extract_meta_from_custom_id(custom_id: str) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"custom_id": custom_id}
    # Formato canônico único: doc|v1|proc=...|topic=...|seg=...|hash=...|lang=...|code=...
    if custom_id.startswith("doc|v1|"):
        try:
            parts = custom_id.split("|")
            kvs = {}
            for p in parts[2:]:
                if "=" in p:
                    k, v = p.split("=", 1)
                    kvs[k] = v
            meta.update({
                "format": "v1",
                "proc": kvs.get("proc"),
                "topic": kvs.get("topic"),
                "seg": int(kvs.get("seg", "0")),
                "hash": kvs.get("hash"),
                "lang": kvs.get("lang"),
                "code": kvs.get("code"),
            })
        except Exception:
            meta["format"] = "unknown"
        return meta

    # Se não for v1, marcar como desconhecido (não processado)
    meta["format"] = "unknown"
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

    # Para montagem do final.md por processo
    proc_topic_segments: Dict[str, Dict[str, Dict[int, Path]]] = defaultdict(lambda: defaultdict(dict))

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

            meta = _extract_meta_from_custom_id(cid)

            # Novo formato: salvar em docs/<proc>/<topic>/seg-XXX.(md|puml)
            if meta.get("format") == "v1" and meta.get("proc") and meta.get("topic") is not None:
                proc = meta.get("proc") or "_proc"
                topic = meta.get("topic") or "_topic"
                seg = int(meta.get("seg") or 0)
                is_puml = topic in ("diagram_activity", "diagram_sequence")
                proc_dir = docs_dir / proc / topic
                proc_dir.mkdir(parents=True, exist_ok=True)
                ext = ".puml" if is_puml else ".md"
                target = proc_dir / f"seg-{seg:03d}{ext}"
                if target.exists() and not force:
                    skipped += 1
                    items_index.append({
                        "custom_id": cid,
                        "file": str(target),
                        "status": "skipped",
                        **{k: meta.get(k) for k in ("proc", "topic", "seg", "hash", "lang", "code")},
                    })
                    # registrar para merge do final.md mesmo se skipped
                    proc_topic_segments[proc][topic][seg] = target
                    continue

                target.write_text(content, encoding="utf-8")
                processed += 1
                items_index.append({
                    "custom_id": cid,
                    "file": str(target),
                    "status": "ok",
                    **{k: meta.get(k) for k in ("proc", "topic", "seg", "hash", "lang", "code")},
                })
                proc_topic_segments[proc][topic][seg] = target
                continue

            # Formatos desconhecidos são ignorados (legacy removido)
            skipped += 1
            items_index.append({
                "custom_id": cid,
                "file": None,
                "status": "ignored",
            })

    # Compilar final.md por processo (novo formato)
    for proc, topics in proc_topic_segments.items():
        proc_root = docs_dir / proc
        final_md = proc_root / "final.md"
        # coletar conteúdos disponíveis
        def _read_join(topic_name: str) -> Optional[str]:
            segs = topics.get(topic_name)
            if not segs:
                return None
            ordered = [segs[i] for i in sorted(segs.keys())]
            parts = []
            for p in ordered:
                try:
                    txt = Path(p).read_text(encoding="utf-8")
                    parts.append(txt)
                except Exception:
                    continue
            return "\n\n".join(parts) if parts else None

        resumo = _read_join("resumo")
        fluxo = _read_join("fluxo_execucao")
        regras = _read_join("regras_negocio")

        # Diagramas: apenas links/indicações para os .puml
        diag_lines: List[str] = []
        for tname, title in (("diagram_activity", "Diagrama de Atividades"), ("diagram_sequence", "Diagrama de Sequência")):
            segs = topics.get(tname)
            if segs:
                for i in sorted(segs.keys()):
                    rel = Path(proc_root.name) / tname / f"seg-{i:03d}.puml"
                    diag_lines.append(f"- {title}: {rel}")

        sections = []
        if resumo:
            sections.append("# 📌 Resumo Geral (Visão Macro)\n\n" + resumo.strip())
        if fluxo:
            sections.append("## Fluxo de Execução Principal\n\n" + fluxo.strip())
        if regras:
            sections.append("## Regras de Negócio e Lógica Chave\n\n" + regras.strip())
        if diag_lines:
            sections.append("## Diagramas\n\n" + "\n".join(diag_lines))

        if sections:
            final_md.write_text("\n\n".join(sections) + "\n", encoding="utf-8")

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
