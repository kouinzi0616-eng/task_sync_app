# 🚀 Render.com デプロイ手順

> このリポジトリはすでに GitHub にあり、Render の公開サービスは **main ブランチから自動でデプロイ**されます。
> 変更は作業ブランチで行い、PR で CI（テスト）が通ってから main に入れてください。
> 初めて Render に載せるときは、下の Step 1 から進めます。

## 📋 準備

### 1. GitHubアカウント作成
https://github.com でアカウントを作成（既にある場合はスキップ）

### 2. Render.comアカウント作成
https://render.com でアカウントを作成（GitHubアカウントで連携可能）

---

## 📦 Step 1: GitHubにプロジェクトをアップロード

### 1-1. GitHub Desktop のインストール（推奨）
https://desktop.github.com/ からダウンロード

### 1-2. リポジトリ作成

1. GitHub Desktop を開く
2. 「File」→「New Repository」
3. 設定:
   - **Name**: `task-sync-app`
   - **Local Path**: task_sync_app を置く親フォルダ（任意の場所）
   - **Initialize with README**: チェック
   - **Git Ignore**: Python

4. 「Create Repository」をクリック

### 1-3. ファイルの確認

次のファイルがプロジェクトのルートにあることを確かめます（どれもリポジトリに入っています）:
- `requirements.txt` … Render が読む依存（版を固定したもの）
- `.python-version` … Python の版（`3.12`）
- `.gitignore` … 鍵・ログ・`.env` をコミットしないための設定
- `Procfile` … 起動コマンドの控え（Render は読みません。Start Command は画面で設定します）

`.env`・`client_secret*.json`・`credentials.json`・`token.json` はコミットしないでください。

### 1-4. コミット＆プッシュ

1. GitHub Desktop で変更を確認
2. 左下にコミットメッセージを入力: `Initial commit`
3. 「Commit to main」をクリック
4. 「Publish repository」をクリック
5. **Keep this code private** のチェックを外す（公開リポジトリ）
6. 「Publish Repository」をクリック

---

## ☁️ Step 2: Render.comでデプロイ

### 2-1. Render.comにログイン
https://dashboard.render.com/

### 2-2. 新規Webサービス作成

1. 「New +」→「Web Service」をクリック
2. 「Connect GitHub」でGitHubアカウントを連携
3. リポジトリ一覧から `task-sync-app` を選択
4. 「Connect」をクリック

### 2-3. サービス設定

| 項目 | 値 |
|------|-----|
| **Name** | `task-sync-app`（任意） |
| **Region** | Singapore（日本に近い） |
| **Branch** | `main` |
| **Root Directory** | 空欄 |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn backend.api:app --host 0.0.0.0 --port $PORT` |
| **Instance Type** | **Free** |

### 2-4. Python の版と環境変数

Python の版は、リポジトリの `.python-version`（中身は `3.12`）で決まります。Render はこの場合、3.12 系の最新の修正版を使います。
`runtime.txt` は Render では読まれないので、置いていません。

**注意**: Render の環境変数 `PYTHON_VERSION` があると、そちらが `.python-version` より優先されます。
以前の手順で `PYTHON_VERSION` = `3.11.0` を設定した場合は、次のどちらかにしてください。
- 環境変数 `PYTHON_VERSION` を消す（`.python-version` の 3.12 が使われる）
- または `3.12.x` のように修正版まで書いた版にする（公式ドキュメントでは、`PYTHON_VERSION` は修正版まで書く決まり。`3.12` だけの短い書き方は `.python-version` でのみ使える）

どちらも無いと、Render の既定の版になります（2026-02-11 以降に作ったサービスでは 3.14 系）。

参考: https://render.com/docs/python-version

### 2-5. デプロイ開始

1. 「Create Web Service」をクリック
2. デプロイが自動で開始されます（5-10分）
3. ログを見てエラーがないか確認

---

## ✅ Step 3: 動作確認

### 3-1. URLを確認

デプロイ完了後、以下のようなURLが発行されます:
```
https://task-sync-app-xxxx.onrender.com
```

### 3-2. アクセステスト

1. ブラウザで上記URLにアクセス
2. Task Syncアプリが表示されればOK

### 3-3. スマホでテスト

1. スマホのブラウザで同じURLにアクセス
2. **ホーム画面に追加** でPWAとしてインストール
3. **PCが閉じていてもアクセスできることを確認**

---

## 🔄 Step 4: 更新方法

コードを修正した場合:

1. 作業ブランチで変更をコミットし、GitHub にプッシュ
2. PR を作り、CI（テスト・lint）が通ることを確認
3. main にマージすると、Render.com が自動で再デプロイ（Auto Deploy 有効の場合）

---

## 💡 Tips

### カスタムドメイン設定（オプション）

独自ドメインを持っている場合:
1. Render.com Dashboard → Settings → Custom Domains
2. ドメインを追加してDNS設定

### 無料プランの制限

- 無料の稼働時間はワークスペースごとに月750時間（1つのサービスを常に動かしても足りる）
- 15分間アクセスがないとスリープ
- スリープ後の最初のアクセスは、起動まで**約1分**待つ（コールドスタート）

参考: https://render.com/docs/free

### スリープを防ぐ方法

UptimeRobot（無料）で5分ごとにpingを送る:
https://uptimerobot.com/

---

## 🐛 トラブルシューティング

### エラー: "Failed to install requirements"

→ `requirements.txt` の内容を確認（直接の依存は `requirements.in`。直したら作り直す）
→ Google カレンダー用の依存は `requirements-calendar.txt` に分けてあり、本番には入れていません
→ Python の版を確認（上の 2-4）

### エラー: "Application failed to respond"

→ Start Command を確認: `uvicorn backend.api:app --host 0.0.0.0 --port $PORT`
→ `$PORT` は環境変数（Render.comが自動設定）

### 404 Error

→ フロントエンドファイルが正しくGitHubにアップロードされているか確認
→ `frontend/` フォルダがリポジトリに含まれているか確認

---

## 📞 サポート

問題が解決しない場合:
- Render.com Docs: https://render.com/docs
- GitHub Issues: プロジェクトのIssuesタブで質問

---

## 🎉 完成！

これで、どこからでもアクセスできるTask Syncアプリが完成しました！

**URL**: `https://task-sync-app-xxxx.onrender.com`

スマホのホーム画面に追加して、アプリとして使いましょう 📱
