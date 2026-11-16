"""Build a Windows x64 executable on a Windows host; no cross compilation."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def build(output):
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise SystemExit('Build on Windows x64 with x64 Python')
    root = Path(__file__).resolve().parents[1]
    output = Path(output).resolve()
    if output.exists():
        raise SystemExit('Output exists; choose a new directory')
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        licenses = work / 'LICENSES'
        subprocess.run([sys.executable, str(root / 'tools/collect_native_licenses.py'), str(licenses)], cwd=root, check=True)
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--onefile', '--clean', '--noupx',
                        '--name', 'recompose', '--paths', str(root), '--distpath', str(work / 'dist'),
                        '--workpath', str(work / 'work'), '--specpath', str(work),
                        '--add-data', f'{licenses}:licenses', str(root / 'tools/native_entrypoint.py')], cwd=root, check=True)
        binary = work / 'dist/recompose.exe'
        subprocess.run([str(binary), '--version'], check=True)
        output.mkdir(parents=True)
        shutil.copyfile(binary, output / 'recompose.exe')
        shutil.copytree(licenses, output / 'LICENSES')
        (output / 'BUILD-INFO.json').write_text(json.dumps({'platform': platform.platform(), 'architecture': platform.machine(),
            'python': sys.version, 'python_embedded': True, 'code_signed': False}, indent=2), encoding='utf-8')
        deps = subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True, check=True)
        (output / 'BUILD-DEPENDENCIES.txt').write_text(deps.stdout, encoding='utf-8')
        archive = output / 'recompose-windows-amd64.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(output.rglob('*')):
                if path.is_file() and path != archive:
                    bundle.write(path, path.relative_to(output))
        (output / 'SHA256SUMS-windows.txt').write_text(''.join(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
            for path in [output / 'recompose.exe', archive]), encoding='utf-8')
        print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='dist/windows')
    build(parser.parse_args().output)
