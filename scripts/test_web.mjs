#!/usr/bin/env node
// Repeatable execution tests for the real wasm-gc bridge. These use the same
// web/bridge.js + web/analysis.js modules as the browser worker, with Node's
// File implementation standing in for the browser File handle.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { analyzeFile } from '../web/analysis.js';
import { instantiateMoonlog } from '../web/bridge.js';

const execFileAsync = promisify(execFile);
const root = fileURLToPath(new URL('..', import.meta.url));
const wasmPath = resolve(root, process.argv[2] || 'web/generated/moonlog_web.wasm');
const cliPath = resolve(root, process.argv[3] || 'bin/moonlog');
const fixturePath = resolve(root, process.argv[4] || 'fixtures/incident.log');
const encoder = new TextEncoder();

const wasmBytes = await readFile(wasmPath);

function defaultOptions(overrides = {}) {
  return {
    bucketMinutes: 5,
    baselineBuckets: 6,
    multiplier: 3,
    minErrors: 3,
    context: 10,
    maxSamples: 20,
    level: '',
    keyword: '',
    from: '',
    to: '',
    ...overrides,
  };
}

async function newBridge() {
  return instantiateMoonlog(wasmBytes);
}

async function run(bridge, bytes, name, overrides = {}, extra = {}) {
  const file = new File([bytes], name);
  const progress = [];
  const result = await analyzeFile({
    bridge,
    file,
    options: defaultOptions(overrides),
    signal: extra.signal,
    onProgress: (item) => {
      progress.push(item);
      if (extra.onProgress) {
        extra.onProgress(item);
      }
    },
  });
  return {
    chunks: result.chunks,
    json: result.json,
    report: JSON.parse(result.json),
    progress,
  };
}

function textBytes(text) {
  return encoder.encode(text);
}

function comparable(document) {
  const copy = structuredClone(document);
  delete copy.source;
  delete copy.sources;
  for (const window of copy.context_windows || []) {
    delete window.source;
  }
  return copy;
}

function contextByNumber(document) {
  const byNumber = new Map();
  for (const window of document.context_windows || []) {
    for (const line of window.lines) {
      byNumber.set(line.number, line.text);
    }
  }
  return byNumber;
}

function makeSyntheticLines(count) {
  const rows = [];
  for (let index = 0; index < count; index += 1) {
    const minute = index % 1440;
    const hour = String(Math.floor(minute / 60)).padStart(2, '0');
    const mm = String(minute % 60).padStart(2, '0');
    rows.push(`2026-10-28 ${hour}:${mm}:00 [INFO] request id=${index}\n`);
  }
  return rows.join('');
}

let passed = 0;
let failed = 0;

async function test(name, body) {
  try {
    await body();
    passed += 1;
    console.log(`ok - ${name}`);
  } catch (error) {
    failed += 1;
    console.error(`not ok - ${name}`);
    console.error(error && error.stack ? error.stack : error);
  }
}

console.log(`WASM: ${wasmPath}`);
console.log(`CLI:  ${cliPath}`);
console.log(`Node: ${process.version}`);

