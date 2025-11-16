import json
import sys

from ..utils.files import ensure_output_dir


def parse(batch_id: str) -> None:
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
            content = (
                choices[0]["message"]["content"] if choices and "message" in choices[0] else "(Sem conteúdo)"
            )

            safe_id = (
                cid.replace("/", "__")
                .replace("\\", "__")
                .replace(" ", "_")
                .replace(":", "_")
                .replace("|", "_")
            )

            if "m3type_business" in cid:
                fname = f"{safe_id}.business.md"
            elif "m3type_tech_resume" in cid:
                fname = f"{safe_id}.tech.md"
            else:
                fname = f"{safe_id}.md"

            (docs_dir / fname).write_text(content, encoding="utf-8")
            count += 1

    print(f"Arquivos gerados: {count} (pasta {docs_dir})")
