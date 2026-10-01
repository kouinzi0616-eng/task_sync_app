// ============================================================
// frontend/app.js を偽 DOM（fake_dom.mjs）の上で動かして、画面の動きを確かめる。
// 結果は JSON で標準出力に出す（tests/test_b28_frontend_js.py が読む）。
// 外部には送信しない（fetch は偽物）。入力はすべて架空の文字列。
// 使い方: node tests/frontend/app_checks.mjs
//   TSA_APP_JS=別のファイル を付けると、そのファイルを app.js の代わりに動かす（検査が働くかの確認用）
// index.html と同じ順に task_core.js・store.js・app.js を読み込む。偽の環境には IndexedDB が無いので、
// 保存は一時の保存（store.js の memoryStore）になる（IndexedDB そのものは実ブラウザで確かめる）。
// ============================================================
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import vm from 'node:vm';
import { FakeDocument, FakeEvent, parseHTML } from './fake_dom.mjs';

const ROOT = new URL('../../', import.meta.url);
const INDEX_HTML = readFileSync(new URL('frontend/index.html', ROOT), 'utf8');
const APP_JS = readFileSync(process.env.TSA_APP_JS || new URL('frontend/app.js', ROOT), 'utf8');
// index.html が app.js より先に読み込む画面の JS（読み込む順も index.html から取る）
const HELPER_SCRIPTS = Array.from(INDEX_HTML.matchAll(/<script src="\/([\w.]+)" defer><\/script>/g), m => m[1])
    .filter(name => name !== 'app.js')
    .map(name => ({ name, source: readFileSync(new URL(`frontend/${name}`, ROOT), 'utf8') }));

// 架空の攻撃文字列（画像の読み込み失敗でスクリプトを動かそうとする形）
const XSS_IMG = '<img src=x onerror="window.__xss=1">';
const XSS_SCRIPT = '<script>window.__xss=2</script>';

const results = [];

function check(name, ok, detail = '') {
    results.push({ name, ok: Boolean(ok), detail: ok ? '' : String(detail) });
}

const flush = async (times = 5) => {
    for (let i = 0; i < times; i++) await new Promise(resolve => setImmediate(resolve));
};

// 本物の fetch と同じく、json() は毎回新しいオブジェクトを返す
function jsonResponse(status, body) {
    return { ok: status >= 200 && status < 300, status, json: async () => JSON.parse(JSON.stringify(body)) };
}

function makeEmitter(extra = {}) {
    const listeners = {};
    return Object.assign({
        listeners,
        addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
        emit(type, event = {}) { for (const fn of listeners[type] || []) fn(event); }
    }, extra);
}

function setup({ fetchImpl, onLine = true, serviceWorker, clipboard, confirmAnswer = true } = {}) {
    const document = parseHTML(new FakeDocument(), INDEX_HTML);
    const timers = [];
    const reloads = [];
    const fetchCalls = [];
    const downloads = [];
    const confirms = [];
    const alerts = [];
    const navigator = { onLine };
    if (serviceWorker) navigator.serviceWorker = serviceWorker;
    if (clipboard) navigator.clipboard = clipboard;
    class FakeBlob {
        constructor(parts, options = {}) {
            this.text = parts.join('');
            this.type = options.type || '';
        }
    }
    const blobs = new Map();
    const sandbox = {
        document,
        navigator,
        console: { log() {}, warn() {}, error() {} },
        fetch: (url, init) => {
            fetchCalls.push({ url, init });
            return fetchImpl ? fetchImpl(url, init) : Promise.reject(new TypeError('Failed to fetch'));
        },
        setTimeout: (...args) => { timers.push(args); return timers.length; },
        setInterval: (...args) => { timers.push(args); return timers.length; },
        alert: message => { alerts.push(message); },
        confirm: message => { confirms.push(message); return confirmAnswer; },
        location: { reload: () => reloads.push(1) },
        addEventListener: () => {},
        crypto: webcrypto,
        Blob: FakeBlob,
        URL: {
            createObjectURL: blob => { const url = `blob:fake/${blobs.size + 1}`; blobs.set(url, blob); return url; },
            revokeObjectURL: () => {}
        }
    };
    sandbox.window = sandbox;
    // ダウンロード用のリンクが押されたら、ファイル名と中身を記録する（実際には保存しない）
    document.body.addEventListener('click', event => {
        const link = event.target;
        if (link.tagName !== 'A' || !link.hasAttribute('download')) return;
        const blob = blobs.get(link.getAttribute('href'));
        downloads.push({ name: link.getAttribute('download'), type: blob && blob.type, text: blob && blob.text });
    });
    vm.createContext(sandbox);
    for (const helper of HELPER_SCRIPTS) vm.runInContext(helper.source, sandbox, { filename: `frontend/${helper.name}` });
    vm.runInContext(APP_JS, sandbox, { filename: 'frontend/app.js' });
    const $ = id => document.getElementById(id);
    return { document, sandbox, timers, reloads, fetchCalls, downloads, confirms, alerts, $ };
}

