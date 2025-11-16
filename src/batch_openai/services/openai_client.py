import sys

from ..config import require_env

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: pacote 'openai' não instalado. Execute 'pip install -r requirements.txt'.", file=sys.stderr)
    raise


def get_client() -> "OpenAI":
    """Cria e retorna um cliente OpenAI após validar a OPENAI_API_KEY."""
    # Valida que a variável está definida (mensagem amigável se não estiver)
    require_env("OPENAI_API_KEY")
    return OpenAI()
