// ============================================================
// frontend/ics.js を node で動かし、.ics の文字を返す（tests/test_b30_ics.py が使う）。
// 標準入力: { "tasks": [...], "now": "ISO 8601", "includeDone": false } の JSON
// 標準出力: { "text": "...", "count": 1, "skipped": {...} } の JSON
// 外部には送信しない。
// ============================================================
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ics = require(process.env.TSA_ICS_JS || '../../frontend/ics.js');
const input = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(ics.buildIcs(input.tasks, { now: input.now, includeDone: Boolean(input.includeDone) })));