// ------------------------------------------------------------
// 1. HTML を混ぜた入力・応答を、文字のまま表示する
// ------------------------------------------------------------
async function xssIsShownAsText() {
    const rows = [
        {
            ok: true, title: `${XSS_IMG}架空の資料作り`, deadline: '2027-03-15T00:00:00+09:00',
            category: '個人', raw_text: '', warnings: [`注意 ${XSS_SCRIPT}`],
            due_type: 'exact', due_raw: `3/15まで${XSS_IMG}`, due_time: null, needs_review: true, overdue: false
        },
        {
            ok: true, title: '架空の片付け', deadline: null, category: XSS_IMG, raw_text: '', warnings: [],
            due_type: 'none', due_raw: '', due_time: null, needs_review: false, overdue: false
        },
        {
            ok: false, title: XSS_SCRIPT, raw_text: XSS_SCRIPT, warnings: [], error: `理由 ${XSS_IMG}`,
            due_type: null, due_raw: '', due_time: null, needs_review: true, overdue: false
        }
    ];
    const env = setup({ fetchImpl: async () => jsonResponse(200, rows) });
    env.$('taskInput').value = `${XSS_IMG}架空の資料作り (3/15まで)\n架空の片付け\n${XSS_SCRIPT}`;
    env.$('parseBtn').click();
    await flush();

    const items = env.$('taskList').children;
    check('xss: 3行とも表示する', items.length === 3, `items=${items.length}`);
    check('xss: img・script の要素を作らない',
        !env.document.createdTags.includes('IMG') && !env.document.createdTags.includes('SCRIPT'),
        env.document.createdTags.join(','));
    check('xss: 画面の木に img が無い',
        env.document.allElements().every(e => e.tagName !== 'IMG'), 'IMG がある');
    check('xss: HTML として解釈させる書き方を使わない',
        env.document.htmlSinkUses.length === 0, env.document.htmlSinkUses.join(' / '));
    check('xss: 題名は文字のまま', items[0] && items[0].querySelector('.task-title').textContent === rows[0].title,
        items[0] && items[0].querySelector('.task-title').textContent);
    check('xss: 読み取りの括弧の中身も文字のまま',
        items[0] && items[0].querySelector('.task-reading').textContent.includes(rows[0].due_raw));
    check('xss: 注意も文字のまま', items[0] && items[0].querySelector('.task-note').textContent.includes(XSS_SCRIPT));
    check('xss: 色の番号が無いカテゴリは色 0 で、名前は文字のまま',
        items[1] && items[1].querySelector('.badge').className === 'badge badge-cat-0'
        && items[1].querySelector('.badge').textContent === XSS_IMG);
    check('xss: 解析できなかった行の題名と理由も文字のまま',
        items[2] && items[2].querySelector('.task-title').textContent === XSS_SCRIPT
        && items[2].querySelector('.task-note').textContent.includes(XSS_IMG));
    check('xss: スクリプトは動いていない', env.sandbox.__xss === undefined, String(env.sandbox.__xss));
    const sent = env.fetchCalls[0] && JSON.parse(env.fetchCalls[0].init.body);
    check('xss: 入力は JSON で API に送る（3行）', sent && sent.tasks.length === 3 && sent.tasks[0].startsWith(XSS_IMG));
    check('xss: 結果の知らせ', env.$('success').textContent === '2件のタスクを解析しました（1件は解析できませんでした）',
        env.$('success').textContent);
    check('xss: 要確認の印と行の色', items[0] && items[0].classList.contains('task-review')
        && items[0].textContent.includes('要確認'));
    check('xss: 知らせを消すタイマーを使わない', env.timers.length === 0, `timers=${env.timers.length}`);
}

// ------------------------------------------------------------
// 1b. カテゴリの印の色（category_color）と、判定の理由（category_hits）（B27）
// ------------------------------------------------------------
async function categoryReason() {
    const base = { raw_text: '', warnings: [], due_type: 'none', due_raw: '', due_time: null, needs_review: false, overdue: false, deadline: null };
    const rows = [
        { ...base, ok: true, title: '架空の会議資料', category: '仕事', category_color: 1, category_hits: ['会議', XSS_IMG] },
        { ...base, ok: true, title: '架空のメモ', category: '暮らし', category_color: 4, category_hits: [] },
        { ...base, ok: true, title: '架空の番号違い', category: '学び', category_color: 9, category_hits: ['練習'] },
        { ...base, ok: true, title: '架空の文字の番号', category: '地域', category_color: '2', category_hits: null },
        { ...base, ok: false, title: '架空の失敗', category: null, category_color: null, category_hits: [], error: '解析できませんでした', needs_review: true }
    ];
    const env = setup({ fetchImpl: async () => jsonResponse(200, rows) });
    env.$('taskInput').value = rows.map(row => row.title).join('\n');
    env.$('parseBtn').click();
    await flush();
    const items = env.$('taskList').children;
    const badge = i => items[i] && items[i].querySelector('.badge');
    const reason = i => items[i] && items[i].querySelector('.task-reason');
    check('category: 色の番号の印', badge(0) && badge(0).className === 'badge badge-cat-1' && badge(0).textContent === '仕事',
        badge(0) && badge(0).className);
    check('category: 当たった語を理由に出す', reason(0) && reason(0).textContent === `カテゴリの理由: 「会議」「${XSS_IMG}」`,
        reason(0) && reason(0).textContent);
    check('category: 理由の語も文字のまま（要素を作らない）',
        !env.document.createdTags.includes('IMG') && env.document.htmlSinkUses.length === 0);
    check('category: 当たった語が無ければ、決まりのカテゴリと書く',
        reason(1) && reason(1).textContent === 'カテゴリの理由: 当てはまる語が無いので「暮らし」', reason(1) && reason(1).textContent);
    check('category: 色 4', badge(1) && badge(1).className === 'badge badge-cat-4');
    check('category: 1〜6 以外の番号は色 0', badge(2) && badge(2).className === 'badge badge-cat-0', badge(2) && badge(2).className);
    check('category: 文字の番号も色 0', badge(3) && badge(3).className === 'badge badge-cat-0', badge(3) && badge(3).className);
    check('category: 当たった語が null でも動く', reason(3) && reason(3).textContent === 'カテゴリの理由: 当てはまる語が無いので「地域」');
    check('category: 解析できなかった行には理由を出さない', items[4] && !items[4].querySelector('.task-reason') && !items[4].querySelector('.badge'));
}

