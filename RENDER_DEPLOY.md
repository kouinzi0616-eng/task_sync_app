# 🚀 Render.com デプロイ手順

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
   - **Local Path**: `C:\Users\owner\Documents\`（task_sync_appの親フォルダ）
   - **Initialize with README**: チェック
   - **Git Ignore**: Python

4. 「Create Repository」をクリック

### 1-3. ファイル追加

以下のファイルをプロジェクトルートに配置:
- `requirements.txt` ← requirements_prod.txt をリネーム
- `runtime.txt`
- `Procfile`
- `.gitignore` ← gitignore.txt をリネーム

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

### 2-4. 環境変数設定（オプション）

「Advanced」→「Add Environment Variable」で以下を追加:

| Key | Value |
|-----|-------|
| `PYTHON_VERSION` | `3.11.0` |

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

1. GitHub Desktop で変更をコミット
2. 「Push origin」でGitHubにプッシュ
3. Render.comが自動で再デプロイ（Auto Deploy有効の場合）

---

## 💡 Tips

### カスタムドメイン設定（オプション）

独自ドメインを持っている場合:
1. Render.com Dashboard → Settings → Custom Domains
2. ドメインを追加してDNS設定

### 無料プランの制限

- 月750時間（十分）
- 15分間アクセスがないとスリープ
- 初回アクセス時に数秒待つ（コールドスタート）

### スリープを防ぐ方法

UptimeRobot（無料）で5分ごとにpingを送る:
https://uptimerobot.com/

---

## 🐛 トラブルシューティング

### エラー: "Failed to install requirements"

→ `requirements.txt` の内容を確認
→ 不要なライブラリを削除

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
