from __future__ import annotations

from typing import Dict, Any, List, Optional
from pathlib import Path

from .openai_client import get_client
from ..tools import input_builder


def build_preview_entries_from_payload(payload: Dict[str, Any], *, topics: Optional[List[str]] = None,
                                       max_tokens_override: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Gera lista de entradas (sem escrever .jsonl) para execução direta de preview.

    Reusa lógica do builder de payload, mas sem segmentação e sem persistência de contexto.
    """
    norm = input_builder.normalize_payload_sada(payload)
    ep_language = norm.get("ep_language") or "unknown"
    entry = norm.get("entry_point") or {}
    proc = entry.get("name") or "processo_desconhecido"
    content = entry.get("content") or ""
    deps = entry.get("deps") or []

    topics = topics or list(input_builder.DEFAULT_TOPICS)  # type: ignore
    templates_dir = Path("prompts")
    packs = input_builder.build_topic_packs(proc, content, deps, topics=topics)  # type: ignore

    base_vars = {
        "language": payload.get("language", "pt-BR"),
        "file_name": proc,
        "code_language": ep_language,
        "title": proc,
        "context_md": "",
    }

    entries: List[Dict[str, Any]] = []
    max_tokens_map = max_tokens_override or input_builder.DEFAULT_MAX_TOKENS  # type: ignore
    for topic in topics:
        pack = packs.get(topic, {"content": content, "methods": "", "rules": ""})
        vars = {**base_vars, **pack}
        effective = f"{proc}\n{topic}\n{vars.get('content','')}\n{vars.get('methods','')}\n{vars.get('rules','')}"
        h8 = input_builder._sha8(effective)  # type: ignore
        content_text = input_builder._build_message_content(topic, templates_dir, {  # type: ignore
            **vars,
            "content": vars.get("content", ""),
            "processes": vars.get("methods", ""),
            "rules": vars.get("rules", ""),
        })
        cid = input_builder._build_custom_id(proc, topic, 0, h8, base_vars["language"], ep_language)  # type: ignore
        entry = input_builder._build_entry(  # type: ignore
            cid,
            norm.get("model") or payload.get("model") or "gpt-5",
            content_text,
            max_tokens_map.get(topic, 600),
            seed=input_builder._sha_seed(h8),  # type: ignore
        )
        entries.append(entry)
    return entries


def run_preview(payload: Dict[str, Any], *, topics: Optional[List[str]] = None,
                max_tokens_override: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Executa cada entrada via chat completions normal e retorna lista de resultados.

    Retorna lista de dicts: {custom_id, output_text, usage?, request_body, error?}.
    """
    client = get_client()
    entries = build_preview_entries_from_payload(
        payload,
        topics=topics,
        max_tokens_override=max_tokens_override,
    )
    results: List[Dict[str, Any]] = []
    STRICT_SAMPLING_MODELS = {"gpt-5", "openai_o4-mini", "o4-mini"}

    def _sanitize(body: Dict[str, Any]) -> Dict[str, Any]:
        b = dict(body)
        model = b.get("model")
        if model in STRICT_SAMPLING_MODELS:
            # Esses modelos só aceitam defaults (sem temperature/top_p/seed customizado)
            b.pop("temperature", None)
            b.pop("top_p", None)
            b.pop("seed", None)
        return b

    for e in entries:
        original_body = e.get("body", {})
        body = _sanitize(original_body)
        try:
            resp = client.chat.completions.create(**body)
        except Exception as ex:
            msg = str(ex)
            # Retry heurístico: se erro de unsupported_value para sampling, remover e tentar 1 vez
            if any(tok in msg for tok in ("unsupported_value", "temperature", "top_p")) and (
                "temperature" in body or "top_p" in body or "seed" in body
            ):
                body_retry = dict(body)
                body_retry.pop("temperature", None)
                body_retry.pop("top_p", None)
                body_retry.pop("seed", None)
                try:
                    resp = client.chat.completions.create(**body_retry)
                    body = body_retry  # usar body efetivo
                except Exception as ex2:
                    results.append({
                        "custom_id": e.get("custom_id"),
                        "error": str(ex2),
                        "request_body": body_retry,
                    })
                    continue
            else:
                results.append({
                    "custom_id": e.get("custom_id"),
                    "error": msg,
                    "request_body": body,
                })
                continue

        # Sucesso
        content = None
        if hasattr(resp, "choices") and resp.choices:
            first = resp.choices[0]
            if hasattr(first, "message") and getattr(first.message, "content", None):
                content = first.message.content
        usage = getattr(resp, "usage", None)
        usage_data = None
        if usage is not None:
            usage_data = getattr(usage, "model_dump", lambda: usage)()
        results.append({
            "custom_id": e.get("custom_id"),
            "output_text": content,
            "usage": usage_data,
            "request_body": body,
        })
    return results
