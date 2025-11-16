Estrutura
---------

```
src/batch_openai/
	cli.py                  # CLI e orquestração de comandos
	main.py                 # entrypoint (importa e chama cli.main)
	config.py               # carregamento do .env e helpers de env
	utils/
		files.py              # utilidades de filesystem
	services/
		openai_client.py      # criação do cliente OpenAI
		batch_service.py      # submit, wait, download
	parsers/
		output_parser.py      # parse do output.jsonl -> arquivos .md
```

Requisitos
----------

- Python 3.10+
- Dependências em `requirements.txt`:
	- openai
	- python-dotenv
	- tqdm (opcional)

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

Execute com Python:

```
$env:PYTHONPATH="src"
python -m batch_openai.main run inputs\sample_input.jsonl --parse

python -m batch_openai.main submit inputs/sample_input.jsonl
python -m batch_openai.main wait <batch_id>
python -m batch_openai.main download <batch_id>
python -m batch_openai.main status <batch_id>
python -m batch_openai.main status <batch_id> --json  # imprime JSON completo
python -m batch_openai.main parse <batch_id>
python -m batch_openai.main run inputs/sample_input.jsonl --parse
```

Notas
-----

- Os artefatos de cada batch são gravados em `outputs/<batch_id>/` (batch.json, input.jsonl, output.jsonl, errors.jsonl e pasta docs/ quando há parse).
- A camada de serviços não executa parsing e nem lida com argparse; cada camada tem uma responsabilidade clara.
