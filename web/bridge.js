// Thin wrapper around the MoonBit wasm-gc module. All analysis runs in WASM;
// this file only marshals arguments/results and enforces the export contract.
const INSTANTIATE_OPTIONS = {
  builtins: ['js-string'],
  importedStringConstants: '_',
};

const REQUIRED_EXPORTS = [
  'moonlog_start',
  'moonlog_feed_base64',
  'moonlog_end_pass',
  'moonlog_phase',
  'moonlog_bytes_processed',
  'moonlog_cancel',
  'moonlog_result_json',
  'moonlog_last_error',
];

const INT_OPTIONS = [
  'bucketMinutes',
  'baselineBuckets',
  'multiplier',
  'minErrors',
  'context',
  'maxSamples',
];
const STRING_OPTIONS = ['source', 'level', 'keyword', 'from', 'to'];

function checkStartOptions(options) {
  for (const name of INT_OPTIONS) {
    const value = options[name];
    if (!Number.isInteger(value) || value < -2147483648 || value > 2147483647) {
      throw new Error(`${name} 必须是 32 位整数，未调用 WASM。`);
    }
  }
  for (const name of STRING_OPTIONS) {
    if (typeof options[name] !== 'string') {
      throw new Error(`${name} 必须是字符串，未调用 WASM。`);
    }
  }
}

export async function instantiateMoonlog(wasmSource) {
  let bytes = wasmSource;
  if (typeof wasmSource === 'string' || wasmSource instanceof URL) {
    const response = await fetch(wasmSource);
    if (!response.ok) {
      throw new Error(`无法加载 WASM 模块（HTTP ${response.status}）。请先运行 make web-build。`);
    }
    bytes = await response.arrayBuffer();
  }
  let instance;
  try {
    ({ instance } = await WebAssembly.instantiate(bytes, {}, INSTANTIATE_OPTIONS));
  } catch (error) {
    throw new Error(
      'WASM 实例化失败。该网页需要支持 WebAssembly GC 与 JS String Builtins 的浏览器。' +
        `原始错误：${error && error.message ? error.message : error}`,
    );
  }
  for (const name of REQUIRED_EXPORTS) {
    if (typeof instance.exports[name] !== 'function') {
      throw new Error(`WASM 导出缺失：${name}。请重新运行 make web-build。`);
    }
  }
  return wrapInstance(instance);
}

function wrapInstance(instance) {
  const ex = instance.exports;
  const lastError = () => ex.moonlog_last_error() || '未知错误';

  return {
    start(options) {
      checkStartOptions(options);
      const code = ex.moonlog_start(
        options.source,
        options.bucketMinutes,
        options.baselineBuckets,
        options.multiplier,
        options.minErrors,
        options.context,
        options.maxSamples,
        options.level,
        options.keyword,
        options.from,
        options.to,
      );
      if (code !== 0) {
        throw new Error(lastError());
      }
    },
    feedBase64(chunk) {
      if (ex.moonlog_feed_base64(chunk) !== 0) {
        throw new Error(lastError());
      }
    },
    endPass() {
      const next = ex.moonlog_end_pass();
      if (next === -1) {
        throw new Error(lastError());
      }
      return next;
    },
    phase() {
      return ex.moonlog_phase();
    },
    bytesProcessed() {
      return ex.moonlog_bytes_processed();
    },
    cancel() {
      ex.moonlog_cancel();
    },
    resultJson() {
      const json = ex.moonlog_result_json();
      if (!json) {
        throw new Error(lastError());
      }
      return json;
    },
    lastError,
  };
}
