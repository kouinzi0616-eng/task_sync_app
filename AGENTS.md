# AGENTS.md — task_sync_app の作業ガイド（目次）

AI エージェント（Claude Code・Codex など）と人が最初に読む短い目次です。詳しい説明はリンク先にあります。

## これは何か
- 日本語のタスク1行（例: `資料作り (3/15まで)`）から、期限とカテゴリを取り出す PWA と FastAPI のアプリ。
- 公開リポジトリ。Render の公開サービスは **main ブランチから自動でデプロイ**される。

## 構成
| 場所 | 中身 |
|------|------|
| `backend/api.py` | FastAPI 本体。画面（frontend/）も配信する。Render は `uvicorn backend.api:app` で起動 |
| `backend/date_parser.py` | Web API 用の期限解析 |
| `backend/category_classifier.py`・`backend/models.py` | カテゴリ分類とデータの形 |
| `backend/task_sync/` | カレンダー同期用の解析・同期の部品（Google の依存は `requirements-calendar.txt`） |
| `backend/database.py` | 履歴保存（今は API から使っていない） |
| `frontend/` | PWA（index.html・sw.js・manifest.json・アイコン） |
| `tests/` | pytest。`labs/` ができたら、そこのテストも一緒に回る |
| `scripts/check.sh` | 検証コマンド（構文確認 → ruff → pytest） |
| `requirements*.in` / `requirements*.txt` | 直接の依存（.in）と、版を固定したロック（.txt） |

## 検証（変更したら必ず回す）
```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt   # 初回だけ
bash scripts/check.sh
```
- CI（`.github/workflows/ci.yml`）も同じ `scripts/check.sh` を Python 3.11 / 3.12 / 3.13 で回す。
- 期限解析を変えたら、`tests/test_api_parse_current.py` の正常系の出力が変わらないことを確かめる。
- Claude Code on the web では、SessionStart フック（`.claude/hooks/session-start.sh`）が `.venv` に依存を入れる。

## 依存と版
- 依存を足すときは `.in` を直し、各 `.in` の先頭にある `uv pip compile ...` で `.txt` を作り直す。
- `requirements.txt` は Render が読む本命のファイル。消さない・名前を変えない。
- Python の版は `.python-version`（3.12）。Render の設定は `RENDER_DEPLOY.md` を見る。

## 禁止事項
- 実名・顧客名・寺や檀家の実データ・私用メール・手元 PC のパス・鍵（API キー、OAuth の client_secret、token.json など）を、コード・テスト・ドキュメント・コミットに書かない。例とテストは架空の文字列だけにする。
- 鍵の形をした文字列がテストに要るときは、実行時に文字列をつなげて作る（ソースに完全な形で書かない）。
- 外部に送信しない。テストはネットワークに出ない。Google カレンダーなど本物の API を呼ばない。
- `.env*`（`.env.example` を除く）・`client_secret*.json`・`credentials.json`・`token.json`・`private/` を読まない・コミットしない。
- main へ直接入れない（公開サービスにすぐ反映される）。作業ブランチと PR を使う。
- 既存ファイル冒頭の作者表記は変えない。

## 関連ドキュメント
- `README.md`: できること・期限の書き方・起動とテストの方法
- `RENDER_DEPLOY.md`: Render での公開手順
- `.env.example`: アプリが読む環境変数
