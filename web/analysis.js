// Shared by the Web Worker and the Node bridge tests. It only slices the File,
// encodes each chunk, and calls the WASM session; parsing and statistics stay
// inside MoonBit.
export const CHUNK_SIZE = 65536;

export class CancelledError extends Error {
  constructor() {
    super('已取消');
    this.name = 'CancelledError';
  }
}

export function bytesToBase64(bytes) {
  let binary = '';
  const step = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += step) {
    binary += String.fromCharCode.apply(null, bytes.subarray(offset, offset + step));
  }
  return btoa(binary);
}

export async function analyzeFile({ bridge, file, options, onProgress = () => {}, signal }) {
  if (!file || typeof file.slice !== 'function' || typeof file.size !== 'number') {
    throw new Error('需要一个可读取的 File 对象。');
  }
  const total = file.size;
  const source = file.name || 'input.log';
  bridge.start({ ...options, source });
  const checkCancelled = () => {
    if (signal && signal.aborted) {
      bridge.cancel();
      throw new CancelledError();
    }
  };
  checkCancelled();
  let chunks = 0;
  onProgress({ pass: 1, phase: bridge.phase(), bytes: 0, total });
  for (let pass = 1; pass <= 2; pass++) {
    let offset = 0;
    while (offset < total) {
      checkCancelled();
      const end = Math.min(offset + CHUNK_SIZE, total);
      const buffer = await file.slice(offset, end).arrayBuffer();
      checkCancelled();
      bridge.feedBase64(bytesToBase64(new Uint8Array(buffer)));
      chunks += 1;
      offset = end;
      onProgress({ pass, phase: bridge.phase(), bytes: bridge.bytesProcessed(), total });
    }
    const next = bridge.endPass();
    if (next === 3) {
      break;
    }
    if (next !== 2) {
      throw new Error(`扫描阶段异常：期望 2 或 3，收到 ${next}。`);
    }
    if (pass === 2) {
      throw new Error('扫描阶段异常：第二遍结束后仍要求重读文件。');
    }
    onProgress({ pass: 2, phase: bridge.phase(), bytes: 0, total });
  }
  const json = bridge.resultJson();
  onProgress({ pass: 2, phase: bridge.phase(), bytes: total, total });
  return { json, chunks };
}
