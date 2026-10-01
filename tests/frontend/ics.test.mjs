// ============================================================
// frontend/ics.js（カレンダー用ファイル .ics）の検算。node:test だけを使う。
// 使い方: node --test tests/frontend/ics.test.mjs
//   TSA_ICS_JS=別のファイル を付けると、そのファイルを確かめる（検算が働くかの確認用）
// RFC 5545 の決まり（必須の項目・終日の予定・75 オクテットの折り返し・CRLF・文字の逃がし方）を確かめる。
// データはすべて架空。外部には送信しない。
// ============================================================
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ics = require(process.env.TSA_ICS_JS || '../../frontend/ics.js');
const core = require('../../frontend/task_core.js');

const NOW = '2026-10-01T01:02:03.456Z';
const ID1 = '11111111-1111-4111-8111-111111111111';
const ID2 = '22222222-2222-4222-8222-222222222222';

function task(overrides = {}) {
    return {
        id: ID1, title: '架空の資料作り', lane: '仕事', status: 'my_turn', next_action: '架空の下書きを読む',
        deadline: '2026-10-15', due_time: null, category: '個人', raw_text: '架空の資料作り (10/15まで)',
        created_at: '2026-09-30T00:00:00.000Z', updated_at: '2026-09-30T12:00:00.000Z', revision: 2, ...overrides
    };
}

// 折り返しを戻して、行ごとの「名前 → 値」にする
function unfold(text) {
    return text.replace(/\r\n[ \t]/g, '').split('\r\n').filter(Boolean);
}

function props(text) {
    return unfold(text).map(line => {
        const index = line.search(/[:;]/);
        return { name: line.slice(0, index), rest: line.slice(index) };
    });
}

const utf8 = text => Buffer.byteLength(text, 'utf8');

