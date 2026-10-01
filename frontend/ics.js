// ============================================================
// カレンダー用ファイル（.ics・RFC 5545）を作る純粋関数（B30）
// - 期限のあるタスクを、終日の予定（DTSTART;VALUE=DATE と翌日の DTEND）にする
// - UID はタスクの固定の ID（B29 の UUID）。題名や期限を直しても変わらないので、
//   読み込み直したときに同じ予定として扱える（扱いはカレンダーのアプリ次第）
// - 1行は 75 オクテットまで（文字の途中では切らない）で折り返し、改行は CRLF
// 画面（app.js）からは window.TaskIcs、node のテストからは require で使う。保存も通信もしない。
// ============================================================
(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.TaskIcs = api;
}(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    const PRODID = '-//task_sync_app//Task Sync//JA';
    const MAX_OCTETS = 75;  // CRLF を除いた1行の長さ（RFC 5545 3.1）
    const STATUS_LABELS = { in_progress: '進行中', my_turn: '本人の番', done: '完了', on_hold: '保留' };
    const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

    // UTF-8 で何オクテットか（1文字＝1つの符号位置）
    function octets(ch) {
        const cp = ch.codePointAt(0);
        if (cp < 0x80) return 1;
        if (cp < 0x800) return 2;
        if (cp < 0x10000) return 3;
        return 4;
    }

    // 75 オクテットを超える行は CRLF と空白1つで折り返す（続きの行は空白を含めて 75 まで）
    function foldLine(line) {
        const parts = [];
        let current = '';
        let size = 0;
        for (const ch of line) {  // for...of は符号位置ごと（サロゲートペアを分けない）
            const n = octets(ch);
            if (size + n > MAX_OCTETS) {
                parts.push(current);
                current = ' ';
                size = 1;
            }
            current += ch;
            size += n;
        }
        parts.push(current);
        return parts.join('\r\n');
    }

    // TEXT の値（RFC 5545 3.3.11）: \ ; , 改行を逃がし、使えない制御文字は除く
    function escapeText(value) {
        return String(value === undefined || value === null ? '' : value)
            .replace(/\\/g, '\\\\')
            .replace(/;/g, '\\;')
            .replace(/,/g, '\\,')
            .replace(/\r\n|\r|\n/g, '\\n')
            .replace(/[\u0000-\u0008\u000A-\u001F\u007F]/g, '');
    }

    function parseDate(text) {
        const match = typeof text === 'string' && DATE_RE.exec(text);
        if (!match) return null;
        const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
        const date = new Date(Date.UTC(y, m - 1, d));
        if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) return null;
        return date;
    }

    // YYYY-MM-DD → YYYYMMDD（days 日あと）
    function formatDate(text, days = 0) {
        const date = parseDate(text);
        if (!date) throw new Error(`日付が読めません: ${text}`);
        date.setUTCDate(date.getUTCDate() + days);
        return date.toISOString().slice(0, 10).replace(/-/g, '');
    }

    // 時刻 → UTC の YYYYMMDDTHHMMSSZ
    function formatUtc(value) {
        const ms = value instanceof Date ? value.getTime() : Date.parse(value);
        if (!Number.isFinite(ms)) throw new Error('時刻が読めません');
        return new Date(ms).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
    }

    function canExport(task, includeDone) {
        return Boolean(task) && UUID_RE.test(task.id || '') && parseDate(task.deadline) !== null
            && (includeDone || task.status !== 'done');
    }

    function describe(task) {
        const lines = [`状態: ${STATUS_LABELS[task.status] || task.status}`];
        if (task.next_action) lines.push(`次に本人がすること: ${task.next_action}`);
        if (task.due_time) lines.push(`時刻: ${task.due_time}`);
        if (task.raw_text) lines.push(`もとの行: ${task.raw_text}`);
        return lines.join('\n');
    }

    function eventLines(task, stamp) {
        const lines = [
            'BEGIN:VEVENT',
            `UID:${task.id.toLowerCase()}`,
            `DTSTAMP:${stamp}`,
            `DTSTART;VALUE=DATE:${formatDate(task.deadline)}`,
            `DTEND;VALUE=DATE:${formatDate(task.deadline, 1)}`,  // 終日の予定の終わりは翌日（その日を含まない）
            `SUMMARY:${escapeText(task.title)}`,
            `DESCRIPTION:${escapeText(describe(task))}`
        ];
        if (task.lane) lines.push(`CATEGORIES:${escapeText(task.lane)}`);
        lines.push('TRANSP:TRANSPARENT');  // 期限の目印なので、予定の空き時間はふさがない
        lines.push(`SEQUENCE:${Number.isInteger(task.revision) && task.revision >= 0 ? task.revision : 0}`);
        if (task.created_at && Number.isFinite(Date.parse(task.created_at))) lines.push(`CREATED:${formatUtc(task.created_at)}`);
        if (task.updated_at && Number.isFinite(Date.parse(task.updated_at))) lines.push(`LAST-MODIFIED:${formatUtc(task.updated_at)}`);
        lines.push('END:VEVENT');
        return lines;
    }

    // タスクの一覧から .ics の文字を作る。期限の無いもの・完了（includeDone が false のとき）は入れない
    function buildIcs(tasks, { now, includeDone = false } = {}) {
        const stamp = formatUtc(now === undefined ? new Date() : now);
        const chosen = tasks.filter(task => canExport(task, includeDone))
            .sort((a, b) => (a.deadline < b.deadline ? -1 : a.deadline > b.deadline ? 1 : 0));
        const skipped = {
            no_deadline: tasks.filter(task => task && parseDate(task.deadline) === null).length,
            done: includeDone ? 0 : tasks.filter(task => task && task.status === 'done' && parseDate(task.deadline) !== null).length
        };
        if (chosen.length === 0) return { text: '', count: 0, skipped };  // 予定が1つも無い VCALENDAR は作らない
        const lines = [
            'BEGIN:VCALENDAR',
            'VERSION:2.0',
            `PRODID:${PRODID}`,
            'CALSCALE:GREGORIAN',
            'METHOD:PUBLISH'
        ];
        chosen.forEach(task => lines.push(...eventLines(task, stamp)));
        lines.push('END:VCALENDAR');
        return { text: lines.map(foldLine).join('\r\n') + '\r\n', count: chosen.length, skipped };
    }

    return { PRODID, MAX_OCTETS, octets, foldLine, escapeText, formatDate, formatUtc, buildIcs };
}));
