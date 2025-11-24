'Estrutura Enxuta
-----------------

```
src/batch_openai/
	api.py                # App FastAPI
	web/
		routers/
			batches.py        # Endpoints de batch
			preview.py        # Endpoint único de preview completo
		schemas/
			batches.py        # Schemas ativos (submit, status, wait, download, run-payload-file)
			preview.py        # PreviewItem / PreviewFullResponse
		errors.py           # Mapeamento exceções → HTTP
	services/
		openai_client.py    # Cliente OpenAI
		batch_service.py    # Lógica submit/wait/download
		preview_service.py  # Execução direta para preview
	parsers/
		output_parser.py    # Parser v1 (doc|v1|...)
	tools/
		input_builder.py    # Builder a partir de payload SADA (somente modo --payload)
	utils/
		files.py            # Helpers de filesystem
	prompts/              # Templates de tópicos (resumo, fluxo_execucao, regras_negocio, diagram_activity, diagram_sequence)
```

Requisitos
----------

- Python 3.10+
- Dependências em `requirements.txt`:
	- openai
	- python-dotenv
	- tqdm (opcional)
	- fastapi
	- uvicorn[standard]
	- python-multipart (para upload via multipart/form-data)

Instalação
----------

1. Crie um virtualenv (opcional mas recomendado) e instale os requisitos:

```
pip install -r requirements.txt
```

2. Crie um arquivo `.env` na raiz com sua chave:

```
OPENAI_API_KEY=sk-seu-token-aqui
```

Como usar
---------

API Web (FastAPI)
-----------------

1) Instale dependências e configure `OPENAI_API_KEY` (via `.env` na raiz):

```
pip install -r requirements.txt
echo OPENAI_API_KEY=sk-seu-token-aqui > .env
```

2) Suba o servidor (PowerShell):
uvicorn batch_openai.api:app --host 0.0.0.0 --port 8000 --reload
```
$env:PYTHONPATH="src"
python -m uvicorn batch_openai.api:app --reload --host 0.0.0.0 --port 8000
```

3) Exemplos rápidos (PowerShell)

- Upload + fluxo completo (recomendado para teste):
```
curl.exe -X POST "http://localhost:8000/batches/run-file" -H "Accept: application/json" -F "file=@inputs/sample_input.jsonl" -F "job_name=demo" -F "completion_window=24h" -F "poll_interval=5" -F "do_parse=true"
```
- Pipeline com arquivo já no disco (sem upload):
```
$body = @{ input_path = "inputs/sample_input.jsonl"; job_name = "demo"; completion_window = "24h"; poll_interval = 5; do_parse = $true } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/batches/run" -Method Post -ContentType "application/json" -Body $body
```

Nota PowerShell: use `curl.exe` (não o alias `curl`) para enviar `-H`/`-F` sem erro.

Endpoints Ativos
----------------

- `POST /batches` — Criar batch (submit)
- `GET /batches/{batch_id}/status` — Consultar status
- `POST /batches/{batch_id}/wait` — Aguardar conclusão
- `POST /batches/{batch_id}/download` — Baixar `output.jsonl` / `errors.jsonl`
- `POST /batches/run-payload-file` — Upload de payload JSON → gerar .jsonl → submit → wait → download → parse
- `POST /preview/payload-file/full` — Preview completo (sem fila Batch) via upload de payload JSON (gera output.jsonl sintético + parse)

Todos os endpoints acima estão documentados em `/docs` (Swagger UI).

Observações
-----------
- Swagger UI: http://localhost:8000/docs | ReDoc: http://localhost:8000/redoc
- Artefatos são gravados em `outputs/<batch_id>/`.

Formato do JSONL (input)
------------------------
Cada linha segue o formato:

```json
{
	"custom_id": "doc|v1|proc=<proc>|topic=<topic>|seg=<n>|hash=<h8>|lang=pt-BR|code=<lang>",
	"method": "POST",
	"url": "/v1/chat/completions",
	"body": {
		"model": "gpt-5",
		"messages": [ {"role":"system","content":"..."}, {"role":"user","content":"..."} ],
		"max_completion_tokens": 120
	}
}
```

Observação: Batch API recente exige `max_completion_tokens` (não `max_tokens`).

Fluxo Payload → Batch
---------------------
Use `POST /batches/run-payload-file` com um payload JSON (formato SADA) para gerar o `.jsonl`, submeter, aguardar e parsear automaticamente.

Artefatos finais: `outputs/<batch_id>/output.jsonl`, `docs/<proc>/<topic>/seg-XXX.(md|puml)` e `final.md` por processo.

Preview Completo (único endpoint)
---------------------------------
Para validar saída e parse sem fila Batch, use:

```
curl -X POST http://localhost:8000/preview/payload-file/full \
  -H "Accept: application/json" \
  -F "file=@payloadSADA.json" \
  -F "do_parse=true"
```

Parâmetros opcionais:
- `max_tokens_override=NN` ou JSON por tópico.
- `topics=...` lista separada por vírgulas (default: cinco tópicos padrão).

Custom ID v1
------------
Formato: `doc|v1|proc=<proc>|topic=<topic>|seg=<n>|hash=<h8>|lang=<lang>|code=<code_language>`.
Usado para:
- Nome de arquivo por tópico/segmento.
- Merge automático em `final.md`.
- Correlação input/output.

Exemplo extra
-------------
Se preferir não fazer upload em toda chamada, reutilize o mesmo `.jsonl` local mudando apenas `job_name`.

Notas da API
------------
- Saídas gravadas em `outputs/<batch_id>/`.
- `download` retorna 409 se o batch ainda não estiver `completed`.
- Modelos estritos (ex.: `gpt-5`, `openai_o4-mini`) não aceitam `temperature/top_p/seed`; sanitização automática aplicada.

Troubleshooting
---------------
- 400 "Invalid file format for Batch API. Must be .jsonl": o arquivo deve ter extensão `.jsonl` e conter uma linha JSON válida por linha (sem vírgulas extras, sem arrays). O upload já preserva `.jsonl`.
- 400 "Unsupported parameter: 'max_tokens' ...": atualize suas linhas para usar `max_completion_tokens` em vez de `max_tokens`.
- 401/403: verifique `OPENAI_API_KEY` no `.env`.
- 409 no download: chame `wait` primeiro (ou use `run`/`run-file`).
- 404 ao parsear: verifique se `outputs/<batch_id>/output.jsonl` existe (faça `download`).
- PowerShell: use `curl.exe` em vez do alias `curl` para `-H`/`-F`.

Limpeza e Artefatos Gerados
---------------------------

- Artefatos gerados (podem ser removidos a qualquer momento, serão recriados):
	- `outputs/` (resultados por `batch_id`)
	- `inputs/by_process/` (JSONL por processo e context packs por tópico quando `persist_context=true`)
	- `**/__pycache__/` (caches do Python)

- Mantenha versionado (essencial):
	- `src/**`, `prompts/**`, `requirements.txt`, `README.md`, `.env.example`, `.gitignore`

- Script de limpeza rápida:
	```bash
	bash scripts/clean.sh
	```

Observações finais
------------------
- Artefatos: `batch.json`, `output.jsonl`, `errors.jsonl`, `docs/` por processo.
- Tópicos suportados: `resumo`, `fluxo_execucao`, `regras_negocio`, `diagram_activity`, `diagram_sequence`.
- Tópicos antigos (`riscos`, `arch-context`) e formatos legacy foram removidos na refatoração.
