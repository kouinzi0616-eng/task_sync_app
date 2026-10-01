// ============================================================
// frontend/task_core.js（台帳の純粋関数）の検算。node:test だけを使う（依存を増やさない）。
// 使い方: node --test tests/frontend/task_core.test.mjs
//   TSA_TASK_CORE=別のファイル を付けると、そのファイルを確かめる（検算が働くかの確認用）
// データはすべて架空。外部には送信しない。
// ============================================================
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { webcrypto } from 'node:crypto';

const require = createRequire(import.meta.url);
const core = require(process.env.TSA_TASK_CORE || '../../frontend/task_core.js');

// 基準の「今」: 2026-10-01（木）10:00 日本時間
const NOW = '2026-10-01T01:00:00.000Z';
const HOUR = 60 * 60 * 1000;
const hoursBefore = h => new Date(Date.parse(NOW) - h * HOUR).toISOString();
const ID1 = '11111111-1111-4111-8111-111111111111';
const ID2 = '22222222-2222-4222-8222-222222222222';
const ID3 = '33333333-3333-4333-a333-333333333333';

function sample(overrides = {}) {
    return {
        id: ID1, title: '架空の資料作り', lane: '仕事', status: 'in_progress', next_action: '',
        deadline: '2027-03-15', due_time: null, category: '個人', raw_text: '架空の資料作り (3/15まで)',
        created_at: hoursBefore(100), updated_at: hoursBefore(10), revision: 0, ...overrides
    };
}

// ------------------------------------------------------------
// ID
// ------------------------------------------------------------
test('newUuid: randomUUID があればそれを使う', () => {
    assert.equal(core.newUuid({ randomUUID: () => ID2 }), ID2);
});

test('newUuid: randomUUID が無くても getRandomValues で UUID v4 を作る（1000件重ならない）', () => {
    const fallback = { getRandomValues: array => webcrypto.getRandomValues(array) };
    const ids = new Set();
    for (let i = 0; i < 1000; i++) {
        const id = core.newUuid(fallback);
        assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
        ids.add(id);
    }
    assert.equal(ids.size, 1000);
});

test('newUuid: 乱数が無ければ ID を振らない', () => {
    assert.throws(() => core.newUuid(undefined), /乱数/);
});

// ------------------------------------------------------------
// タスクを作る
// ------------------------------------------------------------
test('createTask: API の1行から作る（ID は渡したもの・状態は進行中）', () => {
    const task = core.createTask({
        title: '架空の会議の準備', deadline: '2026-10-02T00:00:00+09:00', due_time: '15:00',
        category: '個人', raw_text: '架空の会議の準備 (明日15時)'
    }, { id: ID1, now: NOW, lane: '学び' });
    assert.deepEqual(task, {
        id: ID1, title: '架空の会議の準備', lane: '学び', status: 'in_progress', next_action: '',
        deadline: '2026-10-02', due_time: '15:00', category: '個人', raw_text: '架空の会議の準備 (明日15時)',
        created_at: NOW, updated_at: NOW, revision: 0
    });
});

test('createTask: 期限なし・おかしな値・空の件名・UUID でない ID', () => {
    const task = core.createTask({ title: ' 架空のメモ ', deadline: null, due_time: '25:00' }, { id: ID1, now: NOW, lane: '' });
    assert.equal(task.title, '架空のメモ');
    assert.equal(task.deadline, null);
    assert.equal(task.due_time, null);
    assert.equal(task.lane, core.DEFAULT_LANES[0]);
    assert.equal(core.createTask({ title: 'x', deadline: '2026-02-30T00:00:00+09:00' }, { id: ID1, now: NOW }).deadline, null);
    assert.throws(() => core.createTask({ title: '  ' }, { id: ID1, now: NOW }), /件名/);
    assert.throws(() => core.createTask({ title: 'x' }, { id: 'abc', now: NOW }), /UUID/);
});

// ------------------------------------------------------------
// 状態の移り変わり
// ------------------------------------------------------------
test('transition: 進行中 → 本人の番 で状態・更新時刻・直した回数が変わり、ID は変わらない', () => {
    const before = sample();
    const after = core.transition(before, 'my_turn', NOW);
    assert.equal(after.status, 'my_turn');
    assert.equal(after.updated_at, NOW);
    assert.equal(after.revision, 1);
    assert.equal(after.id, ID1);
    assert.equal(before.status, 'in_progress', 'もとのタスクは書きかえない');
    assert.notEqual(after, before);
});

