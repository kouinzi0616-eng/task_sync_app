// ============================================================
// 端末の中の保存場所（IndexedDB）（B29）
// - データベース task-sync の入れ物 tasks（タスク。id が鍵）と settings（設定。key が鍵）
// - IndexedDB が使えない環境（古いブラウザ・一部のプライベートブラウズ）では、
//   画面を閉じると消える一時の保存（memory）に切り替え、画面でそのことを伝える
// 外部には送信しない（ブラウザの中だけで読み書きする）。方針は docs/storage.md。
// ============================================================
(function (root) {
    'use strict';

    const DB_NAME = 'task-sync';
    const DB_VERSION = 1;
    const TASKS = 'tasks';
    const SETTINGS = 'settings';

    function promisify(request) {
        return new Promise((resolve, reject) => {
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    function openDatabase(factory) {
        return new Promise((resolve, reject) => {
            const request = factory.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = () => {
                const db = request.result;
                if (!db.objectStoreNames.contains(TASKS)) db.createObjectStore(TASKS, { keyPath: 'id' });
                if (!db.objectStoreNames.contains(SETTINGS)) db.createObjectStore(SETTINGS, { keyPath: 'key' });
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
            request.onblocked = () => reject(new Error('ほかの画面が古い保存場所を使っています。ほかのタブを閉じてください'));
        });
    }

    // 書き込みは、取引（transaction）が終わってから「済んだ」と返す
    function write(db, storeName, action) {
        return new Promise((resolve, reject) => {
            const tx = db.transaction(storeName, 'readwrite');
            action(tx.objectStore(storeName));
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
            tx.onabort = () => reject(tx.error || new Error('保存を取り消しました'));
        });
    }

    function indexedDbStore(db) {
        return {
            kind: 'indexeddb',
            getAll: () => promisify(db.transaction(TASKS, 'readonly').objectStore(TASKS).getAll()),
            putMany: tasks => write(db, TASKS, store => tasks.forEach(task => store.put(task))),
            put: task => write(db, TASKS, store => store.put(task)),
            remove: id => write(db, TASKS, store => store.delete(id)),
            getSetting: key => promisify(db.transaction(SETTINGS, 'readonly').objectStore(SETTINGS).get(key))
                .then(row => (row ? row.value : undefined)),
            setSetting: (key, value) => write(db, SETTINGS, store => store.put({ key, value }))
        };
    }

    // 一時の保存（画面を閉じると消える）。値は写しを持つ（呼んだ側が書きかえても中身は変わらない）
    function memoryStore() {
        const tasks = new Map();
        const settings = new Map();
        const copy = value => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
        return {
            kind: 'memory',
            getAll: async () => Array.from(tasks.values(), copy),
            putMany: async list => { list.forEach(task => tasks.set(task.id, copy(task))); },
            put: async task => { tasks.set(task.id, copy(task)); },
            remove: async id => { tasks.delete(id); },
            getSetting: async key => copy(settings.get(key)),
            setSetting: async (key, value) => { settings.set(key, copy(value)); }
        };
    }

    // IndexedDB を開く。開けなければ一時の保存を返す（reason に理由）
    async function openStore(env) {
        const scope = env || root;
        let factory = null;
        try {
            factory = scope.indexedDB || null;
        } catch (err) {
            factory = null;  // 一部のブラウザは、使えないとき読むだけで例外を出す
        }
        if (!factory) return { store: memoryStore(), reason: 'IndexedDB が使えません' };
        try {
            return { store: indexedDbStore(await openDatabase(factory)), reason: '' };
        } catch (err) {
            return { store: memoryStore(), reason: (err && err.message) || 'IndexedDB を開けません' };
        }
    }

    // ブラウザに「空きが少なくても消さないで」と頼む（受け入れるかはブラウザ次第。通信はしない）
    async function requestPersistence(env) {
        const scope = env || root;
        try {
            const storage = scope.navigator && scope.navigator.storage;
            if (!storage || typeof storage.persist !== 'function') return false;
            if (typeof storage.persisted === 'function' && await storage.persisted()) return true;
            return Boolean(await storage.persist());
        } catch (err) {
            return false;
        }
    }

    root.TaskStore = { DB_NAME, DB_VERSION, openStore, memoryStore, requestPersistence };
}(typeof self !== 'undefined' ? self : this));