// ------------------------------------------------------------
// 2. 知らせ（aria-live）: 解析中・エラー・自動で消さない
// ------------------------------------------------------------
async function noticesStay() {
    const env = setup();
    env.$('taskInput').value = '   ';
    env.$('parseBtn').click();
    await flush();
    check('notice: 空の入力はエラーの領域に出す', env.$('error').textContent === 'タスクを入力してください',
        env.$('error').textContent);
    check('notice: エラーの領域は role=alert', env.$('error').getAttribute('role') === 'alert');
    check('notice: 入力欄に戻す', env.document.activeElement === env.$('taskInput'));
    await flush(20);
    check('notice: しばらくたっても消えない（タイマーなし）',
        env.$('error').textContent !== '' && env.timers.length === 0, `timers=${env.timers.length}`);
}

async function loadingState() {
    let resolveFetch;
    const env = setup({ fetchImpl: () => new Promise(resolve => { resolveFetch = resolve; }) });
    env.$('taskInput').value = '架空の用事 (明日)';
    env.$('parseBtn').click();
    await flush();
    check('loading: 解析中の知らせ', env.$('loading').textContent === '解析中…', env.$('loading').textContent);
    check('loading: 解析中の領域は role=status', env.$('loading').getAttribute('role') === 'status');
    check('loading: ボタンは aria-disabled（フォーカスは失わない）',
        env.$('parseBtn').getAttribute('aria-disabled') === 'true' && !env.$('parseBtn').disabled);
    env.$('parseBtn').click();
    await flush();
    check('loading: 解析中にもう一度押しても送らない', env.fetchCalls.length === 1, `calls=${env.fetchCalls.length}`);
    resolveFetch(jsonResponse(200, [{
        ok: true, title: '架空の用事', deadline: '2026-10-02T00:00:00+09:00', category: '個人', raw_text: '',
        warnings: [], due_type: 'relative', due_raw: '明日', due_time: null, needs_review: false, overdue: false
    }]));
    await flush();
    check('loading: 終わったら解析中の知らせを外す', env.$('loading').textContent === '');
    check('loading: 終わったらボタンを戻す', env.$('parseBtn').getAttribute('aria-disabled') === 'false');
    check('loading: 結果の知らせ', env.$('success').textContent === '1件のタスクを解析しました');
}

async function errorResponses() {
    let env = setup({ fetchImpl: async () => jsonResponse(422, {}) });
    env.$('taskInput').value = '架空の用事';
    env.$('parseBtn').click();
    await flush();
    check('error: 長すぎる入力（422）', env.$('error').textContent.includes('1行500文字・200行まで'),
        env.$('error').textContent);

    env = setup({ onLine: false });
    env.$('taskInput').value = '架空の用事';
    env.$('parseBtn').click();
    await flush();
    check('error: 電波が無いときはオフラインと伝える', env.$('error').textContent.includes('オフライン'),
        env.$('error').textContent);

    env = setup({ fetchImpl: async () => jsonResponse(503, { error: 'x', offline: true }) });
    env.$('taskInput').value = '架空の用事';
    env.$('parseBtn').click();
    await flush();
    check('error: Service Worker のオフライン応答（503）', env.$('error').textContent.includes('オフライン'),
        env.$('error').textContent);

    env = setup({ fetchImpl: async () => jsonResponse(500, {}) });
    env.$('taskInput').value = '架空の用事';
    env.$('parseBtn').click();
    await flush();
    check('error: サーバーの失敗（500）', env.$('error').textContent.includes('解析に失敗しました'),
        env.$('error').textContent);
    check('error: 失敗したら前の結果の知らせを消す', env.$('success').textContent === '');
}

// ------------------------------------------------------------
// 3. タブ（矢印キー・Home・End・クリック）
// ------------------------------------------------------------
async function tabsKeyboard() {
    const env = setup();
    const tabs = env.document.querySelectorAll('[role="tab"]');
    const state = () => tabs.map(t => `${t.dataset.tab}:${t.getAttribute('aria-selected')}:${t.getAttribute('tabindex')}`).join(' ');
    const panelHidden = () => ['tab-parse', 'tab-mine', 'tab-tasks'].map(id => env.$(id).hidden);
    const key = (tab, k) => {
        const event = new FakeEvent('keydown', { key: k, bubbles: true });
        tab.dispatchEvent(event);
        return event;
    };

    check('tabs: 3つある', tabs.length === 3, `tabs=${tabs.length}`);
    let event = key(tabs[0], 'ArrowRight');
    check('tabs: → で次のタブを選ぶ', state() === 'parse:false:-1 mine:true:0 tasks:false:-1', state());
    check('tabs: → で移った先にフォーカス', env.document.activeElement === tabs[1]);
    check('tabs: 選んだタブの中身だけ表示', JSON.stringify(panelHidden()) === '[true,false,true]',
        JSON.stringify(panelHidden()));
    check('tabs: 矢印キーの既定の動き（スクロール）を止める', event.defaultPrevented);
    await flush();
    check('tabs: 本人の番を開くと、件数の案内を文字で入れる',
        env.$('mineSummary').textContent.startsWith('本人の番のタスクはありません'), env.$('mineSummary').textContent);
    key(tabs[1], 'End');
    check('tabs: End で最後のタブ', state() === 'parse:false:-1 mine:false:-1 tasks:true:0', state());
    key(tabs[2], 'ArrowRight');
    check('tabs: 最後で → なら最初に戻る', state() === 'parse:true:0 mine:false:-1 tasks:false:-1', state());
    key(tabs[0], 'ArrowLeft');
    check('tabs: 最初で ← なら最後へ', state() === 'parse:false:-1 mine:false:-1 tasks:true:0', state());
    key(tabs[2], 'Home');
    check('tabs: Home で最初のタブ', state() === 'parse:true:0 mine:false:-1 tasks:false:-1', state());
    event = key(tabs[0], 'a');
    check('tabs: ほかのキーでは何もしない', !event.defaultPrevented
        && state() === 'parse:true:0 mine:false:-1 tasks:false:-1', state());
    tabs[1].click();
    check('tabs: クリックでも選べる', state() === 'parse:false:-1 mine:true:0 tasks:false:-1', state());
}

