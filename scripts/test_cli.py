#!/usr/bin/env python3
"""Black-box acceptance tests against the real native executable; stdlib only."""
from pathlib import Path
from decimal import Decimal
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1) if len(sys.argv) > 1 else 'bin/moonlog').resolve()
ROOT = Path(__file__).resolve().parent.parent

RATIO_LINE = re.compile(
    r'^Log error ratio \(all observed lines\): (\S+) \((\d+)/(\d+)\)\.$')
SPIKE_RATIO_LINE = re.compile(r'^  Log error ratio: (\S+) \((\d+)/(\d+)\)\.$')
TERMINAL_WINDOW = re.compile(
    r'^(\S+ \S+) to (\S+ \S+) \(end exclusive\); (\d+) min; '
    r'(\d+) occurrence\(s\); (\d+\.\d{3}) per minute\.$')
TERMINAL_MULTIPLIER = re.compile(r'^(\d+\.\d{2}x)\.$')


def percent(fraction):
    """One-decimal display percentage, half-up, matching the CLI's format_ratio."""
    if fraction is None:
        return 'N/A'
    tenths = int(Decimal(fraction) * 1000 + Decimal('0.5'))
    return f'{tenths // 10}.{tenths % 10}%'


def per_minute(value):
    """Three-decimal per-minute rate, half-up, matching the CLI's format_per_minute."""
    thousandths = int(Decimal(value) * 1000 + Decimal('0.5'))
    return f'{thousandths // 1000}.{thousandths % 1000:03d}'


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

    def analyze_to(self, report, *options, ok=True):
        return self.run_cli('analyze', self.source, '--report', report, *options, ok=ok)

    def report_summary(self, stdout):
        """Terminal summary without its last line, which names the format and path."""
        lines = stdout.splitlines()
        self.assertTrue(lines, 'terminal summary missing')
        self.assertTrue(stdout.endswith('\n'))
        self.assertFalse(stdout.endswith('\n\n'))
        return lines[:-1]

    def table_rows(self, report, heading):
        block = report.split(heading + '\n', 1)[1].split('\n\n', 1)[0]
        return [[cell.strip() for cell in row.strip('|').split('|')]
                for row in block.splitlines() if row.startswith('|')][2:]

    def markdown_total_ratio(self, report):
        row = self.table_rows(report, '### All observed lines')[0]
        return int(row[0]), int(row[1]), row[2]

    def markdown_spike_ratios(self, report):
        return [(int(row[0]), row[1], row[2], int(row[3]), int(row[4]), row[5])
                for row in self.table_rows(report, '### By spike')]

    def markdown_bucket_ratios(self, report):
        return [(row[0], row[1], int(row[2]), int(row[3]), row[4])
                for row in self.table_rows(report, '### By observation bucket')]

    def terminal_ratio(self, stdout):
        for line in stdout.splitlines():
            if RATIO_LINE.match(line):
                return int(RATIO_LINE.match(line).group(2)), \
                    int(RATIO_LINE.match(line).group(3)), \
                    RATIO_LINE.match(line).group(1)
        self.fail(f'no overall ratio line in: {stdout}')

    def terminal_spike_ratios(self, stdout):
        return [(int(m.group(2)), int(m.group(3)), m.group(1))
                for m in (SPIKE_RATIO_LINE.match(line) for line in stdout.splitlines())
                if m]

    def spike_sections(self, report):
        block = report.split('## Error signatures by spike\n', 1)[1]
        block = block.split('## Top error signatures', 1)[0]
        sections = {}
        for piece in block.split('### Spike ')[1:]:
            number, body = piece.split(':', 1)
            sections[int(number)] = body
        return sections

    def comparison_section(self, report):
        block = report.split('## Selected signature comparison\n', 1)[1]
        return block.split('\n## ', 1)[0]

    def comparison_windows(self, report):
        """[(spike index, 'baseline'|'spike', start, end, minutes, count, rate)]."""
        rows = []
        index = None
        for line in self.comparison_section(report).splitlines():
            heading = re.match(r'^### Spike (\d+): ', line)
            if heading:
                index = int(heading.group(1))
                continue
            cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
            if line.startswith('| Pre-spike baseline |'):
                rows.append((index, 'baseline', cells[1], cells[2], int(cells[3]),
                             int(cells[4]), cells[5]))
            elif line.startswith('| Spike |'):
                rows.append((index, 'spike', cells[1], cells[2], int(cells[3]),
                             int(cells[4]), cells[5]))
        return rows

    def comparison_spikes(self, report):
        return [tuple(re.match(r'^### Spike (\d+): (\S+ \S+) to (\S+ \S+)$',
                               line).groups())
                for line in self.comparison_section(report).splitlines()
                if line.startswith('### Spike ')]

    def terminal_comparisons(self, stdout):
        """{spike index: {'baseline': (start, end, minutes, count, rate), ...}}."""
        found = {}
        for line in stdout.splitlines():
            if not line.startswith('  Spike '):
                continue
            head, _, rest = line.partition(': ')
            parts = head.split()
            if len(parts) < 3 or not parts[1].isdigit():
                continue
            entry = found.setdefault(int(parts[1]), {})
            if parts[2] in ('baseline', 'spike'):
                match = TERMINAL_WINDOW.match(rest)
                self.assertIsNotNone(match, line)
                entry[parts[2]] = (match.group(1), match.group(2),
                                   int(match.group(3)), int(match.group(4)),
                                   match.group(5))
            elif parts[2] == 'rate':
                entry['rate'] = rest
        return found

    def signature_log(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] healthy\n'
            '2026-10-28 08:00:00 [ERROR] sig 1\n'
            '2026-10-28 08:05:00 [ERROR] sig 2\n'
            '2026-10-28 08:10:00 [ERROR] sig 3\n'
            '2026-10-28 08:10:00 [ERROR] sig 4\n'
            '2026-10-28 08:10:00 [ERROR] other 9\n'
            '2026-10-28 08:20:00 [ERROR] sig 5\n'
            '2026-10-28 08:25:00 [ERROR] sig 6\n'
            '2026-10-28 08:30:00 [ERROR] sig 7\n'
            '2026-10-28 08:30:00 [ERROR] sig 8\n',
            encoding='utf8',
        )

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

    def test_help_documents_format_and_json_limits(self):
        for args in [('--help',), ('analyze', '--help')]:
            with self.subTest(args=args):
                text = self.run_cli(*args).stdout
                self.assertIn('--format FORMAT', text)
                self.assertIn('markdown or json (default markdown)', text)
                self.assertIn('JSON keeps raw context lines', text)
                self.assertIn('not part of the core result config', text)

    def test_default_format_is_markdown_and_matches_explicit_markdown(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        default = self.analyze('--context', '2')
        markdown = self.report.read_text()
        self.assertIn('Markdown report written to', default.stdout)
        self.report.unlink()
        explicit = self.analyze('--format', 'markdown', '--context', '2')
        self.assertEqual(markdown, self.report.read_text())
        self.assertEqual(self.report_summary(default.stdout),
                         self.report_summary(explicit.stdout))

    def test_json_report_is_parseable_and_covers_schema_fields(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        result = self.analyze('--format', 'json', '--context', '2')
        text = self.report.read_text()
        self.assertIn('JSON report written to', result.stdout)
        self.assertTrue(text.startswith('{'), text[:40])
        self.assertTrue(text.rstrip().endswith('}'))
        document = json.loads(text)
        self.assertEqual(document['schema_version'], 1)
        self.assertEqual(document['engine_version'], '0.1.0')
        self.assertEqual(document['source'], str(self.source))
        self.assertIn('UTC', document['time_semantics'])
        self.assertIn('unfiltered original lines', document['diagnostic_note'])
        self.assertEqual(document['config']['context_mode'], 'spikes')
        self.assertEqual(document['config']['max_signatures'], 1000)
        self.assertNotIn('max_line_bytes', document['config'])
        self.assertEqual(sorted(document['level_counts']),
                         ['DEBUG', 'ERROR', 'FATAL', 'INFO', 'OTHER', 'WARN'])
        self.assertEqual(document['filter']['keyword'], '')
        self.assertIsNone(document['filter']['from_inclusive'])
        summary = document['summary']
        self.assertEqual(
            (summary['total'], summary['matched'], summary['untimed'],
             summary['errors'], summary['spike_count']), (30, 30, 0, 4, 1))
        self.assertEqual(
            (summary['sampled_targets'], summary['omitted_targets'],
             summary['omitted_global_signature_occurrences']), (4, 0, 0))
        bucket = document['buckets'][0]
        self.assertEqual(sorted(bucket), ['end_exclusive', 'errors', 'start', 'total'])
        spike = document['spikes'][0]
        self.assertEqual(spike['start'], '2026-10-28 08:30:00Z')
        self.assertEqual(spike['end_exclusive'], '2026-10-28 08:35:00Z')
        self.assertEqual(spike['errors'], 4)
        self.assertEqual(spike['signatures'],
                         [{'text': 'ERROR: database timeout retry=#', 'count': 4}])
        self.assertEqual(spike['omitted_signature_occurrences'], 0)
        window = document['context_windows'][0]
        self.assertEqual(window['targets'], [23, 24, 25, 26])
        self.assertEqual(sorted(window['lines'][0]), ['number', 'text'])

    def test_both_formats_report_identical_statistics(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        json_path = self.root / 'report.json'
        markdown_run = self.analyze('--context', '2')
        markdown = self.report.read_text()
        json_run = self.analyze_to(json_path, '--format', 'json', '--context', '2')
        document = json.loads(json_path.read_text())
        summary = document['summary']
        for expected in [
            f"- Lines scanned: {summary['total']}\n",
            f"- Lines matching filters: {summary['matched']}\n",
            f"- ERROR + FATAL: {summary['errors']}\n",
            f"- Detected spikes: {summary['spike_count']}\n",
            f"- Context targets sampled: {summary['sampled_targets']} (limit 20); "
            f"omitted: {summary['omitted_targets']}\n",
        ]:
            self.assertIn(expected, markdown)
        spike_block = markdown.split('## Detected spikes\n', 1)[1].split('\n## ', 1)[0]
        spike_rows = [line for line in spike_block.splitlines() if line.startswith('| 2026-')]
        self.assertEqual(len(spike_rows), summary['spike_count'])
        for row, spike in zip(spike_rows, document['spikes']):
            self.assertIn(spike['start'], row)
            self.assertIn(spike['end_exclusive'], row)
            self.assertIn(f"| {spike['errors']} |", row)
        self.assertEqual(self.report_summary(markdown_run.stdout),
                         self.report_summary(json_run.stdout))

    def test_empty_input_in_both_formats(self):
        self.source.write_bytes(b'')
        self.analyze()
        self.assertIn('- Lines scanned: 0\n', self.report.read_text())
        self.report.unlink()
        result = self.analyze('--format', 'json')
        document = json.loads(self.report.read_text())
        self.assertEqual(document['summary']['total'], 0)
        for key in ['spikes', 'buckets', 'context_windows', 'signatures']:
            self.assertEqual(document[key], [])
        self.assertIn('No spikes met the rule; this does not imply the service was healthy.',
                      result.stdout)

    def test_json_errors_mode_samples_errors_without_spikes(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] before\n'
            '2026-10-28 08:01:00 [ERROR] failed\n'
            'stack frame without timestamp\n'
            '2026-10-28 08:02:00 [INFO] after\n',
            encoding='utf8',
        )
        result = self.analyze('--format', 'json', '--context-mode', 'errors', '--context', '1')
        document = json.loads(self.report.read_text())
        self.assertEqual(document['config']['context_mode'], 'errors')
        self.assertEqual(document['spikes'], [])
        self.assertEqual(document['summary']['spike_count'], 0)
        self.assertEqual(document['summary']['sampled_targets'], 1)
        window = document['context_windows'][0]
        self.assertEqual(window['targets'], [2])
        self.assertEqual([line['number'] for line in window['lines']], [1, 2, 3])
        self.assertEqual(window['lines'][2]['text'], 'stack frame without timestamp')
        self.assertIn('Context mode: errors; sampled 1; omitted 0.', result.stdout)
        self.assertIn('does not imply the service was healthy', result.stdout)

    def test_json_reports_signature_capacity_omissions(self):
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
        result = self.analyze('--format', 'json', '--baseline-buckets', '1',
                              '--multiplier', '2', '--min-errors', '2',
                              '--max-signatures', '1', '--context', '0',
                              '--max-samples', '0')
        document = json.loads(self.report.read_text())
        first, second = document['spikes']
        self.assertEqual(first['signatures'], [{'text': 'ERROR: alpha', 'count': 2}])
        self.assertEqual(first['omitted_signature_occurrences'], 1)
        self.assertEqual(second['signatures'], [])
        self.assertEqual(second['omitted_signature_occurrences'], 3)
        self.assertEqual(second['errors'], 3)
        self.assertIn('1 occurrence(s) were omitted after the shared signature capacity limit',
                      result.stdout)
        self.assertIn('No signature retained; all 3 error occurrence(s) were dropped',
                      result.stdout)
        self.assertIn('not error-free', result.stdout)

    def test_terminal_shows_three_signatures_and_labels_display_limit(self):
        lines = ['2026-10-28 08:00:00 [INFO] healthy']
        lines += [f'2026-10-28 08:05:00 [ERROR] sig-{name}' for name in 'abcdefghijkl']
        self.source.write_text('\n'.join(lines) + '\n', encoding='utf8')
        result = self.analyze('--format', 'json', '--baseline-buckets', '1',
                              '--min-errors', '2', '--context', '0', '--max-samples', '0')
        document = json.loads(self.report.read_text())
        self.assertEqual(len(document['spikes'][0]['signatures']), 12)
        top = [line for line in self.report_summary(result.stdout)
               if line.startswith('  Top signatures (3):')]
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].count(' (1)'), 3)
        self.assertIn(
            'Showing the top 3 of 12 retained signatures; the other 9 are hidden '
            'by this display limit, not by capacity omissions.', result.stdout)

    def test_invalid_or_missing_format_fails_before_writing(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n', encoding='utf8')
        cases = [
            (('--format', 'xml'), 'unknown format: xml'),
            (('--format', 'JSON'), 'unknown format: JSON'),
            (('--format', ''), 'unknown format: '),
            (('--format',), 'missing value for --format'),
            (('--format', 'json', '--format', 'markdown'), 'duplicate option: --format'),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.analyze(*args, ok=False)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.report.exists())

    def test_json_report_never_overwrites_existing_file(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n', encoding='utf8')
        self.report.write_text('KEEP', encoding='utf8')
        result = self.analyze('--format', 'json', ok=False)
        self.assertIn('existing files are never overwritten', result.stderr)
        self.assertEqual(self.report.read_text(), 'KEEP')
        self.assertEqual(result.stdout, '')

    def test_terminal_summary_escapes_control_characters(self):
        payload = 'pwn\u001b[2J\u001b]0;spoof\u0007'
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] healthy\n'
            + f'2026-10-28 08:05:00 [ERROR] {payload}\n' * 3
            + '2026-10-28 08:05:00 [ERROR] tab\there\rback\n',
            encoding='utf8',
        )
        result = self.analyze('--format', 'json', '--baseline-buckets', '1',
                              '--min-errors', '2', '--context', '0')
        self.assertIn('pwn\\x1b[#J\\x1b]#;spoof\\x07 (3)', result.stdout)
        self.assertIn('tab\\there\\rback', result.stdout)
        for raw in ['\u001b', '\u0007', '\r']:
            self.assertNotIn(raw, result.stdout)
        self.assertEqual(
            len([line for line in result.stdout.splitlines() if line.startswith('Spike 1:')]), 1)
        # JSON keeps the original bytes instead of terminal escaping them.
        texts = [s['text'] for s in json.loads(self.report.read_text())['spikes'][0]['signatures']]
        self.assertTrue(any('\u001b' in text and '\u0007' in text for text in texts), texts)
        self.assertFalse(any('\\x1b' in text for text in texts), texts)

    def test_terminal_summary_escapes_source_path(self):
        weird = self.root / 'in\u001b[31mput.log'
        weird.write_text('2026-10-28 08:00:00 [INFO] ready\n', encoding='utf8')
        report = self.root / 'out.md'
        result = self.run_cli('analyze', weird, '--report', report)
        self.assertIn('Source: ', result.stdout)
        self.assertIn('in\\x1b[31mput.log', result.stdout)
        self.assertNotIn('\u001b', result.stdout)
        self.assertTrue(report.exists())

    def test_diagnostics_never_emit_raw_control_characters(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n', encoding='utf8')
        result = self.analyze('--format', 'js\u001bon', ok=False)
        self.assertIn('unknown format: js\\x1bon', result.stderr)
        self.assertNotIn('\u001b', result.stderr)
        missing = self.root / 'in\u001bput.log'
        result = self.run_cli('analyze', missing, '--report', self.report, ok=False)
        self.assertNotIn('\u001b', result.stderr)
        self.assertIn('in\\x1bput.log', result.stderr)

    def test_json_report_and_terminal_summary_do_not_mix(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        result = self.analyze('--format', 'json', '--context', '2')
        text = self.report.read_text()
        document = json.loads(text)
        self.assertEqual(document['summary']['total'], 30)
        self.assertNotIn('Scanned ', text)
        self.assertNotIn('report written to', text)
        self.assertNotIn('schema_version', result.stdout)
        self.assertFalse([line for line in result.stdout.splitlines() if line.startswith('{')])
        self.assertIn('Spike 1: 2026-10-28 08:30:00Z to 2026-10-28 08:35:00Z (end exclusive); '
                      'errors 4.', result.stdout)


    def test_signature_argument_errors_fail_before_writing(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n', encoding='utf8')
        cases = [
            (('--signature', ''), '--signature must not be empty'),
            (('--signature', '   '), '--signature must not be empty'),
            (('--signature',), 'missing value for --signature'),
            (('--signature', 'ERROR: a', '--signature', 'ERROR: b'),
             'duplicate option: --signature'),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.analyze(*args, ok=False)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.report.exists())

    def test_help_lists_the_signature_option(self):
        for args in [('--help',), ('analyze', '--help')]:
            with self.subTest(args=args):
                text = self.run_cli(*args).stdout
                self.assertIn('--signature SIG', text)
                self.assertIn('ERROR: database timeout retry=#', text)

    def test_signature_matches_the_complete_normalized_signature_only(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        exact = self.analyze(
            '--signature', 'ERROR: database timeout retry=#', '--context', '0')
        report = self.report.read_text()
        self.assertIn('- Context targets sampled: 4 (limit 20); omitted: 0', report)
        self.assertIn('Selected signature: `ERROR: database timeout retry=\\#`',
                      report)
        self.assertIn('  Spike 1 spike: 2026-10-28 08:30:00Z to '
                      '2026-10-28 08:35:00Z (end exclusive); 5 min; '
                      '4 occurrence(s); 0.800 per minute.', exact.stdout)
        self.report.unlink()
        for partial in ['database timeout', 'ERROR: database timeout',
                        'FATAL: database timeout retry=#', 'error: database timeout retry=#']:
            with self.subTest(signature=partial):
                run = self.analyze('--signature', partial, '--context', '0')
                report = self.report.read_text()
                self.assertIn('- Context targets sampled: 0 (limit 20); omitted: 0',
                              report)
                self.assertIn(
                    'The selected signature was not counted inside any of these windows',
                    report)
                self.assertIn('Rate multiplier: N/A', report)
                self.assertIn('  Spike 1 spike: 2026-10-28 08:30:00Z to '
                              '2026-10-28 08:35:00Z (end exclusive); 5 min; '
                              '0 occurrence(s); 0.000 per minute.', run.stdout)
                self.report.unlink()

    def test_signature_limits_errors_mode_context_and_keeps_neighbors(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] before\n'
            '2026-10-28 08:01:00 [ERROR] keep 1\n'
            'stack frame\n'
            '2026-10-28 08:02:00 [INFO] quiet\n'
            '2026-10-28 08:03:00 [ERROR] drop 1\n'
            '2026-10-28 08:04:00 [INFO] quiet\n'
            '2026-10-28 08:08:00 [ERROR] drop 2\n'
            '2026-10-28 08:09:00 [ERROR] keep 2\n'
            '2026-10-28 08:10:00 [INFO] after\n',
            encoding='utf8',
        )
        self.analyze('--context-mode', 'errors', '--context', '1',
                     '--signature', 'ERROR: keep #')
        report = self.report.read_text()
        self.assertIn('- Detected spikes: 0\n', report)
        self.assertIn('- Context targets sampled: 2 (limit 20); omitted: 0', report)
        self.assertIn('Targets are further restricted to the exact signature', report)
        self.assertIn('Target source lines: 2.', report)
        self.assertIn('Target source lines: 8.', report)
        self.assertIn('  1: 2026-10-28 08:00:00 [INFO] before', report)
        self.assertIn('> 2: 2026-10-28 08:01:00 [ERROR] keep 1', report)
        self.assertIn('  3: stack frame', report)
        self.assertIn('  7: 2026-10-28 08:08:00 [ERROR] drop 2', report)
        self.assertIn('> 8: 2026-10-28 08:09:00 [ERROR] keep 2', report)
        self.assertIn('  9: 2026-10-28 08:10:00 [INFO] after', report)
        for line in report.splitlines():
            self.assertNotIn(line, ('> 5: 2026-10-28 08:03:00 [ERROR] drop 1',
                                    '> 7: 2026-10-28 08:08:00 [ERROR] drop 2'))

    def test_signature_comparison_agrees_across_markdown_terminal_and_json(self):
        self.signature_log()
        json_path = self.root / 'report.json'
        options = ('--signature', 'ERROR: sig #', '--baseline-buckets', '2',
                   '--multiplier', '2', '--min-errors', '2', '--context', '0')
        markdown_run = self.analyze(*options)
        markdown = self.report.read_text()
        json_run = self.analyze_to(json_path, '--format', 'json', *options)
        document = json.loads(json_path.read_text())
        self.assertEqual(document['selected_signature'], 'ERROR: sig #')
        comparison = document['signature_comparisons'][0]
        self.assertEqual(comparison['signature'], 'ERROR: sig #')

        rows = self.comparison_windows(markdown)
        self.assertEqual([row[:2] for row in rows],
                         [(1, 'baseline'), (1, 'spike')])
        self.assertEqual(self.comparison_spikes(markdown),
                         [('1', comparison['spike_start'],
                           comparison['spike_end_exclusive'])])
        expected_baseline = (comparison['before_start'], comparison['spike_start'],
                             int(comparison['before_minutes']),
                             int(comparison['before_count']),
                             per_minute(comparison['before_per_minute']))
        expected_spike = (comparison['spike_start'], comparison['spike_end_exclusive'],
                          int(comparison['spike_minutes']),
                          int(comparison['spike_count']),
                          per_minute(comparison['spike_per_minute']))
        self.assertEqual(tuple(rows[0][2:]), expected_baseline)
        self.assertEqual(tuple(rows[1][2:]), expected_spike)
        self.assertEqual(expected_baseline,
                         ('2026-10-28 08:00:00Z', '2026-10-28 08:10:00Z', 10, 2, '0.200'))
        self.assertEqual(expected_spike,
                         ('2026-10-28 08:10:00Z', '2026-10-28 08:15:00Z', 5, 2, '0.400'))
        self.assertEqual(comparison['rate_multiplier'], 2.0)
        self.assertIn('Rate multiplier: 2.00x', markdown)

        terminal = self.terminal_comparisons(markdown_run.stdout)[1]
        self.assertEqual(terminal['baseline'], expected_baseline)
        self.assertEqual(terminal['spike'], expected_spike)
        self.assertEqual(terminal['rate'], '2.00x.')
        self.assertEqual(self.report_summary(markdown_run.stdout),
                         self.report_summary(json_run.stdout))

    def test_zero_baseline_reports_na_and_both_sides(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        result = self.analyze('--signature', 'ERROR: database timeout retry=#')
        report = self.report.read_text()
        self.assertEqual(
            self.comparison_windows(report)[0][2:],
            ('2026-10-28 08:00:00Z', '2026-10-28 08:30:00Z', 30, 0, '0.000'))
        self.assertIn('Rate multiplier: N/A', report)
        self.assertIn('the baseline counted 0 occurrence(s) over 30 minute(s) '
                      '(0.000 per minute) and the spike counted 4 over 5 minute(s) '
                      '(0.800 per minute)', report)
        self.assertIn('undefined, not zero', report)
        self.assertIn('  Spike 1 rate multiplier: N/A (zero baseline: 0 occurrence(s) '
                      'over 30 min; spike 4 over 5 min).', result.stdout)
        self.report.unlink()
        self.analyze('--format', 'json',
                     '--signature', 'ERROR: database timeout retry=#')
        comparison = json.loads(self.report.read_text())['signature_comparisons'][0]
        self.assertIsNone(comparison['rate_multiplier'])
        self.assertEqual(comparison['before_per_minute'], 0)

    def test_comparison_window_follows_bucket_and_baseline_settings(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        cases = [
            (('--baseline-buckets', '6'), (30, 5, '0.000', '0.800')),
            (('--baseline-buckets', '3'), (15, 5, '0.000', '0.800')),
            (('--baseline-buckets', '2', '--bucket-minutes', '10'),
             (20, 10, '0.000', '0.400')),
        ]
        for options, expected in cases:
            with self.subTest(options=options):
                self.analyze('--signature', 'ERROR: database timeout retry=#',
                             '--context', '0', *options)
                report = self.report.read_text()
                self.report.unlink()
                rows = self.comparison_windows(report)
                self.assertEqual((rows[0][4], rows[1][4], rows[0][6], rows[1][6]),
                                 expected)

    def test_signature_without_spikes_never_claims_health(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] before\n'
            '2026-10-28 08:01:00 [ERROR] failed\n',
            encoding='utf8',
        )
        result = self.analyze('--context-mode', 'errors',
                              '--signature', 'ERROR: failed')
        report = self.report.read_text()
        self.assertIn('- Detected spikes: 0\n', report)
        self.assertIn('there is no comparison window', report)
        self.assertIn('does not mean the selected signature never occurred', report)
        self.assertIn('- Context targets sampled: 1 (limit 20); omitted: 0', report)
        self.assertIn('  No spikes met the rule, so there is no comparison window; '
                      'this does not mean the selected signature never occurred.',
                      result.stdout)
        self.assertIn('does not imply the service was healthy', result.stdout)
        self.assertEqual(self.comparison_windows(report), [])

    def test_signature_does_not_change_original_statistics(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        plain_run = self.analyze('--format', 'json', '--context', '2')
        plain = json.loads(self.report.read_text())
        self.report.unlink()
        json_path = self.root / 'signed.json'
        signed_run = self.analyze_to(json_path, '--format', 'json', '--context', '2',
                                     '--signature', 'ERROR: database timeout retry=#')
        signed = json.loads(json_path.read_text())
        self.assertIsNone(plain['selected_signature'])
        self.assertEqual(plain['signature_comparisons'], [])
        for key in ('summary', 'spikes', 'buckets', 'observation_buckets',
                    'signatures', 'level_counts', 'context_windows', 'filter',
                    'config'):
            self.assertEqual(plain[key], signed[key], key)
        for document in (plain, signed):
            document.pop('selected_signature')
            document.pop('signature_comparisons')
        self.assertEqual(plain, signed)
        extra = [line for line in self.report_summary(signed_run.stdout)
                 if line not in self.report_summary(plain_run.stdout)]
        self.assertTrue(extra)
        for line in extra:
            self.assertTrue(line.startswith('Selected signature:') or
                            line.startswith('  Exact match') or
                            'Spike 1' in line, line)

    def test_terminal_escapes_the_signature_but_json_keeps_it_raw(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n', encoding='utf8')
        payload = 'ERROR: pwn\u001b[2J'
        result = self.analyze('--format', 'json', '--signature', payload)
        self.assertIn('Selected signature: ERROR: pwn\\x1b[2J', result.stdout)
        self.assertNotIn('\u001b', result.stdout)
        document = json.loads(self.report.read_text())
        self.assertEqual(document['selected_signature'], payload)

    def test_ratio_ignores_level_and_keyword_filters(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        plain = self.analyze()
        baseline = self.markdown_total_ratio(self.report.read_text())
        self.assertEqual(baseline, (4, 30, '13.3%'))
        self.assertEqual(self.terminal_ratio(plain.stdout), baseline)
        self.report.unlink()

        level_run = self.analyze('--level', 'ERROR')
        report = self.report.read_text()
        self.assertEqual(self.markdown_total_ratio(report), baseline)
        self.assertEqual(self.terminal_ratio(level_run.stdout), baseline)
        self.assertIn('- Lines matching filters: 4\n', report)
        self.assertIn('| ERROR | 4 |', report)
        self.report.unlink()

        keyword_run = self.analyze('--keyword', 'health')
        report = self.report.read_text()
        self.assertEqual(self.markdown_total_ratio(report), baseline)
        self.assertEqual(self.terminal_ratio(keyword_run.stdout), baseline)
        self.assertIn('- Lines matching filters: 23\n', report)
        self.assertIn('- ERROR + FATAL: 0\n', report)

    def test_ratio_respects_time_filter(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        json_path = self.root / 'report.json'
        window = ('--from', '2026-10-28 08:30:00', '--to', '2026-10-28 08:34:00')
        result = self.analyze(*window)
        report = self.report.read_text()
        self.assertEqual(self.markdown_total_ratio(report), (4, 5, '80.0%'))
        self.assertEqual(self.terminal_ratio(result.stdout), (4, 5, '80.0%'))
        self.assertEqual(self.markdown_bucket_ratios(report),
                         [('2026-10-28 08:30:00Z', '2026-10-28 08:35:00Z', 4, 5, '80.0%')])
        self.analyze_to(json_path, '--format', 'json', *window)
        document = json.loads(json_path.read_text())
        overall = document['summary']['log_error_ratio']
        self.assertEqual((overall['errors'], overall['total']), ('4', '5'))
        self.assertEqual(overall['fraction'], 0.8)
        self.assertEqual(len(document['observation_buckets']), 1)
        self.assertEqual(document['observation_buckets'][0]['log_error_ratio']['total'], '5')

    def test_empty_bucket_ratio_is_na_and_json_null(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [ERROR] boom\n'
            '2026-10-28 08:20:00 [INFO] later\n',
            encoding='utf8',
        )
        json_path = self.root / 'report.json'
        result = self.analyze()
        report = self.report.read_text()
        self.assertEqual(self.markdown_total_ratio(report), (1, 2, '50.0%'))
        self.assertEqual(self.terminal_ratio(result.stdout), (1, 2, '50.0%'))
        self.assertEqual([row[4] for row in self.markdown_bucket_ratios(report)],
                         ['100.0%', 'N/A', 'N/A', 'N/A', '0.0%'])
        self.assertIn('An empty bucket contains no time-valid line', report)
        self.analyze_to(json_path, '--format', 'json')
        document = json.loads(json_path.read_text())
        self.assertEqual([bucket['log_error_ratio']['fraction']
                          for bucket in document['observation_buckets']],
                         [1.0, None, None, None, 0.0])
        self.assertEqual([bucket['log_error_ratio']['total']
                          for bucket in document['observation_buckets']],
                         ['1', '0', '0', '0', '1'])

    def test_empty_input_ratio_is_na(self):
        self.source.write_bytes(b'')
        result = self.analyze()
        self.assertEqual(self.markdown_total_ratio(self.report.read_text()), (0, 0, 'N/A'))
        self.assertEqual(self.terminal_ratio(result.stdout), (0, 0, 'N/A'))
        self.assertIn('No time-valid line was observed', self.report.read_text())

    def test_ratio_counts_other_lines_and_excludes_untimed(self):
        self.source.write_text(
            '2026-10-28 08:00:00 [OTHER] unknown level\n'
            '2026-10-28 08:00:00 [INFO] ok\n'
            '2026-10-28 08:00:00 [ERROR] boom\n'
            '{"ts":"bad","level":"ERROR","msg":"untimed"}\n'
            'stack frame\n',
            encoding='utf8',
        )
        result = self.analyze()
        self.assertIn('Scanned 5 lines; matched 5; untimed 2', result.stdout)
        self.assertEqual(self.markdown_total_ratio(self.report.read_text()), (1, 3, '33.3%'))
        self.assertEqual(self.terminal_ratio(result.stdout), (1, 3, '33.3%'))

    def test_ratio_matches_across_markdown_terminal_and_json(self):
        self.source.write_bytes((ROOT / 'fixtures/incident.log').read_bytes())
        json_path = self.root / 'report.json'
        markdown_run = self.analyze()
        markdown = self.report.read_text()
        json_run = self.analyze_to(json_path, '--format', 'json')
        document = json.loads(json_path.read_text())

        overall = document['summary']['log_error_ratio']
        expected = (int(overall['errors']), int(overall['total']), percent(overall['fraction']))
        self.assertEqual(expected, (4, 30, '13.3%'))
        self.assertEqual(self.markdown_total_ratio(markdown), expected)
        self.assertEqual(self.terminal_ratio(markdown_run.stdout), expected)
        self.assertEqual(self.terminal_ratio(json_run.stdout), expected)

        spike_rows = self.markdown_spike_ratios(markdown)
        terminal_spikes = self.terminal_spike_ratios(markdown_run.stdout)
        self.assertEqual(len(spike_rows), len(document['spikes']))
        self.assertEqual(len(terminal_spikes), len(document['spikes']))
        for row, spike, terminal in zip(spike_rows, document['spikes'], terminal_spikes):
            ratio = spike['log_error_ratio']
            expected_spike = (int(ratio['errors']), int(ratio['total']),
                              percent(ratio['fraction']))
            self.assertEqual((row[3], row[4], row[5]), expected_spike)
            self.assertEqual(terminal, expected_spike)
            self.assertEqual((row[1], row[2]), (spike['start'], spike['end_exclusive']))
        self.assertEqual(spike_rows[0][3:6], (4, 5, '80.0%'))

        bucket_rows = self.markdown_bucket_ratios(markdown)
        self.assertEqual(len(bucket_rows), len(document['observation_buckets']))
        for row, bucket in zip(bucket_rows, document['observation_buckets']):
            ratio = bucket['log_error_ratio']
            self.assertEqual(row[0], bucket['start'])
            self.assertEqual(row[1], bucket['end_exclusive'])
            self.assertEqual((row[2], row[3], row[4]),
                             (int(ratio['errors']), int(ratio['total']),
                              percent(ratio['fraction'])))

        self.assertIn('not a request failure rate', document['log_error_ratio_semantics'])
        # The filtered spike table is still present and separate from the ratio table.
        self.assertIn('| 2026-10-28 08:30:00Z | 2026-10-28 08:35:00Z | 4 | 4 | 0 |',
                      markdown)

    def test_observation_bucket_table_caps_display_at_fifty(self):
        lines = [f'2026-10-28 {8 + i // 12:02d}:{(i % 12) * 5:02d}:00 [INFO] tick'
                 for i in range(60)]
        self.source.write_text('\n'.join(lines) + '\n', encoding='utf8')
        json_path = self.root / 'report.json'
        self.analyze()
        report = self.report.read_text()
        self.assertEqual(len(self.markdown_bucket_ratios(report)), 50)
        self.assertIn('Showing the first 50 of 60 observation buckets', report)
        self.analyze_to(json_path, '--format', 'json')
        self.assertEqual(len(json.loads(json_path.read_text())['observation_buckets']), 60)


if __name__ == '__main__':
    unittest.main()
