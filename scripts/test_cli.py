#!/usr/bin/env python3
"""Black-box acceptance tests against the real native executable; stdlib only."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1) if len(sys.argv) > 1 else 'bin/moonlog').resolve()
ROOT = Path(__file__).resolve().parent.parent


class CLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='moonlog-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'input.log'
        self.report = self.root / 'report.md'

    def run_cli(self, *options, ok=True):
        result = subprocess.run([str(BINARY), *map(str, options)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def analyze(self, *options, ok=True):
        return self.run_cli('analyze', self.source, '--report', self.report, *options, ok=ok)

    def test_help_and_invalid_arguments(self):
        self.assertIn('offline incident', self.run_cli('--help').stdout)
        self.assertIn('0.1.0', self.run_cli('--version').stdout)
        self.run_cli(ok=False)
        self.run_cli('unknown', ok=False)
        self.source.write_text('', encoding='utf8')
        for args in [('--context', 'bad'), ('--context', '-1'),
                     ('--bucket-minutes', '0'), ('--unknown', 'value'),
                     ('--level', 'oops'), ('--from', 'not-a-date'),
                     ('--context', '1', '--context', '2'),
                     ('--from', '2026-10-29 00:00:00', '--to', '2026-10-28 00:00:00')]:
            with self.subTest(args=args):
                self.analyze(*args, ok=False)
                self.assertFalse(self.report.exists())

    def test_fixture_spike_context_and_determinism(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        self.analyze('--context', '2')
        report = self.report.read_text()
        self.assertIn('- Lines scanned: 30\n', report)
        self.assertIn('- Detected spikes: 1\n', report)
        self.assertIn('| 2026-10-28 08:30:00Z | 2026-10-28 08:35:00Z | 4 |', report)
        self.assertIn('Target source lines: 23, 24, 25, 26.', report)
        self.assertIn('  21:', report)
        self.assertIn('  28:', report)
        self.assertNotIn('  20:', report)
        self.assertNotIn('  29:', report)
        second = self.root / 'second.md'
        self.run_cli('analyze', self.source, '--report', second, '--context', '2')
        self.assertEqual(report, second.read_text())

    def test_jsonl_unicode_crlf_bom_and_final_line_without_newline(self):
        rows = [json.dumps({'ts': '2026-10-28T08:00:00Z', 'level': 'INFO', 'msg': '服务正常'}, ensure_ascii=False)]
        rows += [json.dumps({'ts': '2026-10-28T08:30:00Z', 'level': 'ERROR', 'msg': '连接超时'}, ensure_ascii=False)] * 3
        self.source.write_bytes(b'\xef\xbb\xbf' + '\r\n'.join(rows).encode())
        self.analyze()
        report = self.report.read_text()
        self.assertIn('- Lines scanned: 4\n', report)
        self.assertIn('- Detected spikes: 1\n', report)
        self.assertIn('连接超时', report)
        self.assertNotIn('\ufffd', report)

    def test_10000_lines(self):
        with self.source.open('w') as out:
            for i in range(10000):
                out.write(f'2026-10-28 08:00:00 [INFO] message-{i}\n')
        self.analyze()
        report = self.report.read_text()
        self.assertIn('- Lines scanned: 10000\n', report)
        self.assertIn('| INFO | 10000 |', report)

    def test_utf8_character_split_across_read_chunks(self):
        # First byte of the multibyte character is the last byte in a 64 KiB chunk.
        data = b'x' * 65535 + '中'.encode() + b'\n2026-10-28 08:00:00 [INFO] ready\n'
        self.source.write_bytes(data)
        self.analyze('--max-line-bytes', '100000')
        report = self.report.read_text()
        self.assertIn('- Lines scanned: 2\n', report)
        self.assertIn('| INFO | 1 |', report)

    def test_long_line_and_invalid_utf8_fail_without_report(self):
        self.source.write_bytes(b'x' * 65537 + b'\n')
        self.assertIn('exceeds --max-line-bytes', self.analyze(ok=False).stderr)
        self.assertFalse(self.report.exists())
        self.source.write_bytes(b'\xff\n')
        self.assertIn('invalid UTF-8', self.analyze(ok=False).stderr)
        self.assertFalse(self.report.exists())

    def test_reports_and_input_aliases_are_not_overwritten(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n')
        original = self.source.read_bytes()
        self.run_cli('analyze', self.source, '--report', self.source, ok=False)
        self.report.write_text('KEEP')
        self.analyze(ok=False)
        self.assertEqual(self.report.read_text(), 'KEEP')
        self.report.unlink()
        self.report.symlink_to(self.source)
        self.analyze(ok=False)
        self.report.unlink()
        os.link(self.source, self.report)
        self.analyze(ok=False)
        self.assertEqual(self.source.read_bytes(), original)

    def test_missing_input_and_directory_fail(self):
        self.analyze(ok=False)
        self.run_cli('analyze', self.root, '--report', self.report, ok=False)
        self.assertFalse(self.report.exists())

    def test_filters_apply_to_report_and_context(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        self.analyze('--level', 'INFO', '--keyword', 'health')
        report = self.report.read_text()
        self.assertIn('- ERROR + FATAL: 0\n', report)
        self.assertIn('- Detected spikes: 0\n', report)
        self.assertNotIn('database timeout', report)

    def test_error_filter_does_not_remove_healthy_baseline(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        self.analyze('--level', 'ERROR', '--keyword', 'timeout')
        report = self.report.read_text()
        self.assertIn('- Lines matching filters: 4\n', report)
        self.assertIn('- Detected spikes: 1\n', report)
        self.assertIn('| INFO | 0 |', report)

    def test_empty_file_and_newline_counts(self):
        self.source.write_bytes(b'')
        self.analyze()
        self.assertIn('- Lines scanned: 0\n', self.report.read_text())
        self.report.unlink()
        self.source.write_bytes(b'\n\n')
        self.analyze()
        self.assertIn('- Lines scanned: 2\n', self.report.read_text())

    def test_bucket_span_limit(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] a\n2026-10-28 09:00:00 [INFO] b\n')
        self.assertIn('exceeds max buckets', self.analyze('--max-buckets', '2', ok=False).stderr)
        self.assertFalse(self.report.exists())


if __name__ == '__main__':
    unittest.main()