// ------------------------------------------------------------
// 4. 「新しい版があります」（Service Worker の更新）
// ------------------------------------------------------------
function fakeServiceWorker({ controller, waiting = null }) {
    const posted = [];
    const worker = makeEmitter({ state: 'installing', postMessage: message => posted.push(message) });
    const reg = makeEmitter({ waiting, installing: worker });
    const registered = [];
    const container = makeEmitter({
        controller,
        register: async url => { registered.push(url); return reg; }
    });
    return { container, reg, worker, posted, registered };
}

async function updateNotice() {
    const sw = fakeServiceWorker({ controller: {} });
    const env = setup({ serviceWorker: sw.container });
    await flush();
    check('update: /sw.js を登録する', sw.registered.join() === '/sw.js', sw.registered.join());
    check('update: 最初は案内なし', env.$('updateBanner').textContent === '');
    sw.reg.emit('updatefound');
    sw.worker.state = 'installed';
    sw.worker.emit('statechange');
    const banner = env.$('updateBanner');
    check('update: 「新しい版があります」を出す', banner.textContent.includes('新しい版があります'), banner.textContent);
    check('update: 案内は role=status の領域', banner.getAttribute('role') === 'status');
    const button = banner.querySelector('button');
    check('update: 「更新する」ボタン', button && button.textContent === '更新する' && button.getAttribute('type') === 'button');
    sw.worker.emit('statechange');
    check('update: 案内は1回だけ', banner.querySelectorAll('button').length === 1);
    sw.container.emit('controllerchange');
    check('update: 押す前に切り替わっても読み込み直さない', env.reloads.length === 0);
    button.click();
    check('update: 押したら新しい版に SKIP_WAITING を送る',
        sw.posted.length === 1 && sw.posted[0].type === 'SKIP_WAITING', JSON.stringify(sw.posted));
    sw.container.emit('controllerchange');
    sw.container.emit('controllerchange');
    check('update: 切り替わったら1回だけ読み込み直す', env.reloads.length === 1, `reloads=${env.reloads.length}`);
}

async function firstInstallHasNoNotice() {
    const sw = fakeServiceWorker({ controller: null });
    const env = setup({ serviceWorker: sw.container });
    await flush();
    sw.reg.emit('updatefound');
    sw.worker.state = 'installed';
    sw.worker.emit('statechange');
    sw.container.emit('controllerchange');
    check('update: 初めて入れたときは案内を出さない', env.$('updateBanner').textContent === '');
    check('update: 初めて入れたときは読み込み直さない', env.reloads.length === 0);
}

async function waitingWorkerShowsNotice() {
    const waiting = makeEmitter({ state: 'installed', postMessage() {} });
    const sw = fakeServiceWorker({ controller: {}, waiting });
    const env = setup({ serviceWorker: sw.container });
    await flush();
    check('update: 前から待っている新しい版も案内する', env.$('updateBanner').textContent.includes('新しい版があります'));
}

// ------------------------------------------------------------
// 5. 端末に保存したタスク（B29）: 保存・本人の番・状態・動きなし・書き出しと読み込み・コピー・Notion の CSV
// ------------------------------------------------------------
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const PARSED_ROWS = [
    {
        ok: true, title: '架空の資料作り', deadline: '2027-03-15T00:00:00+09:00', category: '個人', raw_text: '架空の資料作り (3/15まで)',
        warnings: [], due_type: 'exact', due_raw: '3/15まで', due_time: null, needs_review: false, overdue: false
    },
    {
        ok: true, title: '架空の打ち合わせ', deadline: '2026-10-02T00:00:00+09:00', category: '個人', raw_text: '架空の打ち合わせ (明日15時)',
        warnings: [], due_type: 'relative', due_raw: '明日15時', due_time: '15:00', needs_review: false, overdue: false
    },
    {
        ok: false, title: '架空の読めない行', raw_text: '架空の読めない行', warnings: [], error: 'この行は解析できませんでした',
        due_type: null, due_raw: '', due_time: null, needs_review: true, overdue: false
    }
];

function fakeFile(text, size) {
    return { name: 'fake', size: size === undefined ? Buffer.byteLength(text) : size, text: async () => text };
}

async function chooseFile(env, inputId, file) {
    const input = env.$(inputId);
    input.files = [file];
    input.dispatchEvent(new FakeEvent('change', { bubbles: true }));
    await flush(10);
}

async function parseAndSave(env, text = '架空の資料作り (3/15まで)\n架空の打ち合わせ (明日15時)\n架空の読めない行') {
    env.$('taskInput').value = text;
    env.$('parseBtn').click();
    await flush();
    env.$('saveBtn').click();
    await flush(10);
}

const ids = list => list.children.map(item => item.getAttribute('data-id'));
const button = (item, status) => item && item.querySelector(`button[data-status="${status}"]`);

