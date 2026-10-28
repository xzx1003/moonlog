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

    def spike_sections(self, report):
        block = report.split('## Error signatures by spike\n', 1)[1]
        block = block.split('## Top error signatures', 1)[0]
        sections = {}
        for piece in block.split('### Spike ')[1:]:
            number, body = piece.split(':', 1)
            sections[int(number)] = body
        return sections

    def test_help_and_invalid_arguments(self):
        self.assertIn('offline incident', self.run_cli('--help').stdout)
        self.assertIn('0.1.0', self.run_cli('--version').stdout)
        self.run_cli(ok=False)
        self.run_cli('unknown', ok=False)
        self.source.write_text('', encoding='utf8')
        for args in [('--context', 'bad'), ('--context', '-1'),
                     ('--bucket-minutes', '0'), ('--unknown', 'value'),
                     ('--level', 'oops'), ('--from', 'not-a-date'),
                     ('--context-mode', 'oops'), ('--context-mode',),
                     ('--context-mode', 'errors', '--context-mode', 'spikes'),
                     ('--context', '1', '--context', '2'),
                     ('--from', '2026-10-29 00:00:00', '--to', '2026-10-28 00:00:00')]:
            with self.subTest(args=args):
                self.analyze(*args, ok=False)
                self.assertFalse(self.report.exists())

    def test_analyze_help(self):
        result = self.run_cli('analyze', '--help')
        self.assertIn('Usage: moonlog analyze', result.stdout)
        self.assertEqual(result.stderr, '')

    def test_analyze_help_lists_context_mode(self):
        result = self.run_cli('analyze', '--help')
        self.assertIn('--context-mode MODE', result.stdout)
        result = self.run_cli('--help')
        self.assertIn('--context-mode MODE', result.stdout)

    def test_cli_errors_hide_internal_failure_wrapper(self):
        for args in [(), ('analyze',),
                     ('analyze', self.root / 'missing.log', '--report', self.report)]:
            with self.subTest(args=args):
                result = self.run_cli(*args, ok=False)
                self.assertTrue(result.stderr.startswith('moonlog: '), result.stderr)
                for marker in ('Failure(', '.mbt:', 'FAILED:'):
                    self.assertNotIn(marker, result.stderr)
        self.assertFalse(self.report.exists())

    def test_other_level_is_accepted(self):
        self.source.write_text('2026-10-28 08:00:00 [OTHER] noise\n', encoding='utf8')
        self.analyze('--level', 'OTHER')
        report = self.report.read_text()
        self.assertIn('- Lines matching filters: 1\n', report)
        self.assertIn('| OTHER | 1 |', report)

    def test_signature_length_cap_is_message_only(self):
        self.source.write_text(
            json.dumps({'ts': 'bad', 'level': 'ERROR', 'msg': 'a' * 600}) + '\n',
            encoding='utf8',
        )
        self.analyze('--max-samples', '0')
        report = self.report.read_text()
        self.assertIn('message portion is capped at 512', report)
        rows = [line for line in report.splitlines() if line.startswith('| ERROR: ')]
        self.assertEqual(len(rows), 1)
        signature = rows[0].strip('|').split('|')[0].strip()
        self.assertEqual(signature, 'ERROR: ' + 'a' * 512)
        self.assertEqual(len(signature), 519)

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

    def test_default_context_mode_matches_explicit_spikes(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        self.analyze('--context', '2')
        default = self.report.read_text()
        second = self.root / 'second.md'
        self.run_cli('analyze', self.source, '--report', second,
                     '--context', '2', '--context-mode', 'spikes')
        self.assertEqual(default, second.read_text())
        self.assertIn('- Context mode: spikes', default)

    def test_errors_context_mode_samples_errors_without_spikes(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] before\n'
            '2026-10-28 08:01:00 [ERROR] failed\n'
            'stack frame without timestamp\n'
            '2026-10-28 08:02:00 [INFO] after\n',
            encoding='utf8',
        )
        self.analyze('--context-mode', 'errors', '--context', '1')
        report = self.report.read_text()
        self.assertIn('- Detected spikes: 0\n', report)
        self.assertIn('- Context mode: errors', report)
        self.assertIn('- Context targets sampled: 1 (limit 20); omitted: 0', report)
        self.assertIn('Error context is still collected', report)
        self.assertIn('Target source lines: 2.', report)
        self.assertIn('  1: 2026-10-28 08:00:00 [INFO] before', report)
        self.assertIn('> 2: 2026-10-28 08:01:00 [ERROR] failed', report)
        self.assertIn('  3: stack frame without timestamp', report)
        self.assertNotIn('No sampled', report)

    def test_errors_context_mode_does_not_change_spike_ranking(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        self.analyze('--context-mode', 'errors', '--context', '0')
        report = self.report.read_text()
        sections = self.spike_sections(report)
        self.assertIn('| ERROR: database timeout retry=\\# | 4 |', sections[1])
        self.assertIn('- Context targets sampled: 4 (limit 20); omitted: 0', report)

    def test_errors_context_mode_applies_filters_and_accepts_untimed_json(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] before\n'
            '2026-10-28 08:00:00 [ERROR] keep this\n'
            '2026-10-28 08:00:00 [ERROR] discard\n'
            '2026-10-28 08:00:00 [INFO] after\n'
            '{"ts":"bad","level":"ERROR","msg":"keep untimed"}\n',
            encoding='utf8',
        )
        self.analyze('--context-mode', 'errors', '--context', '1',
                     '--level', 'ERROR', '--keyword', 'keep',
                     '--from', '2026-10-28 08:00:00',
                     '--to', '2026-10-28 08:00:00')
        report = self.report.read_text()
        self.assertIn('- Lines matching filters: 1\n', report)
        self.assertIn('- Context targets sampled: 1 (limit 20); omitted: 0', report)
        self.assertIn('Target source lines: 2.', report)
        self.assertIn('  1: 2026-10-28 08:00:00 [INFO] before', report)
        self.assertIn('> 2: 2026-10-28 08:00:00 [ERROR] keep this', report)
        self.assertIn('  3: 2026-10-28 08:00:00 [ERROR] discard', report)
        self.assertNotIn('keep untimed', report)

        self.report.unlink()
        self.analyze('--context-mode', 'errors', '--context', '0',
                     '--keyword', 'keep')
        report = self.report.read_text()
        self.assertIn('- Context targets sampled: 2 (limit 20); omitted: 0', report)
        self.assertIn('Target source lines: 2.', report)
        self.assertIn('Target source lines: 5.', report)
        self.assertIn('> 5: {"ts":"bad","level":"ERROR","msg":"keep untimed"}', report)

    def test_spike_signatures_rank_separately_and_exclude_baseline(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] healthy\n'
            '2026-10-28 08:00:00 [ERROR] baseline noise\n'
            '2026-10-28 08:05:00 [ERROR] alpha\n'
            '2026-10-28 08:05:00 [ERROR] alpha\n'
            '2026-10-28 08:05:00 [ERROR] beta\n'
            '2026-10-28 08:10:00 [INFO] healthy\n'
            '2026-10-28 08:10:00 [ERROR] baseline noise\n'
            '2026-10-28 08:15:00 [ERROR] gamma\n'
            '2026-10-28 08:15:00 [ERROR] gamma\n'
            '2026-10-28 08:15:00 [ERROR] delta\n',
            encoding='utf8',
        )
        self.analyze('--baseline-buckets', '1', '--multiplier', '2',
                     '--min-errors', '2', '--context', '0', '--max-samples', '0')
        report = self.report.read_text()
        self.assertIn('- Detected spikes: 2\n', report)
        sections = self.spike_sections(report)
        self.assertEqual(sorted(sections), [1, 2])
        first, second = sections[1], sections[2]
        self.assertIn('| ERROR: alpha | 2 |', first)
        self.assertIn('| ERROR: beta | 1 |', first)
        for text in ('gamma', 'delta', 'baseline noise'):
            self.assertNotIn(text, first)
        self.assertIn('| ERROR: gamma | 2 |', second)
        self.assertIn('| ERROR: delta | 1 |', second)
        for text in ('alpha', 'beta', 'baseline noise'):
            self.assertNotIn(text, second)
        global_ranking = report.split('## Top error signatures', 1)[1]
        self.assertIn('| ERROR: baseline noise | 2 |', global_ranking)

    def test_spike_signature_capacity_omissions_are_reported_per_spike(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] healthy\n'
            '2026-10-28 08:05:00 [ERROR] alpha\n'
            '2026-10-28 08:05:00 [ERROR] beta\n'
            '2026-10-28 08:05:00 [ERROR] alpha\n'
            '2026-10-28 08:10:00 [INFO] healthy\n'
            '2026-10-28 08:15:00 [ERROR] alpha\n'
            '2026-10-28 08:15:00 [ERROR] alpha\n'
            '2026-10-28 08:15:00 [ERROR] alpha\n',
            encoding='utf8',
        )
        self.analyze('--baseline-buckets', '1', '--multiplier', '2',
                     '--min-errors', '2', '--max-signatures', '1',
                     '--context', '0', '--max-samples', '0')
        sections = self.spike_sections(self.report.read_text())
        first, second = sections[1], sections[2]
        self.assertIn('| ERROR: alpha | 2 |', first)
        self.assertNotIn('| ERROR: beta |', first)
        self.assertIn('1 error occurrence(s) were omitted', first)
        self.assertNotIn('| ERROR: alpha |', second)
        self.assertIn('No signatures were retained for this spike.', second)
        self.assertIn('does not mean the spike had no errors', second)
        self.assertIn('3 error occurrence(s) were dropped', second)
        self.assertNotIn('Showing the top 10', second)

    def test_spike_signature_table_limits_display_to_top_ten(self):
        lines = ['2026-10-28 08:00:00 [INFO] healthy']
        lines += [f'2026-10-28 08:05:00 [ERROR] sig-{name}' for name in 'abcdefghijkl']
        self.source.write_text('\n'.join(lines) + '\n', encoding='utf8')
        self.analyze('--baseline-buckets', '1', '--multiplier', '2',
                     '--min-errors', '2', '--context', '0', '--max-samples', '0')
        section = self.spike_sections(self.report.read_text())[1]
        rows = [line for line in section.splitlines() if line.startswith('| ERROR: ')]
        self.assertEqual(len(rows), 10)
        self.assertIn('| ERROR: sig-j | 1 |', rows)
        self.assertNotIn('| ERROR: sig-k |', section)
        self.assertIn('Showing the top 10 of 12 retained signatures', section)
        self.assertIn('not by capacity', section)
        self.assertNotIn('were omitted after the shared signature capacity', section)

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