await test('WASM and CLI agree on counts, buckets, spikes, signatures, and context', async () => {
  const bridge = await newBridge();
  const fixtureBytes = await readFile(fixturePath);
  const wasm = await run(bridge, fixtureBytes, basename(fixturePath));
  const tempDir = await mkdtemp(join(tmpdir(), 'moonlog-web-'));
  try {
    const cliReportPath = join(tempDir, 'cli.json');
    await execFileAsync(
      cliPath,
      ['analyze', fixturePath, '--report', cliReportPath, '--format', 'json'],
      { cwd: root },
    );
    const cli = JSON.parse(await readFile(cliReportPath, 'utf8'));

    assert.equal(wasm.report.summary.total, cli.summary.total);
    assert.equal(wasm.report.summary.matched, cli.summary.matched);
    assert.equal(wasm.report.summary.untimed, cli.summary.untimed);
    assert.equal(wasm.report.summary.errors, cli.summary.errors);
    assert.equal(wasm.report.summary.spike_count, cli.summary.spike_count);
    assert.deepEqual(wasm.report.buckets, cli.buckets);
    assert.deepEqual(wasm.report.observation_buckets, cli.observation_buckets);
    assert.deepEqual(
      wasm.report.spikes.map((spike) => ({
        start: spike.start,
        end_exclusive: spike.end_exclusive,
        errors: spike.errors,
        peak_errors: spike.peak_errors,
        baseline: spike.baseline,
        signatures: spike.signatures,
      })),
      cli.spikes.map((spike) => ({
        start: spike.start,
        end_exclusive: spike.end_exclusive,
        errors: spike.errors,
        peak_errors: spike.peak_errors,
        baseline: spike.baseline,
        signatures: spike.signatures,
      })),
    );
    assert.deepEqual(wasm.report.signatures, cli.signatures);
    assert.deepEqual(
      wasm.report.context_windows.map((window) => window.lines),
      cli.context_windows.map((window) => window.lines),
    );

    // The only allowed difference is the source label. The browser only has
    // File.name; the CLI records the path argument it was given.
    assert.equal(wasm.report.source, basename(fixturePath));
    assert.equal(cli.source, fixturePath);
    assert.equal(wasm.report.sources[0], wasm.report.source);
    assert.equal(cli.sources[0], cli.source);
    for (const window of wasm.report.context_windows) {
      assert.equal(window.source, wasm.report.source);
    }
    for (const window of cli.context_windows) {
      assert.equal(window.source, cli.source);
    }
    assert.deepEqual(comparable(wasm.report), comparable(cli));
    console.log(
      `     source label difference is expected: WASM "${wasm.report.source}" vs CLI "${cli.source}"`,
    );
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
});

await test('empty file produces a valid report and zero-safe progress', async () => {
  const bridge = await newBridge();
  const result = await run(bridge, new Uint8Array(0), 'empty.log');
  assert.equal(result.report.summary.total, 0);
  assert.equal(result.report.summary.errors, 0);
  assert.equal(result.report.summary.spike_count, 0);
  assert.equal(result.report.summary.log_error_ratio.fraction, null);
  assert.equal(result.report.summary.log_error_ratio.total, '0');
  assert.equal(result.report.summary.log_error_ratio.errors, '0');
  assert.equal(result.report.spikes.length, 0);
  assert.equal(result.report.context_windows.length, 0);
  assert.ok(result.json.length > 0);
  assert.ok(result.progress.length >= 2);
  for (const progress of result.progress) {
    assert.equal(progress.total, 0);
    assert.equal(progress.bytes, 0);
    assert.ok(Number.isFinite(progress.bytes));
    assert.ok(Number.isFinite(progress.total));
  }
});

await test('no spike is reported as zero spikes without claiming health', async () => {
  const bridge = await newBridge();
  const text = [
    '2026-10-28 08:00:00 [INFO] ok',
    '2026-10-28 08:01:00 [ERROR] boom',
    '2026-10-28 08:02:00 [INFO] ok',
    '',
  ].join('\n');
  const result = await run(bridge, textBytes(text), 'calm.log');
  assert.equal(result.report.summary.total, 3);
  assert.equal(result.report.summary.errors, 1);
  assert.equal(result.report.summary.spike_count, 0);
  assert.equal(result.report.spikes.length, 0);
  assert.equal(result.report.context_windows.length, 0);
  assert.equal(result.report.signatures.length, 1);
  assert.equal(result.report.signatures[0].text, 'ERROR: boom');
  assert.equal(result.report.signatures[0].count, 1);
  const ratio = result.report.summary.log_error_ratio;
  assert.equal(Number(ratio.total), 3);
  assert.equal(Number(ratio.errors), 1);
  assert.ok(Math.abs(ratio.fraction - 1 / 3) < 1e-12);
});

await test('UTF-8 Chinese split across the 64 KiB chunk boundary decodes intact', async () => {
  const bridge = await newBridge();
  const line1 = `${'a'.repeat(65000)}\n`;
  const line2 = '2026-10-28 08:04:00 [INFO] baseline\n';
  const prefix3 = '2026-10-28 08:05:00 [ERROR] ';
  const beforeChinese = encoder.encode(line1 + line2 + prefix3).length;
  const pad = 65535 - beforeChinese;
  assert.ok(pad > 0, 'padding must fit before the Chinese text');
  const line3 = `${prefix3}${'x'.repeat(pad)}中文错误\n`;
  const bytes = textBytes(line1 + line2 + line3);
  const chineseOffset = encoder.encode(line1 + line2 + prefix3 + 'x'.repeat(pad)).length;
  assert.equal(chineseOffset, 65535);
  assert.ok(chineseOffset < 65536 && chineseOffset + 3 > 65536);
  assert.ok(bytes.length > 65536);

  const result = await run(bridge, bytes, 'chinese-boundary.log', {
    bucketMinutes: 1,
    baselineBuckets: 1,
    multiplier: 2,
    minErrors: 1,
    context: 1,
    maxSamples: 10,
  });
  assert.equal(result.report.summary.total, 3);
  assert.equal(result.report.summary.untimed, 1);
  assert.equal(result.report.level_counts.INFO, 1);
  assert.equal(result.report.level_counts.ERROR, 1);
  assert.equal(result.report.summary.spike_count, 1);
  const lineThree = result.report.context_windows
    .flatMap((window) => window.lines)
    .find((line) => line.number === 3);
  assert.ok(lineThree, 'context should contain the error line');
  assert.ok(lineThree.text.includes('中文错误'));
  assert.equal(lineThree.text, line3.trimEnd());
  assert.ok(result.report.signatures[0].text.includes('中文错误'));
});

await test('BOM, CRLF, and a final line without newline stay intact', async () => {
  const bridge = await newBridge();
  const rows = [
    '\uFEFF2026-10-28 08:00:00 [INFO] 起始',
    '2026-10-28 08:01:00 [ERROR] 错误一',
    '2026-10-28 08:02:00 [ERROR] 错误二',
    '2026-10-28 08:03:00 [INFO] 末行无换行',
  ];
  const text = rows.join('\r\n');
  const result = await run(bridge, textBytes(text), 'bom-crlf.log', {
    bucketMinutes: 1,
    baselineBuckets: 1,
    multiplier: 2,
    minErrors: 1,
    context: 2,
    maxSamples: 10,
  });
  assert.equal(result.report.summary.total, 4);
  assert.equal(result.report.summary.untimed, 0);
  assert.equal(result.report.level_counts.INFO, 2);
  assert.equal(result.report.level_counts.ERROR, 2);
  assert.equal(result.report.signatures.some((item) => item.text === 'ERROR: 错误一'), true);
  assert.equal(result.report.signatures.some((item) => item.text === 'ERROR: 错误二'), true);

  const expected = new Map(rows.map((row, index) => [index + 1, row.replace(/^\uFEFF/, '')]));
  const context = contextByNumber(result.report);
  assert.ok(context.has(4), 'the line without a final newline should be in context');
  for (const [number, line] of context) {
    assert.equal(line, expected.get(number), `line ${number} should be the raw line without CR/BOM`);
    assert.equal(line.includes('\r'), false);
    assert.equal(line.includes('\uFEFF'), false);
  }
});

await test('invalid UTF-8 stops the run and a later analysis recovers', async () => {
  const bridge = await newBridge();
  const good = textBytes('2026-10-28 08:00:00 [INFO] ok\n');
  const bad = new Uint8Array(good.length + 2);
  bad.set(good, 0);
  bad[good.length] = 0xff;
  bad[good.length + 1] = 0x0a;
  await assert.rejects(run(bridge, bad, 'bad-utf8.log'), /invalid UTF-8/);
  const recovered = await run(bridge, good, 'recovered.log');
  assert.equal(recovered.report.summary.total, 1);
  assert.equal(recovered.report.level_counts.INFO, 1);
});

await test('an overlong line is rejected and the bridge can be reused', async () => {
  const bridge = await newBridge();
  const overlong = new Uint8Array(70001);
  overlong.fill(0x61, 0, 70000);
  overlong[70000] = 0x0a;
  await assert.rejects(run(bridge, overlong, 'long-line.log'), /line exceeds 64 KiB/);
  const recovered = await run(
    bridge,
    textBytes('2026-10-28 08:00:00 [INFO] ok\n'),
    'recovered.log',
  );
  assert.equal(recovered.report.summary.total, 1);
});

await test('parameter errors come from the core and are not clamped', async () => {
  const bridge = await newBridge();
  const bytes = textBytes('2026-10-28 08:00:00 [INFO] ok\n');
  const cases = [
    [{ bucketMinutes: 0 }, /bucket minutes must be 1\.\.1440/],
    [{ bucketMinutes: 1441 }, /bucket minutes must be 1\.\.1440/],
    [{ baselineBuckets: 0 }, /baseline buckets must be 1\.\.1000/],
    [{ multiplier: 1 }, /multiplier must be 2\.\.1000/],
    [{ minErrors: 0 }, /minimum errors must be positive/],
    [{ context: -1 }, /context must be 0\.\.100/],
    [{ context: 101 }, /context must be 0\.\.100/],
    [{ maxSamples: 101 }, /max samples must be 0\.\.100/],
    [{ level: 'TRACE' }, /unknown log level/],
    [{ from: '2026-10-28 08:00' }, /invalid from timestamp/],
    [{ to: 'not-a-time' }, /invalid to timestamp/],
    [
      { from: '2026-10-28 09:00:00', to: '2026-10-28 08:00:00' },
      /from must not be after to/,
    ],
  ];
  for (const [overrides, pattern] of cases) {
    await assert.rejects(run(bridge, bytes, 'params.log', overrides), pattern);
  }
  await assert.rejects(
    run(bridge, bytes, 'params.log', { bucketMinutes: 2.5 }),
    /bucketMinutes 必须是 32 位整数/,
  );
  const recovered = await run(bridge, bytes, 'params.log');
  assert.equal(recovered.report.summary.total, 1);
});

await test('oversized and invalid base64 chunks are rejected before the session', async () => {
  const bridge = await newBridge();
  bridge.start({ ...defaultOptions(), source: 'guard.log' });
  assert.throws(() => bridge.feedBase64('A'.repeat(87385)), /chunk exceeds 64 KiB/);
  await assert.rejects(
    (async () => {
      bridge.start({ ...defaultOptions(), source: 'guard.log' });
      bridge.feedBase64('not base64!');
    })(),
    /invalid base64 chunk/,
  );
  const recovered = await run(
    bridge,
    textBytes('2026-10-28 08:00:00 [INFO] ok\n'),
    'guard.log',
  );
  assert.equal(recovered.report.summary.total, 1);
});

await test('cancel stops the scan and the same bridge can analyze again', async () => {
  const bridge = await newBridge();
  const bytes = textBytes(makeSyntheticLines(20000));
  const controller = new AbortController();
  let chunksBeforeCancel = 0;
  await assert.rejects(
    run(bridge, bytes, 'cancel.log', {}, {
      signal: controller.signal,
      onProgress: (progress) => {
        if (progress.bytes >= 65536) {
          chunksBeforeCancel += 1;
          if (chunksBeforeCancel === 1) {
            controller.abort();
          }
        }
      },
    }),
    (error) => error && error.name === 'CancelledError',
  );
  assert.equal(bridge.phase(), -1);
  const recovered = await run(bridge, bytes, 'cancel.log');
  assert.equal(recovered.report.summary.total, 20000);
  assert.equal(recovered.report.summary.errors, 0);
  assert.equal(recovered.report.summary.spike_count, 0);
  assert.ok(recovered.chunks > 1);
});

await test('repeated analysis returns byte-identical JSON', async () => {
  const bridge = await newBridge();
  const fixtureBytes = await readFile(fixturePath);
  const first = await run(bridge, fixtureBytes, basename(fixturePath));
  const second = await run(bridge, fixtureBytes, basename(fixturePath));
  assert.equal(first.json, second.json);
  assert.equal(first.chunks, second.chunks);
});

await test('bundled demo covers three incidents, backgrounds and raw stack context', async () => {
  const bytes = await readFile(resolve(root, 'web/sample.log'));
  const { report } = await run(await newBridge(), bytes, 'sample.log', { maxSamples: 100 });
  assert.equal(report.summary.total, 335);
  assert.equal(report.summary.errors, 53);
  assert.equal(report.summary.untimed, 2);
  assert.equal(report.summary.spike_count, 3);
  assert.deepEqual(report.spikes.map(s => s.errors), [16, 15, 15]);
  assert.equal(report.summary.omitted_targets, 0);
  for (const level of ['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL', 'OTHER']) {
    assert.ok(Number(report.level_counts[level]) > 0, level);
  }
  const contexts = JSON.stringify(report.context_windows);
  for (const text of ['database query timeout', 'TLS certificate expired', 'worker out of memory', 'processOrder']) {
    assert.ok(contexts.includes(text), text);
  }
});

await test('page ids are unique and every getElementById target exists', async () => {
  const html = await readFile(resolve(root, 'web/index.html'), 'utf8');
  const app = await readFile(resolve(root, 'web/app.js'), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
  assert.deepEqual(duplicates, []);
  const references = [...app.matchAll(/getElementById\('([^']+)'\)/g)].map(
    (match) => match[1],
  );
  assert.ok(references.length > 0);
  for (const reference of references) {
    assert.ok(ids.includes(reference), `missing element id: ${reference}`);
  }
  assert.equal(app.includes('innerHTML'), false);
});

console.log('');
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exitCode = 1;
}