async function saveAndChangeStatus() {
    const env = setup({ fetchImpl: async () => jsonResponse(200, PARSED_ROWS) });
    await flush();
    await parseAndSave(env);
    const all = env.$('allList');
    check('save: 解析できた2行を保存する（読めない行は保存しない）', all.children.length === 2, `items=${all.children.length}`);
    check('save: 保存の知らせ', env.$('success').textContent.startsWith('2件を端末に保存しました'), env.$('success').textContent);
    check('save: IndexedDB が無い環境では一時の保存だと伝える',
        env.$('storageWarning').textContent.includes('一時の保存') && env.$('success').textContent.includes('一時の保存'),
        env.$('storageWarning').textContent);
    const firstIds = ids(all);
    check('save: 各タスクに固定の UUID（v4）を振る', firstIds.every(id => UUID_V4.test(id)) && new Set(firstIds).size === 2,
        firstIds.join(','));
    check('save: 状態は進行中で始まる', all.children.every(item => item.querySelector('.badge-status').textContent === '進行中'));
    check('save: 期限と時刻を出す', all.children.some(item => item.querySelector('.deadline').textContent.includes('2026年10月2日 15:00')),
        all.children.map(item => item.querySelector('.deadline').textContent).join(' / '));
    env.$('saveBtn').click();
    await flush(10);
    check('save: 同じ結果をもう一度押しても重ねて保存しない',
        all.children.length === 2 && env.$('success').textContent === 'この結果は、もう端末に保存してあります', env.$('success').textContent);
    check('mine: 最初は本人の番なし', env.$('mineList').children.length === 0
        && env.$('mineSummary').textContent.startsWith('本人の番のタスクはありません'));

    // 一覧で「本人の番にする」
    const target = all.children.find(item => item.querySelector('.task-title').textContent === '架空の打ち合わせ');
    const targetId = target.getAttribute('data-id');
    button(target, 'my_turn').click();
    await flush(10);
    const mine = env.$('mineList');
    check('mine: 本人の番にすると本人の番の一覧に出る', ids(mine).join() === targetId, ids(mine).join());
    check('mine: 状態を変えても ID は変わらない', ids(env.$('allList')).sort().join() === firstIds.slice().sort().join());
    check('mine: 一覧の知らせ', env.$('tasksNotice').textContent === '「架空の打ち合わせ」を本人の番にしました',
        env.$('tasksNotice').textContent);
    const moved = env.$('allList').querySelector(`[data-id="${targetId}"]`);
    check('mine: 押したあと、同じタスクのボタンにフォーカスを戻す',
        env.document.activeElement && env.document.activeElement === moved.querySelector('button'),
        env.document.activeElement && env.document.activeElement.textContent);
    check('mine: 今の状態のボタンは出さない（ほかの3つと削除）',
        !button(moved, 'my_turn') && button(moved, 'in_progress') && button(moved, 'done') && button(moved, 'on_hold')
        && moved.querySelector('.btn-danger'));
    check('mine: 一覧の並びは本人の番が先', env.$('allList').children[0].getAttribute('data-id') === targetId);
    check('mine: 件数の案内', env.$('mineSummary').textContent === '本人の番は 1件です', env.$('mineSummary').textContent);

    // 本人の番の一覧で「次に本人がすること」を書く
    const mineItem = mine.children[0];
    const next = mineItem.querySelector('input');
    check('mine: 次に本人がすることの入力欄に見出しがある',
        mineItem.querySelector('label').getAttribute('for') === next.id && next.id === `next-mine-${targetId}`);
    next.value = '架空の資料を印刷して持っていく';
    next.dispatchEvent(new FakeEvent('change', { bubbles: true }));
    await flush(10);
    check('mine: 入力を終えたら保存して知らせる', env.$('mineNotice').textContent === '「架空の打ち合わせ」を保存しました',
        env.$('mineNotice').textContent);
    check('mine: 入力中の一覧は描き直さない（フォーカスを奪わない）', env.$('mineList').children[0] === mineItem);
    check('mine: 一覧の側にも反映する',
        env.$('allList').querySelector(`[data-id="${targetId}"] input`).value === '架空の資料を印刷して持っていく');

    // 本人の番の一覧で「完了にする」→ 一覧から消え、見出しへ
    // 入力の直後（保存が終わる前）に押しても、入力した文字を消さない
    next.value = '架空の資料を印刷して持っていく（2部）';
    next.dispatchEvent(new FakeEvent('change', { bubbles: true }));
    button(mineItem, 'done').click();
    await flush(10);
    check('mine: 完了にすると本人の番の一覧から消える', env.$('mineList').children.length === 0);
    check('mine: 消えたら見出しにフォーカス', env.document.activeElement === env.$('mineHeading'));
    check('mine: 完了は一覧の最後', env.$('allList').children[1].getAttribute('data-id') === targetId
        && env.$('allList').children[1].querySelector('.badge-status').textContent === '完了');

    // JSON の書き出し（ID・状態・次にすることを含む）
    env.$('exportJsonBtn').click();
    await flush(10);
    const file = env.downloads[0];
    let backup = null;
    try { backup = JSON.parse(file.text); } catch (err) { backup = null; }
    check('io: JSON を書き出す（ファイル名・種類）', file && /^task-sync-\d{8}\.json$/.test(file.name) && file.type === 'application/json',
        JSON.stringify(file && { name: file.name, type: file.type }));
    check('io: 書き出した JSON に固定の ID と状態が入る', backup && backup.format === 'task-sync-backup'
        && backup.tasks.map(t => t.id).sort().join() === firstIds.slice().sort().join()
        && backup.tasks.find(t => t.id === targetId).status === 'done'
        && backup.tasks.find(t => t.id === targetId).next_action === '架空の資料を印刷して持っていく（2部）');
    check('io: 書き出しの知らせ', env.$('ioNotice').textContent.startsWith('2件を task-sync-'), env.$('ioNotice').textContent);

    // 別の端末（新しい環境）で読み込む → 同じ ID
    const other = setup();
    await flush();
    await chooseFile(other, 'importJsonInput', fakeFile(file.text));
    check('io: 別の端末で読み込むと同じ ID で入る',
        ids(other.$('allList')).sort().join() === firstIds.slice().sort().join(), other.$('ioNotice').textContent);
    check('io: 読み込みの知らせ（足した件数）', other.$('ioNotice').textContent.startsWith('読み込みました: 足した 2件'),
        other.$('ioNotice').textContent);
    await chooseFile(other, 'importJsonInput', fakeFile(file.text));
    check('io: 同じファイルをもう一度読んでも重ならない', other.$('allList').children.length === 2
        && other.$('ioNotice').textContent.includes('そのまま 2件'), other.$('ioNotice').textContent);
    check('io: 読み込んだあと、同じファイルを選び直せるよう選択を外す', other.$('importJsonInput').value === '');

    // 削除（確かめてから）
    const env2 = setup({ fetchImpl: async () => jsonResponse(200, PARSED_ROWS), confirmAnswer: false });
    await flush();
    await parseAndSave(env2);
    env2.$('allList').children[0].querySelector('.btn-danger').click();
    await flush(10);
    check('io: 削除は確かめて、取り消せば残す', env2.confirms.length === 1 && env2.$('allList').children.length === 2,
        env2.confirms.join());
    const env3 = setup({ fetchImpl: async () => jsonResponse(200, PARSED_ROWS), confirmAnswer: true });
    await flush();
    await parseAndSave(env3);
    env3.$('allList').children[0].querySelector('.btn-danger').click();
    await flush(10);
    check('io: 削除を選ぶと消える', env3.$('allList').children.length === 1
        && env3.$('tasksNotice').textContent.endsWith('を削除しました'), env3.$('tasksNotice').textContent);

    check('network: 通信は解析の /api/parse-batch だけ',
        [env, other, env2, env3].every(e => e.fetchCalls.every(call => call.url === '/api/parse-batch')),
        [env, other, env2, env3].flatMap(e => e.fetchCalls.map(call => call.url)).join(','));
}

