const els = {
  form: document.getElementById('analysis-form'),
  controls: document.getElementById('controls'),
  workbenchFields: document.getElementById('workbench-fields'),
  workbenchSummary: document.getElementById('workbench-summary'),
  summaryLine: document.getElementById('summary-line'),
  editParams: document.getElementById('edit-params'),
  file: document.getElementById('file'),
  fileInfo: document.getElementById('file-info'),
  bucketMinutes: document.getElementById('bucket-minutes'),
  baselineBuckets: document.getElementById('baseline-buckets'),
  multiplier: document.getElementById('multiplier'),
  minErrors: document.getElementById('min-errors'),
  contextLines: document.getElementById('context-lines'),
  maxSamples: document.getElementById('max-samples'),
  level: document.getElementById('level'),
  keyword: document.getElementById('keyword'),
  from: document.getElementById('from'),
  to: document.getElementById('to'),
  actions: document.getElementById('actions'),
  start: document.getElementById('start'),
  cancel: document.getElementById('cancel'),
  status: document.getElementById('status'),
  progressPanel: document.getElementById('progress-panel'),
  progressPhase: document.getElementById('progress-phase'),
  progressBytes: document.getElementById('progress-bytes'),
  progressBar: document.getElementById('progress-bar'),
  progressDetail: document.getElementById('progress-detail'),
  errorBox: document.getElementById('error-box'),
  results: document.getElementById('results'),
  download: document.getElementById('download'),
  overview: document.getElementById('overview'),
  spikes: document.getElementById('spikes'),
  signatures: document.getElementById('signatures'),
  contextWindows: document.getElementById('context-windows'),
  configBody: document.getElementById('config-body'),
};

const LEVELS = ['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL', 'OTHER'];
const copyTimers = new WeakMap();
let activeRun = null;
let reportText = null;
let currentFileName = '';
let selectedFile = null;
let currentStep = 0;
const stepItems = [...document.querySelectorAll('#analysis-steps li')];
const stepPanels = [...document.querySelectorAll('[data-step]')];
const backButton = document.getElementById('step-back');
const progressPercent = document.getElementById('progress-percent');
const progressFile = document.getElementById('progress-file');
function renderStep(focus = false) {
  stepItems.forEach((item, index) => {
    item.classList.toggle('is-current', index === currentStep);
    item.classList.toggle('is-done', index < currentStep);
    if (index === currentStep) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  });
  stepPanels.forEach((panel, index) => { panel.hidden = index !== currentStep; });
  backButton.disabled = currentStep === 0 || Boolean(activeRun);
  els.start.textContent = activeRun ? '分析中' : currentStep === 2 ? '开始分析' : '下一步';
  if (focus) (stepPanels[currentStep].querySelector('h3, input') || els.start).focus();
}
backButton.addEventListener('click', () => {
  if (activeRun || currentStep === 0) return;
  currentStep--;
  hideError();
  renderStep(true);
});
renderStep();

els.file.addEventListener('change', () => {
  selectedFile = els.file.files[0] || null;
  hideError();
  clearResults();
  hideProgress();
  els.status.textContent = '';
  updateFileInfo();
});

function selectFile(file) {
  selectedFile = file;
  hideError();
  clearResults();
  hideProgress();
  els.status.textContent = '';
  updateFileInfo();
}

const dropZone = document.getElementById('drop-zone');
dropZone.addEventListener('dragover', (event) => {
  event.preventDefault();
  if (!activeRun) dropZone.classList.add('is-dragging');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('is-dragging'));
dropZone.addEventListener('drop', (event) => {
  event.preventDefault();
  dropZone.classList.remove('is-dragging');
  if (activeRun) return;
  if (event.dataTransfer.files.length !== 1) {
    showError('请一次导入一个日志文件。');
    return;
  }
  els.file.value = '';
  selectFile(event.dataTransfer.files[0]);
});
document.getElementById('load-example').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const response = await fetch(new URL('./sample.log', import.meta.url));
    if (!response.ok) throw new Error('示例日志加载失败，请稍后重试。');
    if (activeRun) return;
    els.file.value = '';
    selectFile(new File([await response.blob()], 'sample.log', { type: 'text/plain' }));
    currentStep = 1;
    renderStep(true);
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
  }
});

