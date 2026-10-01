// ============================================================
// 画面の動き（index.html から分けた）
// Content-Security-Policy で script-src 'self' にしているので、
// HTML の中に script を書かず、このファイルから読み込む。
// 入力や API の応答に由来する文字は textContent で入れる（HTML として解釈させない）。
// ============================================================
'use strict';

(function () {
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
    // カテゴリ（API の値）→ 印の色のクラス
    const CATEGORY_CLASSES = {
        '寺院関係': 'temple',
        '青鳳会': 'seihoukai',
        '詠道部': 'eidoubu',
        '個人': 'personal'
    };
    // 利用者に見せる文言（読み上げにも使う）
    const MESSAGES = {
        loading: '解析中…',
        empty: 'タスクを入力してください',
        noTasks: '有効なタスクがありません',
        tooLong: '入力が長すぎるか、行が多すぎます（1行500文字・200行まで）',
        failed: '解析に失敗しました',
        offline: 'オフラインのため解析できません。電波のよい所で、もう一度「解析する」を押してください',
        network: 'サーバーにつながりませんでした。少し待ってから、もう一度「解析する」を押してください'
    };

    let parsedTasks = [];
    let deferredPrompt = null;
    let busy = false;
    let ui = null;

    // 要素を作る（文字は textContent で入れる）
    function create(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    // 読み上げない飾りの絵文字
    function icon(symbol) {
        const node = create('span', null, symbol);
        node.setAttribute('aria-hidden', 'true');
        return node;
    }

    function isOffline() {
        return typeof navigator !== 'undefined' && navigator.onLine === false;
    }

    // ------------------------------------------------------------
    // 結果の表示
    // ------------------------------------------------------------

    function formatDeadline(task) {
        if (!task.deadline) return '期限なし';
        return new Date(task.deadline).toLocaleDateString('ja-JP', {
            timeZone: 'Asia/Tokyo',  // 期限は日本時間の日付
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    }

    function buildTaskItem(task) {
        const item = create('li', 'task-item');
        const failed = task.ok === false;
        if (failed) item.classList.add('task-failed');
        else if (task.needs_review) item.classList.add('task-review');

        const categoryClass = CATEGORY_CLASSES[task.category] || 'personal';
        const deadlineText = formatDeadline(task);
        const timeText = task.due_time ? ` ${task.due_time}` : '';

        // 入力された文字は textContent で入れる（HTML として解釈させない）
        const title = document.createElement('div');
        title.className = 'task-title';
        title.textContent = task.title;
        item.appendChild(title);

        if (!failed) {
            const meta = create('div', 'task-meta');
            const badge = create('span', `badge badge-${categoryClass}`, task.category);
            const deadline = create('span', 'deadline');
            deadline.append(icon('📅'), ` ${deadlineText}${timeText}`);
            meta.append(badge, deadline);
            if (task.overdue) {
                const overdue = create('span', 'badge badge-overdue');
                overdue.textContent = '期限切れ';
                meta.appendChild(overdue);
            }
            if (task.needs_review) {
                const review = create('span', 'badge badge-review');
                review.textContent = '要確認';
                meta.appendChild(review);
            }
            item.appendChild(meta);

            // どの表現をどう読んだか（例: 「3/15まで」→ 2027年3月15日（日付））
            if (task.due_raw) {
                const reading = create('div', 'task-reading');
                const how = task.due_type === 'unknown'
                    ? '期限として読めませんでした'
                    : `${deadlineText}${timeText}（${DUE_TYPE_LABELS[task.due_type] || task.due_type}）`;
                reading.textContent = `読み取り: 「${task.due_raw}」→ ${how}`;
                item.appendChild(reading);
            }
        }

        const notes = failed ? [task.error || '解析できませんでした'] : (task.warnings || []);
        notes.forEach(text => {
            const note = create('div', 'task-note');
            note.append(icon('⚠'), ` ${text}`);
            item.appendChild(note);
        });

        return item;
    }

    function displayResults(tasks) {
        ui.taskList.replaceChildren();  // 前の結果を消す
        tasks.forEach(task => ui.taskList.appendChild(buildTaskItem(task)));
        ui.results.classList.add('show');
    }

    // ------------------------------------------------------------
    // 知らせ（aria-live で読み上げる。自動では消さず、次の操作で入れ替える）
    // ------------------------------------------------------------

    function showError(message) {
        ui.success.textContent = '';
        ui.error.textContent = message;
    }

    function showSuccess(message) {
        ui.error.textContent = '';
        ui.success.textContent = message;
    }

    function clearNotices() {
        ui.error.textContent = '';
        ui.success.textContent = '';
    }

    function setBusy(on) {
        busy = on;
        ui.loading.textContent = on ? MESSAGES.loading : '';
        // disabled にするとキーボードの位置が失われるので、aria-disabled で押せないことを伝える
        ui.parseBtn.setAttribute('aria-disabled', on ? 'true' : 'false');
        ui.results.setAttribute('aria-busy', on ? 'true' : 'false');
    }

    // ------------------------------------------------------------
    // 解析
    // ------------------------------------------------------------

    async function requestParse(tasks) {
        let response;
        try {
            response = await fetch(`${API_BASE}/api/parse-batch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tasks })
            });
        } catch (err) {
            throw new Error(isOffline() ? MESSAGES.offline : MESSAGES.network);
        }

        if (response.status === 422) throw new Error(MESSAGES.tooLong);
        if (response.status === 503) {
            // Service Worker が返すオフラインの応答（{ offline: true }）
            const body = await response.json().catch(() => null);
            if (body && body.offline) throw new Error(MESSAGES.offline);
        }
        if (!response.ok) throw new Error(MESSAGES.failed);
        return response.json();
    }

    async function onParse() {
        if (busy) return;
        const text = ui.taskInput.value.trim();
        clearNotices();

        if (!text) {
            showError(MESSAGES.empty);
            ui.taskInput.focus();
            return;
        }

        const tasks = text.split('\n').filter(t => t.trim());
        if (tasks.length === 0) {
            showError(MESSAGES.noTasks);
            return;
        }

        setBusy(true);
        ui.results.classList.remove('show');

        try {
            parsedTasks = await requestParse(tasks);
            displayResults(parsedTasks);
            const failedCount = parsedTasks.filter(t => t.ok === false).length;
            const okCount = parsedTasks.length - failedCount;
            showSuccess(failedCount
                ? `${okCount}件のタスクを解析しました（${failedCount}件は解析できませんでした）`
                : `${okCount}件のタスクを解析しました`);
        } catch (err) {
            showError('エラーが発生しました: ' + err.message);
        } finally {
            setBusy(false);
        }
    }

    // ------------------------------------------------------------
    // タブ（WAI-ARIA のタブの型: 矢印キー・Home・End で移り、移った先を表示する）
    // ------------------------------------------------------------

    function setupTabs() {
        const tabs = Array.from(document.querySelectorAll('[role="tab"]'));

        function select(tab, moveFocus) {
            tabs.forEach(t => {
                const selected = t === tab;
                t.setAttribute('aria-selected', selected ? 'true' : 'false');
                t.setAttribute('tabindex', selected ? '0' : '-1');
                const panel = document.getElementById(t.getAttribute('aria-controls'));
                if (panel) panel.hidden = !selected;
            });
            if (moveFocus) tab.focus();

            // 履歴・統計タブを開いたらデータ読み込み
            const tabName = tab.dataset.tab;
            if (tabName === 'history') loadHistory();
            if (tabName === 'stats') loadStats();
        }

        tabs.forEach((tab, index) => {
            tab.addEventListener('click', () => select(tab, false));
            tab.addEventListener('keydown', event => {
                let next = null;
                if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
                else if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
                else if (event.key === 'Home') next = tabs[0];
                else if (event.key === 'End') next = tabs[tabs.length - 1];
                if (!next) return;
                event.preventDefault();
                select(next, true);
            });
        });
    }

    // 履歴読み込み
    async function loadHistory() {
        const historyList = document.getElementById('historyList');
        historyList.replaceChildren(create('p', 'muted', 'データベース機能は実装中...'));
        // TODO: データベースAPIエンドポイント実装後に有効化（表示は textContent で組み立てる）
    }

    // 統計読み込み
    async function loadStats() {
        ['statTotal', 'statMonth', 'statSynced', 'statPending'].forEach(id => {
            document.getElementById(id).textContent = '-';
        });
        // TODO: データベースAPIエンドポイント実装後に有効化
    }

    // ------------------------------------------------------------
    // PWA（ホーム画面への追加・Service Worker）
    // ------------------------------------------------------------

    function setupInstallPrompt() {
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            deferredPrompt = e;
            ui.installPrompt.classList.add('show');
        });

        ui.installBtn.addEventListener('click', async () => {
            if (!deferredPrompt) return;
            deferredPrompt.prompt();
            await deferredPrompt.userChoice;
            deferredPrompt = null;
            ui.installPrompt.classList.remove('show');
        });
    }

    // 新しい版（sw.js）が入って待っているとき、「新しい版があります」と「更新する」を出す
    function showUpdateNotice(worker, onAccept) {
        const banner = ui.updateBanner;
        if (!banner || banner.childNodes.length > 0) return;  // 出すのは1回だけ
        const button = create('button', null, '更新する');
        button.setAttribute('type', 'button');
        button.addEventListener('click', () => {
            button.setAttribute('aria-disabled', 'true');
            onAccept();
            worker.postMessage({ type: 'SKIP_WAITING' });
        });
        banner.append(create('span', null, '新しい版があります。'), button);
    }

    function registerServiceWorker() {
        if (!('serviceWorker' in navigator)) return;
        const sw = navigator.serviceWorker;
        let updateAccepted = false;
        let reloading = false;

        // 「更新する」を押して新しい版に切り替わったら、読み込み直す。
        // 初めて入れたとき（押していないとき）は読み込み直さない
        sw.addEventListener('controllerchange', () => {
            if (!updateAccepted || reloading) return;
            reloading = true;
            window.location.reload();
        });

        const accept = () => { updateAccepted = true; };
        sw.register('/sw.js')
            .then(reg => {
                // 前に開いたときから待っている新しい版
                if (reg.waiting && sw.controller) showUpdateNotice(reg.waiting, accept);
                reg.addEventListener('updatefound', () => {
                    const worker = reg.installing;
                    if (!worker) return;
                    worker.addEventListener('statechange', () => {
                        // 今の版が動いている（controller がある）ときだけ「新しい版」と言う
                        if (worker.state === 'installed' && sw.controller) showUpdateNotice(worker, accept);
                    });
                });
            })
            .catch(err => console.warn('Service Worker を登録できませんでした:', err));
    }

    function init() {
        const byId = id => document.getElementById(id);
        ui = {
            taskInput: byId('taskInput'),
            parseBtn: byId('parseBtn'),
            syncBtn: byId('syncBtn'),
            loading: byId('loading'),
            error: byId('error'),
            success: byId('success'),
            results: byId('results'),
            taskList: byId('taskList'),
            installPrompt: byId('installPrompt'),
            installBtn: byId('installBtn'),
            updateBanner: byId('updateBanner')
        };

        setupTabs();
        ui.parseBtn.addEventListener('click', onParse);

        // 同期ボタン
        ui.syncBtn.addEventListener('click', () => {
            alert('Google Calendar API連携は次のステップで実装します！\n\nGOOGLE_CALENDAR_SETUP.mdを参照してください。');
        });

        setupInstallPrompt();
        registerServiceWorker();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
