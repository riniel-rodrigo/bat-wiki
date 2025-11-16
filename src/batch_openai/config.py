import os
import sys

try:
    from dotenv import load_dotenv
except ImportError:  # fallback silencioso se python-dotenv não estiver instalado
    def load_dotenv(*args, **kwargs):
        return False

# Carrega variáveis do .env (se existir)
load_dotenv()

def require_env(name: str) -> str:
    """Obtém uma variável de ambiente ou encerra com erro amigável."""
    value = os.getenv(name)
    if not value:
        print(
            f"ERROR: variável de ambiente {name} não definida. Crie um .env com {name}=...",
            file=sys.stderr,
        )
        sys.exit(1)
    return value
