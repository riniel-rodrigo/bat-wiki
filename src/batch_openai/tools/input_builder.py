import argparse
import hashlib
import json
import re
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

TEMPLATE_FILES = {
    "diagram_activity": "03-diagram-activity.md",
    "diagram_sequence": "03-diagram-sequence.md",
    "__general": "02-doc-general.md",
}

TOPIC_INSTRUCTIONS = {
    "resumo": "Gere SOMENTE a seção '# 📌 Resumo Geral (Visão Macro)'.",
    "fluxo_execucao": "Gere SOMENTE a seção '## Fluxo de Execução Principal' como lista ordenada.",
    "regras_negocio": "Gere SOMENTE a seção '## Regras de Negócio e Lógica Chave' como bullets claros.",
}

DEFAULT_TOPICS = [
    "resumo",
    "fluxo_execucao",
    "regras_negocio",
    "diagram_activity",
    "diagram_sequence",
]

DEFAULT_MAX_TOKENS = {
    "resumo": 80,
    "fluxo_execucao": 60,
    "regras_negocio": 60,
    "diagram_activity": 70,
    "diagram_sequence": 70,
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
    if topic in ("diagram_activity", "diagram_sequence"):
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


SYSTEM_PROMPT_DEFAULT = (
    "Siga estritamente o formato do tópico. Idioma pt-BR. "
    "Quando identificar lacunas, descreva-as de forma clara em vez de usar placeholders fixos. "
    "Não invente detalhes e não inclua texto fora do formato solicitado."
)


def _build_entry(custom_id: str, model: str, content: str, max_tokens: int, *, system_prompt: Optional[str] = None,
                 temperature: float = 0.2, top_p: float = 0.9, seed: Optional[int] = None) -> Dict[str, Any]:
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": ([{"role": "system", "content": system_prompt or SYSTEM_PROMPT_DEFAULT}] +
                         [{"role": "user", "content": content}]),
            # A API recente de batch para alguns modelos não aceita mais 'max_tokens';
            # usar 'max_completion_tokens' conforme mensagem de erro retornada.
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            **({"seed": seed} if seed is not None else {}),
        },
    }


def _sha_seed(h8: str) -> int:
    # derive a deterministic small int seed from an 8-hex hash
    return int(h8, 16) % 2_147_483_547


 # build_inputs removido na refatoração (escopo multi-processos legacy)


# -------- Payload adapter (SADA-like) --------

def _map_code_language(ep_language: str) -> str:
    mapping = {
        "dotnet": "csharp",
        ".net": "csharp",
        "c#": "csharp",
        "vb6": "vb",
        "vb": "vb",
        "java": "java",
        "python": "python",
        "sql": "sql",
    }
    key = (ep_language or "").strip().lower()
    return mapping.get(key, key or "unknown")


def _first_n_lines(text: str, n: int) -> str:
    return "\n".join(text.splitlines()[:n])


def _extract_control_skeleton(text: str, max_lines: int = 200) -> str:
    lines = []
    for ln in text.splitlines():
        if any(kw in ln for kw in ("if", "else", "for", "foreach", "while", "switch", "case", "return")):
            lines.append(ln)
        if len(lines) >= max_lines:
            break
    return "\n".join(lines[:max_lines])


def _extract_rules(text: str, max_rules: int = 20) -> str:
    # heurística simples: capturar linhas com if/validação/erro/modal
    patt = re.compile(r"\b(if|validate|valida|erro|error|throw|return)\b", re.IGNORECASE)
    rules = []
    for ln in text.splitlines():
        if patt.search(ln):
            rules.append(f"- {ln.strip()}")
        if len(rules) >= max_rules:
            break
    return "\n".join(rules)


def _top_dep_names(deps: List[Dict[str, Any]], top_n: int = 10) -> List[str]:
    scored: List[Tuple[int, str]] = []
    for d in deps or []:
        name = d.get("name") or ""
        node_lines = int(d.get("node_lines") or d.get("total_subtree_lines") or 0)
        scored.append((node_lines, name))
    scored.sort(reverse=True)
    return [n for _, n in scored[:top_n] if n]


def _aggregate_deps_content(deps: List[Dict[str, Any]], max_chars: int = 6000) -> str:
    parts: List[str] = []
    acc = 0
    for d in deps:
        nm = d.get("name") or "dep"
        body = d.get("content") or ""
        if not isinstance(body, str) or not body.strip():
            continue
        snippet = f"// DEP: {nm}\n" + body.strip() + "\n"
        if acc + len(snippet) > max_chars:
            break
        parts.append(snippet)
        acc += len(snippet)
    return "\n".join(parts)


