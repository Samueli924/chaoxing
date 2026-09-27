#!/bin/zsh
set -eu
cd -- "${0:A:h}"
exec "${CHAOXING_PYTHON:-$HOME/.venv/bin/python}" scripts/local.py "$@"
