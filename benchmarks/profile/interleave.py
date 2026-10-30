"""Interleaved before/after confirmation runs; paired medians, not new ablations."""
import hashlib, importlib.util, json, os, platform, statistics, subprocess, tempfile, time
from pathlib import Path

ROOT = Path('/Users/xzx/Documents/ChatGPT/moonlog')
spec = importlib.util.spec_from_file_location('baseline', ROOT / 'scripts/bench_cli.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

BEFORE = '/tmp/moonlog-profile-before'
AFTER = str(ROOT / '_build/native/release/build/benchmarks/compare/compare.exe')
RUNS = 5
MODES = ['read', 'digest', 'parse', 'aggregate', 'full']

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

result = {
    'environment': {
        'platform': platform.platform(),
        'hardware': b.hardware(),
        'moon': subprocess.check_output(['moon', 'version', '--all'], text=True),
        'loadavg_at_start': os.getloadavg(),
    },
    'runs': RUNS,
    'warmups': 1,
    'method': (
        'interleaved paired runs of preserved before binary and current build; '
        'binary order alternates by round; read/parse code is identical in both '
        'binaries and serve as noise controls; ablation differences are estimates, '
        'not additive stage timings; aggregate aggregates both passes while full '
        'aggregates only the first pass'
    ),
    'binaries': {
        'before': {'path': BEFORE, 'sha256': sha256(BEFORE)},
        'after': {'path': AFTER, 'sha256': sha256(AFTER)},
    },
    'cases': [],
}

with tempfile.TemporaryDirectory(prefix='moonlog-interleave-') as tmp:
    tmp = Path(tmp)
    for fmt in ['text', 'jsonl']:
        source = tmp / 'input'
        expected = b.generate(source, 100, fmt, True, 20261029)
        samples = {name: {mode: [] for mode in MODES} for name in ['before', 'after']}
        for repeat in range(RUNS + 1):
            order = ['before', 'after'] if repeat % 2 == 0 else ['after', 'before']
            for name in order:
                exe = BEFORE if name == 'before' else AFTER
                modes = MODES if repeat % 2 == 0 else list(reversed(MODES))
                for mode in modes:
                    x = b.run([exe, str(source), mode], tmp / 'out', tmp / 'err')
                    if repeat:
                        samples[name][mode].append(x)
        medians = {
            name: {mode: statistics.median(x['seconds'] for x in vals) for mode, vals in by_mode.items()}
            for name, by_mode in samples.items()
        }
        delta = {
            mode: (medians['after'][mode] - medians['before'][mode]) / medians['before'][mode] * 100.0
            for mode in MODES
        }
        result['cases'].append({
            'format': fmt,
            'input': expected,
            'samples': samples,
            'median_seconds': medians,
            'after_vs_before_percent': delta,
        })
        print(fmt, {m: round(delta[m], 2) for m in MODES}, flush=True)

result['environment']['loadavg_at_end'] = os.getloadavg()
out = Path('/Users/xzx/Documents/ChatGPT/moonlog/benchmarks/profile/interleave.json')
out.write_text(json.dumps(result, indent=2) + '\n')
print('saved', out)
