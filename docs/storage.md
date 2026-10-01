# 保存のしかた（方針）

このアプリが、タスクをどこに保存するかの決まりです（B29）。

## 結論
- タスクは**端末の中**（ブラウザの IndexedDB）に保存します。サーバーは解析するだけで、何も覚えません（無状態）。
- 端末を替えるときや控えを取るときは、**JSON ファイルを書き出して、手で読み込み**ます。
- 理由: Render の無料枠では、サーバーのファイルも無料のデータベースも、いずれ消えます。サーバーに保存すると、ログイン（認証）も必要になります。

## 言葉
- **IndexedDB**: ブラウザが持つ保存場所。サイトごとに分かれていて、ほかのサイトからは読めません。
- **無状態**: サーバーが前のやり取りを覚えていないこと。どの要求も、その場で解析して返すだけです。
- **認証**: 「この人は本人か」を確かめること（ログイン）。サーバーに保存するなら、他人に見られないよう必ず要ります。

## 比べた案

| 案 | 消えるか | 認証 | サーバーへ送るもの | 費用 | 端末間 | 判定 |
|----|----------|------|--------------------|------|--------|------|
| A. 端末の中（IndexedDB） | ブラウザのデータを消すと消える。Safari は使わない日が続くと消すことがある（下の注意） | 要らない | 解析する行だけ（今と同じ。保存はしない） | 0 | JSON を手で移す | **推奨** |
| B. Render のサーバーのファイル（SQLite） | デプロイのたびに消える[^disks]。無料のサービスには永続ディスクを付けられない[^web] | 要る | 毎回すべて | 0 | 自動 | 使えない |
| C. Render の無料 Postgres | 作ってから 30 日で期限が切れ、猶予の 14 日のあと消える（**未確認・二次情報**[^pg]） | 要る | 毎回すべて | 0（30 日） | 自動 | 使えない |
| D. 有料のデータベース・永続ディスク | 消えない | 要る | 毎回すべて | 有料 | 自動 | 今は不要（決めるのは本人） |
| E. 外部のサービス（Notion の API など） | 消えない | 鍵が要る | 外部へ送る | サービスによる | 自動 | 方針（外部に送らない）に合わない |

ほかに、Render の無料のサービスは、しばらく使わないと止まり（スリープ）、次に開くとき起動を待ちます[^web]。
止まるまでの時間（15 分）と起動の待ち（約 1 分）は、`RENDER_DEPLOY.md` と検索の抜粋による**二次情報**です（公式の説明ページは、この環境からは開けず未確認[^free]）。
保存をサーバーに置かなければ、スリープしても、デプロイしても、タスクは消えません。

## 決めたこと
1. **サーバー（`backend/`）はタスクを保存しない。** 使われていなかった `backend/database.py`（SQLite）は削除しました。
   - 保存が必ず失敗していた（`Task` の `category` が文字列になり、`.value` で止まる）。
   - 読み込むだけで、作業フォルダに `task_sync.db` を作っていた。
   - Render では、作れてもデプロイのたびに消える。
2. **画面（`frontend/`）が IndexedDB に保存する。** データベースの名前は `task-sync`、入れ物は `tasks`（タスク）と `settings`（レーン名などの設定）。
3. **各タスクに、最初に振った固定の ID（UUID）を持たせる。** 題名や期限を直しても変えません。JSON の読み込みで同じ ID のものは上書き（新しい方を残す）し、カレンダー用ファイル（.ics）の UID にも使います（B30）。
4. **外部には送らない。** 新しい機能（保存・書き出し・読み込み・コピー）は、どれもネットワークを使いません。テスト（`tests/test_b29_no_network.py`）で、画面の JS の通信の書き方が増えていないことを確かめます。
5. **端末間は手で移す。** 「JSON に書き出す」→ ファイルを移す → もう一方で「JSON を読み込む」。自動の同期はしません。

## タスクの形（IndexedDB の 1 件）

