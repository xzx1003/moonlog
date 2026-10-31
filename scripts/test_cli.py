#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Black-box acceptance tests against the real native executable; stdlib only."""
from pathlib import Path
from decimal import Decimal
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1) if len(sys.argv) > 1 else 'bin/moonlog').resolve()
ROOT = Path(__file__).resolve().parent.parent

def is_windows():
    return platform.system() == 'Windows'

def skip_on_windows(reason):
    """Decorator to skip entire test methods on Windows."""
    def decorator(test_func):
        def wrapper(self, *args, **kwargs):
            if is_windows():
                self.skipTest(reason)
            return test_func(self, *args, **kwargs)
        return wrapper
    return decorator

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

    def test_detector_config_override_and_output_rules(self):
        self.source.write_text('2026-10-28 08:00:00 [ERROR] baseline\n' +
                               '2026-10-28 08:05:00 [ERROR] burst\n' * 3)
        config = self.root / 'config.json'
        config.write_text(json.dumps({'detector': 'mad', 'baseline-buckets': 1,
                                      'mad-threshold': 2.5, 'ewma-alpha': 0.5}))
        docs = {}
        for detector in ['moving-average', 'ewma', 'mad']:
            report = self.root / (detector + '.json')
            result = self.analyze_to(report, '--config', config, '--detector', detector,
                                     '--format', 'json')
            doc = json.loads(report.read_text()); docs[detector] = doc
            if detector == 'moving-average':
                self.assertNotIn('detector', doc['config'])
                self.assertNotIn('Detector:', result.stdout)
            else:
                self.assertEqual(doc['config']['detector'], detector)
                self.assertIn('Detector: ' + detector, result.stdout)
        self.assertEqual(len(docs['mad']['spikes']), 1)
        self.assertEqual(len(docs['ewma']['spikes']), 0)
        self.assertEqual(docs['mad']['config']['mad_threshold'], 2.5)
        self.assertEqual(docs['ewma']['config']['ewma_alpha'], 0.5)
        for doc in docs.values():
            self.assertEqual({k: doc['summary'][k] for k in ['total', 'matched', 'untimed', 'errors', 'log_error_ratio']},
                             {k: docs['mad']['summary'][k] for k in ['total', 'matched', 'untimed', 'errors', 'log_error_ratio']})
        md = self.root / 'mad.md'
        self.analyze_to(md, '--config', config)
        self.assertIn('median + 2.5 * 1.4826 * MAD', md.read_text())

    def test_detector_default_output_compatibility(self):
        self.source.write_text((ROOT / 'fixtures/incident.log').read_text())
        for fmt in ['json', 'markdown']:
            first = self.root / ('default.' + fmt); second = self.root / ('explicit.' + fmt)
            a = self.analyze_to(first, '--format', fmt)
            b = self.analyze_to(second, '--format', fmt, '--detector', 'moving-average')
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(self.report_summary(a.stdout), self.report_summary(b.stdout))

    def test_detector_invalid_parameters_do_not_write_reports(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ok\n')
        for flag, values in [('--detector', ['unknown', 'EWMA', '']),
                             ('--ewma-alpha', ['0', '-1', '1.1', 'NaN', 'Infinity', '1e999', '"0.5"', 'null']),
                             ('--mad-threshold', ['0', '-1', '1001', 'NaN', 'Infinity', 'false'])]:
            for value in values:
                with self.subTest(flag=flag, value=value):
                    self.analyze(flag, value, ok=False)
                    self.assertFalse(self.report.exists())
            self.analyze(flag, ok=False)
            self.analyze(flag, 'mad' if flag == '--detector' else '0.5', flag,
                         'mad' if flag == '--detector' else '0.5', ok=False)

    def test_detector_config_rejects_invalid_layer_even_when_overridden(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ok\n')
        config = self.root / 'config.json'
        for settings in [{'detector': 1}, {'detector': 'bad'}, {'ewma-alpha': '0.5'},
                         {'ewma-alpha': 0}, {'mad-threshold': 1001}]:
            config.write_text(json.dumps(settings))
            self.analyze('--config', config, '--detector', 'mad', '--ewma-alpha', '0.5',
                         '--mad-threshold', '3', ok=False)
            self.assertFalse(self.report.exists())

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
        try:
            self.report.symlink_to(self.source)
        except OSError:
            pass
        else:
            self.analyze(ok=False)
            self.report.unlink()
        os.link(self.source, self.report)
        self.analyze(ok=False)
        self.assertEqual(self.source.read_bytes(), original)

    def test_missing_input_and_directory_fail(self):
        self.analyze(ok=False)
        self.run_cli('analyze', self.root, '--report', self.report, ok=False)
        self.assertFalse(self.report.exists())


    def test_explicit_config_defaults_and_cli_precedence(self):
        self.source.write_text((ROOT / 'fixtures/incident.log').read_text(), encoding='utf8')
        config = self.root / 'moonlog.json'
        config.write_text(json.dumps({
            'bucket-minutes': 10, 'baseline-buckets': 2, 'multiplier': 2,
            'min-errors': 2, 'context': 1, 'context-mode': 'errors',
            'max-samples': 1, 'format': 'json',
        }), encoding='utf8')
        self.run_cli('analyze', self.source, '--config', config, '--report', self.report)
        doc = json.loads(self.report.read_text())
        self.assertEqual(doc['config']['bucket_minutes'], 10)
        self.assertEqual(doc['config']['baseline_buckets'], 2)
        self.assertEqual(doc['config']['context_mode'], 'errors')
        self.assertEqual(doc['summary']['sampled_targets'], 1)
        self.assertEqual(doc['scans'], 2)
        self.report.unlink()
        self.run_cli('analyze', self.source, '--config', config, '--report', self.report,
                     '--bucket-minutes', '5', '--format', 'markdown')
        text = self.report.read_text()
        self.assertIn('- Bucket size: 5 minutes', text)
        self.assertIn('- Context mode: errors', text)

    def test_config_is_explicit_unique_strict_and_cannot_contain_paths(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n', encoding='utf8')
        config = self.root / 'moonlog.json'
        cases = [
            ('{"bucket-minutes": 5, "bucket-minutes": 10}', 'unique keys'),
            ('{"input": "private.log"}', 'unknown or forbidden config key'),
            ('{"report": "out.md"}', 'unknown or forbidden config key'),
            ('{"bucket-minutes": 0}', 'must be 1..1440'),
            ('{"format": 3}', 'must be a string'),
            ('[]', 'config must be a JSON object'),
            ('not json', 'config must be a JSON object'),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                config.write_text(raw, encoding='utf8')
                result = self.analyze('--config', config, ok=False)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.report.exists())
        config.write_text('{}', encoding='utf8')
        result = self.run_cli('analyze', self.source, '--config', config, '--config', config,
                              '--report', self.report, ok=False)
        self.assertIn('duplicate option: --config', result.stderr)
        self.assertFalse(self.report.exists())

    def test_config_flag_inside_keyword_is_a_literal_value(self):
        self.source.write_text('2026-10-28 08:00:00 [ERROR] --config\n', encoding='utf8')
        self.analyze('--keyword', '--config', '--format', 'json')
        self.assertEqual(json.loads(self.report.read_text())['summary']['matched'], 1)

    def test_config_can_be_omitted_and_default_behavior_is_unchanged(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n', encoding='utf8')
        result = self.analyze()
        self.assertIn('Markdown report written', result.stdout)
        self.assertIn('- Bucket size: 5 minutes', self.report.read_text())

    def test_multifile_analyze_matches_single_concatenated_input(self):
        # Split the fixture across two files at a spike boundary; the merged
        # statistics must equal a single concatenated file.
        lines = (ROOT / 'fixtures/incident.log').read_text().splitlines(True)
        first = self.root / 'old.log'
        second = self.root / 'app.log'
        first.write_text(''.join(lines[:23]), encoding='utf8')
        second.write_text(''.join(lines[23:]), encoding='utf8')
        merged = self.root / 'merged.log'
        merged.write_text(''.join(lines), encoding='utf8')

        multi_report = self.root / 'multi.md'
        self.run_cli('analyze', first, second, '--report', multi_report)
        multi = multi_report.read_text()

        single_report = self.root / 'single.md'
        self.run_cli('analyze', merged, '--report', single_report)
        single = single_report.read_text()

        for needle in ('- Lines scanned: 30\n', '- Detected spikes: 1\n',
                       '| 2026-10-28 08:30:00Z | 2026-10-28 08:35:00Z | 4 |',
                       '| ERROR: database timeout retry=\\# | 4 |',
                       '| ERROR | 4 |', '| INFO | 26 |'):
            self.assertIn(needle, multi)
            self.assertIn(needle, single)
        # Both report the same aggregate counts; only the source listing differs.
        self.assertIn('- Sources: ', multi)
        self.assertIn('- Source: ', single)

    def test_multifile_context_windows_carry_source_and_local_lines(self):
        lines = (ROOT / 'fixtures/incident.log').read_text().splitlines(True)
        first = self.root / 'old.log'
        second = self.root / 'app.log'
        first.write_text(''.join(lines[:23]), encoding='utf8')
        second.write_text(''.join(lines[23:]), encoding='utf8')
        self.run_cli('analyze', first, second, '--report', self.report,
                     '--context', '2')
        report = self.report.read_text()
        # Windows never merge across the file boundary; two windows, each named.
        self.assertIn('### Window 1', report)
        self.assertIn('### Window 2', report)
        self.assertIn('Source: ', report)
        # The second file's target line numbers restart at 1 within the file.
        self.assertIn('> 1: 2026-10-28 08:31:00 [ERROR] database timeout retry=2', report)

    def test_multifile_sampling_first_and_distributed_are_deterministic(self):
        lines = (ROOT / 'fixtures/incident.log').read_text().splitlines(True)
        first = self.root / 'old.log'
        second = self.root / 'app.log'
        first.write_text(''.join(lines[:23]), encoding='utf8')
        second.write_text(''.join(lines[23:]), encoding='utf8')
        for mode in ('first', 'distributed'):
            report_a = self.root / f'{mode}-a.md'
            report_b = self.root / f'{mode}-b.md'
            self.run_cli('analyze', first, second, '--report', report_a,
                         '--sampling', mode)
            self.run_cli('analyze', first, second, '--report', report_b,
                         '--sampling', mode)
            self.assertEqual(report_a.read_text(), report_b.read_text())
            self.assertIn(f'- Sampling mode: {mode}; scans: 3', report_a.read_text())

    def test_multifile_distributed_sampling_shared_budget(self):
        # Four targets across two files; a limit of 2 distributed should select
        # the endpoints (first and last target) regardless of file boundaries.
        first = self.root / 'a.log'
        second = self.root / 'b.log'
        first.write_text(
            '2026-10-28 08:00:00 [INFO] healthy\n'
            '2026-10-28 08:05:00 [ERROR] e1\n'
            '2026-10-28 08:05:00 [ERROR] e2\n',
            encoding='utf8',
        )
        second.write_text(
            '2026-10-28 08:05:00 [ERROR] e3\n'
            '2026-10-28 08:05:00 [ERROR] e4\n',
            encoding='utf8',
        )
        self.run_cli('analyze', first, second, '--report', self.report,
                     '--sampling', 'distributed', '--max-samples', '2',
                     '--baseline-buckets', '1', '--min-errors', '2',
                     '--context', '0')
        report = self.report.read_text()
        self.assertIn('- Context targets sampled: 2 (limit 2); omitted: 2', report)
        json_path = self.root / 'dist.json'
        self.run_cli('analyze', first, second, '--report', json_path,
                     '--format', 'json', '--sampling', 'distributed',
                     '--max-samples', '2', '--baseline-buckets', '1',
                     '--min-errors', '2', '--context', '0')
        doc = json.loads(json_path.read_text())
        self.assertEqual(doc['sampling'], 'distributed')
        self.assertEqual(doc['scans'], 3)
        self.assertEqual(doc['summary']['sampled_targets'], 2)
        self.assertEqual(doc['summary']['omitted_targets'], 2)
        # Every window carries a source field that matches one of the inputs.
        for window in doc['context_windows']:
            self.assertIn(window['source'], [str(first), str(second)])

    def test_multifile_rejects_duplicate_and_aliased_inputs(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n')
        # Duplicate path.
        self.run_cli('analyze', self.source, self.source, '--report', self.report,
                     ok=False)
        self.assertFalse(self.report.exists())
        # Hard-link alias.
        hard = self.root / 'hard.log'
        os.link(self.source, hard)
        self.run_cli('analyze', self.source, hard, '--report', self.report, ok=False)
        self.assertFalse(self.report.exists())
        # Symbolic-link alias.
        soft = self.root / 'soft.log'
        try:
            soft.symlink_to(self.source)
        except OSError:
            pass
        else:
            self.run_cli('analyze', self.source, soft, '--report', self.report, ok=False)
            self.assertFalse(self.report.exists())

    def test_sampling_flag_validation(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n')
        for args, expected in [
            (('--sampling', 'oops'), 'unknown sampling mode: oops'),
            (('--sampling',), 'missing value for --sampling'),
            (('--sampling', 'first', '--sampling', 'distributed'),
             'duplicate option: --sampling'),
        ]:
            with self.subTest(args=args):
                result = self.analyze(*args, ok=False)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.report.exists())

    def test_empty_input_file_in_multifile_does_not_cross_boundaries(self):
        first = self.root / 'empty.log'
        second = self.root / 'real.log'
        first.write_text('', encoding='utf8')
        second.write_text(
            '2026-10-28 08:00:00 [INFO] before\n'
            '2026-10-28 08:05:00 [ERROR] boom\n',
            encoding='utf8',
        )
        self.run_cli('analyze', first, second, '--report', self.report,
                     '--context-mode', 'errors', '--context', '1')
        report = self.report.read_text()
        self.assertIn('- Lines scanned: 2\n', report)
        self.assertIn('Source: ', report)
        # The empty file contributes no window; the target is line 2 of second.
        self.assertIn('Target source lines: 2.', report)

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

    def custom_field_log(self, path=None):
        path = path or self.source
        path.write_text(
            '{"timestamp":"2026-10-28T08:00:00Z","severity":"INFO","message":"healthy","ts":"bad","level":"ERROR","msg":"decoy"}\n'
            '{"timestamp":"2026-10-28T08:05:00Z","severity":"INFO","message":"healthy","ts":"bad","level":"ERROR","msg":"decoy"}\n'
            '{"timestamp":"2026-10-28T08:10:00Z","severity":"INFO","message":"healthy","ts":"bad","level":"ERROR","msg":"decoy"}\n'
            '{"timestamp":"2026-10-28T08:15:00Z","severity":"ERROR","message":"db timeout retry=1","ts":"bad","level":"INFO","msg":"decoy"}\n'
            '{"timestamp":"2026-10-28T08:15:00Z","severity":"ERROR","message":"db timeout retry=2","ts":"bad","level":"INFO","msg":"decoy"}\n'
            '{"timestamp":"2026-10-28T08:15:00Z","severity":"ERROR","message":"db timeout retry=3","ts":"bad","level":"INFO","msg":"decoy"}\n'
            '{"timestamp":"2026-10-28T08:15:00Z","severity":"INFO","message":"retry succeeded","ts":"bad","level":"ERROR","msg":"decoy"}\n'
            '{"timestamp":"2026-10-28T08:20:00Z","severity":"INFO","message":"recovered","ts":"bad","level":"ERROR","msg":"decoy"}\n',
            encoding='utf8',
        )

    CUSTOM_FIELDS = ('--json-time-field', 'timestamp',
                     '--json-level-field', 'severity',
                     '--json-message-field', 'message')

    def test_custom_json_fields_drive_full_analysis(self):
        self.custom_field_log()
        result = self.analyze(
            *self.CUSTOM_FIELDS,
            '--baseline-buckets', '1', '--multiplier', '2', '--min-errors', '2',
            '--context', '1', '--signature', 'ERROR: db timeout retry=#')
        report = self.report.read_text()
        self.assertIn(
            'JSON fields: time=timestamp; level=severity; message=message '
            '(exact top-level string keys; text logs unaffected).', result.stdout)
        self.assertIn(
            '- JSON fields (exact top-level string keys; text logs unaffected): '
            'time=timestamp; level=severity; message=message\n', report)
        # The ts/level/msg decoys would produce INFO lines and no spike on
        # fallback; the custom mapping must win instead.
        self.assertIn('- Detected spikes: 1\n', report)
        self.assertIn('| 2026-10-28 08:15:00Z | 2026-10-28 08:20:00Z | 3 |', report)
        self.assertIn('| ERROR | 3 |', report)
        self.assertIn('| INFO | 5 |', report)
        self.assertIn('| ERROR: db timeout retry=\\# | 3 |', report)
        self.assertEqual(self.markdown_total_ratio(report), (3, 8, '37.5%'))
        self.assertEqual(self.markdown_spike_ratios(report),
                         [(1, '2026-10-28 08:15:00Z', '2026-10-28 08:20:00Z',
                           3, 4, '75.0%')])
        self.assertEqual(
            [row[2:] for row in self.comparison_windows(report)],
            [('2026-10-28 08:10:00Z', '2026-10-28 08:15:00Z', 5, 0, '0.000'),
             ('2026-10-28 08:15:00Z', '2026-10-28 08:20:00Z', 5, 3, '0.600')])
        # Context targets and raw surrounding lines survive the mapping.
        self.assertIn('- Context targets sampled: 3 (limit 20); omitted: 0', report)
        self.assertIn('Target source lines: 4, 5, 6.', report)
        self.assertIn(
            '> 4: {"timestamp":"2026-10-28T08:15:00Z","severity":"ERROR",'
            '"message":"db timeout retry=1","ts":"bad","level":"INFO","msg":"decoy"}',
            report)
        self.assertIn('  3:', report)
        self.assertIn('  7:', report)

        json_path = self.root / 'custom.json'
        self.analyze_to(
            json_path, '--format', 'json', *self.CUSTOM_FIELDS,
            '--baseline-buckets', '1', '--multiplier', '2', '--min-errors', '2',
            '--context', '1', '--signature', 'ERROR: db timeout retry=#')
        document = json.loads(json_path.read_text())
        self.assertEqual(document['json_fields'],
                         {'time': 'timestamp', 'level': 'severity',
                          'message': 'message'})
        self.assertEqual(document['summary']['total'], 8)
        self.assertEqual(document['summary']['errors'], 3)
        self.assertEqual(document['summary']['spike_count'], 1)
        self.assertEqual(document['spikes'][0]['signatures'],
                         [{'text': 'ERROR: db timeout retry=#', 'count': 3}])
        comparison = document['signature_comparisons'][0]
        self.assertEqual((comparison['before_count'], comparison['spike_count']),
                         ('0', '3'))
        self.assertEqual(document['context_windows'][0]['targets'], [4, 5, 6])

    def test_json_field_config_and_cli_overrides(self):
        config = self.root / 'moonlog.json'
        config.write_text(json.dumps({
            'json-time-field': 'when',
            'json-level-field': 'severity',
            'json-message-field': 'body',
        }), encoding='utf8')
        rows = [
            '{"when":"2026-10-28T08:00:00Z","severity":"INFO","body":"healthy"}',
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","body":"boom 1"}',
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","body":"boom 2"}',
        ]
        self.source.write_text('\n'.join(rows) + '\n', encoding='utf8')
        result = self.run_cli('analyze', self.source, '--config', config,
                              '--report', self.report, '--baseline-buckets', '1',
                              '--multiplier', '2', '--min-errors', '2',
                              '--context', '0')
        report = self.report.read_text()
        self.assertIn(
            'JSON fields: time=when; level=severity; message=body',
            result.stdout)
        self.assertIn('time=when; level=severity; message=body', report)
        self.assertIn('- Detected spikes: 1\n', report)
        self.assertIn('| ERROR: boom \\# | 2 |', report)

        # A partial config keeps the built-in default for the missing field.
        config.write_text(json.dumps({
            'json-time-field': 'when',
            'json-level-field': 'severity',
        }), encoding='utf8')
        self.source.write_text(
            '{"when":"2026-10-28T08:00:00Z","severity":"INFO","msg":"healthy"}\n'
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","msg":"boom 3"}\n'
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","msg":"boom 4"}\n',
            encoding='utf8')
        self.report.unlink()
        self.run_cli('analyze', self.source, '--config', config,
                     '--report', self.report, '--baseline-buckets', '1',
                     '--multiplier', '2', '--min-errors', '2', '--context', '0')
        report = self.report.read_text()
        self.assertIn(
            'time=when; level=severity; message=msg', report)
        self.assertIn('- Detected spikes: 1\n', report)
        self.assertIn('| ERROR: boom \\# | 2 |', report)

        # CLI wins over config for one field while the other config keys stay.
        self.source.write_text(
            '{"stamp":"2026-10-28T08:00:00Z","severity":"INFO","body":"healthy"}\n'
            '{"stamp":"2026-10-28T08:05:00Z","severity":"ERROR","body":"boom 5"}\n'
            '{"stamp":"2026-10-28T08:05:00Z","severity":"ERROR","body":"boom 6"}\n',
            encoding='utf8')
        self.report.unlink()
        config.write_text(json.dumps({
            'json-time-field': 'when',
            'json-level-field': 'severity',
            'json-message-field': 'body',
        }), encoding='utf8')
        json_path = self.root / 'override.json'
        self.run_cli('analyze', self.source, '--config', config,
                     '--report', json_path, '--format', 'json',
                     '--json-time-field', 'stamp',
                     '--baseline-buckets', '1', '--multiplier', '2',
                     '--min-errors', '2', '--context', '0')
        document = json.loads(json_path.read_text())
        self.assertEqual(document['json_fields'],
                         {'time': 'stamp', 'level': 'severity',
                          'message': 'body'})
        self.assertEqual(document['summary']['errors'], 2)
        self.assertEqual(document['summary']['spike_count'], 1)

        # A single CLI override with everything else at defaults.
        self.source.write_text(
            '{"when":"2026-10-28T08:00:00Z","level":"INFO","msg":"healthy"}\n'
            '{"when":"2026-10-28T08:05:00Z","level":"ERROR","msg":"boom 7"}\n'
            '{"when":"2026-10-28T08:05:00Z","level":"ERROR","msg":"boom 8"}\n',
            encoding='utf8')
        self.analyze('--json-time-field', 'when', '--baseline-buckets', '1',
                     '--multiplier', '2', '--min-errors', '2', '--context', '0')
        report = self.report.read_text()
        self.assertIn('time=when; level=level; message=msg', report)
        self.assertIn('| ERROR: boom \\# | 2 |', report)

    def test_missing_nonstring_and_nested_json_fields_are_not_parsed(self):
        self.source.write_text(
            '{"when":"2026-10-28T08:00:00Z","severity":"ERROR"}\n'
            '{"when":"2026-10-28T08:05:00Z","severity":3,"body":"bad"}\n'
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","body":123}\n'
            '{"outer":{"when":"2026-10-28T08:05:00Z","severity":"ERROR","body":"nested"}}\n'
            '{"when":123,"severity":"ERROR","body":"numeric time"}\n'
            '{"when":"2026-10-28T08:05:00Z","severity":"error","body":"lowercase"}\n',
            encoding='utf8')
        self.analyze('--format', 'json',
                     '--json-time-field', 'when',
                     '--json-level-field', 'severity',
                     '--json-message-field', 'body')
        document = json.loads(self.report.read_text())
        self.assertEqual(document['json_fields'],
                         {'time': 'when', 'level': 'severity',
                          'message': 'body'})
        self.assertEqual(document['summary']['total'], 6)
        self.assertEqual(document['summary']['untimed'], 5)
        self.assertEqual(document['summary']['errors'], 0)
        self.assertEqual(document['summary']['spike_count'], 0)
        self.assertEqual(document['level_counts']['ERROR'], 0)
        self.assertEqual(document['level_counts']['OTHER'], 6)
        self.assertEqual(document['spikes'], [])
        self.assertEqual(document['signatures'], [])
        # Only the lowercase-level line kept a valid timestamp, and it stays OTHER.
        ratio = document['summary']['log_error_ratio']
        self.assertEqual((ratio['errors'], ratio['total'], ratio['fraction']),
                         ('0', '1', 0.0))

        # Dotted names are literal top-level keys, never nested paths.
        self.source.write_text(
            '{"a.b":"2026-10-28T08:00:00Z","级别":"ERROR","内容":"literal"}\n',
            encoding='utf8')
        json_path = self.root / 'literal.json'
        self.analyze_to(json_path, '--format', 'json',
                        '--json-time-field', 'a.b',
                        '--json-level-field', '级别',
                        '--json-message-field', '内容')
        document = json.loads(json_path.read_text())
        self.assertEqual(document['json_fields'],
                         {'time': 'a.b', 'level': '级别', 'message': '内容'})
        self.assertEqual(document['summary']['errors'], 1)
        self.assertEqual(document['signatures'],
                         [{'text': 'ERROR: literal', 'count': 1}])

    def test_json_field_defaults_mixed_text_and_multifile_distributed(self):
        # Defaults stay compatible and text lines ignore any mapping.
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] text healthy\n'
            '{"ts":"2026-10-28T08:00:00Z","level":"INFO","msg":"json healthy"}\n'
            '2026-10-28 08:05:00 [ERROR] text boom 1\n'
            '{"ts":"2026-10-28T08:05:00Z","level":"ERROR","msg":"json boom 2"}\n'
            '2026-10-28 08:05:00 [ERROR] text boom 3\n',
            encoding='utf8')
        result = self.analyze('--baseline-buckets', '1', '--multiplier', '2',
                              '--min-errors', '2', '--context', '0')
        report = self.report.read_text()
        self.assertIn('time=ts; level=level; message=msg', report)
        self.assertIn('time=ts; level=level; message=msg', result.stdout)
        self.assertIn('| ERROR | 3 |', report)
        self.assertIn('| ERROR: text boom \\# | 2 |', report)
        self.assertIn('| ERROR: json boom \\# | 1 |', report)

        # The same mixed file with custom JSON keys still parses text lines.
        self.source.write_text(
            '2026-10-28 08:00:00 [INFO] text healthy\n'
            '{"when":"2026-10-28T08:00:00Z","severity":"INFO","body":"json healthy"}\n'
            '2026-10-28 08:05:00 [ERROR] text boom 1\n'
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","body":"json boom 2"}\n'
            '2026-10-28 08:05:00 [ERROR] text boom 3\n',
            encoding='utf8')
        self.report.unlink()
        self.analyze('--json-time-field', 'when',
                     '--json-level-field', 'severity',
                     '--json-message-field', 'body', '--baseline-buckets', '1',
                     '--multiplier', '2', '--min-errors', '2', '--context', '0')
        report = self.report.read_text()
        self.assertIn('time=when; level=severity; message=body', report)
        self.assertIn('| ERROR | 3 |', report)
        self.assertIn('| ERROR: text boom \\# | 2 |', report)
        self.assertIn('| ERROR: json boom \\# | 1 |', report)

        # Multi-file distributed sampling shares one custom mapping.
        first = self.root / 'first.log'
        second = self.root / 'second.log'
        first.write_text(
            '{"when":"2026-10-28T08:00:00Z","severity":"INFO","body":"healthy"}\n'
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","body":"boom 1"}\n'
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","body":"boom 2"}\n',
            encoding='utf8')
        second.write_text(
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","body":"boom 3"}\n'
            '{"when":"2026-10-28T08:05:00Z","severity":"ERROR","body":"boom 4"}\n',
            encoding='utf8')
        json_path = self.root / 'distributed.json'
        self.run_cli('analyze', first, second, '--report', json_path,
                     '--format', 'json',
                     '--json-time-field', 'when',
                     '--json-level-field', 'severity',
                     '--json-message-field', 'body',
                     '--sampling', 'distributed', '--max-samples', '2',
                     '--baseline-buckets', '1', '--multiplier', '2',
                     '--min-errors', '2', '--context', '0')
        document = json.loads(json_path.read_text())
        self.assertEqual(document['json_fields'],
                         {'time': 'when', 'level': 'severity',
                          'message': 'body'})
        self.assertEqual(document['sampling'], 'distributed')
        self.assertEqual(document['scans'], 3)
        self.assertEqual(document['summary']['errors'], 4)
        self.assertEqual(document['summary']['spike_count'], 1)
        self.assertEqual(document['summary']['sampled_targets'], 2)
        self.assertEqual(document['spikes'][0]['signatures'],
                         [{'text': 'ERROR: boom #', 'count': 4}])
        self.assertEqual(
            {window['source'] for window in document['context_windows']},
            {str(first), str(second)})

    def test_json_field_argument_and_name_validation(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n',
                               encoding='utf8')
        cases = [
            (('--json-time-field',), 'missing value for --json-time-field'),
            (('--json-time-field', 'a', '--json-time-field', 'b'),
             'duplicate option: --json-time-field'),
            (('--json-level-field', ''), 'JSON field names must be nonblank'),
            (('--json-message-field', 'bad\nname'),
             'JSON field names must not contain control characters'),
            (('--json-time-field', 'x' * 257), 'at most 256 UTF-16'),
            (('--json-time-field', 'same', '--json-level-field', 'same'),
             'must be distinct'),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.analyze(*args, ok=False)
                self.assertIn(expected, result.stderr)
                self.assertNotIn('.mbt:', result.stderr)
                self.assertFalse(self.report.exists())

        config = self.root / 'moonlog.json'
        config_cases = [
            ('{"json-time-field": 3}', 'config json-time-field must be a string'),
            ('{"json-level-field": ""}',
             'config JSON field mapping is invalid: JSON field names must be nonblank'),
            ('{"json-message-field": "a\\u007fb"}',
             'config JSON field mapping is invalid: JSON field names must not contain control characters'),
            ('{"json-time-field": "%s"}' % ('x' * 257),
             'config JSON field mapping is invalid: JSON field names must be nonblank and at most 256'),
            ('{"json-time-field": "a", "json-level-field": "a"}',
             'config JSON field mapping is invalid: JSON time, level and message field names must be distinct'),
            ('{"json-other-field": "x"}',
             'unknown or forbidden config key: json-other-field'),
        ]
        for raw, expected in config_cases:
            with self.subTest(raw=raw):
                config.write_text(raw, encoding='utf8')
                result = self.analyze('--config', config, ok=False)
                self.assertIn(expected, result.stderr)
                self.assertNotIn('.mbt:', result.stderr)
                self.assertFalse(self.report.exists())

    def test_help_documents_json_field_options(self):
        for args in [('--help',), ('analyze', '--help')]:
            with self.subTest(args=args):
                text = self.run_cli(*args).stdout
                self.assertIn('--json-time-field K', text)
                self.assertIn('--json-level-field K', text)
                self.assertIn('--json-message-field K', text)
                self.assertIn('exact top-level string keys', text)
                self.assertIn('default ts', text)
                self.assertIn('default level', text)
                self.assertIn('default msg', text)

    def test_redaction_cross_format_and_statistics_unchanged(self):
        self.source = self.root / 'pathsecret-input.log'
        rows = [
            '2026-10-28 08:00:00 [INFO] healthy alice@example.com',
            '2026-10-28 08:05:00 [ERROR] alice@example.com token=abc123',
            '{"ts":"2026-10-28T08:05:00Z","level":"ERROR","msg":"alice@example.com token=abc123","token":"field-secret","nested":{"token":"nested-secret"}}',
            'broken alice@example.com token=abc123 {"token":"invalid-secret"}',
            '2026-10-28 08:05:00 [ERROR] alice@example.com token=abc123',
        ]
        self.source.write_text('\n'.join(rows) + '\n', encoding='utf8')
        original = self.source.read_bytes()
        config = self.root / 'moonlog.json'
        config.write_text(json.dumps({
            'redact-text': [
                {'needle': 'alice@example.com', 'replacement': '[EMAIL]'},
                {'needle': 'token=abc123', 'replacement': 'token=[TOKEN]'},
                {'needle': 'pathsecret', 'replacement': '[PATH]'},
                {'needle': 'invalid-secret', 'replacement': '[INVALID]'},
            ],
            'redact-fields': ['token'],
            'baseline-buckets': 1,
            'multiplier': 2,
            'min-errors': 2,
            'context': 2,
        }), encoding='utf8')
        args = ('--keyword', 'alice@example.com',
                '--signature', 'ERROR: alice@example.com token=abc#')
        md_path = self.root / 'pathsecret-report.md'
        md = self.run_cli('analyze', self.source, '--config', config,
                          '--report', md_path, *args)
        json_path = self.root / 'pathsecret-report.json'
        js = self.run_cli('analyze', self.source, '--config', config,
                          '--report', json_path, '--format', 'json', *args)
        secrets = ['alice@example.com', 'token=abc123', 'pathsecret',
                   'field-secret', 'nested-secret', 'invalid-secret']
        for text in (md.stdout, js.stdout, md_path.read_text(),
                     json_path.read_text()):
            for secret in secrets:
                self.assertNotIn(secret, text)
        md_text = md_path.read_text()
        self.assertIn('Redaction:', md.stdout)
        self.assertIn('Redaction:', md_text)
        self.assertIn('\\[PATH\\]-input.log', md_text)
        self.assertIn('[EMAIL] token=[TOKEN]', md_text)
        document = json.loads(json_path.read_text())
        self.assertEqual(document['redaction']['literal_rule_count'], 4)
        self.assertEqual(document['redaction']['json_field_rule_count'], 1)
        self.assertIn('not a guarantee', document['redaction']['notice'])
        self.assertNotIn('needle', document['redaction'])
        self.assertIn('[PATH]', document['source'])
        self.assertEqual(document['sources'], [document['source']])
        self.assertEqual(document['filter']['keyword'], '[EMAIL]')
        self.assertEqual(document['selected_signature'],
                         'ERROR: [EMAIL] token=abc#')
        self.assertEqual(document['signatures'][0]['text'],
                         'ERROR: [EMAIL] token=abc#')
        self.assertEqual(document['spikes'][0]['signatures'][0]['text'],
                         'ERROR: [EMAIL] token=abc#')
        self.assertEqual(document['signature_comparisons'][0]['signature'],
                         'ERROR: [EMAIL] token=abc#')
        for window in document['context_windows']:
            self.assertIn('[PATH]', window['source'])
        context = {}
        for window in document['context_windows']:
            for line in window['lines']:
                context[line['number']] = line['text']
        self.assertIn('[EMAIL] token=[TOKEN]', context[2])
        self.assertIn('[EMAIL] token=[TOKEN]', context[5])
        nested = json.loads(context[3])
        self.assertEqual(nested['token'], '[REDACTED]')
        self.assertEqual(nested['nested']['token'], '[REDACTED]')
        self.assertIn('[EMAIL]', nested['msg'])
        self.assertIn('[INVALID]', context[4])
        self.assertTrue(context[4].startswith('broken '))

        # The same numeric analysis without redaction must be identical.
        plain_path = self.root / 'plain.json'
        self.run_cli('analyze', self.source, '--report', plain_path,
                     '--format', 'json', '--baseline-buckets', '1',
                     '--multiplier', '2', '--min-errors', '2',
                     '--context', '2', *args)
        plain = json.loads(plain_path.read_text())
        self.assertNotIn('redaction', plain)

        def comparable(doc):
            return {
                'summary': doc['summary'],
                'level_counts': doc['level_counts'],
                'buckets': doc['buckets'],
                'observation_buckets': doc['observation_buckets'],
                'spikes': [
                    {key: spike[key] for key in
                     ('start', 'end_exclusive', 'errors', 'peak_errors',
                      'baseline')}
                    for spike in doc['spikes']
                ],
                'signature_counts': [item['count']
                                     for item in doc['signatures']],
                'spike_signature_counts': [
                    [item['count'] for item in spike['signatures']]
                    for spike in doc['spikes']
                ],
                'comparisons': [
                    (item['before_start'], item['spike_start'],
                     item['spike_end_exclusive'], item['before_minutes'],
                     item['spike_minutes'], item['before_count'],
                     item['spike_count'])
                    for item in doc['signature_comparisons']
                ],
                'context': [
                    {'targets': window['targets'],
                     'numbers': [line['number']
                                 for line in window['lines']]}
                    for window in doc['context_windows']
                ],
                'sampling': doc['sampling'],
                'scans': doc['scans'],
                'json_fields': doc['json_fields'],
                'filter': {key: value for key, value in doc['filter'].items()
                           if key != 'keyword'},
            }

        self.assertEqual(comparable(document), comparable(plain))
        self.assertEqual(self.source.read_bytes(), original)

    def test_redaction_field_rules_only_touch_raw_json_context(self):
        rows = [
            '{"ts":"2026-10-28T08:00:00Z","level":"INFO","msg":"healthy"}',
            '{"ts":"2026-10-28T08:05:00Z","level":"ERROR","msg":"boom","source":"raw-source-secret","summary":"raw-summary-secret"}',
            '{"ts":"2026-10-28T08:05:00Z","level":"ERROR","msg":"boom"}',
        ]
        self.source.write_text('\n'.join(rows) + '\n', encoding='utf8')
        config = self.root / 'moonlog.json'
        config.write_text(json.dumps({
            'redact-fields': ['source', 'summary'],
            'baseline-buckets': 1,
            'multiplier': 2,
            'min-errors': 2,
            'context': 1,
        }), encoding='utf8')
        json_path = self.root / 'scope.json'
        result = self.run_cli('analyze', self.source, '--config', config,
                              '--report', json_path, '--format', 'json')
        document = json.loads(json_path.read_text())
        # Field rules apply to raw JSON context lines, never to report keys.
        self.assertEqual(document['source'], str(self.source))
        self.assertIsInstance(document['summary'], dict)
        self.assertEqual(document['summary']['total'], 3)
        self.assertEqual(document['redaction']['literal_rule_count'], 0)
        self.assertEqual(document['redaction']['json_field_rule_count'], 2)
        self.assertIn('Redaction:', result.stdout)
        for window in document['context_windows']:
            self.assertEqual(window['source'], str(self.source))
        context_text = next(
            line['text']
            for window in document['context_windows']
            for line in window['lines'] if line['number'] == 2)
        parsed = json.loads(context_text)
        self.assertEqual(parsed['source'], '[REDACTED]')
        self.assertEqual(parsed['summary'], '[REDACTED]')
        self.assertEqual(parsed['msg'], 'boom')
        self.assertNotIn('raw-source-secret', json_path.read_text())

        md_path = self.root / 'scope.md'
        md = self.run_cli('analyze', self.source, '--config', config,
                          '--report', md_path)
        md_text = md_path.read_text()
        self.assertIn('Redaction:', md.stdout)
        self.assertIn('Redaction:', md_text)
        self.assertIn('"source":"[REDACTED]"', md_text)
        self.assertNotIn('raw-source-secret', md_text)
        self.assertNotIn('raw-summary-secret', md_text)

    def test_redaction_config_validation_never_echoes_rules(self):
        self.source.write_text('2026-10-28 08:00:00 [INFO] ready\n',
                               encoding='utf8')
        needle = 'TOP-SECRET-NEEDLE'
        replacement = 'TOP-SECRET-REPLACEMENT'
        config = self.root / 'moonlog.json'
        cases = [
            ({'redact-text': 'x'}, 'config redact-text must be an array'),
            ({'redact-text': [{}]},
             'must contain exactly needle and replacement'),
            ({'redact-text': [{'needle': needle}]},
             'must contain exactly needle and replacement'),
            ({'redact-text': [{'needle': needle,
                               'replacement': replacement, 'extra': 'x'}]},
             'must contain exactly needle and replacement'),
            ({'redact-text': [{'needle': 3, 'replacement': 'x'}]},
             'needle must be a string'),
            ({'redact-text': [{'needle': needle, 'replacement': 3}]},
             'replacement must be a string'),
            ({'redact-text': [{'needle': '', 'replacement': 'x'}]},
             'needle must not be empty'),
            ({'redact-text': [{'needle': needle + '\n',
                               'replacement': 'x'}]},
             'needle must not contain newlines'),
            ({'redact-text': [{'needle': needle,
                               'replacement': replacement + '\u0001'}]},
             'replacement must not contain control characters'),
            ({'redact-text': [{'needle': needle,
                               'replacement': needle}]},
             'replacement must differ from needle'),
            ({'redact-text': [
                {'needle': needle, 'replacement': 'a'},
                {'needle': needle, 'replacement': 'b'},
            ]}, 'duplicates an earlier rule'),
            ({'redact-text': [
                {'needle': 'x' * 1025, 'replacement': 'y'},
            ]}, 'needle must be at most 1024 UTF-16 code units'),
            ({'redact-text': [
                {'needle': 'x', 'replacement': 'y' * 1025},
            ]}, 'replacement must be at most 1024 UTF-16 code units'),
            ({'redact-fields': 'token'},
             'config redact-fields must be an array'),
            ({'redact-fields': [3]},
             'redact-fields[0] must be a string'),
            ({'redact-fields': ['  ']},
             'redact-fields[0] must be nonblank'),
            ({'redact-fields': ['a\u007fb']},
             'redact-fields[0] must not contain control characters'),
            ({'redact-fields': ['x' * 257]},
             'redact-fields[0] must be at most 256 UTF-16 code units'),
            ({'redact-fields': ['token', 'token']},
             'duplicates an earlier field'),
            ({'redact-text': [
                {'needle': needle, 'replacement': replacement},
            ], 'format': needle}, 'invalid config format: [REDACTED]'),
            ({'redact-text': [
                {'needle': needle, 'replacement': replacement},
            ], 'bucket-minutes': 0}, 'must be 1..1440'),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                config.write_text(json.dumps(raw), encoding='utf8')
                result = self.analyze('--config', config, ok=False)
                self.assertIn(expected, result.stderr)
                self.assertNotIn(needle, result.stderr)
                self.assertNotIn(replacement, result.stderr)
                self.assertNotIn('.mbt:', result.stderr)
                self.assertFalse(self.report.exists())
        too_many = {'redact-text': [
            {'needle': 'n%d' % index, 'replacement': '[X]'}
            for index in range(101)
        ]}
        config.write_text(json.dumps(too_many), encoding='utf8')
        result = self.analyze('--config', config, ok=False)
        self.assertIn('at most 100 rules', result.stderr)
        self.assertFalse(self.report.exists())
        too_many_fields = {'redact-fields': ['f%d' % index
                                             for index in range(101)]}
        config.write_text(json.dumps(too_many_fields), encoding='utf8')
        result = self.analyze('--config', config, ok=False)
        self.assertIn('at most 100 fields', result.stderr)
        self.assertFalse(self.report.exists())
        for flag in ('--redact-text', '--redact-fields'):
            result = self.analyze(flag, 'value', ok=False)
            self.assertIn('unknown option: %s' % flag, result.stderr)
            self.assertFalse(self.report.exists())

    def test_redaction_disabled_keeps_output_byte_identical(self):
        self.source.write_text((ROOT / 'fixtures/incident.log').read_text(),
                               encoding='utf8')
        config = self.root / 'moonlog.json'
        config.write_text('{}', encoding='utf8')
        plain_md = self.root / 'plain.md'
        empty_md = self.root / 'empty.md'
        plain = self.run_cli('analyze', self.source, '--report', plain_md)
        empty = self.run_cli('analyze', self.source, '--config', config,
                             '--report', empty_md)
        self.assertEqual(plain_md.read_text(), empty_md.read_text())
        self.assertEqual(self.report_summary(plain.stdout),
                         self.report_summary(empty.stdout))
        self.assertNotIn('Redaction:', plain_md.read_text())
        self.assertNotIn('Redaction:', plain.stdout)
        self.assertNotIn('Redaction:', empty.stdout)
        plain_json = self.root / 'plain.json'
        empty_json = self.root / 'empty.json'
        self.run_cli('analyze', self.source, '--report', plain_json,
                     '--format', 'json')
        self.run_cli('analyze', self.source, '--config', config,
                     '--report', empty_json, '--format', 'json')
        plain_doc = json.loads(plain_json.read_text())
        empty_doc = json.loads(empty_json.read_text())
        self.assertEqual(plain_doc, empty_doc)
        self.assertNotIn('redaction', plain_doc)

    def test_redaction_applies_to_error_diagnostics(self):
        source = self.root / 'pathsecret-input.log'
        source.write_text('2026-10-28 08:00:00 [INFO] ready\n',
                          encoding='utf8')
        config = self.root / 'moonlog.json'
        config.write_text(json.dumps({
            'redact-text': [
                {'needle': 'pathsecret', 'replacement': '[PATH]'},
            ],
        }), encoding='utf8')
        missing = self.root / 'pathsecret-missing.log'
        result = self.run_cli('analyze', missing, '--config', config,
                              '--report', self.report, ok=False)
        self.assertIn('[REDACTED]', result.stderr)
        self.assertNotIn('[PATH]', result.stderr)
        self.assertNotIn('pathsecret', result.stderr)
        self.assertFalse(self.report.exists())
        output_dir = self.root / 'pathsecret-dir'
        output_dir.mkdir()
        result = self.run_cli('analyze', source, '--config', config,
                              '--report', output_dir, ok=False)
        self.assertIn('[REDACTED]', result.stderr)
        self.assertNotIn('[PATH]', result.stderr)
        self.assertNotIn('pathsecret', result.stderr)
        self.assertTrue(output_dir.is_dir())
        alias = self.root / 'pathsecret-alias.md'
        os.link(source, alias)
        result = self.run_cli('analyze', source, '--config', config,
                              '--report', alias, ok=False)
        self.assertIn('[REDACTED]', result.stderr)
        self.assertNotIn('[PATH]', result.stderr)
        self.assertNotIn('pathsecret', result.stderr)

    def test_redaction_help_is_config_only(self):
        for args in [('--help',), ('analyze', '--help')]:
            with self.subTest(args=args):
                text = self.run_cli(*args).stdout
                self.assertIn('Redaction is config-file only', text)
                self.assertIn('redact-text', text)
                self.assertIn('redact-fields', text)
                self.assertIn('shell history', text)
                self.assertIn('not a guarantee', text)

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

    @skip_on_windows("control characters not allowed in Windows filenames")
    def test_terminal_summary_escapes_source_path(self):
        weird = self.root / 'in\u001b[31mput.log'
        weird.write_text('2026-10-28 08:00:00 [INFO] ready\n', encoding='utf8')
        report = self.root / 'out.md'
        result = self.run_cli('analyze', weird, '--report', report)
        self.assertIn('Source: ', result.stdout)
        self.assertIn('in\\x1b[31mput.log', result.stdout)
        self.assertNotIn('\u001b', result.stdout)
        self.assertTrue(report.exists())

    @skip_on_windows("control characters not allowed in Windows filenames")
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