test('必須の項目: VCALENDAR に VERSION・PRODID、VEVENT に UID・DTSTAMP・DTSTART', () => {
    const { text, count } = ics.buildIcs([task()], { now: NOW });
    assert.equal(count, 1);
    const lines = unfold(text);
    assert.deepEqual(lines.slice(0, 5), ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//task_sync_app//Task Sync//JA', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']);
    assert.equal(lines.at(-1), 'END:VCALENDAR');
    for (const line of [`UID:${ID1}`, 'DTSTAMP:20261001T010203Z', 'DTSTART;VALUE=DATE:20261015', 'DTEND;VALUE=DATE:20261016',
        'SUMMARY:架空の資料作り', 'CATEGORIES:仕事', 'TRANSP:TRANSPARENT', 'SEQUENCE:2',
        'CREATED:20260930T000000Z', 'LAST-MODIFIED:20260930T120000Z']) {
        assert.ok(lines.includes(line), line);
    }
    assert.equal(lines.filter(l => l === 'BEGIN:VEVENT').length, 1);
    assert.equal(lines.filter(l => l === 'END:VEVENT').length, 1);
});

test('終日の予定: DTEND は翌日（月末・年末・うるう年もまたぐ）', () => {
    const cases = [['2026-12-31', '20261231', '20270101'], ['2027-02-28', '20270228', '20270301'],
        ['2028-02-28', '20280228', '20280229'], ['2028-02-29', '20280229', '20280301'], ['2026-04-30', '20260430', '20260501']];
    for (const [deadline, start, end] of cases) {
        const lines = unfold(ics.buildIcs([task({ deadline })], { now: NOW }).text);
        assert.ok(lines.includes(`DTSTART;VALUE=DATE:${start}`), deadline);
        assert.ok(lines.includes(`DTEND;VALUE=DATE:${end}`), deadline);
    }
});

test('改行は CRLF だけで、最後も CRLF', () => {
    const { text } = ics.buildIcs([task({ title: 'あ'.repeat(60) }), task({ id: ID2 })], { now: NOW });
    assert.ok(text.endsWith('\r\n'));
    assert.equal(/[^\r]\n/.test(text), false, 'LF だけの改行がある');
    assert.equal(/\r[^\n]/.test(text), false, 'CR だけの改行がある');
});

test('折り返し: どの行も 75 オクテット以内。続きの行は空白1つで始まり、戻すと元の値になる', () => {
    const title = '架空の長い題名' + 'とても長い説明'.repeat(20) + '🙏絵文字も' + 'A'.repeat(50);
    const { text } = ics.buildIcs([task({ title, next_action: '次は' + '確認'.repeat(40) })], { now: NOW });
    for (const line of text.split('\r\n')) assert.ok(utf8(line) <= 75, `${utf8(line)} オクテット: ${line}`);
    const physical = text.split('\r\n');
    assert.ok(physical.some(line => line.startsWith(' ')), '折り返しがある');
    assert.ok(unfold(text).includes(`SUMMARY:${title}`), '戻すと元の題名');
});

test('折り返し: 文字（UTF-8 の多バイト・サロゲートペア）の途中では切らない', () => {
    const line = 'SUMMARY:' + '漢'.repeat(30) + '🙏'.repeat(20);
    const folded = ics.foldLine(line);
    for (const part of folded.split('\r\n')) {
        assert.ok(utf8(part) <= 75);
        assert.equal(Buffer.from(part, 'utf8').toString('utf8'), part, '壊れた文字がない');
        assert.equal(/[\uD800-\uDBFF]$/.test(part), false, 'サロゲートペアを分けていない');
    }
    assert.equal(folded.replace(/\r\n /g, ''), line);
});

test('折り返し: ちょうど 75 オクテットは折り返さず、76 から折り返す', () => {
    assert.equal(ics.foldLine('A'.repeat(75)), 'A'.repeat(75));
    assert.equal(ics.foldLine('A'.repeat(76)), `${'A'.repeat(75)}\r\n A`);
    assert.equal(ics.foldLine('A'.repeat(75 + 74 + 1)), `${'A'.repeat(75)}\r\n ${'A'.repeat(74)}\r\n A`);
    // 3 オクテットの文字: 25 文字で 75。26 文字目から折り返す
    assert.equal(ics.foldLine('あ'.repeat(26)), `${'あ'.repeat(25)}\r\n あ`);
});

test('文字の逃がし方: \\ ; , 改行。使えない制御文字は除く', () => {
    assert.equal(ics.escapeText('a\\b;c,d\ne\r\nf\u0007g\th'), 'a\\\\b\\;c\\,d\\ne\\nfg\th');
    const lines = unfold(ics.buildIcs([task({ title: '架空の会議, 第2回; 準備', lane: 'A,B' })], { now: NOW }).text);
    assert.ok(lines.includes('SUMMARY:架空の会議\\, 第2回\\; 準備'));
    assert.ok(lines.includes('CATEGORIES:A\\,B'));
    const description = lines.find(l => l.startsWith('DESCRIPTION:'));
    assert.equal(description, 'DESCRIPTION:状態: 本人の番\\n次に本人がすること: 架空の下書きを読む\\nもとの行: 架空の資料作り (10/15まで)');
});

test('UID は固定の ID: 同じタスクの期限・題名・状態を変えても UID は変わらない', () => {
    const before = task();
    const changed = { ...core.transition(before, 'in_progress', NOW), deadline: '2026-11-30', title: '架空の資料作り（改訂）' };
    const a = props(ics.buildIcs([before], { now: NOW }).text);
    const b = props(ics.buildIcs([changed], { now: NOW }).text);
    const value = (list, name) => list.find(p => p.name === name).rest;
    assert.equal(value(a, 'UID'), value(b, 'UID'));
    assert.equal(value(a, 'UID'), `:${ID1}`);
    assert.notEqual(value(a, 'DTSTART'), value(b, 'DTSTART'));
    assert.equal(value(b, 'SEQUENCE'), ':3', '直した回数（SEQUENCE）は増える');
});

test('入れないもの: 期限の無いタスク・完了（includeDone で入れられる）・ID が UUID でないもの', () => {
    const tasks = [task(), task({ id: ID2, deadline: null }), task({ id: '33333333-3333-4333-8333-333333333333', status: 'done' }),
        task({ id: 'not-a-uuid' })];
    const result = ics.buildIcs(tasks, { now: NOW });
    assert.equal(result.count, 1);
    assert.deepEqual(result.skipped, { no_deadline: 1, done: 1 });
    assert.equal(ics.buildIcs(tasks, { now: NOW, includeDone: true }).count, 2);
});

test('予定が1つも無ければ、ファイルの中身を作らない（空の VCALENDAR は RFC に合わない）', () => {
    assert.deepEqual(ics.buildIcs([task({ deadline: null })], { now: NOW }), { text: '', count: 0, skipped: { no_deadline: 1, done: 0 } });
    assert.equal(ics.buildIcs([], { now: NOW }).count, 0);
});

test('並び: 期限の近い順', () => {
    const lines = unfold(ics.buildIcs([task({ id: ID1, deadline: '2026-12-01' }), task({ id: ID2, deadline: '2026-10-05' })], { now: NOW }).text);
    assert.deepEqual(lines.filter(l => l.startsWith('UID:')), [`UID:${ID2}`, `UID:${ID1}`]);
});

test('formatUtc・formatDate', () => {
    assert.equal(ics.formatUtc('2026-10-01T09:00:00+09:00'), '20261001T000000Z');
    assert.equal(ics.formatDate('2026-10-01'), '20261001');
    assert.equal(ics.formatDate('2026-10-31', 1), '20261101');
    assert.throws(() => ics.formatDate('2026-02-30'), /日付が読めません/);
    assert.throws(() => ics.formatUtc('きのう'), /時刻が読めません/);
});