els.form.addEventListener('submit', (event) => {
  event.preventDefault();
  if (activeRun) return;
  hideError();
  if (currentStep === 0) {
    if (!selectedFile) { showError('请选择一个日志文件。'); els.file.focus(); return; }
    currentStep = 1;
    renderStep(true);
  } else if (currentStep === 1) {
    const invalid = stepPanels[1].querySelector('input:invalid');
    if (invalid) { invalid.reportValidity(); return; }
    currentStep = 2;
    renderStep(true);
  } else startAnalysis();
});

els.cancel.addEventListener('click', cancelAnalysis);
els.download.addEventListener('click', downloadReport);
els.editParams.addEventListener('click', () => {
  currentStep = 0;
  expandWorkbench();
  els.file.focus();
});
els.spikes.addEventListener('click', handleSpikeToggle);
els.signatures.addEventListener('click', handleSignatureCopy);

updateFileInfo();

function updateFileInfo() {
  const file = selectedFile;
  if (!file) {
    els.fileInfo.textContent = '';
    els.fileInfo.hidden = true;
    return;
  }
  const empty = file.size === 0 ? ' · 空文件' : '';
  els.fileInfo.textContent = `${file.name} · ${formatBytes(file.size)}${empty}`;
  els.fileInfo.hidden = false;
}

function readInteger(input, label) {
  const raw = input.value.trim();
  if (!/^[+-]?\d+$/.test(raw)) {
    throw new Error(`${label}必须是整数。`);
  }
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < -2147483648 || value > 2147483647) {
    throw new Error(`${label}超出 32 位整数范围。`);
  }
  return value;
}

function readOptions() {
  return {
    bucketMinutes: readInteger(els.bucketMinutes, '桶宽'),
    baselineBuckets: readInteger(els.baselineBuckets, '基线桶数'),
    multiplier: readInteger(els.multiplier, '倍数'),
    minErrors: readInteger(els.minErrors, '最少错误数'),
    context: readInteger(els.contextLines, '上下文行数'),
    maxSamples: readInteger(els.maxSamples, '样本上限'),
    level: els.level.value,
    keyword: els.keyword.value,
    from: els.from.value.trim(),
    to: els.to.value.trim(),
  };
}

function startAnalysis() {
  if (activeRun) {
    return;
  }
  hideError();
  clearResults();
  hideProgress();
  const file = selectedFile;
  if (!file) {
    showError('请选择一个日志文件。');
    return;
  }
  let options;
  try {
    options = readOptions();
  } catch (error) {
    showError(error.message);
    return;
  }

  let worker;
  try {
    worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
  } catch (error) {
    showError(
      `无法启动分析：${error && error.message ? error.message : error}。` +
        '请通过 HTTP 服务器打开页面，不要直接打开本地文件。',
    );
    return;
  }

  const run = { worker, settled: false };
  activeRun = run;
  setRunning(true);
  startProgress(file.size);
  els.status.textContent = '分析中…';

  worker.onmessage = (event) => {
    if (activeRun !== run || run.settled) {
      return;
    }
    handleWorkerMessage(run, event.data);
  };
  worker.onerror = (event) => {
    if (activeRun !== run || run.settled) {
      return;
    }
    event.preventDefault();
    failRun(
      run,
      `分析模块加载失败：${event.message || '未知错误'}。` +
        '请确认已运行 make web-build，并通过 HTTP 服务器打开页面。',
    );
  };
  worker.onmessageerror = () => {
    if (activeRun !== run || run.settled) {
      return;
    }
    failRun(run, '分析结果传输失败。');
  };

  // Structured clone keeps the File handle, not the file contents.
  worker.postMessage({ type: 'analyze', file, options });
}

