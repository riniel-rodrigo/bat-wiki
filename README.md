'Estrutura
---------

```
src/batch_openai/
	api.py                  # app FastAPI (faz include dos routers)
	web/
		routers/
			batches.py          # rotas HTTP (batches)
		schemas/
			batches.py          # modelos Pydantic (requests/responses)
		errors.py             # mapeamento central de exceções → HTTP
	config.py               # carregamento do .env e helpers de env
	services/
		openai_client.py      # criação do cliente OpenAI
		batch_service.py      # submit, wait, download (camada de serviço)
	parsers/
		output_parser.py      # parse do output.jsonl → arquivos .md
	utils/
		files.py              # utilidades de filesystem
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

Sumário de Endpoints (Swagger)
------------------------------

- `POST /batches` — Criar batch (submit):
	- Corpo: `input_path`, `job_name` (opcional), `completion_window` (ex. `24h`).
	- Retorna: `batch_id`, `output_dir`.

- `GET /batches/{batch_id}/status` — Consultar status atual.

- `POST /batches/{batch_id}/wait` — Aguardar conclusão:
	- Corpo: `poll_interval` (opcional). Persiste `outputs/<batch_id>/batch.json`.

- `POST /batches/{batch_id}/download` — Baixar resultados:
	- Pré-condição: batch em `completed` (senão 409). Salva `output.jsonl` e `errors.jsonl` (quando houver).

- `POST /batches/{batch_id}/parse` — Gerar documentos a partir do output:
	- Corpo (opcional): `{ "force": false, "only": ["<custom_id>", ...] }`.
	- Retorna: `docs_dir`, `processed`, `skipped`, `index_file`.

- `POST /batches/run` — Fluxo completo com `input_path`.

- `POST /batches/run-file` — Upload + fluxo completo:
	- Multipart: `file` (.jsonl), `job_name`, `completion_window`, `poll_interval`, `do_parse`.

Observações
-----------
- Swagger UI: http://localhost:8000/docs | ReDoc: http://localhost:8000/redoc
- Artefatos são gravados em `outputs/<batch_id>/`.

Formato do JSONL (input)
------------------------
Cada linha deve ser um objeto JSON com os campos esperados pelo Batch API. Exemplo mínimo para chat completions:

```json
{"custom_id":"MinhaClasse.meuMetodo.m3type_business","method":"POST","url":"/v1/chat/completions","body":{"model":"gpt-4o-mini","messages":[{"role":"system","content":"Você é um assistente útil."},{"role":"user","content":"Explique X."}]}}
```

- `custom_id`: identificador único por item (usado no parser e idempotência)
- `method`: "POST"
- `url`: "/v1/chat/completions"
- `body`: payload compatível com o endpoint escolhido

Novo fluxo: Payload → JSONL → Batch
-----------------------------------
Gere entradas a partir de um payload (ponto de entrada único) e rode o batch:

```
# 1) Gerar .jsonl a partir de um payload
python -m batch_openai.tools.input_builder --payload C:\\Users\\Meta3\\Downloads\\payloadSADA.json \
	--out inputs\\payload_sada.jsonl --prompts prompts --persist-context inputs\\compiled

# 2) Submeter e orquestrar (submit→wait→download→parse)
curl.exe -X POST "http://localhost:8000/batches/run" -H "Content-Type: application/json" \
	-d '{"input_path":"inputs/payload_sada.jsonl","job_name":"sada-docs"}'
```

Saídas em `outputs/<batch_id>/docs/<proc>/<topic>/seg-XXX.(md|puml)` e `final.md` por processo.

Contexto e idempotência via custom_id
-------------------------------------

- Cada item no JSONL possui `custom_id`, que carrega contexto (classe/método e tipo como `m3type_*`).
- Benefícios:
	- Idempotência: evita duplicar saídas; o parser pode pular arquivos existentes (`force=false`).
	- Reprocessamento seletivo: processe apenas alguns `custom_id` (`only=[...]`).
	- Tracking: correlação input → output → arquivo `.md` no `docs/` através do `custom_id`.
	- Agrupamento: geração por tipo (ex.: `business`, `tech_resume`).

Parser e index
--------------

- Arquivos `.md` gerados em `outputs/<batch_id>/docs/` usam o `custom_id` sanetizado no nome e preservam o tipo (`.business.md`, `.tech.md`, ou `.md`).
- Cada arquivo contém front-matter com: `custom_id`, `batch_id`, `type`, `class_path`, `method`.
- É gerado `outputs/<batch_id>/index.json` com um resumo:
	- `batch_id`, `docs_dir`, `processed`, `skipped`, e `items` (lista de `{custom_id, file, status}`).

Exemplo extra
-------------
Se preferir não fazer upload em toda chamada, reutilize o mesmo `.jsonl` local mudando apenas `job_name`.

Notas da API
------------
- Saídas são gravadas em `outputs/<batch_id>/`.
- Endpoints retornam erros HTTP amigáveis quando o serviço interno sinaliza falhas.
- `download` retorna 409 se o batch ainda não estiver `completed`.

Troubleshooting
---------------
- 400 "Invalid file format for Batch API. Must be .jsonl": o arquivo deve ter extensão `.jsonl` e conter uma linha JSON válida por linha (sem vírgulas extras, sem arrays). O upload já preserva `.jsonl`.
- 401/403: verifique `OPENAI_API_KEY` no `.env`.
- 409 no download: chame `wait` primeiro (ou use `run`/`run-file`).
- 404 ao parsear: verifique se `outputs/<batch_id>/output.jsonl` existe (faça `download`).
- PowerShell: use `curl.exe` em vez do alias `curl` para `-H`/`-F`.

Limpeza e Artefatos Gerados
---------------------------

- Artefatos gerados (podem ser removidos a qualquer momento, serão recriados):
	- `outputs/` (resultados por `batch_id`)
	- `inputs/by_process/` (JSONL por processo e context packs por tópico quando `persist_context=true`)
	- `inputs/payloads/` (JSONL gerados a partir de payloads)
	- `inputs/compiled/` (layout antigo de context packs)
	- `**/__pycache__/` (caches do Python)

- Mantenha versionado (essencial):
	- `src/**`, `prompts/**`, `requirements.txt`, `README.md`, `.env.example`, `.gitignore`

- Script de limpeza rápida:
	```bash
	bash scripts/clean.sh
	```

Observações finais
------------------

- Os artefatos de cada batch são gravados em `outputs/<batch_id>/` (batch.json, input.jsonl, output.jsonl, errors.jsonl e pasta docs/ quando há parse).
- A camada de serviços não executa parsing e nem lida com argparse; cada camada tem uma responsabilidade clara.
