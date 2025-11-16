from pathlib import Path


def ensure_output_dir(batch_id: str) -> Path:
    """Garante/cria o diretório outputs/<batch_id> e o retorna."""
    out_dir = Path("outputs") / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def safe_copy_input(input_path: Path, out_dir: Path) -> None:
    """Copia o arquivo de entrada para o diretório de saída, se ainda não for o mesmo caminho."""
    dst = out_dir / "input.jsonl"
    if input_path.resolve() != dst.resolve():
        dst.write_bytes(input_path.read_bytes())
