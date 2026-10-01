// ============================================================
// タスクの台帳の純粋関数（B29）
// - 状態の移り変わり・2日以上動きなしの判定・台帳の形（Markdown の表・CSV）への変換
// - Notion から書き出した CSV の読み取り・JSON の控え（書き出しと読み込み）
// 画面（app.js）からは window.TaskCore、node のテストからは require で使う。
// ここでは保存も通信もしない（引数を受け取って、新しい値を返すだけ）。
// ============================================================
(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.TaskCore = api;
}(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    // 状態（Notion の台帳と同じ4つ）
    const STATUSES = ['in_progress', 'my_turn', 'done', 'on_hold'];
    const STATUS_LABELS = { in_progress: '進行中', my_turn: '本人の番', done: '完了', on_hold: '保留' };
    // 一覧で並べる順（本人の番を先に）
    const STATUS_ORDER = { my_turn: 0, in_progress: 1, on_hold: 2, done: 3 };
    // 「動きなし」の印を付ける状態（完了・保留は、止まっていてよい）
    const ACTIVE_STATUSES = new Set(['in_progress', 'my_turn']);
    // 公開するコードには見本のレーン名だけを置く（本当の名前は端末ごとの設定で変える）
    const DEFAULT_LANES = ['仕事', '学び', '暮らし'];
    const STALE_HOURS = 48;  // 2日以上動きなし
    const HOUR_MS = 60 * 60 * 1000;
    const JST_OFFSET_MS = 9 * HOUR_MS;  // 日本時間（夏時間なし）
    const LEDGER_COLUMNS = ['件名', 'レーン', '状態', '本人の番', '更新日'];
    const BACKUP_FORMAT = 'task-sync-backup';
    const BACKUP_VERSION = 1;
    const LIMITS = { title: 500, text: 500, lane: 30, lanes: 20, tasks: 5000 };

    const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
    const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

    // ------------------------------------------------------------
    // ID と時刻
    // ------------------------------------------------------------

    // 固定の ID（UUID v4）。crypto.randomUUID が無い環境（http の LAN など）では getRandomValues で作る
    function newUuid(cryptoObj) {
        if (cryptoObj && typeof cryptoObj.randomUUID === 'function') return cryptoObj.randomUUID();
        if (!cryptoObj || typeof cryptoObj.getRandomValues !== 'function') {
            throw new Error('乱数を作れないため、ID を振れません');
        }
        const bytes = cryptoObj.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 0x0f) | 0x40;  // 版 4
        bytes[8] = (bytes[8] & 0x3f) | 0x80;  // RFC 4122 の型
        const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }

    function isUuid(value) {
        return typeof value === 'string' && UUID_RE.test(value);
    }

    function toMillis(value) {
        if (value instanceof Date) return value.getTime();
        if (typeof value === 'number') return value;
        if (typeof value === 'string') return Date.parse(value);
        return NaN;
    }

    function toIso(value) {
        const ms = toMillis(value);
        if (!Number.isFinite(ms)) throw new Error('時刻が読めません');
        return new Date(ms).toISOString();
    }

    function isValidTimestamp(value) {
        return typeof value === 'string' && Number.isFinite(Date.parse(value));
    }

    // 日本時間の日付（YYYY-MM-DD）
    function jstDate(value) {
        const ms = toMillis(value);
        if (!Number.isFinite(ms)) return '';
        return new Date(ms + JST_OFFSET_MS).toISOString().slice(0, 10);
    }

    function isValidDate(text) {
        const match = typeof text === 'string' && DATE_RE.exec(text);
        if (!match) return false;
        const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
        const date = new Date(Date.UTC(y, m - 1, d));
        return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
    }

    function clip(value, max) {
        return String(value === undefined || value === null ? '' : value).trim().slice(0, max);
    }

    // ------------------------------------------------------------
    // タスクを作る・状態を変える・直す
    // ------------------------------------------------------------

    // 解析の結果（API の1行）から、保存するタスクを作る。ID はここで振り、あとで変えない
    function createTask(parsed, { id, now, lane }) {
        if (!isUuid(id)) throw new Error('ID が UUID ではありません');
        const title = clip(parsed && parsed.title, LIMITS.title);
        if (!title) throw new Error('件名がありません');
        const deadline = typeof parsed.deadline === 'string' ? parsed.deadline.slice(0, 10) : '';
        const at = toIso(now);
        return {
            id,
            title,
            lane: clip(lane, LIMITS.lane) || DEFAULT_LANES[0],
            status: 'in_progress',
            next_action: '',
            deadline: isValidDate(deadline) ? deadline : null,
            due_time: TIME_RE.test(parsed.due_time || '') ? parsed.due_time : null,
            category: clip(parsed.category, LIMITS.lane),
            raw_text: clip(parsed.raw_text, LIMITS.text),
            created_at: at,
            updated_at: at,
            revision: 0
        };
    }

    // 変えた項目だけを入れた新しいタスクを返す。何も変わらなければ、もとの task をそのまま返す
    function applyChange(task, changes, now) {
        const next = { ...task };
        let changed = false;
        if (changes.status !== undefined) {
            if (!STATUSES.includes(changes.status)) throw new Error(`知らない状態です: ${changes.status}`);
            if (changes.status !== task.status) {
                next.status = changes.status;
                changed = true;
            }
        }
        if (changes.next_action !== undefined) {
            const text = clip(changes.next_action, LIMITS.text);
            if (text !== (task.next_action || '')) {
                next.next_action = text;
                changed = true;
            }
        }
        if (changes.lane !== undefined) {
            const lane = clip(changes.lane, LIMITS.lane);
            if (!lane) throw new Error('レーン名が空です');
            if (lane !== task.lane) {
                next.lane = lane;
                changed = true;
            }
        }
        if (!changed) return task;
        next.updated_at = toIso(now);
        next.revision = (Number.isInteger(task.revision) ? task.revision : 0) + 1;
        return next;
    }

    // 状態を変える（どの状態からどの状態へも変えられる。同じ状態なら何もしない）
    function transition(task, status, now) {
        return applyChange(task, { status }, now);
    }

    // ------------------------------------------------------------
    // 2日以上動きなし・本人の番の一覧
    // ------------------------------------------------------------

    function hoursSince(timestamp, now) {
        const from = toMillis(timestamp);
        const to = toMillis(now);
        if (!Number.isFinite(from) || !Number.isFinite(to)) return NaN;
        return (to - from) / HOUR_MS;
    }

    // 進行中・本人の番のまま、最後に動いてから 48 時間以上たったもの
    function isStale(task, now, hours = STALE_HOURS) {
        if (!task || !ACTIVE_STATUSES.has(task.status)) return false;
        const passed = hoursSince(task.updated_at, now);
        return Number.isFinite(passed) && passed >= hours;
    }

    function compareDeadline(a, b) {
        if (a.deadline && b.deadline) return a.deadline < b.deadline ? -1 : a.deadline > b.deadline ? 1 : 0;
        if (a.deadline) return -1;
        if (b.deadline) return 1;
        return 0;
    }

    // 本人の番だけ。動きのないものを先に、次に期限の近い順、最後に古い順
    function myTurnList(tasks, now) {
        return tasks
            .filter(task => task.status === 'my_turn')
            .map(task => ({ task, stale: isStale(task, now) }))
            .sort((a, b) => (Number(b.stale) - Number(a.stale))
                || compareDeadline(a.task, b.task)
                || String(a.task.updated_at).localeCompare(String(b.task.updated_at)))
            .map(entry => entry.task);
    }

    // 一覧の並び: 本人の番 → 進行中 → 保留 → 完了。同じ状態の中は期限の近い順・作った順
    function sortTasks(tasks) {
        return tasks.slice().sort((a, b) => (STATUS_ORDER[a.status] - STATUS_ORDER[b.status])
            || compareDeadline(a, b)
            || String(a.created_at).localeCompare(String(b.created_at)));
    }

    // ------------------------------------------------------------
    // 台帳の形（件名/レーン/状態/本人の番/更新日）
    // ------------------------------------------------------------

    function toLedgerRows(tasks) {
        return tasks.map(task => ({
            件名: task.title,
            レーン: task.lane,
            状態: STATUS_LABELS[task.status] || task.status,
            本人の番: task.next_action || '',
            更新日: jstDate(task.updated_at)
        }));
    }

    function markdownCell(value) {
        return String(value).replace(/\\/g, '\\\\').replace(/\|/g, '\\|').replace(/\r\n|\r|\n/g, ' ');
    }

    function toMarkdownTable(rows, columns = LEDGER_COLUMNS) {
        const lines = [
            `| ${columns.map(markdownCell).join(' | ')} |`,
            `| ${columns.map(() => '---').join(' | ')} |`
        ];
        for (const row of rows) lines.push(`| ${columns.map(c => markdownCell(row[c] ?? '')).join(' | ')} |`);
        return lines.join('\n') + '\n';
    }

    // RFC 4180 の CSV（, " 改行を含む欄は " で囲み、" は "" にする。行の区切りは CRLF）
    function csvCell(value) {
        const text = String(value);
        return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    }

    function toCsv(rows, columns = LEDGER_COLUMNS) {
        const lines = [columns.map(csvCell).join(',')];
        for (const row of rows) lines.push(columns.map(c => csvCell(row[c] ?? '')).join(','));
        return lines.join('\r\n') + '\r\n';
    }

    // CSV を行の配列に分ける（先頭の BOM・" で囲んだ欄・欄の中の改行・CRLF/LF/CR）
    function parseCsv(text) {
        const source = String(text).replace(/^﻿/, '');
        const rows = [];
        let row = [];
        let field = '';
        let quoted = false;
        let i = 0;
        const endField = () => { row.push(field); field = ''; };
        const endRow = () => {
            endField();
            if (!(row.length === 1 && row[0] === '')) rows.push(row);  // 空の行は飛ばす
            row = [];
        };
        while (i < source.length) {
            const ch = source[i];
            if (quoted) {
                if (ch === '"') {
                    if (source[i + 1] === '"') { field += '"'; i += 2; continue; }
                    quoted = false;
                    i += 1;
                    continue;
                }
                field += ch;
                i += 1;
                continue;
            }
            if (ch === '"' && field === '') { quoted = true; i += 1; continue; }
            if (ch === ',') { endField(); i += 1; continue; }
            if (ch === '\r' || ch === '\n') {
                endRow();
                i += (ch === '\r' && source[i + 1] === '\n') ? 2 : 1;
                continue;
            }
            field += ch;
            i += 1;
        }
        if (quoted) throw new Error('CSV の " が閉じていません');
        if (field !== '' || row.length) endRow();
        return rows;
    }

    const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
        'september', 'october', 'november', 'december'];

    function pad2(n) {
        return String(n).padStart(2, '0');
    }

    // 台帳の「更新日」を YYYY-MM-DD にする（読めなければ null）。時刻は使わず、日付だけを読む
    function parseLooseDate(text) {
        const value = String(text || '').trim().replace(/^@/, '');
        let match = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:$|[\sT])/.exec(value)
            || /^(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日/.exec(value);
        let parts = match ? [match[1], match[2], match[3]] : null;
        if (!parts) {
            match = /^([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})/.exec(value);
            const month = match ? MONTHS.findIndex(m => m.startsWith(match[1].toLowerCase()) && match[1].length >= 3) : -1;
            if (month >= 0) parts = [match[3], String(month + 1), match[2]];
        }
        if (!parts) return null;
        const date = `${parts[0]}-${pad2(parts[1])}-${pad2(parts[2])}`;
        return isValidDate(date) ? date : null;
    }

    // 日付どうしの日数（日本時間の日付で数える）
    function daysBetween(fromDate, toDate) {
        const a = Date.parse(`${fromDate}T00:00:00Z`);
        const b = Date.parse(`${toDate}T00:00:00Z`);
        return Math.round((b - a) / (24 * HOUR_MS));
    }

    // Notion から書き出した CSV を読み、状態が「本人の番」の行だけを返す（保存はしない）
    function readNotionCsv(text, now) {
        const rows = parseCsv(text);
        if (rows.length === 0) throw new Error('CSV が空です');
        const header = rows[0].map(name => name.trim());
        const index = Object.fromEntries(LEDGER_COLUMNS.map(name => [name, header.indexOf(name)]));
        const missing = ['件名', '状態'].filter(name => index[name] < 0);
        if (missing.length) throw new Error(`CSV の1行目に「${missing.join('」「')}」の列がありません`);
        const cell = (row, name) => (index[name] >= 0 ? String(row[index[name]] || '').trim() : '');
        const today = jstDate(now);
        const items = [];
        for (const row of rows.slice(1)) {
            if (cell(row, '状態') !== STATUS_LABELS.my_turn) continue;
            const turn = cell(row, '本人の番');
            const updated = cell(row, '更新日');
            const updatedDate = parseLooseDate(updated);
            items.push({
                title: cell(row, '件名') || '（件名なし）',
                lane: cell(row, 'レーン'),
                next_action: turn,
                updated,
                updated_date: updatedDate,
                stale: Boolean(updatedDate && today && daysBetween(updatedDate, today) >= 2),
                turn_missing: turn === '' || turn.startsWith('なし')
            });
        }
        items.sort((a, b) => (Number(b.stale) - Number(a.stale))
            || String(a.updated_date || '9999').localeCompare(String(b.updated_date || '9999')));
        return { items, total: rows.length - 1 };
    }

    // ------------------------------------------------------------
    // レーン名の設定
    // ------------------------------------------------------------

    function normalizeLanes(input) {
        const list = Array.isArray(input) ? input : String(input || '').split(/\r?\n|,|、/);
        const lanes = [];
        for (const name of list) {
            const lane = clip(name, LIMITS.lane);
            if (lane && !lanes.includes(lane)) lanes.push(lane);
            if (lanes.length >= LIMITS.lanes) break;
        }
        return lanes.length ? lanes : DEFAULT_LANES.slice();
    }

    // ------------------------------------------------------------
    // JSON の控え（端末を替えるときに手で移す）
    // ------------------------------------------------------------

    function makeBackup(tasks, settings, now) {
        return {
            format: BACKUP_FORMAT,
            version: BACKUP_VERSION,
            exported_at: toIso(now),
            settings: { lanes: normalizeLanes(settings && settings.lanes) },
            tasks: tasks.map(task => ({ ...task }))
        };
    }

    // 読み込んだ1件を確かめて、知っている項目だけの形にする（おかしなものは null）
    function sanitizeTask(raw) {
        if (!raw || typeof raw !== 'object') return null;
        if (!isUuid(raw.id) || !STATUSES.includes(raw.status)) return null;
        if (!isValidTimestamp(raw.created_at) || !isValidTimestamp(raw.updated_at)) return null;
        const title = clip(raw.title, LIMITS.title);
        if (!title) return null;
        const deadline = raw.deadline === null || raw.deadline === undefined || raw.deadline === '' ? null : raw.deadline;
        if (deadline !== null && !isValidDate(deadline)) return null;
        return {
            id: raw.id.toLowerCase(),
            title,
            lane: clip(raw.lane, LIMITS.lane) || DEFAULT_LANES[0],
            status: raw.status,
            next_action: clip(raw.next_action, LIMITS.text),
            deadline,
            due_time: TIME_RE.test(raw.due_time || '') ? raw.due_time : null,
            category: clip(raw.category, LIMITS.lane),
            raw_text: clip(raw.raw_text, LIMITS.text),
            created_at: toIso(raw.created_at),
            updated_at: toIso(raw.updated_at),
            revision: Number.isInteger(raw.revision) && raw.revision >= 0 ? raw.revision : 0
        };
    }

    function readBackup(text) {
        let data;
        try {
            data = JSON.parse(String(text).replace(/^﻿/, ''));
        } catch (err) {
            throw new Error('JSON として読めません');
        }
        if (!data || data.format !== BACKUP_FORMAT || !Array.isArray(data.tasks)) {
            throw new Error('このアプリで書き出した JSON ではありません');
        }
        if (data.version !== BACKUP_VERSION) throw new Error(`知らない版の JSON です（version ${data.version}）`);
        if (data.tasks.length > LIMITS.tasks) throw new Error(`タスクが多すぎます（${LIMITS.tasks}件まで）`);
        const tasks = [];
        let invalid = 0;
        for (const raw of data.tasks) {
            const task = sanitizeTask(raw);
            if (task) tasks.push(task);
            else invalid += 1;
        }
        const lanes = data.settings && data.settings.lanes ? normalizeLanes(data.settings.lanes) : null;
        return { tasks, invalid, lanes };
    }

    // 同じ ID は、更新の新しい方を残す（同じ時刻なら今ある方）
    function mergeTasks(existing, incoming) {
        const byId = new Map(existing.map(task => [task.id, task]));
        const changed = [];
        let added = 0;
        let updated = 0;
        let unchanged = 0;
        for (const task of incoming) {
            const current = byId.get(task.id);
            if (!current) {
                added += 1;
            } else if (toMillis(task.updated_at) > toMillis(current.updated_at)) {
                updated += 1;
            } else {
                unchanged += 1;
                continue;
            }
            byId.set(task.id, task);
            changed.push(task);
        }
        return { tasks: Array.from(byId.values()), changed, added, updated, unchanged };
    }

    return {
        STATUSES, STATUS_LABELS, DEFAULT_LANES, STALE_HOURS, LEDGER_COLUMNS, BACKUP_FORMAT, BACKUP_VERSION, LIMITS,
        newUuid, isUuid, toIso, jstDate, isValidDate,
        createTask, applyChange, transition,
        hoursSince, isStale, myTurnList, sortTasks,
        toLedgerRows, toMarkdownTable, toCsv, parseCsv, parseLooseDate, readNotionCsv,
        normalizeLanes, makeBackup, readBackup, mergeTasks
    };
}));
