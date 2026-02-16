// ============================================================
// Service Worker - オフライン対応とキャッシング
// ============================================================
// 作成: Tech僧侶（江音寺 荻原龍光）
// バージョン: 1.0
// ============================================================

const CACHE_NAME = 'task-sync-v1';
const urlsToCache = [
  '/',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

// インストール時: 静的ファイルをキャッシュ
self.addEventListener('install', event => {
  console.log('[SW] Install');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[SW] Caching app shell');
        return cache.addAll(urlsToCache);
      })
      .catch(err => {
        console.error('[SW] Cache error:', err);
      })
  );
  self.skipWaiting();
});

// アクティベート時: 古いキャッシュを削除
self.addEventListener('activate', event => {
  console.log('[SW] Activate');
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            console.log('[SW] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// フェッチ時: キャッシュ優先、フォールバック戦略
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // API リクエストはキャッシュしない（常に最新データを取得）
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .catch(() => {
          // オフライン時のフォールバック
          return new Response(
            JSON.stringify({ 
              error: 'オフラインのため、APIにアクセスできません',
              offline: true 
            }),
            { 
              headers: { 'Content-Type': 'application/json' },
              status: 503
            }
          );
        })
    );
    return;
  }

  // 静的ファイル: キャッシュファースト
  event.respondWith(
    caches.match(request)
      .then(response => {
        if (response) {
          console.log('[SW] Cache hit:', request.url);
          return response;
        }
        
        console.log('[SW] Fetching:', request.url);
        return fetch(request)
          .then(response => {
            // レスポンスが有効な場合のみキャッシュ
            if (!response || response.status !== 200 || response.type === 'error') {
              return response;
            }

            const responseToCache = response.clone();
            caches.open(CACHE_NAME)
              .then(cache => {
                cache.put(request, responseToCache);
              });

            return response;
          });
      })
      .catch(err => {
        console.error('[SW] Fetch failed:', err);
        // オフライン時のフォールバックページ（任意）
        return new Response('オフラインです', {
          headers: { 'Content-Type': 'text/plain; charset=utf-8' }
        });
      })
  );
});

// プッシュ通知受信時
self.addEventListener('push', event => {
  console.log('[SW] Push received');
  
  const options = {
    body: event.data ? event.data.text() : 'タスクの期限が近づいています',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    vibrate: [200, 100, 200],
    tag: 'task-notification',
    requireInteraction: true
  };

  event.waitUntil(
    self.registration.showNotification('Task Sync', options)
  );
});

// 通知クリック時
self.addEventListener('notificationclick', event => {
  console.log('[SW] Notification clicked');
  event.notification.close();
  
  event.waitUntil(
    clients.openWindow('/')
  );
});
