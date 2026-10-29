#!/usr/bin/env node
// Streaming throughput check for the same analysis.js path used by the worker.
// The File-like object reads each 64 KiB slice from an open file descriptor, so
// the whole input is never held in a JS buffer by the analysis code.
import assert from 'node:assert/strict';
import { open, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { fileURLToPath } from 'node:url';
import { analyzeFile } from '../web/analysis.js';
import { instantiateMoonlog } from '../web/bridge.js';

const root = fileURLToPath(new URL('..', import.meta.url));
const wasmPath = resolve(root, process.argv[2] || 'web/generated/moonlog_web.wasm');
const targetMiB = Number(process.argv[3] || 64);
const tempPath = process.argv[4] || join(tmpdir(), `moonlog-bench-${process.pid}.log`);

class DiskFile {
  constructor(path, size, name, handle) {
    this.path = path;
    this.size = size;
    this.name = name;
    this.handle = handle;
  }

  slice(start, end) {
    const handle = this.handle;
    const length = Math.max(0, end - start);
    return {
      async arrayBuffer() {
        const buffer = Buffer.allocUnsafe(length);
        let read = 0;
        while (read < length) {
          const result = await handle.read(buffer, read, length - read, start + read);
          if (result.bytesRead === 0) {
            throw new Error('synthetic file ended before its declared size');
          }
          read += result.bytesRead;
        }
        return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + length);
      },
    };
  }
}

function lineFor(index) {
  const minute = index % 1440;
  const hour = String(Math.floor(minute / 60)).padStart(2, '0');
  const mm = String(minute % 60).padStart(2, '0');
  const stamp = `2026-10-28 ${hour}:${mm}:00`;
  const burst = index % 100000 < 30;
  const sparse = index % 977 === 0;
  if (burst || sparse) {
    return `${stamp} [ERROR] database timeout retry=${index}\n`;
  }
  return `${stamp} [INFO] request completed id=${index}\n`;
}

async function writeSynthetic(path, targetBytes) {
  const handle = await open(path, 'w');
  let written = 0;
  let index = 0;
  let buffer = [];
  let bufferBytes = 0;
  const flush = async () => {
    if (buffer.length === 0) {
      return;
    }
    const text = buffer.join('');
    await handle.write(text);
    written += Buffer.byteLength(text);
    buffer = [];
    bufferBytes = 0;
  };
  while (written + bufferBytes < targetBytes) {
    const line = lineFor(index);
    buffer.push(line);
    bufferBytes += Buffer.byteLength(line);
    index += 1;
    if (bufferBytes >= 1 << 20) {
      await flush();
    }
  }
  await flush();
  await handle.close();
  return { size: written, lines: index };
}

const started = performance.now();
const { size, lines } = await writeSynthetic(tempPath, targetMiB * 1024 * 1024);
const generated = performance.now();
console.log(`environment: node ${process.version} · ${process.platform}/${process.arch}`);
console.log(
  `synthetic: ${(size / 1048576).toFixed(1)} MiB · ${lines.toLocaleString('en-US')} lines · generated in ${(
    (generated - started) /
    1000
  ).toFixed(2)}s`,
);

const handle = await open(tempPath, 'r');
const file = new DiskFile(tempPath, size, 'synthetic.log', handle);
let maxRss = 0;
let progressEvents = 0;
let maxProgressBytes = 0;

try {
  const bridge = await instantiateMoonlog(await readFile(wasmPath));
  const analysisStart = performance.now();
  const result = await analyzeFile({
    bridge,
    file,
    options: {
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
    },
    onProgress: (progress) => {
      progressEvents += 1;
      maxProgressBytes = Math.max(maxProgressBytes, progress.bytes);
      if (progressEvents % 64 === 0) {
        maxRss = Math.max(maxRss, process.memoryUsage().rss);
      }
    },
  });
  const analysisEnd = performance.now();
  maxRss = Math.max(maxRss, process.memoryUsage().rss);
  const elapsed = (analysisEnd - analysisStart) / 1000;
  const report = JSON.parse(result.json);
  assert.equal(report.summary.total, lines);
  assert.equal(report.scans, 2);
  assert.equal(maxProgressBytes, size);
  console.log(
    `analysis: ${elapsed.toFixed(2)}s · ${((size * 2) / 1048576 / elapsed).toFixed(1)} MiB/s across two passes`,
  );
  console.log(
    `chunks: ${result.chunks} · progress events: ${progressEvents} · report JSON: ${(
      result.json.length / 1048576
    ).toFixed(1)} MiB`,
  );
  console.log(
    `report: lines=${report.summary.total} errors=${report.summary.errors} spikes=${report.summary.spike_count} ` +
      `sampled=${report.summary.sampled_targets} signatures=${report.signatures.length}`,
  );
  console.log(
    `rss: max sampled ${(maxRss / 1048576).toFixed(1)} MiB (includes Node, WASM heap, and the generator; not a constant-memory claim)`,
  );
} finally {
  await handle.close();
  await rm(tempPath, { force: true });
}