def _extract_sequence_lines(text: str, max_lines: int = 180) -> str:
    patt = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*\s*\(")
    calls = []
    for ln in text.splitlines():
        if patt.search(ln):
            calls.append(ln.strip())
        if len(calls) >= max_lines:
            break
    return "\n".join(calls)


def build_topic_packs(proc: str, content: str, deps: List[Dict[str, Any]], *,
                      topics: Optional[List[str]] = None) -> Dict[str, Dict[str, str]]:
    topics = topics or list(DEFAULT_TOPICS)
    top_dep_list = _top_dep_names(deps, top_n=10)
    methods_txt = "\n".join(f"- {n}" for n in top_dep_list)
    rules_txt = _extract_rules(content, max_rules=20)
    deps_content_block = _aggregate_deps_content(deps)

    packs: Dict[str, Dict[str, str]] = {
        "resumo": {
            "content": _first_n_lines(content, 120) or content,
            "methods": "\n".join(f"- {n}" for n in top_dep_list[:5]),
            "rules": rules_txt,
        },
        "fluxo_execucao": {
            "content": _extract_control_skeleton(content, 200) or _first_n_lines(content, 200),
            "methods": methods_txt,
            "rules": rules_txt,
        },
        "regras_negocio": {
            "content": _first_n_lines(content, 200),
            "methods": "",
            "rules": rules_txt,
        },
        "diagram_activity": {
            "content": _extract_control_skeleton(content, 150) or _first_n_lines(content, 150),
            "methods": methods_txt,
            "rules": rules_txt,
        },
        "diagram_sequence": {
            "content": _extract_sequence_lines(content, 180) or _extract_sequence_lines(deps_content_block, 180),
            "methods": methods_txt,
            "rules": rules_txt,
        },
    }

    return {k: v for k, v in packs.items() if k in topics}


def build_inputs_from_payload(payload: Dict[str, Any], templates_dir: Path, out_path: Path, *, language: str = "pt-BR",
                              topics: Optional[List[str]] = None, persist_context: Optional[Path] = None,
                              max_tokens_override: Optional[Dict[str, int]] = None) -> None:
    """Gera .jsonl a partir de um payload (formato SADA-like), criando context packs por tópico.

    - persist_context: quando fornecido, salva os context packs em arquivos para auditoria.
    """
    model = payload.get("model") or os.getenv("DEFAULT_MODEL", "gpt-5")
    ep_language = _map_code_language(payload.get("ep_language", ""))
    entry = payload.get("entry_point") or {}
    proc = entry.get("name") or "processo_desconhecido"
    content = entry.get("content") or ""
    deps = entry.get("deps") or []

    topics = topics or list(DEFAULT_TOPICS)
    packs = build_topic_packs(proc, content, deps, topics=topics)

    # variáveis comuns
    base_vars = {
        "language": language,
        "file_name": proc,
        "code_language": ep_language,
        "title": proc,
        "context_md": "",
    }

    lines: List[str] = []
    for topic in topics:
        pack = packs.get(topic, {"content": content, "methods": "", "rules": ""})
        vars = {**base_vars, **pack}
        # custom hash por tópico baseado no conteúdo efetivo (concat chaves relevantes)
        effective = f"{proc}\n{topic}\n{vars.get('content','')}\n{vars.get('methods','')}\n{vars.get('rules','')}"
        h8 = _sha8(effective)

        # opcionalmente persistir packs
        if persist_context is not None:
            topic_dir = persist_context / proc / topic
            topic_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "content.md").write_text(vars.get("content", ""), encoding="utf-8")
            (topic_dir / "methods.txt").write_text(vars.get("methods", ""), encoding="utf-8")
            (topic_dir / "rules.txt").write_text(vars.get("rules", ""), encoding="utf-8")

        # chunking simples por tamanho de conteúdo do pack (caracteres)
        content_text = _build_message_content(topic, templates_dir, {
            **vars,
            "content": vars.get("content", ""),
            "processes": vars.get("methods", ""),
            "rules": vars.get("rules", ""),
        })

        # tamanho alvo aproximado
        max_chars = 6000  # pequeno/seguro para testes; pode ser configurável
        segments: List[str] = []
        if len(content_text) <= max_chars:
            segments = [content_text]
        else:
            # dividir em blocos respeitando quebras de linha
            buf = []
            acc = 0
            for line in content_text.splitlines(True):
                if acc + len(line) > max_chars and buf:
                    segments.append("".join(buf))
                    buf = []
                    acc = 0
                buf.append(line)
                acc += len(line)
            if buf:
                segments.append("".join(buf))

        max_tokens_map = max_tokens_override or DEFAULT_MAX_TOKENS
        for i, seg_txt in enumerate(segments):
            cid = _build_custom_id(proc, topic, i, h8, language, ep_language)
            entry = _build_entry(
                cid,
                model,
                seg_txt,
                max_tokens_map.get(topic, 600),
                seed=_sha_seed(h8),
            )
            lines.append(json.dumps(entry, ensure_ascii=False))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -------- Normalizador/adaptador de payload SADA --------

def _infer_language_from_filenames(files: List[str]) -> str:
    for fp in files:
        f = fp.lower()
        if f.endswith(".cs"):  # C#
            return "csharp"
        if f.endswith(".vb") or f.endswith(".bas"):
            return "vb"
        if f.endswith(".java"):
            return "java"
        if f.endswith(".py"):
            return "python"
        if f.endswith(".sql"):
            return "sql"
    return "unknown"


