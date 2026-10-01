"""
============================================================
FastAPI バックエンド - タスク同期API
============================================================
タスクの解析、カテゴリ分類、Google Calendar連携を提供するREST API

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
必要ライブラリ: fastapi, uvicorn, pydantic
============================================================
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Annotated, List
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

# 絶対インポート（プロジェクトルートから実行する場合）
from backend.models import Category
from backend.date_parser import parse_deadline
from backend.category_classifier import classify_category

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    """環境変数が 1 / true / yes / on なら True"""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


# API の説明ページ（/docs・/redoc・/openapi.json）は既定で無効。
# 手元で見たいときだけ ENABLE_API_DOCS=1 を付けて起動する。
API_DOCS_ENABLED = _env_flag("ENABLE_API_DOCS")

# FastAPIアプリ
app = FastAPI(
    title="Task Sync API",
    description="タスク同期・カテゴリ分類・カレンダー連携API",
    version="1.0.0",
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
)

# CORS は設定しない。画面（frontend/）と API は同じオリジンから配信しているので不要で、
# 他のサイトから資格情報つきで呼べる状態を作らないため。


# ============================================================
# 入力の上限と、利用者に返す汎用の文言
# ============================================================

MAX_TEXT_LENGTH = 500  # 1タスク（1行）の最大文字数
MAX_BATCH_TASKS = 200  # 一括解析・同期の最大件数

# 500 の応答や失敗した行には内部の例外文を載せず、この文言だけを返す
PARSE_ERROR_MESSAGE = "タスク解析に失敗しました"
ROW_ERROR_MESSAGE = "この行は解析できませんでした"


# ============================================================
# リクエスト・レスポンスモデル
# ============================================================

TaskText = Annotated[str, Field(max_length=MAX_TEXT_LENGTH)]


class TaskInput(BaseModel):
    """タスク入力（生テキスト）"""
    text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_TEXT_LENGTH,
        description="タスクテキスト（例: 青鳳会の会議資料準備 (3/15まで)）",
    )

    @field_validator("text")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("空白だけのタスクは解析できません")
        return value


class TaskResponse(BaseModel):
    """解析済みタスク"""
    title: str
    deadline: str | None
    category: Category
    raw_text: str
    warnings: List[str] = Field(default_factory=list, description="利用者に見せる注意（例: 存在しない日付）")
    # B26: どの表現をどう読んだか（項目を足しただけ。上の5項目の意味は変えない）
    due_type: str = Field("none", description="期限の種類（exact・month_end・week・relative・urgent・soon・after・period・unknown・none）")
    due_raw: str = Field("", description="期限として読み取った括弧の中身（例: 3/15まで）")
    due_time: str | None = Field(None, description="時刻 HH:MM（書いてあれば）。deadline は日付の 0:00 のまま")
    needs_review: bool = Field(False, description="人が確かめるべき行か（warnings が1つでもあれば True）")
    overdue: bool = Field(False, description="期限を過ぎているか")


class BatchItemResponse(BaseModel):
    """一括解析の1行分の結果（ok=False の行は error に理由の文言が入る）"""
    ok: bool
    title: str
    deadline: str | None = None
    category: Category | None = None
    raw_text: str
    warnings: List[str] = Field(default_factory=list)
    error: str | None = None
    due_type: str | None = None  # 解析できなかった行（ok=False）は None
    due_raw: str = ""
    due_time: str | None = None
    needs_review: bool = False  # 解析できなかった行（ok=False）は True
    overdue: bool = False


class TaskListInput(BaseModel):
    """複数タスク一括入力（空白だけの行は読み飛ばす）"""
    tasks: List[TaskText] = Field(
        ...,
        max_length=MAX_BATCH_TASKS,
        description=f"タスクテキストのリスト（{MAX_BATCH_TASKS}件・1行{MAX_TEXT_LENGTH}文字まで）",
    )


class SyncRequest(BaseModel):
    """Google Calendar同期リクエスト"""
    tasks: List[TaskResponse] = Field(..., max_length=MAX_BATCH_TASKS)


# ============================================================
# 解析の本体
# ============================================================

def _analyze(text: str) -> TaskResponse:
    """1行を解析する（期限・題名・カテゴリ）"""
    result = parse_deadline(text)
    return TaskResponse(
        title=result.title,
        deadline=result.deadline.isoformat() if result.deadline else None,
        category=classify_category(text),
        raw_text=text,
        warnings=list(result.warnings),
        due_type=result.due_type,
        due_raw=result.due_raw,
        due_time=result.due_time,
        needs_review=result.needs_review,
        overdue=result.overdue,
    )


# ============================================================
# エンドポイント
# ============================================================

@app.get("/api/health")
async def health_check():
    """ヘルスチェック"""
    return {
        "status": "ok",
        "service": "Task Sync API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/parse", response_model=TaskResponse)
async def parse_task(task_input: TaskInput):
    """
    単一タスクを解析してカテゴリ分類・日付抽出を実行
    
    Args:
        task_input: タスクテキスト
        
    Returns:
        解析済みタスク情報
    """
    try:
        response = _analyze(task_input.text)
    except Exception as e:
        # ログにも応答にも、題名や内部の例外文は出さない
        logger.error("タスク解析エラー: 1件（%s）", type(e).__name__)
        raise HTTPException(status_code=500, detail=PARSE_ERROR_MESSAGE) from None

    logger.info("タスク解析: 1件（警告 %d件）", len(response.warnings))
    return response


@app.post("/api/parse-batch", response_model=List[BatchItemResponse])
async def parse_tasks_batch(task_list: TaskListInput):
    """
    複数タスクを一括解析（行ごとに成否を返す。1行の失敗で全体を失敗にしない）
    
    Args:
        task_list: タスクテキストのリスト
        
    Returns:
        行ごとの解析結果のリスト（空白だけの行は含めない）
    """
    results: List[BatchItemResponse] = []
    failed = 0
    warned = 0

    for task_text in task_list.tasks:
        # 空行はスキップ
        if not task_text.strip():
            continue

        try:
            parsed = _analyze(task_text)
        except Exception as e:
            failed += 1
            logger.error("一括解析: 1行失敗（%s）", type(e).__name__)
            results.append(BatchItemResponse(
                ok=False,
                title=task_text.strip(),
                raw_text=task_text,
                error=ROW_ERROR_MESSAGE,
                needs_review=True,
            ))
            continue

        if parsed.warnings:
            warned += 1
        results.append(BatchItemResponse(ok=True, **parsed.model_dump()))

    logger.info(
        "一括解析: %d件（成功 %d件・失敗 %d件・警告あり %d件）",
        len(results), len(results) - failed, failed, warned,
    )
    return results


@app.post("/api/sync-calendar")
async def sync_to_calendar(sync_request: SyncRequest):
    """
    Google Calendarに同期（未実装 - フロントエンドからOAuth経由で実行予定）
    
    Args:
        sync_request: 同期するタスクのリスト
        
    Returns:
        同期結果
    """
    # TODO: Google Calendar API連携を実装
    # 現在はフロントエンドでGoogle Calendar APIを直接呼び出す想定
    
    logger.info(f"カレンダー同期リクエスト受信: {len(sync_request.tasks)}件")
    
    return {
        "status": "not_implemented",
        "message": "Google Calendar同期はフロントエンドから直接実行してください",
        "tasks_count": len(sync_request.tasks)
    }


# ============================================================
# 静的ファイル配信（PWA）- 修正版
# ============================================================

# 起動したフォルダに関係なく見つかるよう、このファイルの位置を基準にする
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"

if frontend_dir.exists() and frontend_dir.is_dir():
    # 静的ファイルを /static にマウント（CSS, JS, 画像など）
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
    
    # ルートパスでindex.htmlを返す
    @app.get("/", response_class=HTMLResponse)
    async def serve_root():
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)
    
    # manifest.json
    @app.get("/manifest.json")
    async def serve_manifest():
        manifest_path = frontend_dir / "manifest.json"
        if manifest_path.exists():
            return FileResponse(manifest_path, media_type="application/json")
        raise HTTPException(status_code=404, detail="manifest.json not found")
    
    # Service Worker
    @app.get("/sw.js")
    async def serve_sw():
        sw_path = frontend_dir / "sw.js"
        if sw_path.exists():
            return FileResponse(sw_path, media_type="application/javascript")
        raise HTTPException(status_code=404, detail="sw.js not found")
    
    # アイコン（複数サイズ対応）
    @app.get("/icon-{size}.png")
    async def serve_icon(size: str):
        icon_path = frontend_dir / f"icon-{size}.png"
        if icon_path.exists():
            return FileResponse(icon_path, media_type="image/png")
        raise HTTPException(status_code=404, detail=f"icon-{size}.png not found")
    
    # Apple Touch Icon（iOS対応）
    @app.get("/apple-touch-icon.png")
    @app.get("/apple-touch-icon-precomposed.png")
    @app.get("/apple-touch-icon-120x120.png")
    @app.get("/apple-touch-icon-120x120-precomposed.png")
    async def serve_apple_icon():
        # iOS用に192pxアイコンを返す
        icon_path = frontend_dir / "icon-192.png"
        if icon_path.exists():
            return FileResponse(icon_path, media_type="image/png")
        raise HTTPException(status_code=404, detail="Apple touch icon not found")
    
    # favicon
    @app.get("/favicon.ico")
    async def serve_favicon():
        # 192pxアイコンをfaviconとして返す
        icon_path = frontend_dir / "icon-192.png"
        if icon_path.exists():
            return FileResponse(icon_path, media_type="image/x-icon")
        raise HTTPException(status_code=404, detail="favicon not found")
    
    logger.info("✅ フロントエンド配信を有効化しました")
else:
    logger.warning("⚠️ frontendディレクトリが見つかりません")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
