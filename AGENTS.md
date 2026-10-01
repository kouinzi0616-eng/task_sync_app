# AGENTS.md — task_sync_app の作業ガイド（目次）

AI エージェント（Claude Code・Codex など）と人が最初に読む短い目次です。詳しい説明はリンク先にあります。

## これは何か
- 日本語のタスク1行（例: `資料作り (3/15まで)`）から、期限とカテゴリを取り出す PWA と FastAPI のアプリ。
- 公開リポジトリ。Render の公開サービスは **main ブランチから自動でデプロイ**される。

## 構成
| 場所 | 中身 |
|------|------|
| `backend/api.py` | FastAPI 本体。画面（frontend/）も配信する。Render は `uvicorn backend.api:app` で起動 |
| `backend/date_parser.py` | 期限解析の薄い互換層（JST の今日を基準日にし、期限を JST 0:00 にする）。読み方の正本は `backend/task_sync/date_rules.py` |
| `backend/category_classifier.py`・`backend/models.py` | カテゴリ判定の薄い互換層（判定の正本は `backend/task_sync/categories.py`）。`models.py` は今は説明だけ |
| `backend/task_sync/` | 期限解析の正本（`date_rules.py`）、カテゴリ判定の正本（`categories.py`。判定語とカテゴリ名は設定の JSON から読む。公開は見本 `categories.sample.json` だけ）、急ぎの規則ベース検出（`urgency.py`。画面・API にはまだつないでいない）、カレンダー同期用の解析・同期の部品（Google の依存は `requirements-calendar.txt`。Web アプリからは使わない。カレンダーへは画面の .ics（`frontend/ics.js`）で入れる） |
| `docs/storage.md` | 保存の方針。タスクは画面が端末の中（IndexedDB）に保存し、サーバーは保存しない（`backend/database.py` は B29 で削除） |
| `frontend/` | PWA（index.html・app.js・app.css・offline.html・sw.js・manifest.json・アイコン）。CSP があるので HTML にインラインの script・style は書かない。タスクの保存は端末の中だけ（`store.js` が IndexedDB、`task_core.js` が台帳の計算）。外部への通信は足さない（`tests/test_b29_no_network.py`） |
| `tests/` | pytest。`labs/` ができたら、そこのテストも一緒に回る。`tests/frontend/` は node で app.js・sw.js を動かす偽 DOM（node が無ければ飛ばす） |
| `scripts/check.sh` | 検証コマンド（構文確認 → ruff → pytest） |
| `scripts/sw_version.py`・`contrast.py`・`make_maskable_icons.py` | Service Worker の版の記録・文字色の対比の表・maskable アイコンの作成（標準ライブラリだけ） |
| `scripts/category_config.py`・`find_words.py` | カテゴリの設定の確かめ・試し・1行化／公開したくない語が残っていないかを手元で数える（語は `private/` に置き、出力に語を出さない） |
| `requirements*.in` / `requirements*.txt` | 直接の依存（.in）と、版を固定したロック（.txt） |

## 検証（変更したら必ず回す）
```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt   # 初回だけ
bash scripts/check.sh
```
- CI（`.github/workflows/ci.yml`）も同じ `scripts/check.sh` を Python 3.11 / 3.12 / 3.13 で回す。
- カテゴリの判定を変えたら、`tests/test_b27_categories.py`（見本の設定と、実物に似せた架空の設定）が通ることを確かめる。カテゴリの印のクラス名は中立な名前（`badge-cat-0`〜`6`）だけにする。
- 期限解析を変えたら、`tests/test_api_parse_current.py` の正常系の出力が変わらないことと、共通検算表 `tests/fixtures/due_cases.json` の全件一致（`tests/test_due_cases.py`）を確かめる。仕様を変えるときは、表の期待値と備考（【旧と違う】と理由）と README の表を一緒に直す。
- 画面（`frontend/` の index.html・app.js・task_core.js・store.js・app.css・offline.html・manifest.json・アイコン）を変えたら、`frontend/sw.js` の `CACHE_VERSION` を1つ上げて `python scripts/sw_version.py --update` を回す（上げ忘れは `tests/test_b28_service_worker.py` が落とす）。
- 画面の色を変えたら `python scripts/contrast.py` で対比の表を見る（文字 4.5・枠 3.0 未満はテストが落とす）。文字は `textContent` で入れ、`innerHTML` などは使わない。
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
- 実際のカテゴリ名・判定語（団体名など）はリポジトリに書かない。Render の環境変数 `CATEGORY_CONFIG_JSON` か `private/categories.json` で渡す。テストは架空の設定（`tests/fixtures/categories_reallike.json`）を使う。

## 関連ドキュメント
- `README.md`: できること・カテゴリの設定（Render で実物の設定を渡す方法）・期限の書き方・起動とテストの方法
- `RENDER_DEPLOY.md`: Render での公開手順
- `.env.example`: アプリが読む環境変数