def normalize_payload_sada(payload_raw: Dict[str, Any]) -> Dict[str, Any]:
    """Converte o payload SADA (ou variantes) para o formato canônico esperado por build_inputs_from_payload.

    Formato canônico:
      {
        "model": str,
        "ep_language": str,
        "entry_point": {"name": str, "content": str, "deps": List[Dict]}
      }
    """
    # Se já estiver canônico, apenas retorne
    if isinstance(payload_raw.get("entry_point"), dict):
        return payload_raw

    pr = payload_raw

    # Nome do processo / entry point
    name_candidates = [
        pr.get("entryPoint"), pr.get("entry_point"), pr.get("process"), pr.get("processo"),
        pr.get("name"), pr.get("title"), pr.get("titulo"), pr.get("id")
    ]
    name = next((x for x in name_candidates if isinstance(x, str) and x.strip()), "processo_desconhecido")

    # Código/conteúdo-fonte
    content = None
    # Campos diretos comuns
    for key in ("source", "source_code", "code", "codigo", "conteudo", "body", "text"):
        v = pr.get(key)
        if isinstance(v, str) and v.strip():
            content = v
            break

    # Listas de fontes/arquivos
    files_collected: List[str] = []
    if content is None:
        # sources: [{path, content|code}]
        sources = pr.get("sources")
        if isinstance(sources, list):
            parts = []
            for it in sources:
                if not isinstance(it, dict):
                    continue
                path = it.get("path") or it.get("file") or it.get("name") or ""
                txt = it.get("content") or it.get("code") or ""
                if isinstance(path, str) and isinstance(txt, str) and txt.strip():
                    files_collected.append(path)
                    header = f"\n\n// FILE: {path}\n"
                    parts.append(header + txt)
            if parts:
                content = "\n".join(parts)

    if content is None:
        # files: [{path, content}] (ou lista de caminhos com outro campo de textos)
        files = pr.get("files")
        if isinstance(files, list):
            parts = []
            for it in files:
                if isinstance(it, dict):
                    path = it.get("path") or it.get("file") or it.get("name") or ""
                    txt = it.get("content") or it.get("code") or ""
                    if isinstance(path, str) and isinstance(txt, str) and txt.strip():
                        files_collected.append(path)
                        header = f"\n\n// FILE: {path}\n"
                        parts.append(header + txt)
                elif isinstance(it, str):
                    files_collected.append(it)
            if parts:
                content = "\n".join(parts)

    if content is None:
        content = ""

    # Dependências / deps
    deps: List[Dict[str, Any]] = []
    raw_deps = pr.get("deps") or pr.get("dependencies") or pr.get("dependencias") or pr.get("methods")
    if isinstance(raw_deps, list):
        for d in raw_deps:
            if isinstance(d, dict):
                name_d = d.get("name") or d.get("id") or d.get("method") or d.get("func")
                node_lines = d.get("node_lines") or d.get("total_lines") or d.get("total_subtree_lines")
                deps.append({"name": name_d, "node_lines": node_lines})
            elif isinstance(d, str):
                deps.append({"name": d, "node_lines": None})

    # callgraph / graph nós (opcional)
    cg = pr.get("callgraph") or pr.get("graph")
    if isinstance(cg, dict):
        nodes = cg.get("nodes") or []
        if isinstance(nodes, list):
            for n in nodes:
                if isinstance(n, dict):
                    nm = n.get("name") or n.get("id")
                    nl = n.get("node_lines") or n.get("total_lines") or n.get("total_subtree_lines")
                    deps.append({"name": nm, "node_lines": nl})

    # Linguagem
    lang_candidates = [
        pr.get("ep_language"), pr.get("code_language"), pr.get("language"), pr.get("lang"),
    ]
    ep_language = next((x for x in lang_candidates if isinstance(x, str) and x.strip()), None)
    if not ep_language and files_collected:
        ep_language = _infer_language_from_filenames(files_collected)
    ep_language = ep_language or "unknown"

    model = pr.get("model") or "gpt-5"

    return {
        "model": model,
        "ep_language": ep_language,
        "entry_point": {
            "name": name,
            "content": content,
            "deps": deps,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Gerador de inputs .jsonl para documentação modular em batch")
    # Removido suporte a --config (multi-processos)
    parser.add_argument("--payload", help="Caminho para payload JSON (ponto de entrada único)")
    parser.add_argument("--out", required=True, help="Caminho de saída do .jsonl gerado")
    parser.add_argument("--prompts", default="prompts", help="Diretório dos templates de prompts")
    parser.add_argument("--persist-context", help="Diretório para salvar context packs (opcional)")
    args = parser.parse_args()

    templates_dir = Path(args.prompts)
    out_path = Path(args.out)

    if not args.payload:
        raise SystemExit("É necessário informar --payload")
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    persist_dir = Path(args.persist_context) if args.persist_context else None
    build_inputs_from_payload(payload, templates_dir, out_path, persist_context=persist_dir)

    print(f"Arquivo gerado: {out_path}")


if __name__ == "__main__":
    main()
