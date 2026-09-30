#!/bin/bash
# ============================================================
# SessionStart フック（Claude Code on the web 用）
# ============================================================
# 依存を .venv に入れて、pytest と ruff がすぐ走る状態にする。
# - CLAUDE_CODE_REMOTE=true（クラウドのセッション）のときだけ動く
# - 何度実行しても同じ結果になる（冪等）・入力を求めない（非対話）
# - 失敗しても作業を止めない（最後は必ず exit 0）
# ============================================================
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

log() { echo "[session-start] $*" >&2; }

project_dir="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$project_dir" || { log "プロジェクトのフォルダに移れません"; exit 0; }

if [ ! -x .venv/bin/python ]; then
  py=""
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      py="$candidate"
      break
    fi
  done
  if [ -z "$py" ]; then
    log "Python が見つからないので、依存は入れません"
    exit 0
  fi
  if ! "$py" -m venv .venv; then
    log ".venv を作れませんでした"
    exit 0
  fi
fi

if .venv/bin/python -m pip install -q --disable-pip-version-check \
    -r requirements.txt -r requirements-dev.txt -r requirements-calendar.txt >&2; then
  log "依存を入れました（$(.venv/bin/python --version 2>&1)）"
else
  log "依存のインストールに失敗しました（作業は続けられます）"
fi

# このセッションのコマンドで .venv の python・pytest・ruff が先に見つかるようにする
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export VIRTUAL_ENV=\"$project_dir/.venv\""
    echo "export PATH=\"$project_dir/.venv/bin:\$PATH\""
  } >> "$CLAUDE_ENV_FILE"
fi

exit 0
