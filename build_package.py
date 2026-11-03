"""Build the installable legacy add-on ZIP; no third-party binaries or models."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'airmetric_agr_viewer'


def build(destination):
    version = (SOURCE / 'VERSION').read_text().strip()
    files = {p.name: p.read_bytes() for p in SOURCE.iterdir() if p.suffix == '.py' or p.name == 'VERSION'}
    manifest = {'module': 'airmetric_agr_viewer', 'version': version, 'blender_min': [4, 2, 0],
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files['PACKAGE_MANIFEST.json'] = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode('utf8')
    output = Path(destination).resolve() / f'airmetric_agr_viewer-{version}.zip'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo('airmetric_agr_viewer/' + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    spec = importlib.util.spec_from_file_location('updates_build', SOURCE / 'updates.py')
    updates = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updates)
    data = output.read_bytes()
    updates.validate_package(data, version)
    print(json.dumps({'path': str(output), 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}, indent=2))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True)
    build(parser.parse_args().output_directory)
