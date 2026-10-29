// One worker per analysis run. The page terminates this worker on cancel or
// error, which releases both the WASM instance and its MoonBit session.
import { instantiateMoonlog } from './bridge.js';
import { analyzeFile } from './analysis.js';

const WASM_URL = new URL('./generated/moonlog_web.wasm', import.meta.url);

let bridgePromise = null;
let running = false;

function loadBridge() {
  if (!bridgePromise) {
    bridgePromise = instantiateMoonlog(WASM_URL);
  }
  return bridgePromise;
}

self.onmessage = async (event) => {
  const data = event.data;
  if (!data || data.type !== 'analyze') {
    return;
  }
  if (running) {
    self.postMessage({ type: 'error', message: '该 Worker 已经在执行分析。' });
    return;
  }
  running = true;
  try {
    const bridge = await loadBridge();
    const result = await analyzeFile({
      bridge,
      file: data.file,
      options: data.options,
      onProgress: (progress) => {
        self.postMessage({ type: 'progress', progress });
      },
    });
    self.postMessage({ type: 'result', json: result.json, chunks: result.chunks });
  } catch (error) {
    const cancelled = error && error.name === 'CancelledError';
    self.postMessage({
      type: 'error',
      cancelled,
      message: error instanceof Error ? error.message : String(error),
    });
  } finally {
    running = false;
  }
};
