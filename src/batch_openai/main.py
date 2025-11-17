import sys


def _disabled() -> None:
    print("CLI desativado. Suba a API: python -m uvicorn batch_openai.api:app", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    _disabled()
