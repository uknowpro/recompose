"""Build a single-file CLI with pure-Python PyYAML and its license included."""
import argparse
import importlib.metadata
import json
import shutil
import tempfile
import zipapp
from pathlib import Path

import yaml


def build(output):
    root = Path(__file__).resolve().parents[1]
    output = Path(output).resolve()
    if output.exists():
        raise SystemExit('Output exists; choose a new path')
    distribution = importlib.metadata.distribution('PyYAML')
    licenses = [distribution.locate_file(f) for f in distribution.files or []
                if Path(f).name.lower() in ('license', 'license.txt')]
    licenses += [Path('/usr/share/doc/python3-yaml/copyright')]
    license_path = next((p for p in licenses if p.is_file()), None)
    if license_path is None:
        raise SystemExit('Installed PyYAML license not found; install the official PyYAML package before building')
    with tempfile.TemporaryDirectory() as temp:
        stage = Path(temp)
        shutil.copytree(root / 'recompose', stage / 'recompose', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        yaml_root = Path(yaml.__file__).parent
        (stage / 'yaml').mkdir()
        for source in yaml_root.glob('*.py'):
            shutil.copyfile(source, stage / 'yaml' / source.name)
        shutil.copyfile(root / 'LICENSE', stage / 'LICENSE.recompose')
        shutil.copyfile(license_path, stage / 'LICENSE.PyYAML')
        (stage / 'BUILD-INFO.json').write_text(json.dumps({'bundled_dependency': 'PyYAML', 'version': distribution.version, 'runtime': 'Python >=3.10', 'external_image_tools': []}, indent=2))
        (stage / '__main__.py').write_text('from recompose.cli import main\nraise SystemExit(main())\n')
        output.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(stage, target=output, interpreter='/usr/bin/env python3', compressed=True)
        output.chmod(0o755)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='dist/recompose.pyz')
    build(parser.parse_args().output)
