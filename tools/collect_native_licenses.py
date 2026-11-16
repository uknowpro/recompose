"""Collect notices from the native build environment for redistribution."""
import importlib.metadata
import shutil
import sys
from pathlib import Path

output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
shutil.copyfile('LICENSE', output / 'recompose-MIT.txt')
python_license = (Path(sys.base_prefix) / 'LICENSE.txt' if sys.platform == 'win32' else
                  Path(sys.base_prefix) / 'lib' / ('python' + '.'.join(map(str, sys.version_info[:2]))) / 'LICENSE.txt')
shutil.copyfile(python_license, output / 'Python-LICENSE.txt')
for name in ('PyYAML', 'pyinstaller'):
    distribution = importlib.metadata.distribution(name)
    found = False
    for relative in distribution.files or []:
        if Path(relative).name.lower() in ('license', 'license.txt', 'copying.txt'):
            shutil.copyfile(distribution.locate_file(relative), output / (name + '-' + Path(relative).name))
            found = True
    if not found:
        raise SystemExit(f'Missing license for {name}')
# Preserve the build distribution's notices, including transitive shared libraries.
for source in Path('/usr/share/doc').glob('*/copyright'):
    destination = output / 'debian' / source.parent.name
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination / 'copyright')