function handleWorkerMessage(run, message) {
  if (!message || typeof message !== 'object') {
    return;
  }
  if (message.type === 'progress') {
    updateProgress(message.progress);
    return;
  }
  if (message.type === 'result') {
    finishRun(run, message);
    return;
  }
  if (message.type === 'error') {
    if (message.cancelled) {
      finishCancelled(run);
    } else {
      failRun(run, message.message || '分析失败。');
    }
  }
}

function finishRun(run, message) {
  run.settled = true;
  run.worker.terminate();
  if (activeRun === run) {
    activeRun = null;
  }
  setRunning(false);
  els.progressPanel.hidden = false;
  els.progressBar.value = 100;
  progressPercent.textContent = '100%';
  els.progressPhase.textContent = '分析完成';
  els.progressDetail.textContent = '';
  els.status.textContent = '分析完成';

  let report;
  try {
    report = JSON.parse(message.json);
  } catch (error) {
    showError('报告解析失败，未展示结果。');
    return;
  }
  reportText = message.json;
  currentFileName = selectedFile ? selectedFile.name : 'moonlog';
  try {
    renderReport(report);
  } catch (error) {
    clearResults();
    els.status.textContent = '分析失败';
    showError(`报告渲染失败：${error && error.message ? error.message : error}`);
    return;
  }
  els.download.disabled = false;
  els.results.hidden = false;
  collapseWorkbench(report);
  els.results.scrollIntoView({ block: 'start' });
}

function finishCancelled(run) {
  run.settled = true;
  run.worker.terminate();
  if (activeRun === run) {
    activeRun = null;
  }
  setRunning(false);
  hideProgress();
  els.status.textContent = '已取消';
}

function failRun(run, message) {
  run.settled = true;
  run.worker.terminate();
  if (activeRun === run) {
    activeRun = null;
  }
  setRunning(false);
  hideProgress();
  clearResults();
  els.status.textContent = '分析失败';
  showError(message);
}

function cancelAnalysis() {
  const run = activeRun;
  if (!run) {
    return;
  }
  run.settled = true;
  run.worker.terminate();
  activeRun = null;
  setRunning(false);
  hideProgress();
  els.status.textContent = '已取消';
}

function setRunning(running) {
  for (const field of els.controls.querySelectorAll('input, select')) {
    field.disabled = running;
  }
  els.start.disabled = running;
  backButton.disabled = running || currentStep === 0;
  renderStep();
  els.cancel.hidden = !running;
  els.cancel.disabled = !running;
  if (running) {
    els.status.textContent = '分析中…';
  }
}

function startProgress(total) {
  els.progressPanel.hidden = false;
  els.progressBar.value = 0;
  progressPercent.textContent = '0%';
  progressFile.textContent = selectedFile ? selectedFile.name : '';
  els.progressPhase.textContent = '准备读取文件…';
  els.progressBytes.textContent = `0 B / ${formatBytes(total)}`;
  els.progressDetail.textContent = total === 0 ? '文件为空，将生成报告。' : '';
}

function updateProgress(progress) {
  if (!progress) {
    return;
  }
  els.progressPanel.hidden = false;
  const total = Number(progress.total) || 0;
  const bytes = Number(progress.bytes) || 0;
  const pass = progress.pass === 2 ? 2 : 1;
  const percent =
    total > 0 ? Math.max(0, Math.min(100, Math.floor(((pass - 1) + bytes / total) * 50))) : 0;
  els.progressBar.value = percent;
  progressPercent.textContent = `${percent}%`;
  els.progressBytes.textContent = `${formatBytes(bytes)} / ${formatBytes(total)}`;
  if (progress.phase === 3) {
    els.progressBar.value = 100;
    progressPercent.textContent = '100%';
    els.progressPhase.textContent = '生成报告…';
    els.progressDetail.textContent = '';
  } else {
    els.progressPhase.textContent = pass === 1 ? '读取日志…' : '采集上下文…';
    els.progressDetail.textContent = total === 0 ? '文件为空，将生成报告。' : '';
  }
}

