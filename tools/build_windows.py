"""Build a Windows x64 executable on a Windows host; no cross compilation."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import sysconfig
import struct
import tempfile
import zipfile
from pathlib import Path


def build(output, arch):
    actual = {'win32': 'x86', 'win-amd64': 'x64', 'win-arm64': 'arm64'}.get(sysconfig.get_platform())
    if sys.platform != 'win32' or actual != arch:
        raise SystemExit('Use a Windows Python interpreter matching --arch')
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
        data = binary.read_bytes()
        pe_offset = struct.unpack_from('<I', data, 0x3c)[0]
        machine = struct.unpack_from('<H', data, pe_offset + 4)[0]
        if machine != {'x86': 0x14c, 'x64': 0x8664, 'arm64': 0xaa64}[arch]:
            raise SystemExit('Executable machine type does not match requested architecture')
        subprocess.run([str(binary), '--version'], check=True)
        output.mkdir(parents=True)
        executable = output / f'recompose-windows-{arch}.exe'
        shutil.copyfile(binary, executable)
        shutil.copytree(licenses, output / 'LICENSES')
        (output / 'BUILD-INFO.json').write_text(json.dumps({'platform': platform.platform(), 'architecture': arch, 'pe_machine': hex(machine),
            'python': sys.version, 'python_embedded': True, 'code_signed': False}, indent=2), encoding='utf-8')
        deps = subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True, check=True)
        (output / 'BUILD-DEPENDENCIES.txt').write_text(deps.stdout, encoding='utf-8')
        archive = output / f'recompose-windows-{arch}.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(output.rglob('*')):
                if path.is_file() and path != archive:
                    bundle.write(path, 'recompose.exe' if path == executable else path.relative_to(output))
        (output / f'SHA256SUMS-windows-{arch}.txt').write_text(''.join(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
            for path in [executable, archive]), encoding='utf-8')
        print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='dist/windows')
    parser.add_argument('--arch', choices=('x86', 'x64', 'arm64'), default='x64')
    args = parser.parse_args()
    build(args.output, args.arch)
