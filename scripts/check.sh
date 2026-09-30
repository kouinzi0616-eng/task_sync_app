#!/usr/bin/env bash
# ============================================================
# 検証コマンド（CI と同じことを手元で1本で回す）: Linux / macOS 用
#   構文確認 → ruff → pytest
# 使い方:
#   bash scripts/check.sh
# 使う Python は、環境変数 PYTHON > .venv/bin/python > python3 の順に選ぶ。
# 先に依存を入れておく:
#   python3 -m pip install -r requirements.txt -r requirements-dev.txt
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -n "${PYTHON:-}" ]]; then
  py="$PYTHON"
elif [[ -x .venv/bin/python ]]; then
  py=".venv/bin/python"
else
  py="python3"
fi

echo "== Python: $("$py" --version 2>&1) ($py)"

echo "== 1/3 構文確認（compileall）"
targets=(backend tests main_api.py)
if [[ -d labs ]]; then
  targets+=(labs)
fi
"$py" -m compileall -q "${targets[@]}"

echo "== 2/3 ruff"
"$py" -m ruff check .

echo "== 3/3 pytest"
"$py" -m pytest -q "$@"

echo "== すべて成功"
