// ============================================================
// 画面の動き（index.html から分けた）
// Content-Security-Policy で script-src 'self' にしているので、
// HTML の中に script を書かず、このファイルから読み込む。
// 入力や API の応答に由来する文字は textContent で入れる（HTML として解釈させない）。
// ============================================================
'use strict';

const API_BASE = '';
// 期限の種類（API の due_type）の表示名
const DUE_TYPE_LABELS = {
    exact: '日付',
    month_end: '月末',
    period: '上旬・中旬・下旬',
    week: '週の終わり（日曜）',
    relative: '今日から数えた日',
    urgent: '至急',
    soon: '早め（3日後）',
    after: 'この日以降',
    unknown: '読めない',
    none: '期限なし'
};
let parsedTasks = [];
let deferredPrompt;

// 要素取得
const taskInput = document.getElementById('taskInput');
const parseBtn = document.getElementById('parseBtn');
const syncBtn = document.getElementById('syncBtn');
const loading = document.getElementById('loading');
const error = document.getElementById('error');
const success = document.getElementById('success');
const results = document.getElementById('results');
const taskList = document.getElementById('taskList');
const installPrompt = document.getElementById('installPrompt');
const installBtn = document.getElementById('installBtn');

// タブ切り替え
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        // タブのアクティブ化
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        
        // コンテンツの切り替え
        const tabName = tab.dataset.tab;
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.getElementById(`tab-${tabName}`).classList.add('active');
        
        // 履歴・統計タブを開いたらデータ読み込み
        if (tabName === 'history') loadHistory();
        if (tabName === 'stats') loadStats();
    });
});

// PWAインストールプロンプト
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    installPrompt.classList.add('show');
});

installBtn.addEventListener('click', async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    deferredPrompt = null;
    installPrompt.classList.remove('show');
});

// 解析ボタン
parseBtn.addEventListener('click', async () => {
    const text = taskInput.value.trim();
    
    if (!text) {
        showError('タスクを入力してください');
        return;
    }
    
    const tasks = text.split('\n').filter(t => t.trim());
    
    if (tasks.length === 0) {
        showError('有効なタスクがありません');
        return;
    }
    
    loading.classList.add('show');
    parseBtn.disabled = true;
    error.classList.remove('show');
    success.classList.remove('show');
    results.classList.remove('show');
    
    try {
        const response = await fetch(`${API_BASE}/api/parse-batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tasks })
        });
        
        if (response.status === 422) {
            throw new Error('入力が長すぎるか、行が多すぎます（1行500文字・200行まで）');
        }
        if (!response.ok) throw new Error('解析に失敗しました');
        
        parsedTasks = await response.json();
        displayResults(parsedTasks);
        const failedCount = parsedTasks.filter(t => t.ok === false).length;
        const okCount = parsedTasks.length - failedCount;
        showSuccess(failedCount
            ? `${okCount}件のタスクを解析しました（${failedCount}件は解析できませんでした）`
            : `${okCount}件のタスクを解析しました`);
        
    } catch (err) {
        showError('エラーが発生しました: ' + err.message);
    } finally {
        loading.classList.remove('show');
        parseBtn.disabled = false;
    }
});

// 結果表示
function displayResults(tasks) {
    taskList.replaceChildren();  // 前の結果を消す
    
    tasks.forEach(task => {
        const item = document.createElement('div');
        item.className = 'task-item';
        const failed = task.ok === false;
        if (failed) item.classList.add('task-failed');
        else if (task.needs_review) item.classList.add('task-review');
        
        const categoryClass = {
            '寺院関係': 'temple',
            '青鳳会': 'seihoukai',
            '詠道部': 'eidoubu',
            '個人': 'personal'
        }[task.category] || 'personal';
        
        const deadlineText = task.deadline 
            ? new Date(task.deadline).toLocaleDateString('ja-JP', {
                timeZone: 'Asia/Tokyo',  // 期限は日本時間の日付
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            })
            : '期限なし';
        const timeText = task.due_time ? ` ${task.due_time}` : '';
        
        // 入力された文字は textContent で入れる（HTML として解釈させない）
        const title = document.createElement('div');
        title.className = 'task-title';
        title.textContent = task.title;
        item.appendChild(title);
        
        if (!failed) {
            const meta = document.createElement('div');
            meta.className = 'task-meta';
            const badge = document.createElement('span');
            badge.className = `badge badge-${categoryClass}`;
            badge.textContent = task.category;
            const deadline = document.createElement('span');
            deadline.className = 'deadline';
            deadline.textContent = `📅 ${deadlineText}${timeText}`;
            meta.append(badge, deadline);
            if (task.overdue) {
                const overdue = document.createElement('span');
                overdue.className = 'badge badge-overdue';
                overdue.textContent = '期限切れ';
                meta.appendChild(overdue);
            }
            if (task.needs_review) {
                const review = document.createElement('span');
                review.className = 'badge badge-review';
                review.textContent = '要確認';
                meta.appendChild(review);
            }
            item.appendChild(meta);
            
            // どの表現をどう読んだか（例: 「3/15まで」→ 2027年3月15日（日付））
            if (task.due_raw) {
                const reading = document.createElement('div');
                reading.className = 'task-reading';
                const how = task.due_type === 'unknown'
                    ? '期限として読めませんでした'
                    : `${deadlineText}${timeText}（${DUE_TYPE_LABELS[task.due_type] || task.due_type}）`;
                reading.textContent = `読み取り: 「${task.due_raw}」→ ${how}`;
                item.appendChild(reading);
            }
        }
        
        const notes = failed ? [task.error || '解析できませんでした'] : (task.warnings || []);
        notes.forEach(text => {
            const note = document.createElement('div');
            note.className = 'task-note';
            note.textContent = `⚠ ${text}`;
            item.appendChild(note);
        });
        
        taskList.appendChild(item);
    });
    
    results.classList.add('show');
}

// 同期ボタン
syncBtn.addEventListener('click', () => {
    alert('Google Calendar API連携は次のステップで実装します！\n\nGOOGLE_CALENDAR_SETUP.mdを参照してください。');
});

// 履歴読み込み
async function loadHistory() {
    const historyList = document.getElementById('historyList');
    const note = document.createElement('p');
    note.className = 'muted';
    note.textContent = 'データベース機能は実装中...';
    historyList.replaceChildren(note);
    
    // TODO: データベースAPIエンドポイント実装後に有効化（表示は textContent で組み立てる）
}

// 統計読み込み
async function loadStats() {
    document.getElementById('statTotal').textContent = '-';
    document.getElementById('statMonth').textContent = '-';
    document.getElementById('statSynced').textContent = '-';
    document.getElementById('statPending').textContent = '-';
    
    // TODO: データベースAPIエンドポイント実装後に有効化
}

// エラー表示
function showError(message) {
    error.textContent = message;
    error.classList.add('show');
    setTimeout(() => error.classList.remove('show'), 5000);
}

// 成功表示
function showSuccess(message) {
    success.textContent = message;
    success.classList.add('show');
    setTimeout(() => success.classList.remove('show'), 3000);
}

// PWA: Service Worker登録
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js')
        .then(reg => console.log('✅ Service Worker registered'))
        .catch(err => console.log('❌ Service Worker registration failed:', err));
}
