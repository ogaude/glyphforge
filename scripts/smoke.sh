#!/usr/bin/env bash
# Clean-venv smoke test of a built wheel: usage `smoke.sh path/to/glyphforge-*.whl`.
# Dependencies resolve from PyPI only; no Docker is needed.
set -euo pipefail

WHEEL=$(realpath "$1")
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

uv venv --quiet --python 3.12 "$T/v"
uv pip install --quiet --python "$T/v/bin/python" "$WHEEL[cli,hf]"

cd "$T"
export PATH="$T/v/bin:$PATH"
glyphforge --help >/dev/null
printf 'composition: {total: 2}\n' >"$T/r.yaml"
glyphforge validate "$T/r.yaml" --schema "$T/schema.json"
glyphforge plan "$T/r.yaml" --json >/dev/null
python -I -c "
import sys
from importlib.resources import files
packaged = files('glyphforge.recipe').joinpath('schema.json').read_bytes()
sys.exit(0 if packaged == open('$T/schema.json', 'rb').read() else 'schema mismatch')
"
python -I -c "import glyphforge, datasets; from glyphforge import canon; print(glyphforge.__version__)"
