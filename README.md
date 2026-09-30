# task_sync_app

日本語で書いたタスクの行から、**期限**と**カテゴリ**を自動で取り出すアプリです。
スマホのホーム画面に追加して使える PWA（ウェブアプリ）と、解析を行う API（FastAPI）でできています。

## できること
- タスクを1行ずつ貼り付けると、行ごとに「題名・期限・カテゴリ」を表示します。
- カテゴリはキーワードで4つ（寺院関係・所属団体2つ・個人）に分けます。どれにも当たらなければ「個人」です。
- Google カレンダーへの登録は、まだ画面からはできません（`/api/sync-calendar` は未実装の応答を返します）。

## 期限の書き方
行の中に、丸括弧で期限を書きます。

| 書き方 | 意味 | 例（今日が 2026-10-01 のとき） |
|--------|------|------|
| `(3/15まで)` | その日まで。過ぎた日付なら翌年 | 2027-03-15 |
| `(5月中)` | その月の末日。過ぎた月なら翌年 | 2027-05-31 |
| `(早め)` `(はやめ)` | 3日後 | 2026-10-04 |
| `(至急)` `(しきゅう)` | 翌日 | 2026-10-02 |
| `(来週まで)` `(来週)` | 来週の日曜日（日曜に書くと2週間後の日曜） | 2026-10-11 |
| 書かない | 期限なし | — |

例: `資料作り (3/15まで)` → 題名「資料作り」・期限 3/15。

- 括弧は半角 `( )` でも全角 `（ ）` でもかまいません。数字と `/` も全角で読めます。
- 期限の部分は題名から除きます。
- `(2/30まで)` のような存在しない日付は、期限なしにして注意（warnings）を返します。

## 起動のしかた（手元）
Python 3.12 を想定しています（3.11 と 3.13 でもテストしています）。

```bash
python3 -m venv .venv
. .venv/bin/activate            # Windows（PowerShell）は .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.api:app --reload --port 8000
```

ブラウザで http://localhost:8000 を開くと画面が出ます。
`python main_api.py` でも同じアプリが起動します（同じ LAN のスマホからも開けます）。

## テストのしかた
```bash
pip install -r requirements.txt -r requirements-dev.txt
bash scripts/check.sh           # 構文確認 → ruff → pytest を1本で回す
```

Windows（PowerShell）で bash が無いときは、同じことを次の1行で行います（venv を有効にしてから）。
`python -m compileall -q backend tests main_api.py; if ($?) { python -m ruff check . }; if ($?) { python -m pytest -q }`

GitHub では push と PR のたびに、同じ検証が Python 3.11 / 3.12 / 3.13 で自動で回ります（`.github/workflows/ci.yml`）。

## 依存ファイル
| ファイル | 用途 |
|----------|------|
| `requirements.txt` | 本番（Render）が読む、版を固定した依存。`requirements.in` から作る |
| `requirements-dev.txt` | テスト・lint 用（pytest・httpx2・ruff） |
| `requirements-calendar.txt` | Google カレンダー連携の部品（`backend/task_sync/`）用。画面と API には不要 |

依存を足すときは `.in` ファイルを直して、先頭に書いてあるコマンドで `.txt` を作り直します。

## 公開（Render）
[RENDER_DEPLOY.md](RENDER_DEPLOY.md) を見てください。main ブランチに入った変更は、公開サービスに自動で反映されます。

## ライセンス
まだ LICENSE ファイルがありません。この状態では、公開されていても他の人に使ってよいとは許可していない扱い（著作権者がすべての権利を持つ）になります。
選ぶ場合の主な候補は次のとおりです（決めるのは作者です）。
- **MIT**: 短くて制限がゆるい。著作権表示を残せば誰でも使える。
- **Apache-2.0**: MIT に近いが、特許の扱いが明記されている。
- **付けない**: 見せるだけで、再利用は許可しない。

## AI エージェント向け
作業の決まりは [AGENTS.md](AGENTS.md) にまとめています。