function backupWith(tasks) {
    return JSON.stringify({ format: 'task-sync-backup', version: 1, exported_at: new Date().toISOString(), settings: { lanes: ['架空A', '架空B'] }, tasks });
}

function savedTask(overrides) {
    const at = new Date(Date.now() - 100 * 3600 * 1000).toISOString();
    return {
        id: webcrypto.randomUUID(), title: '架空のタスク', lane: '架空A', status: 'my_turn', next_action: '', deadline: null,
        due_time: null, category: '個人', raw_text: '', created_at: at, updated_at: at, revision: 0, ...overrides
    };
}

async function staleAndImportErrors() {
    const env = setup();
    await flush();
    const hoursAgo = h => new Date(Date.now() - h * 3600 * 1000).toISOString();
    const tasks = [
        savedTask({ title: '架空の新しい用事', updated_at: hoursAgo(1) }),
        savedTask({ title: `架空の止まった用事<img src=x onerror="window.__xss=1">`, updated_at: hoursAgo(49) }),
        savedTask({ title: '架空の保留', status: 'on_hold', updated_at: hoursAgo(200) })
    ];
    await chooseFile(env, 'importJsonInput', fakeFile(backupWith(tasks)));
    const mine = env.$('mineList').children;
    check('stale: 本人の番は2件', mine.length === 2, `items=${mine.length}`);
    check('stale: 48時間以上動きのないものに印を付け、先に並べる',
        mine[0] && mine[0].classList.contains('task-stale')
        && (mine[0].querySelector('.badge-stale') || {}).textContent === '2日以上動きなし'
        && !mine[1].classList.contains('task-stale'));
    check('stale: 件数の案内に動きなしの件数', env.$('mineSummary').textContent === '本人の番は 2件です（2日以上動きなし 1件）',
        env.$('mineSummary').textContent);
    check('stale: 保留には印を付けない', !env.$('allList').children.find(i => i.textContent.includes('架空の保留')).classList.contains('task-stale'));
    check('stale: 題名は文字のまま（img を作らない）', !env.document.createdTags.includes('IMG') && env.sandbox.__xss === undefined
        && env.document.htmlSinkUses.length === 0);
    check('lanes: 端末で未設定なら、読み込んだ JSON のレーン名を使う', env.$('lanesInput').value === '架空A\n架空B', env.$('lanesInput').value);

    // 次にすることを書くと印が外れる（動いたことになる）
    const staleItem = mine[0];
    const input = staleItem.querySelector('input');
    input.value = '架空の連絡をする';
    input.dispatchEvent(new FakeEvent('change', { bubbles: true }));
    await flush(10);
    check('stale: 次にすることを書くと印が外れる', !staleItem.classList.contains('task-stale') && !staleItem.querySelector('.badge-stale'));

    await chooseFile(env, 'importJsonInput', fakeFile('{"format": "x"'));
    check('io: JSON でないファイルは断る', env.$('ioNotice').textContent === 'JSON として読めません', env.$('ioNotice').textContent);
    await chooseFile(env, 'importJsonInput', fakeFile('{}', 6 * 1024 * 1024));
    check('io: 5MB を超えるファイルは読まない', env.$('ioNotice').textContent.includes('5MB'), env.$('ioNotice').textContent);
    await chooseFile(env, 'importJsonInput', fakeFile('{"tasks": []}'));
    check('io: ほかの形の JSON は断る', env.$('ioNotice').textContent.includes('このアプリで書き出した'), env.$('ioNotice').textContent);
    check('io: 断ったときは何も変えない', env.$('allList').children.length === 3);
}

