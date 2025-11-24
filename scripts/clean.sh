#!/usr/bin/env bash
set -euo pipefail

# Limpa artefatos gerados pelo pipeline
rm -rf "inputs/by_process"
rm -rf "outputs"

# Limpa caches do Python
find . -type d -name "__pycache__" -prune -exec rm -rf {} +

echo "Limpeza concluída."
