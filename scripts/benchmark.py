#!/usr/bin/env python3
"""Generate a bounded-memory workload and measure the release CLI (no third-party libs)."""
from pathlib import Path
import argparse
import json
import platform
import subprocess
import tempfile
import time

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--lines', type=int, default=500_000)
args = parser.parse_args()
if args.lines < 80:
    parser.error('--lines must be at least 80')
with tempfile.TemporaryDirectory(prefix='moonlog-benchmark-') as temp:
    directory = Path(temp)
    source = directory / 'load.log'
    report = directory / 'report.md'
    with source.open('w', encoding='utf8') as out:
        for i in range(args.lines):
            bucket = min(7, i * 8 // args.lines)
            minute = bucket * 5
            error = i % 1000 < (10 if bucket == 6 else 1)
            level = 'ERROR' if error else 'INFO'
            out.write(f'2026-10-28 08:{minute:02}:00 [{level}] request failed retry={i} ' + 'x' * 70 + '\n')
    binary = root / 'bin/moonlog'
    command = [str(binary), 'analyze', str(source), '--report', str(report)]
    if platform.system() == 'Darwin':
        command = ['/usr/bin/time', '-l', *command]
    start = time.monotonic()
    result = subprocess.run(command, text=True, capture_output=True, check=True, timeout=120)
    elapsed = time.monotonic() - start
    rss = None
    for line in result.stderr.splitlines():
        if 'maximum resident set size' in line:
            rss = int(line.split()[0])
    print(json.dumps({'platform': platform.platform(), 'lines': args.lines,
                      'input_bytes': source.stat().st_size, 'elapsed_seconds': round(elapsed, 3),
                      'peak_rss_bytes_macos': rss, 'report_bytes': report.stat().st_size,
                      'cli': result.stdout.strip()}, ensure_ascii=False, indent=2))