async function copyLedger() {
    const copied = [];
    const env = setup({ clipboard: { writeText: async text => { copied.push(text); } } });
    await flush();
    await chooseFile(env, 'importJsonInput', fakeFile(backupWith([
        savedTask({ title: '架空の見積もり|確認', next_action: '架空の数字を見る', updated_at: '2026-09-30T16:00:00.000Z' })
    ])));
    env.$('copyMarkdownBtn').click();
    await flush(10);
    check('copy: Markdown の表（件名/レーン/状態/本人の番/更新日）', copied[0] === [
        '| 件名 | レーン | 状態 | 本人の番 | 更新日 |',
        '| --- | --- | --- | --- | --- |',
        '| 架空の見積もり\\|確認 | 架空A | 本人の番 | 架空の数字を見る | 2026-10-01 |',
        ''
    ].join('\n'), copied[0]);
    check('copy: コピーの知らせ', env.$('ioNotice').textContent === '1件を台帳の形（Markdown の表）でコピーしました',
        env.$('ioNotice').textContent);
    env.$('copyCsvBtn').click();
    await flush(10);
    check('copy: CSV（CRLF）', copied[1] === '件名,レーン,状態,本人の番,更新日\r\n架空の見積もり|確認,架空A,本人の番,架空の数字を見る,2026-10-01\r\n',
        JSON.stringify(copied[1]));

    // クリップボードが使えないとき（http の LAN など）は、選んでコピーできる欄に出す
    const plain = setup();
    await flush();
    await chooseFile(plain, 'importJsonInput', fakeFile(backupWith([savedTask({ title: '架空のA' })])));
    plain.$('copyCsvBtn').click();
    await flush(10);
    check('copy: 使えなければ控えの欄に出して選ぶ', !plain.$('copyFallback').hidden
        && plain.$('copyFallbackText').value.startsWith('件名,レーン,状態,本人の番,更新日')
        && plain.document.selectedElement === plain.$('copyFallbackText')
        && plain.$('ioNotice').textContent.includes('下の欄'), plain.$('ioNotice').textContent);
    const empty = setup({ clipboard: { writeText: async text => { copied.push(text); } } });
    await flush();
    empty.$('copyMarkdownBtn').click();
    await flush(10);
    check('copy: 保存したタスクが無ければコピーしない', empty.$('ioNotice').textContent === '保存したタスクがありません' && copied.length === 2);
}

async function notionCsv() {
    const env = setup();
    await flush();
    const day = 24 * 3600 * 1000;
    const jst = ms => new Date(ms + 9 * 3600 * 1000).toISOString().slice(0, 10).replace(/-/g, '/');
    const csv = [
        '﻿件名,レーン,状態,本人の番,更新日',
        `架空の申請,架空A,本人の番,架空の書類に記入する,${jst(Date.now() - 3 * day)}`,
        `"架空の<img src=x onerror=""window.__xss=1"">見積もり",架空A,本人の番,なし,${jst(Date.now())}`,
        `架空の読書,架空B,進行中,,${jst(Date.now() - 9 * day)}`
    ].join('\r\n');
    await chooseFile(env, 'notionCsvInput', fakeFile(csv));
    const items = env.$('notionList').children;
    check('notion: 本人の番の行だけを出す', items.length === 2, `items=${items.length}`);
    check('notion: 件数の案内', env.$('notionNotice').textContent === '全 3行のうち、本人の番は 2行です（2日以上動きなし 1行）',
        env.$('notionNotice').textContent);
    check('notion: 2日以上前の更新日に印', items[0].querySelector('.badge-stale') && !items[1].querySelector('.badge-stale'));
    check('notion: 本人の番の欄が「なし」なら印', items[1].textContent.includes('本人の番の欄が空') && !items[0].textContent.includes('本人の番の欄が空'));
    check('notion: 本人の番の欄の文字を出す', items[0].querySelector('.task-next').textContent === '本人の番: 架空の書類に記入する');
    check('notion: 題名は文字のまま', items[1].querySelector('.task-title').textContent.includes('<img')
        && !env.document.createdTags.includes('IMG') && env.sandbox.__xss === undefined);
    check('notion: 端末には保存しない', env.$('allList').children.length === 0);
    await chooseFile(env, 'notionCsvInput', fakeFile('Name,Status\nx,y\n'));
    check('notion: 見出しが違えば理由を出して一覧を消す', env.$('notionNotice').textContent.includes('「件名」「状態」の列がありません')
        && env.$('notionList').children.length === 0, env.$('notionNotice').textContent);
}

async function lanesSetting() {
    const env = setup({ fetchImpl: async () => jsonResponse(200, PARSED_ROWS) });
    await flush();
    check('lanes: 見本のレーン名で始まる', env.$('lanesInput').value === '仕事\n学び\n暮らし', env.$('lanesInput').value);
    env.$('lanesInput').value = ' 架空の係\n架空の家、架空の係\n';
    env.$('saveLanesBtn').click();
    await flush(10);
    check('lanes: 保存すると空白と重なりを除く', env.$('lanesInput').value === '架空の係\n架空の家'
        && env.$('lanesNotice').textContent === 'レーン名を保存しました（架空の係・架空の家）', env.$('lanesNotice').textContent);
    await parseAndSave(env);
    const item = env.$('allList').children[0];
    const select = item.querySelector('select');
    check('lanes: 新しいタスクは最初のレーン', item.querySelector('.badge-lane').textContent === '架空の係');
    check('lanes: レーンの選択肢は設定の名前', select.children.map(o => o.textContent).join() === '架空の係,架空の家'
        && item.querySelector(`label[for="${select.id}"]`));
    select.value = '架空の家';
    select.dispatchEvent(new FakeEvent('change', { bubbles: true }));
    await flush(10);
    check('lanes: レーンを変えると保存する', env.$('tasksNotice').textContent.endsWith('を保存しました'), env.$('tasksNotice').textContent);
    env.$('exportJsonBtn').click();
    await flush(10);
    const backup = JSON.parse(env.downloads[0].text);
    check('lanes: 書き出しにレーン名の設定も入る', backup.settings.lanes.join() === '架空の係,架空の家'
        && backup.tasks.some(t => t.lane === '架空の家'));
}

