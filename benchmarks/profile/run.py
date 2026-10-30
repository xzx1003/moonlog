"""Paired end-to-end ablations, not additive internal function timings."""
import argparse, hashlib, importlib.util, json, platform, statistics, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('baseline', ROOT/'scripts/bench_cli.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
p = argparse.ArgumentParser()
p.add_argument('--binary', required=True)
p.add_argument('--output', required=True)
p.add_argument('--runs', type=int, default=5)
a = p.parse_args()
if a.runs < 1: p.error('runs must be positive')
result = {'environment': {'platform': platform.platform(), 'hardware': b.hardware(), 'moon': subprocess.check_output(['moon','version','--all'],text=True), 'binary_sha256': hashlib.sha256(Path(a.binary).read_bytes()).hexdigest()}, 'runs': a.runs, 'warmups': 1, 'method': 'two-pass ablations; each includes reading/decoding; differences are estimates, not additive stage timings', 'cases': []}
with tempfile.TemporaryDirectory() as tmp:
 tmp = Path(tmp)
 for fmt in ['text', 'jsonl']:
  source = tmp/'input'; expected = b.generate(source, 100, fmt, True, 20261029)
  samples = {mode: [] for mode in ['read', 'digest', 'parse', 'aggregate', 'full']}
  for repeat in range(a.runs+1):
   modes = list(samples)
   if repeat % 2: modes.reverse()
   for mode in modes:
    x = b.run([a.binary, str(source), mode], tmp/'out', tmp/'err')
    if repeat: samples[mode].append(x)
  result['cases'].append({'format':fmt,'input':expected,'samples':samples,'median_seconds':{k:statistics.median(x['seconds'] for x in v) for k,v in samples.items()}})
Path(a.output).write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps([{'format':c['format'],**c['median_seconds']} for c in result['cases']],indent=2))
