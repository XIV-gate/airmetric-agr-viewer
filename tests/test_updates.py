import hashlib
import io
import json
import os
from pathlib import Path
import unittest
import zipfile
from test_core import module


def release(version, *, early=False):
    name = f'airmetric_agr_viewer-{version}.zip'
    return {'tag_name': 'v' + version, 'draft': False, 'prerelease': early,
            'published_at': '2026-11-03T12:00:00Z',
            'html_url': f'https://github.com/XIV-gate/airmetric-agr-viewer/releases/tag/v{version}',
            'assets': [{'name': name, 'size': 1200, 'state': 'uploaded',
                        'digest': 'sha256:' + 'a' * 64,
                        'browser_download_url': 'https://github.com/XIV-gate/airmetric-agr-viewer/releases/download/v'
                        + version + '/' + name}]}


def package(version, *, corrupt=False):
    files = {'VERSION': (version + '\n').encode(),
             '__init__.py': ("bl_info = {'version': " + repr(tuple(map(int, version.split('.')))) + '}\n').encode()}
    manifest = {'module': 'airmetric_agr_viewer', 'version': version, 'blender_min': [4, 2, 0],
                'files': {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}
    if corrupt:
        files['VERSION'] = b'999.0.0'
    files['PACKAGE_MANIFEST.json'] = json.dumps(manifest).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name, data in files.items():
            z.writestr('airmetric_agr_viewer/' + name, data)
    return stream.getvalue()


class UpdateTests(unittest.TestCase):
    def test_catalog_sorts_numerically_and_ignores_drafts_and_wrong_repositories(self):
        updates = module('updates')
        draft = release('4.0.0'); draft['draft'] = True
        wrong = release('3.0.0'); wrong['html_url'] = 'https://example.com'
        result = updates.catalog([release('0.9.0'), release('0.10.0'), draft, wrong, release('0.11.0', early=True)])
        self.assertEqual([r['version'] for r in result], ['0.11.0', '0.10.0', '0.9.0'])
        self.assertTrue(result[0]['early'])

    def test_package_checks_digest_and_internal_hashes(self):
        updates = module('updates')
        data = package('0.2.0')
        files = updates.validate_package(data, '0.2.0', hashlib.sha256(data).hexdigest())
        self.assertEqual(files['VERSION'], b'0.2.0\n')
        with self.assertRaises(ValueError):
            updates.validate_package(data, '0.2.0', '0' * 64)
        with self.assertRaises(ValueError):
            updates.validate_package(package('0.2.0', corrupt=True), '0.2.0')
        with self.assertRaises(ValueError):
            updates.validate_package(data, '0.3.0')

    def test_install_rolls_back_on_write_failure(self):
        updates = module('updates')
        root = Path(os.environ['AGR_VIEWER_TEST_ROOT']) / 'packages'
        old = updates.validate_package(package('0.1.0'), '0.1.0')
        new = updates.validate_package(package('0.2.0'), '0.2.0')
        try:
            for name, data in old.items():
                (root / name).write_bytes(data)
            counter = 0
            def write(path, data):
                nonlocal counter
                counter += 1
                if counter == 2:
                    raise OSError('Simulated disk failure')
                path.write_bytes(data)
            with self.assertRaises(OSError):
                updates.install(root, new, writer=write)
            self.assertEqual({n: (root / n).read_bytes() for n in old}, old)
            updates.install(root, new)
            self.assertEqual((root / 'VERSION').read_text().strip(), '0.2.0')
        finally:
            for name in set(old) | set(new):
                (root / name).unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