// ------------------------------------------------------------
// 6. カレンダー用ファイル（.ics）（B30）
// ------------------------------------------------------------
const ICS_ROWS = PARSED_ROWS.slice(0, 2).concat([{
    ok: true, title: '架空の期限なしのメモ', deadline: null, category: '個人', raw_text: '架空の期限なしのメモ',
    warnings: [], due_type: 'none', due_raw: '', due_time: null, needs_review: false, overdue: false
}]);
const uidsOf = text => Array.from(String(text).matchAll(/^UID:(.+)\r$/gm), m => m[1]);

async function calendarFile() {
    const env = setup({ fetchImpl: async () => jsonResponse(200, ICS_ROWS) });
    await flush();
    check('ics: 前の同期ボタン（未実装の案内）は無い', env.$('syncBtn') === null && env.$('icsBtn').textContent.includes('カレンダー用ファイルを保存'));
    env.$('taskInput').value = '架空の資料作り (3/15まで)\n架空の打ち合わせ (明日15時)\n架空の期限なしのメモ';
    env.$('parseBtn').click();
    await flush();
    env.$('icsBtn').click();
    await flush(10);
    const file = env.downloads[0];
    check('ics: 「カレンダー用ファイルを保存」で .ics を保存する',
        file && /^task-sync-\d{8}\.ics$/.test(file.name) && file.type === 'text/calendar;charset=utf-8',
        JSON.stringify(file && { name: file.name, type: file.type }));
    const savedIds = ids(env.$('allList'));
    const uids = uidsOf(file && file.text);
    check('ics: 先に端末に保存し（3件）、その固定の ID を UID にする（期限のある2件）',
        savedIds.length === 3 && uids.length === 2 && uids.every(uid => savedIds.includes(uid)), `${savedIds} / ${uids}`);
    check('ics: 知らせ（保存した件数・予定の件数・入れなかったもの）',
        env.$('success').textContent === `3件を端末に保存しました（一時の保存です。画面を閉じると消えます）。2件の予定をカレンダー用ファイル（${file && file.name}）にしました`
            + '（期限の無い1件は入れていません）。カレンダーのアプリで読み込んでください', env.$('success').textContent);
    check('ics: 中身は VCALENDAR で CRLF', file && file.text.startsWith('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n') && file.text.endsWith('END:VCALENDAR\r\n'));
    check('ics: 未実装の案内（alert）を出さない', env.alerts.length === 0, env.alerts.join(' / '));

    env.$('icsBtn').click();
    await flush(10);
    check('ics: もう一度押しても重ねて保存せず、同じ UID のファイルを作る',
        ids(env.$('allList')).length === 3 && uidsOf(env.downloads[1] && env.downloads[1].text).join() === uids.join()
        && env.$('success').textContent.startsWith('2件の予定をカレンダー用ファイル'), env.$('success').textContent);

    // 一覧から（完了は入れない）
    const done = env.$('allList').children.find(item => item.getAttribute('data-id') === uids[0]);
    button(done, 'done').click();
    await flush(10);
    env.$('icsAllBtn').click();
    await flush(10);
    const all = env.downloads[2];
    check('ics: 一覧からは期限のある未完了のタスクだけ', all && uidsOf(all.text).join() === uids[1]
        && env.$('ioNotice').textContent.endsWith('（期限の無い1件・完了の1件は入れていません）'), env.$('ioNotice').textContent);

    // 期限のあるタスクが無いとき
    const none = setup({ fetchImpl: async () => jsonResponse(200, ICS_ROWS.slice(2)) });
    await flush();
    none.$('taskInput').value = '架空の期限なしのメモ';
    none.$('parseBtn').click();
    await flush();
    none.$('icsBtn').click();
    await flush(10);
    check('ics: 期限のあるタスクが無ければファイルを作らず、理由を出す', none.downloads.length === 0
        && none.$('error').textContent === '1件を端末に保存しました（一時の保存です。画面を閉じると消えます）。期限のあるタスクが無いので、カレンダー用ファイルは作りませんでした',
        none.$('error').textContent);
    check('network: .ics を作っても通信は解析だけ',
        [env, none].every(e => e.fetchCalls.every(call => call.url === '/api/parse-batch')));
}

const scenarios = [
    xssIsShownAsText, categoryReason, noticesStay, loadingState, errorResponses, tabsKeyboard,
    updateNotice, firstInstallHasNoNotice, waitingWorkerShowsNotice,
    saveAndChangeStatus, staleAndImportErrors, copyLedger, notionCsv, lanesSetting, calendarFile
];
for (const scenario of scenarios) {
    try {
        await scenario();
    } catch (err) {
        check(`${scenario.name}: 例外なしで動く`, false, err && err.stack ? err.stack : err);
    }
}
process.stdout.write(JSON.stringify(results, null, 1));