test('transition: 4つの状態のどれからどれへも変えられる（16通り）', () => {
    for (const from of core.STATUSES) {
        for (const to of core.STATUSES) {
            const before = sample({ status: from });
            const after = core.transition(before, to, NOW);
            assert.equal(after.status, to, `${from} → ${to}`);
            if (from === to) {
                assert.equal(after, before, `${from} → ${to} は何もしない`);
            } else {
                assert.equal(after.updated_at, NOW, `${from} → ${to}`);
            }
        }
    }
});

test('transition: 知らない状態は断る', () => {
    assert.throws(() => core.transition(sample(), 'waiting', NOW), /知らない状態/);
    assert.throws(() => core.transition(sample(), '本人の番', NOW), /知らない状態/);
});

test('applyChange: 次に本人がすること・レーンを直す。同じ値なら更新しない', () => {
    const before = sample({ next_action: '下書きを読む' });
    assert.equal(core.applyChange(before, { next_action: ' 下書きを読む ' }, NOW), before);
    const after = core.applyChange(before, { next_action: '架空の先方に電話する', lane: '暮らし' }, NOW);
    assert.equal(after.next_action, '架空の先方に電話する');
    assert.equal(after.lane, '暮らし');
    assert.equal(after.revision, 1);
    assert.throws(() => core.applyChange(before, { lane: '  ' }, NOW), /レーン名が空/);
});

// ------------------------------------------------------------
// 2日以上動きなし
// ------------------------------------------------------------
test('isStale: 48時間ちょうどで印を付け、その手前では付けない', () => {
    assert.equal(core.isStale(sample({ status: 'my_turn', updated_at: hoursBefore(48) }), NOW), true);
    assert.equal(core.isStale(sample({ status: 'my_turn', updated_at: hoursBefore(47.99) }), NOW), false);
    assert.equal(core.isStale(sample({ status: 'in_progress', updated_at: hoursBefore(72) }), NOW), true);
});

test('isStale: 完了・保留・時刻の読めないものには付けない', () => {
    assert.equal(core.isStale(sample({ status: 'done', updated_at: hoursBefore(500) }), NOW), false);
    assert.equal(core.isStale(sample({ status: 'on_hold', updated_at: hoursBefore(500) }), NOW), false);
    assert.equal(core.isStale(sample({ status: 'my_turn', updated_at: 'きのう' }), NOW), false);
});

test('isStale: 状態を変えると印が外れる', () => {
    const stale = sample({ status: 'in_progress', updated_at: hoursBefore(60) });
    assert.equal(core.isStale(stale, NOW), true);
    assert.equal(core.isStale(core.transition(stale, 'my_turn', NOW), NOW), false);
});

test('myTurnList: 本人の番だけ。動きなし → 期限の近い順 → 期限なし', () => {
    const tasks = [
        sample({ id: ID1, title: 'A', status: 'my_turn', deadline: '2026-12-01', updated_at: hoursBefore(1) }),
        sample({ id: ID2, title: 'B', status: 'my_turn', deadline: null, updated_at: hoursBefore(1) }),
        sample({ id: ID3, title: 'C', status: 'my_turn', deadline: '2027-01-01', updated_at: hoursBefore(49) }),
        sample({ title: 'D', status: 'in_progress', deadline: '2026-10-02' }),
        sample({ title: 'E', status: 'done' }),
        sample({ title: 'F', status: 'my_turn', deadline: '2026-10-05', updated_at: hoursBefore(2) })
    ];
    assert.deepEqual(core.myTurnList(tasks, NOW).map(t => t.title), ['C', 'F', 'A', 'B']);
});

test('sortTasks: 本人の番 → 進行中 → 保留 → 完了', () => {
    const tasks = ['done', 'on_hold', 'in_progress', 'my_turn'].map((status, i) => sample({ status, title: String(i) }));
    assert.deepEqual(core.sortTasks(tasks).map(t => t.status), ['my_turn', 'in_progress', 'on_hold', 'done']);
});

// ------------------------------------------------------------
// 台帳の形（Markdown の表・CSV）
// ------------------------------------------------------------
test('toLedgerRows: 件名/レーン/状態/本人の番/更新日（更新日は日本時間の日付）', () => {
    const rows = core.toLedgerRows([sample({ status: 'my_turn', next_action: '架空の書類に印を押す', updated_at: '2026-09-30T16:00:00Z' })]);
    assert.deepEqual(rows, [{ 件名: '架空の資料作り', レーン: '仕事', 状態: '本人の番', 本人の番: '架空の書類に印を押す', 更新日: '2026-10-01' }]);
    assert.deepEqual(core.LEDGER_COLUMNS, ['件名', 'レーン', '状態', '本人の番', '更新日']);
});

