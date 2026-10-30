"""Resource protection tests; do not execute large benchmarks."""
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest

spec = importlib.util.spec_from_file_location('regression', Path(__file__).with_name('run.py'))
reg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reg)


class Resources(unittest.TestCase):
    def test_timeout_reaps_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'slow'
            executable.write_text('#!/bin/sh\nsleep 30\n')
            executable.chmod(0o755)
            started = time.monotonic()
            with self.assertRaises(reg.HarnessError):
                reg.run_process(str(executable), directory, root/'out', root/'err', 0.1)
            self.assertLess(time.monotonic() - started, 3)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'result.json'
            output.write_text('original')
            with self.assertRaises(SystemExit) as error:
                reg.main(['--output', str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(output.read_text(), 'original')

    def test_invalid_timeout_rejected(self):
        for value in ['0', '-1', 'NaN', 'Infinity']:
            with self.subTest(value=value), self.assertRaises(SystemExit) as error:
                reg.main(['--timeout', value])
            self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