| 項目 | 意味 |
|------|------|
| `id` | 固定の UUID（最初に振ったもの。変えない） |
| `title` | 件名 |
| `lane` | レーン（設定で名前を変えられる。見本は「仕事・学び・暮らし」） |
| `status` | 状態。`in_progress`（進行中）・`my_turn`（本人の番）・`done`（完了）・`on_hold`（保留） |
| `next_action` | 次に本人がすること |
| `deadline` | 期限（`YYYY-MM-DD`。無ければ空） |
| `due_time` | 時刻（`HH:MM`。無ければ空） |
| `category`・`raw_text` | 解析したときのカテゴリと、もとの 1 行 |
| `created_at`・`updated_at` | 作った時刻・最後に動いた時刻（ISO 8601） |
| `revision` | 直した回数（.ics の `SEQUENCE` に使う） |

- 「**2日以上動きなし**」は、`updated_at` から 48 時間以上たったものです。状態・次にすること・レーンを変えると `updated_at` が新しくなります。
- 状態はどれからどれへも変えられます。同じ状態を選び直したときは、更新したことにしません。

## Notion の台帳との行き来
- **書き出し**: 件名・レーン・状態・本人の番・更新日 の 5 列で、Markdown の表か CSV をクリップボードにコピーします。「本人の番」の列には「次に本人がすること」を入れます。
- **読み込み**: Notion から書き出した CSV を読み、状態が「本人の番」の行だけを表示します。表示するだけで、端末には保存しません。
  - 1 行目の見出しに「件名」と「状態」が要ります。「レーン」「本人の番」「更新日」は無くても読みます。
  - 「本人の番」の欄が空か「なし」で始まる行には、「本人の番の欄が空」の印を付けます。
  - 更新日は `2026-10-01`・`2026/10/01`・`2026年10月1日`・`October 1, 2026` の形を読みます。読めない形なら、2日以上動きなしの印は付けません。Notion の書き出しの実際の日付の形は**未確認**です。
- レーン名は端末ごとの設定です。公開しているコードには、見本の名前（仕事・学び・暮らし）だけを置きます。

## 注意（消えることがあるとき）
- ブラウザの「サイトのデータを消す」をすると消えます。
- 端末の空きが少ないと、ブラウザが消すことがあります。保存したときに `navigator.storage.persist()`（消さないでほしいという願い）を出しますが、受け入れるかはブラウザ次第です[^mdn]。
- Safari は、そのサイトを 7 日間（Safari を使った日で数えて）操作しないと、スクリプトで保存したデータを消します[^mdn]。ホーム画面に追加したアプリでの扱いは、この環境では**未確認**です。
- どの場合も、**ときどき JSON に書き出して控えを取る**のが確実です。

## 出典（取得日 2026-10-01）
[^disks]: Render 公式の GitHub（render-oss/skills）`skills/render-disks/SKILL.md`「Without a disk, services have an ephemeral filesystem—all local file changes are lost on every deploy.」 https://github.com/render-oss/skills/blob/main/skills/render-disks/SKILL.md
[^web]: 同 `skills/render-web-services/SKILL.md`「Free Web Services have separate limits: services spin down after inactivity (cold starts on the next request), and they do not support scaling beyond a single instance or persistent disks.」 https://github.com/render-oss/skills/blob/main/skills/render-web-services/SKILL.md
[^pg]: 二次情報（検索の抜粋）。https://bex.co/blog/2026/09/23/render-free-postgres-30-day-expiry ・ https://justinmckelvey.com/blog/is-render-free 。本文はこの環境から開けず未確認。
[^free]: Render の説明 https://render.com/docs/free はこの環境から開けない（未確認）。15 分・約 1 分は `RENDER_DEPLOY.md` の記載と検索の抜粋による。
[^mdn]: MDN（GitHub の mdn/content）「Storage quotas and eviction criteria」 https://github.com/mdn/content/blob/main/files/en-us/web/api/storage_api/storage_quotas_and_eviction_criteria/index.md