test('toMarkdownTable: 見出しと区切り。| と改行は表を壊さない形にする', () => {
    const md = core.toMarkdownTable([{ 件名: 'A|B', レーン: '仕事', 状態: '進行中', 本人の番: '1行目\n2行目', 更新日: '2026-10-01' }]);
    assert.equal(md, [
        '| 件名 | レーン | 状態 | 本人の番 | 更新日 |',
        '| --- | --- | --- | --- | --- |',
        '| A\\|B | 仕事 | 進行中 | 1行目 2行目 | 2026-10-01 |',
        ''
    ].join('\n'));
});

test('toCsv: , " 改行を含む欄は囲み、行は CRLF で区切る', () => {
    const csv = core.toCsv([{ 件名: '架空の資料, 第2版', レーン: '仕事', 状態: '本人の番', 本人の番: '「"至急"」と伝える\n2行目', 更新日: '2026-10-01' }]);
    assert.equal(csv, '件名,レーン,状態,本人の番,更新日\r\n"架空の資料, 第2版",仕事,本人の番,"「""至急""」と伝える\n2行目",2026-10-01\r\n');
});

test('toCsv → parseCsv で元に戻る', () => {
    const rows = core.toLedgerRows([
        sample({ title: 'a,b"c', next_action: 'x\r\ny' }),
        sample({ title: '架空の片付け', status: 'on_hold' })
    ]);
    const parsed = core.parseCsv(core.toCsv(rows));
    assert.deepEqual(parsed[0], core.LEDGER_COLUMNS);
    assert.deepEqual(parsed.slice(1), rows.map(r => core.LEDGER_COLUMNS.map(c => r[c])));
});

test('parseCsv: BOM・LF だけの改行・空の行・閉じていない "', () => {
    assert.deepEqual(core.parseCsv('﻿a,b\n\n"c\nd",""\n'), [['a', 'b'], ['c\nd', '']]);
    assert.deepEqual(core.parseCsv('a,b'), [['a', 'b']]);
    assert.deepEqual(core.parseCsv('a,,\r\n'), [['a', '', '']]);
    assert.throws(() => core.parseCsv('a,"b\n'), /閉じていません/);
});

// ------------------------------------------------------------
// Notion から書き出した CSV
// ------------------------------------------------------------
const NOTION_CSV = [
    '﻿件名,状態,本人の番,レーン,更新日,作った人',
    '架空の申請書を出す,本人の番,印鑑を押して出す,仕事,2026/09/28 20:02,架空の人',
    '架空の本を読む,進行中,,学び,2026/09/30,架空の人',
    '"架空の見積もり, 確認",本人の番,なし（先方の返事待ち）,仕事,"September 30, 2026 8:02 PM",架空の人',
    '架空の掃除,本人の番,,暮らし,不明,架空の人',
    '架空の古い用事,完了,済み,仕事,2026年9月1日,架空の人'
].join('\r\n');

test('readNotionCsv: 本人の番の行だけを返し、全体の行数も返す', () => {
    const result = core.readNotionCsv(NOTION_CSV, NOW);
    assert.equal(result.total, 5);
    assert.deepEqual(result.items.map(i => i.title), ['架空の申請書を出す', '架空の見積もり, 確認', '架空の掃除']);
});

test('readNotionCsv: 更新日から2日以上（日本時間の日付で数える）なら印を付ける', () => {
    const [first, second, third] = core.readNotionCsv(NOTION_CSV, NOW).items;
    assert.equal(first.updated_date, '2026-09-28');
    assert.equal(first.stale, true);
    assert.equal(second.updated_date, '2026-09-30');
    assert.equal(second.stale, false);
    assert.equal(third.updated_date, null, '読めない日付');
    assert.equal(third.stale, false);
});

test('readNotionCsv: 本人の番の欄が空・「なし」で始まる行に印を付ける', () => {
    const items = core.readNotionCsv(NOTION_CSV, NOW).items;
    assert.deepEqual(items.map(i => i.turn_missing), [false, true, true]);
    assert.equal(items[0].next_action, '印鑑を押して出す');
    assert.equal(items[0].lane, '仕事');
});

test('readNotionCsv: 件名・状態の列が無ければ断る。列の順番は問わない', () => {
    assert.throws(() => core.readNotionCsv('Name,Status\nx,本人の番\n', NOW), /「件名」「状態」/);
    assert.throws(() => core.readNotionCsv('', NOW), /空/);
    const result = core.readNotionCsv('状態,件名\n本人の番,架空のA\n', NOW);
    assert.deepEqual(result.items.map(i => [i.title, i.lane, i.turn_missing]), [['架空のA', '', true]]);
});

