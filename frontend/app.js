// ============================================================
// 画面の動き（index.html から分けた）
// Content-Security-Policy で script-src 'self' にしているので、
// HTML の中に script を書かず、このファイルから読み込む。
// 入力や API の応答に由来する文字は textContent で入れる（HTML として解釈させない）。
// タスクの保存（B29）は端末の中（IndexedDB）だけ。外部には送らない（通信は解析の /api/parse-batch だけ）。
// 台帳の計算は task_core.js（TaskCore）、保存場所は store.js（TaskStore）、
// カレンダー用ファイル（.ics・B30）は ics.js（TaskIcs）。index.html で先に読み込む。
// ============================================================
'use strict';

(function () {
    const API_BASE = '';
    const TaskCore = window.TaskCore;
    const TaskStore = window.TaskStore;
    const TaskIcs = window.TaskIcs;
    const MAX_FILE_BYTES = 5 * 1024 * 1024;  // 読み込むファイル（JSON・CSV）の上限
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
    // カテゴリの印の色は、API の category_color（1〜6）で選ぶ（B27）。
    // カテゴリ名は設定（サーバーの CATEGORY_CONFIG_JSON など）で決めるので、画面には名前を書かない
    const CATEGORY_COLOR_COUNT = 6;
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

    // 端末に保存したタスク（B29）
    const saved = {
        store: null,       // TaskStore の保存先（IndexedDB か、一時の保存）
        warning: '',       // 一時の保存に切り替えた理由など
        tasks: [],
        lanes: TaskCore ? TaskCore.DEFAULT_LANES.slice() : [],
        lanesSaved: false, // この端末でレーン名を保存したことがあるか
        ready: Promise.resolve()
    };
    let lastObjectUrl = null;

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

    // 印の色のクラス（1〜6 以外は、色の無い 0）
    function categoryClass(color) {
        return Number.isInteger(color) && color >= 1 && color <= CATEGORY_COLOR_COUNT ? `badge-cat-${color}` : 'badge-cat-0';
    }

    // カテゴリの理由（当たった語）。当たった語が無ければ、決まりのカテゴリにしたと書く
    function categoryReason(task) {
        const hits = Array.isArray(task.category_hits) ? task.category_hits.filter(word => typeof word === 'string') : [];
        if (hits.length) return `カテゴリの理由: ${hits.map(word => `「${word}」`).join('')}`;
        return `カテゴリの理由: 当てはまる語が無いので「${task.category}」`;
    }

    function buildTaskItem(task) {
        const item = create('li', 'task-item');
        const failed = task.ok === false;
        if (failed) item.classList.add('task-failed');
        else if (task.needs_review) item.classList.add('task-review');

        const deadlineText = formatDeadline(task);
        const timeText = task.due_time ? ` ${task.due_time}` : '';

        // 入力された文字は textContent で入れる（HTML として解釈させない）
        const title = document.createElement('div');
        title.className = 'task-title';
        title.textContent = task.title;
        item.appendChild(title);

        if (!failed) {
            const meta = create('div', 'task-meta');
            const badge = create('span', `badge ${categoryClass(task.category_color)}`, task.category);
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

            // カテゴリをどの語で決めたか（B27）
            if (task.category) item.appendChild(create('div', 'task-reason', categoryReason(task)));
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

            // 本人の番・一覧のタブを開いたら、今の時刻で描き直す（2日以上動きなしの印）
            const tabName = tab.dataset.tab;
            if (tabName === 'mine' || tabName === 'tasks') saved.ready.then(renderSaved);
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

    // ------------------------------------------------------------
    // 端末に保存したタスク（B29）: 本人の番・一覧・書き出しと読み込み
    // ------------------------------------------------------------

    const now = () => new Date();

    function statusLabel(status) {
        return TaskCore.STATUS_LABELS[status] || status;
    }

    function notify(node, message) {
        if (node) node.textContent = message;
    }

    async function loadSaved() {
        if (!TaskCore || !TaskStore) {
            saved.warning = '保存の部品（task_core.js・store.js）を読み込めませんでした。読み込み直してください';
            renderSaved();
            return;
        }
        const opened = await TaskStore.openStore(window);
        saved.store = opened.store;
        if (opened.store.kind !== 'indexeddb') {
            saved.warning = `この端末では一時の保存です（${opened.reason}）。画面を閉じると消えるので、JSON に書き出して控えを取ってください`;
        }
        try {
            saved.tasks = await saved.store.getAll();
            const lanes = await saved.store.getSetting('lanes');
            saved.lanesSaved = Array.isArray(lanes);
            saved.lanes = TaskCore.normalizeLanes(lanes || []);
        } catch (err) {
            saved.warning = '保存したタスクを読み込めませんでした';
        }
        if (ui.lanesInput) ui.lanesInput.value = saved.lanes.join('\n');
        renderSaved();
    }

    function savedDeadline(task) {
        const text = formatDeadline({ deadline: task.deadline ? `${task.deadline}T00:00:00+09:00` : null });
        return task.due_time ? `${text} ${task.due_time}` : text;
    }

    function labelled(text, control, id) {
        const field = create('div', 'field');
        const label = create('label', null, text);
        label.setAttribute('for', id);
        control.id = id;
        field.append(label, control);
        return field;
    }

    function buildSavedItem(task, where) {
        const name = task.title;  // 読み上げの名前（aria-label）と知らせの文字にだけ使う。HTML としては入れない
        const item = create('li', 'task-item saved-item');
        item.setAttribute('data-id', task.id);
        const stale = TaskCore.isStale(task, now());
        if (stale) item.classList.add('task-stale');

        item.appendChild(create('div', 'task-title', task.title));
        const meta = create('div', 'task-meta');
        meta.appendChild(create('span', 'badge badge-lane', task.lane));
        if (where === 'tasks') meta.appendChild(create('span', 'badge badge-status', statusLabel(task.status)));
        const deadline = create('span', 'deadline');
        deadline.append(icon('📅'), ` ${savedDeadline(task)}`);
        meta.appendChild(deadline);
        if (stale) meta.appendChild(create('span', 'badge badge-stale', '2日以上動きなし'));
        item.appendChild(meta);

        // 次に本人がすること（入力を終えたら保存。描き直さないので、フォーカスはそのまま）
        const next = create('input');
        next.setAttribute('type', 'text');
        next.setAttribute('maxlength', String(TaskCore.LIMITS.text));
        next.setAttribute('data-field', 'next_action');
        next.value = task.next_action || '';
        next.addEventListener('change', () => editSaved(task.id, { next_action: next.value }, where));
        item.appendChild(labelled('次に本人がすること', next, `next-${where}-${task.id}`));

        if (where === 'tasks') {
            const lane = create('select');
            lane.setAttribute('data-field', 'lane');
            const names = saved.lanes.includes(task.lane) ? saved.lanes : saved.lanes.concat(task.lane);
            names.forEach(laneName => {
                const option = create('option', null, laneName);
                option.setAttribute('value', laneName);
                lane.appendChild(option);
            });
            lane.value = task.lane;
            lane.addEventListener('change', () => editSaved(task.id, { lane: lane.value }, where));
            item.appendChild(labelled('レーン', lane, `lane-${where}-${task.id}`));
        }

        // 状態を変えるボタン（今の状態以外の3つ）
        const controls = create('div', 'task-controls');
        controls.setAttribute('role', 'group');
        controls.setAttribute('aria-label', `「${name}」の状態（今は${statusLabel(task.status)}）`);
        TaskCore.STATUSES.filter(status => status !== task.status).forEach(status => {
            const button = create('button', 'btn-small', `${statusLabel(status)}にする`);
            button.setAttribute('type', 'button');
            button.setAttribute('data-status', status);
            button.setAttribute('aria-label', `「${name}」を${statusLabel(status)}にする`);
            button.addEventListener('click', () => changeStatus(task.id, status, where));
            controls.appendChild(button);
        });
        if (where === 'tasks') {
            const remove = create('button', 'btn-small btn-danger', '削除');
            remove.setAttribute('type', 'button');
            remove.setAttribute('aria-label', `「${name}」を削除`);
            remove.addEventListener('click', () => removeSaved(task.id));
            controls.appendChild(remove);
        }
        item.appendChild(controls);
        return item;
    }

    // 本人の番の一覧（携帯で見る画面）
    function renderMine() {
        const at = now();
        const mine = TaskCore.myTurnList(saved.tasks, at);
        const staleCount = mine.filter(task => TaskCore.isStale(task, at)).length;
        ui.mineList.replaceChildren(...mine.map(task => buildSavedItem(task, 'mine')));
        notify(ui.mineSummary, mine.length
            ? `本人の番は ${mine.length}件です${staleCount ? `（2日以上動きなし ${staleCount}件）` : ''}`
            : '本人の番のタスクはありません。「一覧」で「本人の番にする」を押すと、ここに出ます');
    }

    // 保存したタスクの全部
    function renderAll() {
        const all = TaskCore.sortTasks(saved.tasks);
        ui.allList.replaceChildren(...all.map(task => buildSavedItem(task, 'tasks')));
        const counts = TaskCore.STATUSES.map(status => `${statusLabel(status)} ${all.filter(t => t.status === status).length}`);
        notify(ui.tasksSummary, all.length
            ? `${all.length}件（${counts.join('・')}）`
            : 'まだありません。「解析」で解析して「端末に保存」を押すと、ここに出ます');
    }

    function renderSaved() {
        if (!ui) return;
        notify(ui.storageWarning, saved.warning);
        if (!TaskCore) return;
        renderMine();
        renderAll();
    }

    function noticeFor(where) {
        return where === 'mine' ? ui.mineNotice : ui.tasksNotice;
    }

    // 1件を直して保存する。変わらなければ null
    async function updateSaved(id, changes, where) {
        const index = saved.tasks.findIndex(task => task.id === id);
        if (index < 0) return null;
        let next;
        try {
            next = TaskCore.applyChange(saved.tasks[index], changes, now());
        } catch (err) {
            notify(noticeFor(where), err.message);
            return null;
        }
        if (next === saved.tasks[index]) return null;
        // 先に手元の値を新しくする（入力の直後に状態のボタンを押しても、前の変更を消さない）
        const previous = saved.tasks[index];
        saved.tasks[index] = next;
        try {
            await saved.store.put(next);
        } catch (err) {
            if (saved.tasks[index] === next) saved.tasks[index] = previous;
            notify(noticeFor(where), '保存できませんでした。もう一度試してください');
            return null;
        }
        return next;
    }

    // 次に本人がすること・レーン: 今の一覧は描き直さず（入力中のフォーカスを保つ）、印だけを外す
    async function editSaved(id, changes, where) {
        const next = await updateSaved(id, changes, where);
        if (!next) return;
        const list = where === 'mine' ? ui.mineList : ui.allList;
        const item = list.querySelector(`[data-id="${id}"]`);
        if (item) {
            item.classList.remove('task-stale');
            const badge = item.querySelector('.badge-stale');
            if (badge) badge.remove();
        }
        if (where === 'mine') renderAll();
        else renderMine();
        notify(noticeFor(where), `「${next.title}」を保存しました`);
    }

    async function changeStatus(id, status, where) {
        const next = await updateSaved(id, { status }, where);
        if (!next) return;
        renderSaved();
        notify(noticeFor(where), `「${next.title}」を${statusLabel(status)}にしました`);
        // 同じ一覧に残っていれば、そのタスクの最初のボタンへ。消えたら見出しへ
        const list = where === 'mine' ? ui.mineList : ui.allList;
        const item = list.querySelector(`[data-id="${id}"]`);
        const target = item ? item.querySelector('button') : (where === 'mine' ? ui.mineHeading : ui.tasksHeading);
        if (target) target.focus();
    }

    async function removeSaved(id) {
        const task = saved.tasks.find(t => t.id === id);
        if (!task) return;
        const name = task.title;
        if (!window.confirm(`「${name}」を削除しますか。元に戻せません`)) return;
        try {
            await saved.store.remove(id);
        } catch (err) {
            notify(ui.tasksNotice, '削除できませんでした');
            return;
        }
        saved.tasks = saved.tasks.filter(t => t.id !== id);
        renderSaved();
        notify(ui.tasksNotice, `「${name}」を削除しました`);
        if (ui.tasksHeading) ui.tasksHeading.focus();
    }

    // 解析の結果を端末に保存する（一度保存した行は、もう一度は保存しない）。
    // 返す値: { created: 新しく保存したタスク, skipped: 件名が無く保存しなかった数, error: 失敗の文言 }
    async function storeParsed() {
        await saved.ready;
        if (!saved.store) return { created: [], skipped: 0, error: saved.warning || '保存できません' };
        const rows = parsedTasks.filter(row => row.ok !== false && !row.savedId);
        const at = now();
        const created = [];
        let skipped = 0;
        rows.forEach(row => {
            try {
                const task = TaskCore.createTask(row, { id: TaskCore.newUuid(window.crypto), now: at, lane: saved.lanes[0] });
                row.savedId = task.id;
                created.push(task);
            } catch (err) {
                skipped += 1;  // 件名の無い行など
            }
        });
        if (created.length === 0) return { created, skipped, error: '' };
        try {
            await saved.store.putMany(created);
        } catch (err) {
            created.forEach(task => { const row = parsedTasks.find(r => r.savedId === task.id); if (row) delete row.savedId; });
            return { created: [], skipped, error: '端末に保存できませんでした' };
        }
        saved.tasks = saved.tasks.concat(created);
        renderSaved();
        TaskStore.requestPersistence(window);
        return { created, skipped, error: '' };
    }

    function savedNote(result) {
        const note = saved.store && saved.store.kind !== 'indexeddb' ? '（一時の保存です。画面を閉じると消えます）' : '';
        const skipped = result.skipped ? `（件名の無い${result.skipped}件は保存していません）` : '';
        return `${result.created.length}件を端末に保存しました${skipped}${note}`;
    }

    async function saveParsed() {
        const result = await storeParsed();
        if (result.error) {
            showError(result.error);
        } else if (result.created.length === 0) {
            showSuccess(parsedTasks.some(row => row.savedId) ? 'この結果は、もう端末に保存してあります' : '保存できるタスクがありません');
        } else {
            showSuccess(`${savedNote(result)}。「本人の番」「一覧」で状態を変えられます`);
        }
    }

    function fileStamp(at) {
        return TaskCore.jstDate(at).replace(/-/g, '');
    }

    // ファイルとして保存する（ブラウザの中で作る。送信はしない）
    function downloadText(filename, text, type) {
        if (lastObjectUrl) URL.revokeObjectURL(lastObjectUrl);
        lastObjectUrl = URL.createObjectURL(new Blob([text], { type }));
        const link = create('a');
        link.setAttribute('href', lastObjectUrl);
        link.setAttribute('download', filename);
        link.hidden = true;
        document.body.appendChild(link);
        link.click();
        link.remove();
    }

    async function exportJson() {
        await saved.ready;
        if (!saved.tasks.length) {
            notify(ui.ioNotice, '保存したタスクがありません');
            return;
        }
        const at = now();
        const backup = TaskCore.makeBackup(TaskCore.sortTasks(saved.tasks), { lanes: saved.lanes }, at);
        const filename = `task-sync-${fileStamp(at)}.json`;
        downloadText(filename, JSON.stringify(backup, null, 2) + '\n', 'application/json');
        notify(ui.ioNotice, `${saved.tasks.length}件を ${filename} に書き出しました`);
    }

    async function readChosenFile(input, notice) {
        const file = input.files && input.files[0];
        if (!file) return null;
        if (file.size > MAX_FILE_BYTES) {
            notify(notice, 'ファイルが大きすぎます（5MB まで）');
            return null;
        }
        try {
            return await file.text();
        } catch (err) {
            notify(notice, 'ファイルを読めませんでした');
            return null;
        }
    }

    async function importJson() {
        await saved.ready;
        const text = await readChosenFile(ui.importJsonInput, ui.ioNotice);
        ui.importJsonInput.value = '';  // 同じファイルをもう一度選べるように
        if (text === null) return;
        let read;
        try {
            read = TaskCore.readBackup(text);
        } catch (err) {
            notify(ui.ioNotice, err.message);
            return;
        }
        const merged = TaskCore.mergeTasks(saved.tasks, read.tasks);
        try {
            await saved.store.putMany(merged.changed);
            if (read.lanes && !saved.lanesSaved) {
                await saved.store.setSetting('lanes', read.lanes);
                saved.lanes = read.lanes;
                saved.lanesSaved = true;
                ui.lanesInput.value = saved.lanes.join('\n');
            }
        } catch (err) {
            notify(ui.ioNotice, '読み込んだタスクを保存できませんでした');
            return;
        }
        saved.tasks = merged.tasks;
        renderSaved();
        notify(ui.ioNotice, `読み込みました: 足した ${merged.added}件・新しくした ${merged.updated}件・そのまま ${merged.unchanged}件`
            + (read.invalid ? `（読めなかった ${read.invalid}件は飛ばしました）` : ''));
    }

    async function copyLedger(kind) {
        await saved.ready;
        ui.copyFallback.hidden = true;
        if (!saved.tasks.length) {
            notify(ui.ioNotice, '保存したタスクがありません');
            return;
        }
        const rows = TaskCore.toLedgerRows(TaskCore.sortTasks(saved.tasks));
        const text = kind === 'csv' ? TaskCore.toCsv(rows) : TaskCore.toMarkdownTable(rows);
        const what = kind === 'csv' ? 'CSV' : 'Markdown の表';
        try {
            if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') throw new Error('no clipboard');
            await navigator.clipboard.writeText(text);
            notify(ui.ioNotice, `${rows.length}件を台帳の形（${what}）でコピーしました`);
        } catch (err) {
            // http の LAN などクリップボードが使えないときは、選んでコピーできる欄に出す
            ui.copyFallbackText.value = text;
            ui.copyFallback.hidden = false;
            ui.copyFallbackText.focus();
            ui.copyFallbackText.select();
            notify(ui.ioNotice, `自動ではコピーできませんでした。下の欄の${what}を選んでコピーしてください`);
        }
    }

    function buildNotionItem(row) {
        const item = create('li', 'task-item');
        if (row.stale) item.classList.add('task-stale');
        item.appendChild(create('div', 'task-title', row.title));
        const meta = create('div', 'task-meta');
        if (row.lane) meta.appendChild(create('span', 'badge badge-lane', row.lane));
        if (row.updated) meta.appendChild(create('span', 'deadline', `更新日 ${row.updated}`));
        if (row.stale) meta.appendChild(create('span', 'badge badge-stale', '2日以上動きなし'));
        if (row.turn_missing) meta.appendChild(create('span', 'badge badge-review', '本人の番の欄が空'));
        item.appendChild(meta);
        if (row.next_action) item.appendChild(create('div', 'task-next', `本人の番: ${row.next_action}`));
        return item;
    }

    async function showNotionCsv() {
        const text = await readChosenFile(ui.notionCsvInput, ui.notionNotice);
        if (text === null) return;
        let result;
        try {
            result = TaskCore.readNotionCsv(text, now());
        } catch (err) {
            ui.notionList.replaceChildren();
            notify(ui.notionNotice, err.message);
            return;
        }
        ui.notionList.replaceChildren(...result.items.map(buildNotionItem));
        const stale = result.items.filter(row => row.stale).length;
        notify(ui.notionNotice, `全 ${result.total}行のうち、本人の番は ${result.items.length}行です`
            + (stale ? `（2日以上動きなし ${stale}行）` : ''));
    }

    async function saveLanes() {
        await saved.ready;
        const lanes = TaskCore.normalizeLanes(ui.lanesInput.value);
        try {
            await saved.store.setSetting('lanes', lanes);
        } catch (err) {
            notify(ui.lanesNotice, 'レーン名を保存できませんでした');
            return;
        }
        saved.lanes = lanes;
        saved.lanesSaved = true;
        ui.lanesInput.value = lanes.join('\n');
        renderSaved();
        notify(ui.lanesNotice, `レーン名を保存しました（${lanes.join('・')}）`);
    }

    function setupSaved() {
        ui.saveBtn.addEventListener('click', saveParsed);
        ui.exportJsonBtn.addEventListener('click', exportJson);
        ui.importJsonInput.addEventListener('change', importJson);
        ui.copyMarkdownBtn.addEventListener('click', () => copyLedger('markdown'));
        ui.copyCsvBtn.addEventListener('click', () => copyLedger('csv'));
        ui.notionCsvInput.addEventListener('change', showNotionCsv);
        ui.saveLanesBtn.addEventListener('click', saveLanes);
        saved.ready = loadSaved().catch(() => {
            saved.warning = '保存したタスクを読み込めませんでした';
            renderSaved();
        });
    }

    // ------------------------------------------------------------
    // カレンダー用ファイル（.ics）（B30）: 端末の中で作って保存する。送信も OAuth もしない
    // ------------------------------------------------------------

    const ICS_MISSING = 'カレンダー用ファイルの部品（ics.js）を読み込めませんでした。読み込み直してください';

    // 作ったファイルの説明（入れなかったものの数）
    function icsSkippedNote(skipped) {
        const parts = [];
        if (skipped.no_deadline) parts.push(`期限の無い${skipped.no_deadline}件`);
        if (skipped.done) parts.push(`完了の${skipped.done}件`);
        return parts.length ? `（${parts.join('・')}は入れていません）` : '';
    }

    // ファイルを作って保存する。作れたら件数を、予定が無ければ 0 を返す
    function downloadIcs(tasks) {
        const at = now();
        const built = TaskIcs.buildIcs(tasks, { now: at });
        if (built.count === 0) return { count: 0, filename: '', skipped: built.skipped };
        const filename = `task-sync-${fileStamp(at)}.ics`;
        downloadText(filename, built.text, 'text/calendar;charset=utf-8');
        return { count: built.count, filename, skipped: built.skipped };
    }

    // 解析の結果から: 先に端末に保存して固定の ID を振り、その ID を UID にする
    async function saveParsedIcs() {
        if (!TaskIcs) {
            showError(ICS_MISSING);
            return;
        }
        const stored = await storeParsed();
        if (stored.error) {
            showError(stored.error);
            return;
        }
        const tasks = parsedTasks
            .map(row => row.savedId && saved.tasks.find(task => task.id === row.savedId))
            .filter(Boolean);
        const result = downloadIcs(tasks);
        const savedText = stored.created.length ? `${savedNote(stored)}。` : '';
        if (result.count === 0) {
            showError(`${savedText}期限のあるタスクが無いので、カレンダー用ファイルは作りませんでした`);
            return;
        }
        showSuccess(`${savedText}${result.count}件の予定をカレンダー用ファイル（${result.filename}）にしました${icsSkippedNote(result.skipped)}。`
            + 'カレンダーのアプリで読み込んでください');
    }

    // 一覧から: 期限のある未完了のタスクを全部
    async function saveAllIcs() {
        await saved.ready;
        if (!TaskIcs) {
            notify(ui.ioNotice, ICS_MISSING);
            return;
        }
        if (!saved.tasks.length) {
            notify(ui.ioNotice, '保存したタスクがありません');
            return;
        }
        const result = downloadIcs(saved.tasks);
        if (result.count === 0) {
            notify(ui.ioNotice, `期限のある未完了のタスクが無いので、カレンダー用ファイルは作りませんでした${icsSkippedNote(result.skipped)}`);
            return;
        }
        notify(ui.ioNotice, `${result.count}件の予定をカレンダー用ファイル（${result.filename}）にしました${icsSkippedNote(result.skipped)}`);
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
            icsBtn: byId('icsBtn'),
            icsAllBtn: byId('icsAllBtn'),
            loading: byId('loading'),
            error: byId('error'),
            success: byId('success'),
            results: byId('results'),
            taskList: byId('taskList'),
            installPrompt: byId('installPrompt'),
            installBtn: byId('installBtn'),
            updateBanner: byId('updateBanner'),
            saveBtn: byId('saveBtn'),
            mineHeading: byId('mineHeading'),
            mineSummary: byId('mineSummary'),
            mineNotice: byId('mineNotice'),
            mineList: byId('mineList'),
            notionCsvInput: byId('notionCsvInput'),
            notionNotice: byId('notionNotice'),
            notionList: byId('notionList'),
            tasksHeading: byId('tasksHeading'),
            storageWarning: byId('storageWarning'),
            tasksSummary: byId('tasksSummary'),
            tasksNotice: byId('tasksNotice'),
            allList: byId('allList'),
            exportJsonBtn: byId('exportJsonBtn'),
            copyMarkdownBtn: byId('copyMarkdownBtn'),
            copyCsvBtn: byId('copyCsvBtn'),
            importJsonInput: byId('importJsonInput'),
            ioNotice: byId('ioNotice'),
            copyFallback: byId('copyFallback'),
            copyFallbackText: byId('copyFallbackText'),
            lanesInput: byId('lanesInput'),
            saveLanesBtn: byId('saveLanesBtn'),
            lanesNotice: byId('lanesNotice')
        };

        setupTabs();
        ui.parseBtn.addEventListener('click', onParse);
        setupSaved();

        // カレンダー用ファイル（.ics）。前の「Googleカレンダーに同期」（未実装の案内だけ）を置きかえた（B30）
        ui.icsBtn.addEventListener('click', saveParsedIcs);
        ui.icsAllBtn.addEventListener('click', saveAllIcs);

        setupInstallPrompt();
        registerServiceWorker();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
