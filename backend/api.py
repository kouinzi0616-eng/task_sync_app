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
from datetime import datetime
from typing import List
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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

# FastAPIアプリ
app = FastAPI(
    title="Task Sync API",
    description="タスク同期・カテゴリ分類・カレンダー連携API",
    version="1.0.0"
)

# CORS設定（PWAからのアクセスを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番環境では特定のオリジンに限定すること
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# リクエスト・レスポンスモデル
# ============================================================

class TaskInput(BaseModel):
    """タスク入力（生テキスト）"""
    text: str = Field(..., description="タスクテキスト（例: 青鳳会の会議資料準備 (3/15まで)）")


class TaskResponse(BaseModel):
    """解析済みタスク"""
    title: str
    deadline: str | None
    category: Category
    raw_text: str
    warnings: List[str] = Field(default_factory=list, description="利用者に見せる注意（例: 存在しない日付）")


class TaskListInput(BaseModel):
    """複数タスク一括入力"""
    tasks: List[str] = Field(..., description="タスクテキストのリスト")


class SyncRequest(BaseModel):
    """Google Calendar同期リクエスト"""
    tasks: List[TaskResponse]


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
        logger.info(f"タスク解析成功: {response.title} -> {response.category.value}")
        return response

    except Exception as e:
        logger.error(f"タスク解析エラー: {e}")
        raise HTTPException(status_code=500, detail=f"タスク解析に失敗しました: {str(e)}") from e


@app.post("/api/parse-batch", response_model=List[TaskResponse])
async def parse_tasks_batch(task_list: TaskListInput):
    """
    複数タスクを一括解析
    
    Args:
        task_list: タスクテキストのリスト
        
    Returns:
        解析済みタスクのリスト
    """
    try:
        results = []
        
        for task_text in task_list.tasks:
            # 空行はスキップ
            if not task_text.strip():
                continue
                
            results.append(_analyze(task_text))
        
        logger.info(f"一括解析完了: {len(results)}件のタスク")
        return results
        
    except Exception as e:
        logger.error(f"一括解析エラー: {e}")
        raise HTTPException(status_code=500, detail=f"一括解析に失敗しました: {str(e)}") from e


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
