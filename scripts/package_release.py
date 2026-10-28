#!/usr/bin/env python3
"""Package the locally built executable and write SHA-256 without overwriting."""
import argparse
import hashlib
import pathlib
import platform
import re
import tarfile
import tempfile
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=pathlib.Path, default=ROOT / 'dist')
    args = parser.parse_args()
    version = re.search(r'^version = "([^"]+)"', (ROOT / 'moon.mod').read_text(), re.M)[1]
    system = {'Darwin': 'macos', 'Linux': 'linux'}.get(platform.system())
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x86_64', 'AMD64': 'x86_64'}.get(platform.machine())
    if not system or not arch:
        parser.error('unsupported platform')
    binary = ROOT / 'bin/moonlog'
    if not binary.is_file():
        parser.error('run make build first')
    name = f'moonlog-v{version}-{system}-{arch}'
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / f'{name}.tar.gz'
    checksum = args.output / f'{name}.tar.gz.sha256'
    if archive.exists() or checksum.exists():
        parser.error('package already exists; use a fresh output directory')
    with tempfile.TemporaryDirectory() as tmp:
        stage = pathlib.Path(tmp) / name
        stage.mkdir()
        shutil.copy2(binary, stage / 'moonlog')
        (stage / 'moonlog').chmod(0o755)
        for source in ['LICENSE', 'README.md']:
            shutil.copy2(ROOT / source, stage / source)
        shutil.copytree(ROOT / 'config', stage / 'config')
        with archive.open('xb') as stream:
            with tarfile.open(fileobj=stream, mode='w:gz') as tar:
                tar.add(stage, arcname=name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with checksum.open('x') as stream:
        stream.write(f'{digest}  {archive.name}\n')
    print(archive)
    print(checksum)

if __name__ == '__main__':
    main()
