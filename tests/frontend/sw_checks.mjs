// ============================================================
// frontend/sw.js を偽の Service Worker の環境（self・caches・fetch）で動かして確かめる。
// - 画面の本体はネット優先・キャッシュは控え・オフライン画面・API のオフライン応答
// - 新しい版は SKIP_WAITING まで待つ・古い版のキャッシュを消す・push の処理が無い
// 結果は JSON で標準出力に出す（tests/test_b28_frontend_js.py が読む）。外部には送信しない。
// 使い方: node tests/frontend/sw_checks.mjs
// ============================================================
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const ROOT = new URL('../../', import.meta.url);
const SW_JS = readFileSync(process.env.TSA_SW_JS || new URL('frontend/sw.js', ROOT), 'utf8');
const ORIGIN = 'https://task-sync.example';

const results = [];
function check(name, ok, detail = '') {
    results.push({ name, ok: Boolean(ok), detail: ok ? '' : String(detail) });
}

class FakeRequest {
    constructor(input, init = {}) {
        const base = input instanceof FakeRequest ? input : null;
        this.url = base ? base.url : new URL(input, ORIGIN).href;
        this.method = init.method || (base ? base.method : 'GET');
        this.mode = init.mode || (base ? base.mode : 'cors');
        this.cache = init.cache || (base ? base.cache : 'default');
    }
}

