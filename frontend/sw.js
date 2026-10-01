// ============================================================
// Service Worker - オフライン対応とキャッシング
// ============================================================
// 作成: Tech僧侶（江音寺 荻原龍光）
// バージョン: 1.0
// ============================================================
//
// 方針（B28）
// - 画面の本体（/・/index.html・/app.js・/app.css・/manifest.json）はネット優先。
//   取れたらキャッシュを新しくし、電波が無いときだけキャッシュ（控え）を返す。
// - アイコンはキャッシュ優先（めったに変わらない）。
// - API（/api/）はキャッシュしない。電波が無いときは { offline: true } の 503 を返す。
// - 画面を開こうとして、電波も控えも無いときは offline.html（オフライン画面）を返す。
// - 新しい版を入れても勝手には切り替えない。画面の「更新する」（SKIP_WAITING）で切り替える。
//   ただし、案内を出せない古い版（v3 まで）からは、待たずに切り替える（次に開いたときに新しい画面になる）。
// ============================================================

// PRECACHE_URLS のファイルを変えたら、この番号を 1 つ上げる。
// 上げ忘れは tests/test_b28_service_worker.py が見つける。
// 番号を上げたら python scripts/sw_version.py --update で記録（tests/fixtures/sw_precache.json）を作り直す。
const CACHE_VERSION = 4;
const CACHE_PREFIX = 'task-sync-';
const CACHE_NAME = `${CACHE_PREFIX}v${CACHE_VERSION}`;
const OFFLINE_URL = '/offline.html';

// 入れたときに先にキャッシュしておくファイル
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/app.js',
  '/app.css',
  '/offline.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  '/icon-maskable-192.png',
  '/icon-maskable-512.png'
];

// ネット優先で取りに行くもの（画面の本体）。ほかの PRECACHE_URLS（アイコン）はキャッシュ優先
const NETWORK_FIRST_PATHS = new Set(['/', '/index.html', '/app.js', '/app.css', '/manifest.json', OFFLINE_URL]);

// offline.html もキャッシュに無いときの、最後の控え（決まった文言だけ）
const OFFLINE_FALLBACK_HTML =
  '<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><title>オフライン - Task Sync</title></head>' +
  '<body><p>オフラインです。電波のよい所で、もう一度開いてください。</p></body></html>';

// 「新しい版があります」を出せる最初の版。これより古い版（キャッシュ優先だった v3 まで）の画面は
// 案内を出せず、新しい版がいつまでも待ったままになるので、その版からは待たずに切り替える
const FIRST_VERSION_WITH_UPDATE_NOTICE = 4;

function isLegacyCache(name) {
  const match = /^task-sync-v(\d+)$/.exec(name);
  return Boolean(match) && Number(match[1]) < FIRST_VERSION_WITH_UPDATE_NOTICE;
}

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache =>
        // ブラウザの HTTP キャッシュを通さず、サーバーから取り直す
        cache.addAll(PRECACHE_URLS.map(url => new Request(url, { cache: 'reload' })))
      )
      .then(() => caches.keys())
      .then(names => {
        if (names.some(isLegacyCache)) return self.skipWaiting();
      })
  );
});

// 画面の「更新する」が押されたら、待っている新しい版に切り替える
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// 切り替わったら、古い版のキャッシュを消す
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(names => Promise.all(
        names
          .filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
          .map(name => caches.delete(name))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;  // 他のサイトへの通信には手を出さない

  // API: キャッシュしない（常に最新）。電波が無いときは決まった JSON を返す
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request).catch(offlineApiResponse));
    return;
  }
  if (request.method !== 'GET') return;

  if (request.mode === 'navigate') {
    event.respondWith(handleNavigation(request, url));
    return;
  }
  if (NETWORK_FIRST_PATHS.has(url.pathname)) {
    event.respondWith(networkFirst(request, url.pathname));
    return;
  }
  if (PRECACHE_URLS.includes(url.pathname)) {
    event.respondWith(cacheFirst(request));
  }
  // それ以外はブラウザに任せる（キャッシュしない）
});

// ネット優先: 取れたらキャッシュ（cacheKey）を新しくして返す。取れなければキャッシュを返す
async function networkFirst(request, cacheKey) {
  try {
    const response = await fetch(request);
    if (cacheKey && response.ok && response.type === 'basic') {
      const cache = await caches.open(CACHE_NAME);
      await cache.put(cacheKey, response.clone());
    }
    return response;
  } catch (err) {
    const cached = cacheKey ? await caches.match(cacheKey) : undefined;
    if (cached) return cached;
    throw err;
  }
}

// 画面を開くとき: ネット → キャッシュの控え → オフライン画面 の順
async function handleNavigation(request, url) {
  const cacheKey = NETWORK_FIRST_PATHS.has(url.pathname) ? url.pathname : null;
  try {
    return await networkFirst(request, cacheKey);
  } catch (err) {
    const offline = await caches.match(OFFLINE_URL);
    return offline || new Response(OFFLINE_FALLBACK_HTML, {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' }
    });
  }
}

// キャッシュ優先（アイコン）
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok && response.type === 'basic') {
    const cache = await caches.open(CACHE_NAME);
    await cache.put(request, response.clone());
  }
  return response;
}

function offlineApiResponse() {
  return new Response(
    JSON.stringify({
      error: 'オフラインのため、APIにアクセスできません',
      offline: true
    }),
    {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    }
  );
}