test('parseLooseDate: 台帳の更新日の形', () => {
    const cases = {
        '2026-10-01': '2026-10-01',
        '2026-10-01T09:15:00+09:00': '2026-10-01',
        '2026/9/30 20:02': '2026-09-30',
        '2026年9月30日 20:02': '2026-09-30',
        'September 30, 2026 8:02 PM': '2026-09-30',
        'Sep 30, 2026': '2026-09-30',
        '@October 1, 2026': '2026-10-01',
        '2026/2/30': null,
        '9/30': null,
        '': null
    };
    for (const [input, expected] of Object.entries(cases)) assert.equal(core.parseLooseDate(input), expected, input);
});

// ------------------------------------------------------------
// レーン名
// ------------------------------------------------------------
test('normalizeLanes: 改行・読点・カンマで分け、空白と重なりを除く。空なら見本の名前', () => {
    assert.deepEqual(core.normalizeLanes(' 架空A \n架空B、架空A,\n\n架空C'), ['架空A', '架空B', '架空C']);
    assert.deepEqual(core.normalizeLanes(''), ['仕事', '学び', '暮らし']);
    assert.deepEqual(core.normalizeLanes([]), core.DEFAULT_LANES);
    assert.equal(core.normalizeLanes(Array.from({ length: 30 }, (_, i) => `L${i}`)).length, 20);
    assert.equal(core.normalizeLanes(['あ'.repeat(40)])[0].length, 30);
});

// ------------------------------------------------------------
// JSON の控え
// ------------------------------------------------------------
test('makeBackup → readBackup で同じタスクとレーン名に戻る', () => {
    const tasks = [sample(), sample({ id: ID2, status: 'my_turn', next_action: '架空の電話', deadline: null })];
    const backup = core.makeBackup(tasks, { lanes: ['架空A', '架空B'] }, NOW);
    assert.equal(backup.format, 'task-sync-backup');
    assert.equal(backup.version, 1);
    assert.equal(backup.exported_at, NOW);
    const read = core.readBackup(JSON.stringify(backup));
    assert.deepEqual(read.tasks, tasks);
    assert.deepEqual(read.lanes, ['架空A', '架空B']);
    assert.equal(read.invalid, 0);
});

test('readBackup: 形の違う JSON は断る', () => {
    assert.throws(() => core.readBackup('{'), /JSON として読めません/);
    assert.throws(() => core.readBackup('{"tasks": []}'), /このアプリで書き出した/);
    assert.throws(() => core.readBackup('{"format": "task-sync-backup", "version": 9, "tasks": []}'), /知らない版/);
    const many = { format: 'task-sync-backup', version: 1, tasks: Array.from({ length: 5001 }, () => ({})) };
    assert.throws(() => core.readBackup(JSON.stringify(many)), /多すぎます/);
});

test('readBackup: おかしな行は数えて飛ばし、知らない項目は捨てる', () => {
    const good = { ...sample(), extra: '<img src=x onerror=alert(1)>' };
    const data = {
        format: 'task-sync-backup', version: 1,
        tasks: [good, { ...sample(), id: 'not-a-uuid' }, { ...sample(), status: 'waiting' },
            { ...sample(), deadline: '2026-13-01' }, { ...sample(), title: '' }, null]
    };
    const read = core.readBackup(JSON.stringify(data));
    assert.equal(read.tasks.length, 1);
    assert.equal(read.invalid, 5);
    assert.equal('extra' in read.tasks[0], false);
    assert.equal(read.lanes, null);
});

test('mergeTasks: 同じ ID は更新の新しい方を残す', () => {
    const existing = [sample({ id: ID1, title: '今の', updated_at: hoursBefore(5) }), sample({ id: ID2, title: '今の2', updated_at: hoursBefore(5) })];
    const incoming = [
        sample({ id: ID1, title: '新しい', updated_at: hoursBefore(1) }),
        sample({ id: ID2, title: '古い', updated_at: hoursBefore(9) }),
        sample({ id: ID3, title: '足す', updated_at: hoursBefore(9) })
    ];
    const merged = core.mergeTasks(existing, incoming);
    assert.deepEqual([merged.added, merged.updated, merged.unchanged], [1, 1, 1]);
    assert.deepEqual(merged.tasks.map(t => [t.id, t.title]), [[ID1, '新しい'], [ID2, '今の2'], [ID3, '足す']]);
    assert.deepEqual(merged.changed.map(t => t.id), [ID1, ID3]);
});