function hideProgress() {
  els.progressPanel.hidden = true;
  els.progressBar.value = 0;
  els.progressPhase.textContent = '准备读取文件…';
  els.progressBytes.textContent = '';
  els.progressDetail.textContent = '';
}

function showError(message) {
  const reason = localizeError(message);
  els.errorBox.replaceChildren();
  els.errorBox.appendChild(make('strong', null, '分析失败'));
  els.errorBox.appendChild(make('span', null, reason));
  els.errorBox.hidden = false;
}

function hideError() {
  els.errorBox.hidden = true;
  els.errorBox.replaceChildren();
}

function clearResults() {
  reportText = null;
  els.results.hidden = true;
  els.download.disabled = true;
  els.overview.replaceChildren();
  els.spikes.replaceChildren();
  els.signatures.replaceChildren();
  els.contextWindows.replaceChildren();
  els.configBody.replaceChildren();
  expandWorkbench();
}

function expandWorkbench() {
  renderStep();
  els.workbenchFields.hidden = false;
  els.workbenchSummary.hidden = true;
  els.actions.hidden = false;
}

function collapseWorkbench(report) {
  const file = selectedFile;
  const config = report.config || {};
  const bits = [];
  if (file) {
    bits.push(formatBytes(file.size));
  }
  bits.push(formatPeriod(report.filter || {}));
  bits.push(`桶宽 ${formatInt(config.bucket_minutes)} 分`);
  bits.push(`基线 ${formatInt(config.baseline_buckets)} 桶`);
  bits.push(`倍数 ${formatInt(config.multiplier)}×`);
  bits.push(`上下文 ${formatInt(config.context)} 行`);

  const source = report.source || (file ? file.name : 'moonlog');
  els.summaryLine.replaceChildren();
  els.summaryLine.appendChild(make('strong', null, source));
  els.summaryLine.appendChild(document.createTextNode(` ${bits.join(' · ')}`));
  els.workbenchFields.hidden = true;
  els.workbenchSummary.hidden = false;
  els.actions.hidden = true;
}