class FakeResponse {
    constructor(body = '', init = {}) {
        this.body = String(body);
        this.status = init.status || 200;
        this.ok = this.status >= 200 && this.status < 300;
        this.type = init.type || 'basic';
        this.headers = new Map(Object.entries(init.headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
    }

    clone() {
        return new FakeResponse(this.body, { status: this.status, type: this.type, headers: Object.fromEntries(this.headers) });
    }

    async text() {
        return this.body;
    }

    async json() {
        return JSON.parse(this.body);
    }
}

const keyOf = request => {
    const url = new URL(typeof request === 'string' ? request : request.url, ORIGIN);
    return url.pathname + url.search;
};

class FakeCache {
    constructor(env) {
        this.env = env;
        this.store = new Map();
    }

    async put(request, response) {
        this.store.set(keyOf(request), response);
    }

    async match(request) {
        return this.store.get(keyOf(request));
    }

    async addAll(requests) {
        for (const request of requests) {
            const response = await this.env.fetch(request);
            if (!response.ok) throw new TypeError('addAll: 取れないファイルがある');
            this.store.set(keyOf(request), response);
        }
    }
}

function setup({ network = 'online', pages = {} } = {}) {
    const handlers = {};
    const counters = { skipWaiting: 0, claim: 0 };
    const fetchLog = [];
    const stores = new Map();
    const env = {};
    env.fetch = async request => {
        const req = request instanceof FakeRequest ? request : new FakeRequest(request);
        fetchLog.push({ url: keyOf(req), cache: req.cache, method: req.method });
        if (network === 'offline') throw new TypeError('Failed to fetch');
        const path = keyOf(req);
        if (path.startsWith('/api/')) return new FakeResponse('{"ok":true}', { headers: { 'Content-Type': 'application/json' } });
        if (path in pages) return new FakeResponse(pages[path]);
        return new FakeResponse(`network ${path}`);
    };
    const caches = {
        stores,
        async open(name) {
            if (!stores.has(name)) stores.set(name, new FakeCache(env));
            return stores.get(name);
        },
        async keys() {
            return [...stores.keys()];
        },
        async delete(name) {
            return stores.delete(name);
        },
        async match(request) {
            for (const cache of stores.values()) {
                const hit = await cache.match(request);
                if (hit) return hit;
            }
            return undefined;
        }
    };
    const self = {
        location: { origin: ORIGIN, href: `${ORIGIN}/sw.js` },
        addEventListener(type, fn) { handlers[type] = fn; },
        skipWaiting() { counters.skipWaiting += 1; return Promise.resolve(); },
        clients: { claim: async () => { counters.claim += 1; } }
    };
    const sandbox = {
        self, caches, URL, Request: FakeRequest, Response: FakeResponse, console,
        fetch: (...args) => env.fetch(...args)
    };
    vm.createContext(sandbox);
    vm.runInContext(SW_JS, sandbox, { filename: 'frontend/sw.js' });
    const cacheName = vm.runInContext('CACHE_NAME', sandbox);
    const precache = vm.runInContext('PRECACHE_URLS', sandbox);
    return { handlers, counters, fetchLog, caches, env, cacheName, precache, setNetwork: v => { network = v; } };
}

async function lifecycle(env, type, data) {
    let waited = null;
    env.handlers[type]({ data, waitUntil(promise) { waited = promise; } });
    if (waited) await waited;
}

async function fetchEvent(env, path, init = {}) {
    let responded = null;
    const request = new FakeRequest(path.startsWith('http') ? path : `${ORIGIN}${path}`, init);
    env.handlers.fetch({ request, respondWith(promise) { responded = Promise.resolve(promise); } });
    if (!responded) return { handled: false };
    try {
        const response = await responded;
        return { handled: true, response, body: response ? await response.text() : null };
    } catch (err) {
        return { handled: true, error: err };
    }
}

async function installed(options) {
    const env = setup(options);
    await lifecycle(env, 'install');
    return env;
}

async function run() {
    // 入れたとき: 先にキャッシュ・HTTP キャッシュを通さない・勝手に切り替えない
    let env = await installed({ pages: { '/': 'old screen', '/app.js': 'old js' } });
    const cache = env.caches.stores.get(env.cacheName);
    check('install: 版の名前のキャッシュに入れる', env.cacheName.startsWith('task-sync-v') && cache, env.cacheName);
    check('install: PRECACHE_URLS を全部入れる', cache && env.precache.every(url => cache.store.has(url)),
        cache && [...cache.store.keys()].join(','));
    check('install: サーバーから取り直す（cache: reload）', env.fetchLog.every(entry => entry.cache === 'reload'));
    check('install: 入れただけでは切り替えない（skipWaiting しない）', env.counters.skipWaiting === 0);
    check('handlers: push の処理が無い', !('push' in env.handlers) && !('notificationclick' in env.handlers),
        Object.keys(env.handlers).join(','));

    // 「更新する」→ SKIP_WAITING
    await lifecycle(env, 'message', { type: 'OTHER' });
    check('message: ほかの知らせでは切り替えない', env.counters.skipWaiting === 0);
    await lifecycle(env, 'message', { type: 'SKIP_WAITING' });
    check('message: SKIP_WAITING で切り替える', env.counters.skipWaiting === 1);

    // 切り替わったとき: 古い版のキャッシュを消す（ほかの名前のキャッシュは残す）
    await env.caches.open('task-sync-v3');
    await env.caches.open('another-app-cache');
    await lifecycle(env, 'activate');
    const names = await env.caches.keys();
    check('activate: 古い版のキャッシュを消す', !names.includes('task-sync-v3') && names.includes(env.cacheName), names.join(','));
    check('activate: ほかのキャッシュは残す', names.includes('another-app-cache'), names.join(','));
    check('activate: 開いている画面を受け持つ', env.counters.claim === 1);

    // 画面を開く（ネット優先）: 新しい画面を返し、控えも新しくする
    env.env.fetch = async () => new FakeResponse('new screen');
    let result = await fetchEvent(env, '/', { mode: 'navigate' });
    check('navigate: ネットにつながれば新しい画面', result.body === 'new screen', result.body);
    check('navigate: 控え（キャッシュ）も新しくする', (await cache.match('/')).body === 'new screen');

    // JS・CSS もネット優先（キャッシュ優先だと古い app.js が残る）
    env.env.fetch = async () => new FakeResponse('new js');
    result = await fetchEvent(env, '/app.js');
    check('app.js: ネット優先で新しい JS', result.body === 'new js', result.body);

    // 電波が無いとき: 控えを返す
    env.setNetwork('offline');
    env.env.fetch = async () => { throw new TypeError('Failed to fetch'); };
    result = await fetchEvent(env, '/', { mode: 'navigate' });
    check('offline: 画面は控え（最後に取れた版）を返す', result.body === 'new screen', result.body || result.error);
    result = await fetchEvent(env, '/app.js');
    check('offline: app.js も控えを返す', result.body === 'new js', result.body || result.error);
    result = await fetchEvent(env, '/somewhere-else', { mode: 'navigate' });
    check('offline: 控えの無い画面はオフライン画面', result.body === (await cache.match('/offline.html')).body,
        result.body || result.error);
    result = await fetchEvent(env, '/api/parse-batch', { method: 'POST' });
    const apiBody = result.response && JSON.parse(result.body);
    check('offline: API は 503 と { offline: true }', result.response && result.response.status === 503 && apiBody.offline === true,
        result.body || result.error);

    // 控えも無いとき: 決まった文言のオフライン画面（HTML）
    cache.store.clear();
    result = await fetchEvent(env, '/', { mode: 'navigate' });
    check('offline: 控えも無ければ HTML のオフライン画面', result.response && result.response.status === 503
        && String(result.response.headers.get('content-type')).startsWith('text/html') && result.body.includes('オフライン'),
        result.body || result.error);

    // アイコンはキャッシュ優先（ネットに行かない）
    env = await installed();
    env.fetchLog.length = 0;
    result = await fetchEvent(env, '/icon-192.png');
    check('icon: キャッシュにあればネットに行かない', result.handled && env.fetchLog.length === 0, JSON.stringify(env.fetchLog));

    // 手を出さないもの
    result = await fetchEvent(env, 'https://other.example/x.js');
    check('scope: 他のサイトへの通信には手を出さない', result.handled === false);
    result = await fetchEvent(env, '/static/index.html');
    check('scope: PRECACHE 以外のファイルはキャッシュしない（ブラウザに任せる）', result.handled === false);

    // API はつながっていればそのまま
    result = await fetchEvent(env, '/api/parse-batch', { method: 'POST' });
    check('api: つながっていればサーバーの応答', result.body === '{"ok":true}', result.body);
}

try {
    await run();
} catch (err) {
    check('sw: 例外なしで動く', false, err && err.stack ? err.stack : err);
}
process.stdout.write(JSON.stringify(results, null, 1));
