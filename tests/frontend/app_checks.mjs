// ============================================================
// frontend/app.js を偽 DOM（fake_dom.mjs）の上で動かして、画面の動きを確かめる。
// 結果は JSON で標準出力に出す（tests/test_b28_frontend_js.py が読む）。
// 外部には送信しない（fetch は偽物）。入力はすべて架空の文字列。
// 使い方: node tests/frontend/app_checks.mjs
//   TSA_APP_JS=別のファイル を付けると、そのファイルを app.js の代わりに動かす（検査が働くかの確認用）
// ============================================================
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { FakeDocument, FakeEvent, parseHTML } from './fake_dom.mjs';

const ROOT = new URL('../../', import.meta.url);
const INDEX_HTML = readFileSync(new URL('frontend/index.html', ROOT), 'utf8');
const APP_JS = readFileSync(process.env.TSA_APP_JS || new URL('frontend/app.js', ROOT), 'utf8');

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

function jsonResponse(status, body) {
    return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function makeEmitter(extra = {}) {
    const listeners = {};
    return Object.assign({
        listeners,
        addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
        emit(type, event = {}) { for (const fn of listeners[type] || []) fn(event); }
    }, extra);
}

function setup({ fetchImpl, onLine = true, serviceWorker } = {}) {
    const document = parseHTML(new FakeDocument(), INDEX_HTML);
    const timers = [];
    const reloads = [];
    const fetchCalls = [];
    const navigator = { onLine };
    if (serviceWorker) navigator.serviceWorker = serviceWorker;
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
        alert: () => {},
        location: { reload: () => reloads.push(1) },
        addEventListener: () => {}
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(APP_JS, sandbox, { filename: 'frontend/app.js' });
    const $ = id => document.getElementById(id);
    return { document, sandbox, timers, reloads, fetchCalls, $ };
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
    check('xss: 知らないカテゴリは個人の色で文字のまま',
        items[1] && items[1].querySelector('.badge').className === 'badge badge-personal'
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
    const panelHidden = () => ['tab-parse', 'tab-history', 'tab-stats'].map(id => env.$(id).hidden);
    const key = (tab, k) => {
        const event = new FakeEvent('keydown', { key: k, bubbles: true });
        tab.dispatchEvent(event);
        return event;
    };

    check('tabs: 3つある', tabs.length === 3, `tabs=${tabs.length}`);
    let event = key(tabs[0], 'ArrowRight');
    check('tabs: → で次のタブを選ぶ', state() === 'parse:false:-1 history:true:0 stats:false:-1', state());
    check('tabs: → で移った先にフォーカス', env.document.activeElement === tabs[1]);
    check('tabs: 選んだタブの中身だけ表示', JSON.stringify(panelHidden()) === '[true,false,true]',
        JSON.stringify(panelHidden()));
    check('tabs: 矢印キーの既定の動き（スクロール）を止める', event.defaultPrevented);
    check('tabs: 履歴の案内を文字で入れる', env.$('historyList').textContent === 'データベース機能は実装中...',
        env.$('historyList').textContent);
    key(tabs[1], 'End');
    check('tabs: End で最後のタブ', state() === 'parse:false:-1 history:false:-1 stats:true:0', state());
    key(tabs[2], 'ArrowRight');
    check('tabs: 最後で → なら最初に戻る', state() === 'parse:true:0 history:false:-1 stats:false:-1', state());
    key(tabs[0], 'ArrowLeft');
    check('tabs: 最初で ← なら最後へ', state() === 'parse:false:-1 history:false:-1 stats:true:0', state());
    key(tabs[2], 'Home');
    check('tabs: Home で最初のタブ', state() === 'parse:true:0 history:false:-1 stats:false:-1', state());
    event = key(tabs[0], 'a');
    check('tabs: ほかのキーでは何もしない', !event.defaultPrevented
        && state() === 'parse:true:0 history:false:-1 stats:false:-1', state());
    tabs[1].click();
    check('tabs: クリックでも選べる', state() === 'parse:false:-1 history:true:0 stats:false:-1', state());
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

const scenarios = [
    xssIsShownAsText, noticesStay, loadingState, errorResponses, tabsKeyboard,
    updateNotice, firstInstallHasNoNotice, waitingWorkerShowsNotice
];
for (const scenario of scenarios) {
    try {
        await scenario();
    } catch (err) {
        check(`${scenario.name}: 例外なしで動く`, false, err && err.stack ? err.stack : err);
    }
}
process.stdout.write(JSON.stringify(results, null, 1));
