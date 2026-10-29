#!/usr/bin/env python3
"""Deterministic native CLI benchmark; no third-party dependencies (macOS/Linux)."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time


def generate(path, mib, fmt, dense, seed):
    rng = random.Random(seed)
    counts = {'total': 0, 'errors': 0}
    digest = hashlib.sha256()
    size = 0
    # Ordered, fixed 24h span: input size changes traffic volume, not bucket count.
    # Each block has exactly 1000 lines; errors occupy seeded positions.
    blocks = max(1, (mib * 1048576 + 159999) // 160000)
    start = dt.datetime(2026, 10, 28)
    with path.open('wb') as out:
        for block in range(blocks):
            stamp = (start + dt.timedelta(seconds=block * 86399 // blocks)).strftime('%Y-%m-%d %H:%M:%S')
            errors = set(rng.sample(range(1000), 200 if dense else 1))
            buf = bytearray()
            for pos in range(1000):
                error = pos in errors
                level = 'ERROR' if error else 'INFO'
                message = ('database timeout' if error else 'request completed') + ' id=' + str(counts['total']) + ' ' + 'x' * 80
                line = json.dumps({'ts': stamp, 'level': level, 'msg': message}, separators=(',', ':')) if fmt == 'jsonl' else f'{stamp} [{level}] {message}'
                buf.extend((line + '\n').encode())
                counts['total'] += 1
                counts['errors'] += int(error)
            out.write(buf)
            digest.update(buf)
            size += len(buf)
    return dict(counts, bytes=size, sha256=digest.hexdigest())


def run(command, stdout, stderr):
    started = time.perf_counter()
    pid = os.fork()
    if pid == 0:
        try:
            with open(stdout, 'wb') as out, open(stderr, 'wb') as err:
                os.dup2(out.fileno(), 1)
                os.dup2(err.fileno(), 2)
                os.execv(command[0], command)
        except BaseException:
            os._exit(127)
    _, status, usage = os.wait4(pid, 0)
    elapsed = time.perf_counter() - started
    if os.waitstatus_to_exitcode(status) != 0:
        raise RuntimeError(Path(stderr).read_text())
    # Darwin reports bytes; Linux reports KiB. This is the individual child peak.
    rss = usage.ru_maxrss / (1048576 if sys.platform == 'darwin' else 1024)
    return {'seconds': elapsed, 'peak_rss_mib': rss, 'user_seconds': usage.ru_utime, 'system_seconds': usage.ru_stime}


def hardware():
    if sys.platform == 'darwin':
        def sysctl(key):
            return subprocess.check_output(['sysctl', '-n', key], text=True).strip()
        return {'cpu': sysctl('machdep.cpu.brand_string'), 'ram_bytes': int(sysctl('hw.memsize'))}
    info = Path('/proc/cpuinfo').read_text()
    cpu = next((line.split(':', 1)[1].strip() for line in info.splitlines() if line.startswith('model name')), platform.processor())
    return {'cpu': cpu, 'ram': Path('/proc/meminfo').read_text().splitlines()[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes', default='10,100,500', help='nominal MiB workload labels')
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--seed', type=int, default=20261029)
    parser.add_argument('--binary', default='bin/moonlog')
    parser.add_argument('--output', default='benchmarks/latest.json')
    args = parser.parse_args()
    sizes = [int(x) for x in args.sizes.split(',')]
    if args.runs < 1 or any(x < 1 for x in sizes):
        parser.error('sizes and runs must be positive')
    binary = Path(args.binary).resolve()
    result = {'environment': {'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version(), 'cpu_count': os.cpu_count(), 'hardware': hardware(), 'measured_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'moon': subprocess.check_output(['moon', 'version', '--all'], text=True), 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}, 'seed': args.seed, 'runs': args.runs, 'warmups': 1, 'scope': 'end-to-end CLI: process startup, two input scans, JSON write and terminal summary; warm OS cache, generation and verification excluded; RSS is per-child OS high-water mark', 'cases': []}
    with tempfile.TemporaryDirectory(prefix='moonlog-bench-') as tmp:
        tmp = Path(tmp)
        for size in sizes:
            for fmt in ('text', 'jsonl'):
                for dense in (False, True):
                    name = f'{fmt}-{size}MiB-' + ('dense' if dense else 'sparse')
                    source = tmp / 'input.log'
                    expected = generate(source, size, fmt, dense, args.seed)
                    case = {'name': name, 'nominal_mib': size, 'format': fmt, 'errors_per_1000': 200 if dense else 1, 'expected': expected, 'samples': []}
                    for iteration in range(args.runs + 1):
                        report = tmp / 'report.json'
                        report.unlink(missing_ok=True)
                        command = [str(binary), 'analyze', str(source), '--report', str(report), '--format', 'json', '--context', '10', '--max-samples', '20']
                        measurement = run(command, tmp / 'stdout', tmp / 'stderr')
                        data = json.loads(report.read_text())
                        summary = data['summary']
                        for key, value in [('total', expected['total']), ('matched', expected['total']), ('errors', expected['errors']), ('untimed', 0)]:
                            if int(summary[key]) != value:
                                raise AssertionError(f'{name}: {key}: {summary[key]} != {value}')
                        if int(data['level_counts'].get('ERROR', 0)) != expected['errors']:
                            raise AssertionError(f'{name}: level count mismatch')
                        ratio = summary['log_error_ratio']
                        if int(ratio['total']) != expected['total'] or int(ratio['errors']) != expected['errors']:
                            raise AssertionError(f'{name}: ratio denominator/numerator mismatch')
                        measurement['mib_per_second'] = expected['bytes'] / 1048576 / measurement['seconds']
                        if iteration:
                            case['samples'].append(measurement)
                    case['median_seconds'] = statistics.median(x['seconds'] for x in case['samples'])
                    case['median_mib_per_second'] = statistics.median(x['mib_per_second'] for x in case['samples'])
                    case['max_peak_rss_mib'] = max(x['peak_rss_mib'] for x in case['samples'])
                    result['cases'].append(case)
                    print(f"{name}: {expected['bytes']/1048576:.1f} MiB, {case['median_seconds']:.3f}s, {case['median_mib_per_second']:.1f} MiB/s, peak {case['max_peak_rss_mib']:.1f} MiB", flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    rows = ['# CLI benchmark', '', result['scope'], '', '| Case | Actual MiB | Lines | Median s | MiB/s | Max peak RSS MiB |', '|---|---:|---:|---:|---:|---:|']
    for c in result['cases']:
        rows.append(f"| {c['name']} | {c['expected']['bytes']/1048576:.1f} | {c['expected']['total']} | {c['median_seconds']:.3f} | {c['median_mib_per_second']:.1f} | {c['max_peak_rss_mib']:.1f} |")
    rows.extend(['', f"{args.runs} measured runs + 1 warmup per case. Seed: {args.seed}.", '', 'Environment:', '```', json.dumps(result['environment'], indent=2), '```', '', 'Synthetic workloads only; no JS comparison, no browser performance claim, no constant-memory claim. Nominal sizes are labels; use actual bytes for throughput.'])
    output.with_suffix('.md').write_text('\n'.join(rows) + '\n')


if __name__ == '__main__':
    main()
