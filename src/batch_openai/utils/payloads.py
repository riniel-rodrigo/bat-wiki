from __future__ import annotations

from typing import Any
import json as _json
import re as _re

_PREFERRED_ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "latin-1",
    "cp1252",
)


def _decode_bytes(raw: bytes) -> str:
    for enc in _PREFERRED_ENCODINGS:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    # fallback: tentar chardet se disponível
    try:
        import chardet  # type: ignore

        det = chardet.detect(raw)
        enc = (det or {}).get("encoding") or "utf-8"
        return raw.decode(enc, errors="replace")
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _normalize_chars(text: str) -> str:
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u201e", '"').replace("\u201f", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    # remover controles exceto \t, \n, \r
    return "".join(ch for ch in text if ch >= " " or ch in "\t\n\r")


def _sanitize_json_like(text: str) -> str:
    s = _re.sub(r"/\*.*?\*/", "", text, flags=_re.S)
    s = _re.sub(r"(^|\s)//.*$", "", s, flags=_re.M)
    s = _re.sub(r"^\s*#.*$", "", s, flags=_re.M)
    s = _re.sub(r",\s*([}\]])", r"\1", s)

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

    return _drop_unquoted(s)


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
                            blocks.append(txt[i : j + 1])
                            break
            i = txt.find(opener, i + 1)
    return blocks


def _json_loads_loose(text: str) -> Any | None:
    try:
        return _json.loads(text)
    except Exception:
        pass
    try:
        import json5  # type: ignore

        return json5.loads(text)
    except Exception:
        return None


def decode_payload_bytes(raw: bytes) -> Any:
    """Decodifica bytes enviados via upload para um objeto JSON tolerante."""
    if not raw:
        raise ValueError("arquivo vazio")

    text = _normalize_chars(_decode_bytes(raw))
    payload = _json_loads_loose(text)
    if payload is None and text.startswith("\ufeff"):
        payload = _json_loads_loose(text.lstrip("\ufeff"))
    if payload is None:
        sanitized = _sanitize_json_like(text)
        payload = _json_loads_loose(sanitized)
    if payload is None:
        for block in _extract_first_json_block(text):
            payload = _json_loads_loose(block)
            if payload is not None:
                break
    if payload is None:
        raise ValueError("conteúdo inválido: não é JSON")
    return payload