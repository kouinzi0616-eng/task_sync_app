"""
============================================================
logger.py — ログ設定
============================================================
コンソール(INFO)とJSON Lines(監査ログ)の二系統出力。

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
============================================================
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════
# 定数
# ═══════════════════════════════════════════════════════════════

LOG_DIR = Path("logs")
CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ═══════════════════════════════════════════════════════════════
# JSON Lines ハンドラ
# ═══════════════════════════════════════════════════════════════

class JsonLinesHandler(logging.Handler):
    """監査用にJSON Lines形式でログを書き出すハンドラ"""

    def __init__(self, log_dir: Path = LOG_DIR) -> None:
        super().__init__()
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.filepath = log_dir / f"sync_{timestamp}.jsonl"
        self._file = open(self.filepath, "a", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        """1レコードを1行のJSONとして書き出す"""
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        # 追加データがあれば埋め込む
        if hasattr(record, "data"):
            entry["data"] = record.data  # type: ignore[attr-defined]
        try:
            self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._file.flush()
        except OSError:
            self.handleError(record)

    def close(self) -> None:
        self._file.close()
        super().close()


# ═══════════════════════════════════════════════════════════════
# ロガー初期化
# ═══════════════════════════════════════════════════════════════

def setup_logger(name: str = "task_sync", verbose: bool = False) -> logging.Logger:
    """アプリケーションロガーを構築して返す"""
    logger = logging.getLogger(name)

    # 既にハンドラがあれば二重追加しない
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # コンソール出力（見やすい日本語向け）
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT))
    logger.addHandler(console)

    # JSON Lines 監査ログ
    json_handler = JsonLinesHandler()
    json_handler.setLevel(logging.INFO)
    logger.addHandler(json_handler)

    logger.info("ロガー初期化完了（JSON Lines: %s）", json_handler.filepath)
    return logger
