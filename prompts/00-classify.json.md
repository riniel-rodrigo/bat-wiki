**Objetivo**
Classificar o arquivo/processo para roteamento do pipeline.

**Entrada**
- Nome do arquivo: `{{file_name}}`
- Linguagem de código: `{{code_language}}` (se desconhecida, inferir)
- Conteúdo:
```
{{content}}
```

**Saída (JSON estrito, apenas o objeto):**
```json
{
  "language": "string",
  "category": "sql|oo|script|frontend|unknown",
  "has_db": true,
  "has_endpoints": false,
  "is_procedure": false,
  "size_hint": {"lines": 0, "bytes": 0}
}
```

**Regras**
- Detecte linguagem por heurística (extensão, palavras-chave).
- `category`: OO (java/csharp), script (python/vb6), sql, frontend (js/ts com ui), unknown.
- `has_db`: true se houver consultas/ORM.
- `has_endpoints`: true se detectar controllers/routes.
- `is_procedure`: true se CREATE [PROCEDURE|FUNCTION].
- `size_hint`: estime linhas/bytes do `{{content}}`.
