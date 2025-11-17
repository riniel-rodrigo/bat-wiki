import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Any

TEMPLATE_FILES = {
    "diagram_activity": "03-diagram-activity.md",
    "diagram_sequence": "03-diagram-sequence.md",
    "riscos": "04-risk-report.md",
    "arch-context": "05-arch-context.json.md",
    # Para resumo/fluxo_execucao/regras_negocio usaremos 02-doc-general.md com instruções adicionais
    "__general": "02-doc-general.md",
}

TOPIC_INSTRUCTIONS = {
    "resumo": "Gere SOMENTE a seção '# 📌 Resumo Geral (Visão Macro)'.",
    "fluxo_execucao": "Gere SOMENTE a seção '## Fluxo de Execução Principal' como lista ordenada.",
    "regras_negocio": "Gere SOMENTE a seção '## Regras de Negócio e Lógica Chave' como bullets claros.",
}

DEFAULT_MAX_TOKENS = {
    "resumo": 800,
    "fluxo_execucao": 600,
    "regras_negocio": 600,
    "diagram_activity": 700,
    "diagram_sequence": 700,
    "riscos": 900,
    "arch-context": 1200,
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fill_template(tpl: str, vars: Dict[str, str]) -> str:
    out = tpl
    for k, v in vars.items():
        out = out.replace(f"{{{{{k}}}}}", v)
    return out


def _sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]


def _build_custom_id(proc: str, topic: str, seg: int, h8: str, language: str, code_language: str) -> str:
    return f"doc|v1|proc={proc}|topic={topic}|seg={seg}|hash={h8}|lang={language}|code={code_language}"


def _build_message_content(topic: str, templates_dir: Path, variables: Dict[str, str]) -> str:
    if topic in ("diagram_activity", "diagram_sequence", "riscos", "arch-context"):
        tpl_file = templates_dir / TEMPLATE_FILES[topic]
        tpl = _read_text(tpl_file)
        return _fill_template(tpl, variables)
    # tópicos baseados no geral com instrução adicional
    tpl_file = templates_dir / TEMPLATE_FILES["__general"]
    tpl = _read_text(tpl_file)
    extra = TOPIC_INSTRUCTIONS.get(topic, "")
    if extra:
        tpl = extra + "\n\n" + tpl
    return _fill_template(tpl, variables)


def _build_entry(custom_id: str, model: str, content: str, max_tokens: int) -> Dict[str, Any]:
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
        },
    }


def build_inputs(config: Dict[str, Any], templates_dir: Path, out_path: Path) -> None:
    language = config.get("language", "pt-BR")
    model = config.get("model", "gpt-4o-mini")
    default_code_language = config.get("default_code_language", "unknown")

    lines: List[str] = []
    for p in config.get("processes", []):
        proc = p["proc"]
        code_language = p.get("code_language", default_code_language)
        title = p.get("title", proc)
        files = [Path(f) for f in p.get("files", [])]
        topics = p.get("topics", ["resumo", "fluxo_execucao", "regras_negocio", "diagram_activity"])  # default básico

        # concatenar conteúdo dos arquivos
        contents = []
        for fp in files:
            if not fp.exists():
                raise FileNotFoundError(f"Arquivo do processo '{proc}' não encontrado: {fp}")
            contents.append(_read_text(fp))
        content_str = "\n\n".join(contents)

        # variáveis comuns
        vars = {
            "language": language,
            "file_name": proc,
            "code_language": code_language,
            "content": content_str,
            "title": title,
            "processes": "",
            "rules": "",
            "context_md": "",
        }
        h8 = _sha8(proc + "\n" + content_str)

        for topic in topics:
            cid = _build_custom_id(proc, topic, 0, h8, language, code_language)
            msg_content = _build_message_content(topic, templates_dir, vars)
            max_tokens = DEFAULT_MAX_TOKENS.get(topic, 800)
            entry = _build_entry(cid, model, msg_content, max_tokens)
            lines.append(json.dumps(entry, ensure_ascii=False))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Gerador de inputs .jsonl para documentação modular em batch")
    parser.add_argument("--config", required=True, help="Caminho do arquivo JSON de processos")
    parser.add_argument("--out", required=True, help="Caminho de saída do .jsonl gerado")
    parser.add_argument("--prompts", default="prompts", help="Diretório dos templates de prompts")
    args = parser.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    templates_dir = Path(args.prompts)
    out_path = Path(args.out)

    build_inputs(cfg, templates_dir, out_path)
    print(f"Arquivo gerado: {out_path}")


if __name__ == "__main__":
    main()