function downloadReport() {
  if (!reportText) {
    return;
  }
  const blob = new Blob([reportText], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  const base = (currentFileName || 'moonlog').replace(/[\\/:*?"<>|]/g, '_');
  link.href = url;
  link.download = `${base}.moonlog.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderReport(report) {
  renderOverview(report);
  renderSpikes(report);
  renderSignatures(report);
  renderContext(report);
  renderConfig(report);
}

function renderOverview(report) {
  const summary = report.summary || {};
  const ratio = summary.log_error_ratio || {};
  const wrap = make('section', 'report-section overview');
  wrap.appendChild(make('h3', 'visually-hidden', '概览'));

  const strip = make('div', 'overview-strip');

  const ratioCell = make('div', 'ratio-cell');
  ratioCell.appendChild(make('span', 'stat-label', '错误占比'));
  ratioCell.appendChild(make('strong', 'ratio-value', ratioText(ratio)));
  ratioCell.appendChild(
    make('span', 'ratio-detail', ratioDetail(ratio) || '没有可用的日志行'),
  );
  strip.appendChild(ratioCell);

  const omittedTargets = Number(summary.omitted_targets) || 0;
  const stats = make('dl', 'overview-stats');
  addStat(stats, '尖峰', formatInt(summary.spike_count));
  addStat(stats, '错误行', formatInt(summary.errors), 'ERROR / FATAL');
  addStat(stats, '扫描行数', formatInt(summary.total), '文件中实际扫描的全部日志行');
  addStat(stats, '筛选后', formatInt(summary.matched), '级别和关键词筛选后的行数');
  addStat(stats, '无时间戳', formatInt(summary.untimed), '无法解析时间戳的行');
  addStat(
    stats,
    '上下文样本',
    formatInt(summary.sampled_targets),
    omittedTargets > 0
      ? `另有 ${formatInt(omittedTargets)} 个目标未采样`
      : '保留的上下文目标数',
  );
  strip.appendChild(stats);
  wrap.appendChild(strip);

  const levels = make('div', 'level-summary');
  levels.appendChild(make('span', 'stat-label', '级别分布'));
  const counts = report.level_counts || {};
  const present = LEVELS.filter((level) => Number(counts[level]) > 0);
  if (present.length === 0) {
    levels.appendChild(make('span', 'level-empty', '没有级别数据。'));
  } else {
    const list = make('div', 'level-list');
    present.forEach((level, index) => {
      if (index > 0) {
        list.appendChild(document.createTextNode(' · '));
      }
      const item = make('span', 'level-item');
      item.appendChild(make('span', 'level-name', level));
      item.appendChild(make('strong', null, formatInt(counts[level])));
      list.appendChild(item);
    });
    levels.appendChild(list);
  }
  wrap.appendChild(levels);

  wrap.appendChild(
    make(
      'p',
      'ratio-note',
      '占比按日志行计算，不是请求失败率；不受级别和关键词筛选影响。',
    ),
  );

  els.overview.replaceChildren(wrap);
}

function renderSpikes(report) {
  const spikes = Array.isArray(report.spikes) ? report.spikes : [];
  if (spikes.length === 0) {
    els.spikes.replaceChildren(
      make('p', 'empty-state', '未发现尖峰。这不代表服务健康。'),
    );
    return;
  }

  const table = make('table', 'report-table spikes-table');
  table.appendChild(make('caption', 'visually-hidden', '尖峰'));
  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  for (const label of ['时间窗口（UTC）', '错误', '峰值', '基线', '占比']) {
    const th = document.createElement('th');
    th.scope = 'col';
    if (label !== '时间窗口（UTC）') {
      th.className = 'num';
    }
    th.textContent = label;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  spikes.forEach((spike, index) => {
    const detailId = `spike-detail-${index}`;
    const row = document.createElement('tr');
    row.className = 'spike-row';
    const ratio = spike.log_error_ratio || {};

    const windowCell = document.createElement('th');
    windowCell.scope = 'row';
    windowCell.className = 'window-cell';
    const toggle = make(
      'button',
      'row-toggle',
      formatWindow(spike.start, spike.end_exclusive),
    );
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-controls', detailId);
    toggle.appendChild(
      make(
        'span',
        'row-summary',
        [
          `错误 ${formatInt(spike.errors)}`,
          `峰值 ${formatInt(spike.peak_errors)}`,
          `基线 ${formatNumber(spike.baseline)}`,
          `占比 ${ratioText(ratio)}`,
        ].join(' · '),
      ),
    );
    windowCell.appendChild(toggle);
    row.appendChild(windowCell);

    row.appendChild(numberCell(spike.errors));
    row.appendChild(numberCell(spike.peak_errors));
    row.appendChild(numberCell(formatNumber(spike.baseline)));
    const ratioCell = numberCell(ratioText(ratio));
    const detail = ratioDetail(ratio);
    if (detail) {
      ratioCell.title = detail;
    }
    row.appendChild(ratioCell);

    const detailRow = document.createElement('tr');
    detailRow.className = 'spike-detail';
    detailRow.id = detailId;
    detailRow.hidden = true;
    const detailCell = document.createElement('td');
    detailCell.colSpan = 5;
    const inner = make('div', 'spike-detail-inner');
    inner.appendChild(make('p', 'detail-label', '错误签名'));
    const signatures = Array.isArray(spike.signatures) ? spike.signatures : [];
    if (signatures.length === 0) {
      inner.appendChild(make('p', 'field-note', '无错误签名。'));
    } else {
      inner.appendChild(signatureList(signatures));
    }
    if (Number(spike.omitted_signature_occurrences) > 0) {
      inner.appendChild(
        make(
          'p',
          'field-note',
          `另有 ${formatInt(spike.omitted_signature_occurrences)} 次未计入。`,
        ),
      );
    }
    detailCell.appendChild(inner);
    detailRow.appendChild(detailCell);

    tbody.appendChild(row);
    tbody.appendChild(detailRow);
  });
  table.appendChild(tbody);
  els.spikes.replaceChildren(table);
}

function numberCell(value) {
  return make('td', 'num', value);
}

function handleSpikeToggle(event) {
  const target = event.target instanceof Element ? event.target : null;
  const button = target ? target.closest('.row-toggle') : null;
  if (!button) {
    return;
  }
  const detailId = button.getAttribute('aria-controls');
  const detail = detailId ? document.getElementById(detailId) : null;
  if (!detail) {
    return;
  }
  const open = button.getAttribute('aria-expanded') === 'true';
  button.setAttribute('aria-expanded', String(!open));
  detail.hidden = open;
}

function renderSignatures(report) {
  const signatures = Array.isArray(report.signatures) ? report.signatures : [];
  if (signatures.length === 0) {
    els.signatures.replaceChildren(make('p', 'empty-state', '无错误签名。'));
    return;
  }

  const fragment = document.createDocumentFragment();
  const table = make('table', 'report-table signatures-table');
  table.appendChild(make('caption', 'visually-hidden', '错误签名'));
  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  const countHead = make('th', 'num', '次数');
  countHead.scope = 'col';
  const textHead = make('th', null, '签名');
  textHead.scope = 'col';
  const actionHead = make('th', 'action-head', '操作');
  actionHead.scope = 'col';
  headRow.append(countHead, textHead, actionHead);
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (const signature of signatures) {
    const row = document.createElement('tr');
    row.appendChild(make('td', 'num', formatInt(signature.count)));

    const textCell = document.createElement('td');
    textCell.appendChild(
      make('code', 'signature-text', signature.text || '（空签名）'),
    );
    row.appendChild(textCell);

    const actionCell = document.createElement('td');
    const copy = make('button', 'copy-button', '复制');
    copy.type = 'button';
    copy.dataset.copy = signature.text || '';
    copy.setAttribute('aria-label', `复制签名：${signature.text || '空签名'}`);
    actionCell.appendChild(copy);
    row.appendChild(actionCell);
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  fragment.appendChild(table);

  const overflow = Number(
    report.summary && report.summary.omitted_global_signature_occurrences,
  );
  if (overflow > 0) {
    fragment.appendChild(
      make('p', 'field-note', `另有 ${formatInt(overflow)} 次超过签名上限。`),
    );
  }
  els.signatures.replaceChildren(fragment);
}

function signatureList(signatures) {
  const list = make('ol', 'signature-list');
  for (const signature of signatures) {
    const item = document.createElement('li');
    item.appendChild(make('span', 'signature-count', formatInt(signature.count)));
    item.appendChild(make('code', 'signature-text', signature.text || '（空签名）'));
    list.appendChild(item);
  }
  return list;
}

async function handleSignatureCopy(event) {
  const target = event.target instanceof Element ? event.target : null;
  const button = target ? target.closest('.copy-button') : null;
  if (!button) {
    return;
  }
  try {
    await copyText(button.dataset.copy || '');
    showCopyState(button, '已复制');
  } catch (error) {
    showCopyState(button, '复制失败');
  }
}

async function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (error) {
      // Fall through to the selection-based copy.
    }
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.className = 'visually-hidden';
  document.body.appendChild(area);
  area.select();
  const copied = document.execCommand('copy');
  area.remove();
  if (!copied) {
    throw new Error('copy failed');
  }
}

function showCopyState(button, label) {
  button.textContent = label;
  const previous = copyTimers.get(button);
  if (previous) {
    clearTimeout(previous);
  }
  copyTimers.set(
    button,
    setTimeout(() => {
      button.textContent = '复制';
      copyTimers.delete(button);
    }, 1600),
  );
}

function renderContext(report) {
  const windows = Array.isArray(report.context_windows) ? report.context_windows : [];
  if (windows.length === 0) {
    els.contextWindows.replaceChildren(
      make('p', 'empty-state', '没有可显示的上下文。'),
    );
    return;
  }

  const fragment = document.createDocumentFragment();
  windows.forEach((window, index) => {
    const lines = Array.isArray(window.lines) ? window.lines : [];
    const targets = Array.isArray(window.targets)
      ? window.targets.map((number) => Number(number))
      : [];
    const targetSet = new Set(targets);

    const details = document.createElement('details');
    details.className = 'context-window';
    details.open = index === 0;

    const summary = document.createElement('summary');
    summary.appendChild(
      make('strong', null, targets.length > 0 ? targetLabel(targets) : '上下文窗口'),
    );
    summary.appendChild(
      make('span', 'context-size', `${formatInt(lines.length)} 行`),
    );
    details.appendChild(summary);

    const block = make('div', 'log-block');
    for (const line of lines) {
      const isTarget = targetSet.has(Number(line.number));
      const row = make('div', isTarget ? 'log-line is-target' : 'log-line');
      row.appendChild(make('span', 'log-number', formatInt(line.number)));
      row.appendChild(
        make('span', 'log-text', line.text === '' ? '\u00a0' : String(line.text)),
      );
      block.appendChild(row);
    }
    details.appendChild(block);
    fragment.appendChild(details);
  });

  const omitted = Number(report.summary && report.summary.omitted_targets);
  if (omitted > 0) {
    fragment.appendChild(
      make('p', 'field-note after-context', `另有 ${formatInt(omitted)} 个目标行未采样。`),
    );
  }
  els.contextWindows.replaceChildren(fragment);
}

function targetLabel(targets) {
  const shown = targets.slice(0, 3).map(formatInt).join('、');
  if (targets.length > 3) {
    return `目标行 ${shown} 等 ${formatInt(targets.length)} 个`;
  }
  return `目标行 ${shown}`;
}

function renderConfig(report) {
  const config = report.config || {};
  const filter = report.filter || {};
  const facts = make('dl', 'facts');
  addStat(facts, '桶宽（分钟）', formatInt(config.bucket_minutes));
  addStat(facts, '基线桶数', formatInt(config.baseline_buckets));
  addStat(facts, '倍数', formatInt(config.multiplier));
  addStat(facts, '最少错误数', formatInt(config.min_errors));
  addStat(facts, '上下文行数', formatInt(config.context));
  addStat(
    facts,
    '上下文模式',
    config.context_mode === 'spikes' ? '尖峰' : config.context_mode,
  );
  addStat(facts, '样本上限', formatInt(config.max_samples));
  addStat(facts, '最大桶数', formatInt(config.max_buckets));
  addStat(facts, '最大签名数', formatInt(config.max_signatures));
  addStat(facts, '级别过滤', filter.level || '全部');
  addStat(facts, '关键词过滤', filter.keyword ? filter.keyword : '（无）');
  addStat(facts, '起始时间（UTC，含）', filter.from_inclusive || '不限');
  addStat(facts, '结束时间（UTC，含）', filter.to_inclusive || '不限');
  addStat(facts, '采样方式', report.sampling === 'first' ? '按出现顺序' : report.sampling);
  els.configBody.replaceChildren(facts);
  els.configBody.appendChild(make('p', 'field-note', '时间均为 UTC。'));
}

function addStat(list, term, value, title) {
  const row = document.createElement('div');
  const label = make('dt', null, term);
  if (title) {
    label.title = title;
  }
  row.appendChild(label);
  row.appendChild(make('dd', null, value));
  list.appendChild(row);
}

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined && text !== null) {
    node.textContent = String(text);
  }
  return node;
}

function formatWindow(start, endExclusive) {
  const startText = String(start || '').replace(/Z$/, '');
  const endText = String(endExclusive || '').replace(/Z$/, '');
  if (!startText || !endText) {
    return `${startText || '—'} – ${endText || '—'}`;
  }
  const sameDay = startText.slice(0, 10) === endText.slice(0, 10);
  const endLabel = sameDay
    ? clockText(endText)
    : `${endText.slice(0, 10)} ${clockText(endText)}`;
  return `${startText.slice(0, 10)} ${clockText(startText)} – ${endLabel}`;
}

function clockText(value) {
  const time = value.slice(11);
  return time.endsWith(':00') ? time.slice(0, 5) : time;
}

function ratioText(ratio) {
  const fraction = ratio ? ratio.fraction : null;
  if (
    fraction === null ||
    fraction === undefined ||
    !Number.isFinite(Number(fraction))
  ) {
    return 'N/A';
  }
  return `${(Number(fraction) * 100).toFixed(1)}%`;
}

function ratioDetail(ratio) {
  if (!ratio || ratio.total === undefined || ratio.errors === undefined) {
    return '';
  }
  return `${formatInt(ratio.errors)} / ${formatInt(ratio.total)} 行`;
}

function formatInt(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '—';
  }
  return number.toLocaleString('zh-CN');
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '—';
  }
  return number.toFixed(2);
}

function formatPeriod(filter) {
  const from = String((filter && filter.from_inclusive) || '').replace(/Z$/, '');
  const to = String((filter && filter.to_inclusive) || '').replace(/Z$/, '');
  if (!from && !to) {
    return '全部时间';
  }
  if (from && to) {
    const end = from.slice(0, 10) === to.slice(0, 10) ? to.slice(11) : to;
    return `${from} 至 ${end}（UTC）`;
  }
  return from ? `${from} 起（UTC）` : `截至 ${to}（UTC）`;
}

function localizeError(message) {
  const text = String(message === null || message === undefined ? '' : message).trim();
  if (text === 'invalid UTF-8') {
    return '文件不是有效的 UTF-8 文本。';
  }
  if (text === 'line exceeds 64 KiB') {
    return '文件里有超过 64 KiB 的单行，无法分析。';
  }
  if (text === 'input changed between passes') {
    return '文件在分析过程中发生了变化，请重新选择后再试。';
  }
  if (text === 'from must not be after to') {
    return '起始时间不能晚于结束时间。';
  }
  if (text.startsWith('invalid from timestamp')) {
    return '起始时间格式无效，请使用 YYYY-MM-DD HH:MM:SS。';
  }
  if (text.startsWith('invalid to timestamp')) {
    return '结束时间格式无效，请使用 YYYY-MM-DD HH:MM:SS。';
  }
  if (text.startsWith('unknown log level')) {
    return '级别无效，请从列表中选择。';
  }
  if (text.startsWith('bucket minutes must be')) {
    return '桶宽必须在 1 到 1440 分钟之间。';
  }
  if (text.startsWith('baseline buckets must be')) {
    return '基线桶数必须在 1 到 1000 之间。';
  }
  if (text.startsWith('multiplier must be')) {
    return '倍数必须在 2 到 1000 之间。';
  }
  if (text.startsWith('minimum errors must be')) {
    return '最少错误数必须大于 0。';
  }
  if (text.startsWith('context must be')) {
    return '上下文行数必须在 0 到 100 之间。';
  }
  if (text.startsWith('max samples must be') || text.startsWith('sample limit must be')) {
    return '样本上限必须在 0 到 100 之间。';
  }
  if (text.startsWith('max buckets must be')) {
    return '桶数上限无效。';
  }
  if (text.startsWith('max signatures must be')) {
    return '签名上限无效。';
  }
  if (
    text === 'analysis has not started' ||
    text === 'report is not ready' ||
    text === 'invalid session phase' ||
    text === 'unexpected session state'
  ) {
    return '分析状态异常，请重新开始。';
  }
  if (
    text === 'chunk exceeds 64 KiB' ||
    text === 'invalid base64 chunk' ||
    text === 'failed to feed input' ||
    text === 'failed to finish scan pass' ||
    text === 'failed to build report'
  ) {
    return '分析中断，请重试。';
  }
  if (text === 'invalid analysis parameters') {
    return '参数无效，请检查后重试。';
  }
  return text || '分析失败，请重试。';
}

function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) {
    return '0 B';
  }
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let index = 0;
  let scaled = value;
  while (scaled >= 1024 && index < units.length - 1) {
    scaled /= 1024;
    index += 1;
  }
  return index === 0 ? `${Math.round(scaled)} B` : `${scaled.toFixed(1)} ${units[index]}`;
}
