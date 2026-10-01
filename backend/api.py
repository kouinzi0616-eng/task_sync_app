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
from starlette.datastructures import MutableHeaders

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
# 応答ヘッダ（画面の安全: B28）
# ============================================================

# 画面の JS・CSS は自分のサーバーのファイルだけを使う（インラインの script・style は動かさない）。
# 万一、入力が HTML として差し込まれても、スクリプトは実行されない。
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self'",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",  # 他のサイトの枠（iframe）に入れさせない
])

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",  # 宣言した種類以外として読ませない
    "Referrer-Policy": "no-referrer",  # 他のサイトへ URL を渡さない
    "X-Frame-Options": "DENY",  # frame-ancestors を知らない古いブラウザ向け
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# API の説明ページ（ENABLE_API_DOCS=1 のときだけ出る）は外部の JS とインラインの script を使うので、
# そのページにだけ CSP を付けない（ほかのヘッダは付ける）。
API_DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc"})


class SecurityHeadersMiddleware:
    """すべての HTTP 応答に SECURITY_HEADERS を足す（ASGI のミドルウェア）"""

    def __init__(self, app, csp_exempt_paths: frozenset[str] = frozenset()):
        self.app = app
        self.csp_exempt_paths = csp_exempt_paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        skip_csp = scope.get("path") in self.csp_exempt_paths

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if skip_csp and name == "Content-Security-Policy":
                        continue
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(
    SecurityHeadersMiddleware,
    csp_exempt_paths=API_DOCS_PATHS if API_DOCS_ENABLED else frozenset(),
)


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

# 画面の本体は毎回サーバーに確かめさせる（変わっていなければ 304 で軽く済む）。
# 古い画面がブラウザの HTTP キャッシュに残り続けないようにするため。
NO_CACHE_HEADERS = {"Cache-Control": "no-cache"}


def _frontend_file(name: str, media_type: str) -> FileResponse:
    """frontend/ の決まったファイルを返す（名前はコードに書いたものだけ）"""
    path = frontend_dir / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return FileResponse(path, media_type=media_type, headers=NO_CACHE_HEADERS)


if frontend_dir.exists() and frontend_dir.is_dir():
    # 静的ファイルを /static にマウント（CSS, JS, 画像など）
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
    
    # ルートパスでindex.htmlを返す
    @app.get("/", response_class=HTMLResponse)
    @app.get("/index.html", response_class=HTMLResponse)
    async def serve_root():
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path, headers=NO_CACHE_HEADERS)
        return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)

    # 画面の動きと見た目（index.html から分けたファイル）
    @app.get("/app.js")
    async def serve_app_js():
        return _frontend_file("app.js", "application/javascript")

    @app.get("/app.css")
    async def serve_app_css():
        return _frontend_file("app.css", "text/css")

    # 電波が無いときに Service Worker が返すオフライン画面（sw.js が先にキャッシュする）
    @app.get("/offline.html", response_class=HTMLResponse)
    async def serve_offline_page():
        return _frontend_file("offline.html", "text/html")

    # manifest.json
    @app.get("/manifest.json")
    async def serve_manifest():
        return _frontend_file("manifest.json", "application/json")
    
    # Service Worker
    @app.get("/sw.js")
    async def serve_sw():
        return _frontend_file("sw.js", "application/javascript")
    
    # アイコン（any 用 192・512 と、端まで塗った maskable 用 192・512）
    ICON_NAMES = frozenset({"192", "512", "maskable-192", "maskable-512"})

    @app.get("/icon-{size}.png")
    async def serve_icon(size: str):
        icon_path = frontend_dir / f"icon-{size}.png"
        if size in ICON_NAMES and icon_path.is_file():
            return FileResponse(icon_path, media_type="image/png")
        raise HTTPException(status_code=404, detail="icon not found")
    
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
