"""Read-only AGR ZIP checks; all fixtures are synthetic."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from airmetric_agr_viewer import preflight

FBX = b'Kaydara FBX Binary  \x00\x1a\x00' + b'\x00' * 8
METADATA = json.dumps({'features': [{'geometry': {'coordinates': [1, 2]},
                                  'properties': {'h_relief': 3}}]}).encode()


def packed(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return stream.getvalue()


class PreflightTests(unittest.TestCase):
    def setUp(self):
        directory = Path(os.environ['AGR_VIEWER_TEST_ROOT']) / 'packages'
        handle = tempfile.NamedTemporaryFile(suffix='.zip', dir=directory, delete=False)
        self.path = Path(handle.name)
        handle.close()
        self.addCleanup(self.path.unlink, missing_ok=True)

    def inspect(self, entries):
        self.path.write_bytes(packed(entries))
        return preflight.inspect_archive(self.path)

    def test_lp_and_result_contract(self):
        result = self.inspect({'1234_Demo.fbx': FBX})
        self.assertEqual(result, {'path': str(self.path.resolve()), 'name': self.path.name,
                                 'status': 'ready', 'reason': '', 'models': 1,
                                 'stamp': (self.path.stat().st_size, self.path.stat().st_mtime_ns),
                                 'digest': hashlib.sha256(self.path.read_bytes()).hexdigest(),
                                 'contained_digests': []})

    def test_ascii_fbx(self):
        self.assertEqual(self.inspect({'1234_Demo.fbx': b'; FBX 7.4.0 project file\n'})['status'], 'ready')

    def test_zip_metadata_is_not_treated_as_another_model(self):
        result = self.inspect({'1234_Demo.fbx': FBX,
                               '__MACOSX/._1234_Demo.fbx': b'file metadata',
                               '._1234_Demo.geojson': b'file metadata'})
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['models'], 1)

    def test_hp_uses_importer_metadata_and_texture_matching(self):
        entries = {'SM_Demo.fbx': FBX, 'SM_Demo.geojson': METADATA,
                   'T_Demo_Diffuse_2.1003.png': b'not decoded during preflight'}
        self.assertEqual(self.inspect(entries)['status'], 'ready')

    def test_hp_accepts_single_unambiguously_named_metadata_and_texture_fallback(self):
        self.assertEqual(self.inspect({'SM_Demo.fbx': FBX, 'Other.geojson': METADATA,
                                      'T_Other_Normal.1001.png': b'header'})['status'], 'ready')

    def test_light_has_no_texture_requirement(self):
        self.assertEqual(self.inspect({'SM_Demo_Light.fbx': FBX,
                                      'SM_Demo.geojson': METADATA})['status'], 'ready')

    def test_missing_hp_metadata_and_coordinates(self):
        for entries, reason in [({'SM_Demo.fbx': FBX}, 'GeoJSON'),
                                ({'SM_Demo.fbx': FBX, 'SM_Demo.geojson': b'{}'}, 'координат')]:
            with self.subTest(reason=reason):
                result = self.inspect(entries)
                self.assertEqual(result['status'], 'skipped')
                self.assertIn(reason, result['reason'])

    def test_hp_without_textures_defers_object_role_check_to_import(self):
        self.assertEqual(self.inspect({'SM_Demo.fbx': FBX,
                                      'SM_Demo.geojson': METADATA})['status'], 'ready')

    def test_light_can_have_metadata_without_position(self):
        self.assertEqual(self.inspect({'SM_Demo_Light.fbx': FBX,
                                      'SM_Demo.geojson': b'{}'})['status'], 'ready')

    def test_password_protected_archive_is_skipped(self):
        data = bytearray(packed({'1234_Demo.fbx': FBX}))
        # Mark both local and central records encrypted, without creating secrets.
        for signature, offset in ((b'PK\x03\x04', 6), (b'PK\x01\x02', 8)):
            index = data.index(signature) + offset
            data[index] |= 1
        self.path.write_bytes(data)
        self.assertEqual(preflight.inspect_archive(self.path)['status'], 'skipped')

    def test_malformed_metadata_is_skipped(self):
        for data in (b'invalid', b'[]', b'{"features": [null]}'):
            with self.subTest(data=data):
                self.assertEqual(self.inspect({'SM_Demo.fbx': FBX, 'SM_Demo.geojson': data})['status'], 'skipped')

    def test_junk_names_and_invalid_fbx_are_skipped(self):
        for entries in ({'notes.txt': b'text'}, {'model.fbx': FBX}, {'1234_Demo.fbx': b'junk'}):
            with self.subTest(entries=entries):
                self.assertEqual(self.inspect(entries)['status'], 'skipped')

    def test_nonzip_and_missing_file(self):
        self.path.write_bytes(b'not a zip')
        self.assertEqual(preflight.inspect_archive(self.path)['status'], 'skipped')
        self.path.unlink()
        self.assertEqual(preflight.inspect_archive(self.path)['status'], 'skipped')

    def test_nested_archive_and_depth_limit(self):
        payload = packed({'1234_Demo.fbx': FBX})
        self.assertEqual(self.inspect({'inner.zip': payload})['models'], 1)
        payload = packed({'middle.zip': payload})
        self.assertEqual(self.inspect({'inner.zip': payload})['status'], 'ready')
        payload = packed({'deep.zip': payload})
        self.assertEqual(self.inspect({'inner.zip': payload})['status'], 'skipped')

    def test_unsafe_paths_and_global_collisions(self):
        for entries in ({'../1234_Demo.fbx': FBX},
                        {'1234_Demo.fbx': FBX, 'inner.zip': packed({'1234_demo.fbx': FBX})},
                        {'inner.zip': b'broken nested zip'}):
            with self.subTest(entries=list(entries)):
                self.assertEqual(self.inspect(entries)['status'], 'skipped')

    def test_cancellation_propagates_and_closes_temporary_files(self):
        self.path.write_bytes(packed({'inner.zip': packed({'1234_Demo.fbx': FBX})}))
        with self.assertRaises(InterruptedError):
            preflight.inspect_archive(self.path, cancelled=lambda: True)
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 6
        with self.assertRaises(InterruptedError):
            preflight.inspect_archive(self.path, cancelled=cancelled)

    def test_no_extract_or_image_read_and_temporary_files_are_removed(self):
        self.path.write_bytes(packed({'inner.zip': packed({'1234_Demo.fbx': FBX,
                                                          'image.png': b'pixels'})}))
        directory = Path(os.environ['TEMP'])
        before = set(directory.iterdir())
        original = zipfile.ZipFile.open
        original_spool = tempfile.SpooledTemporaryFile
        def spool(**kwargs):
            kwargs['max_size'] = 1  # Exercise automatic disk rollover and cleanup.
            return original_spool(**kwargs)
        stamp = self.path.stat().st_mtime_ns
        def opened(archive, member, *args, **kwargs):
            name = member.filename if isinstance(member, zipfile.ZipInfo) else member
            self.assertFalse(name.endswith('.png'))
            return original(archive, member, *args, **kwargs)
        with mock.patch.object(zipfile.ZipFile, 'extractall', side_effect=AssertionError), \
             mock.patch.object(zipfile.ZipFile, 'open', opened), \
             mock.patch.object(tempfile, 'SpooledTemporaryFile', spool):
            self.assertEqual(preflight.inspect_archive(self.path)['status'], 'ready')
        self.assertEqual(set(directory.iterdir()), before)
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)

    def test_selection_deduplicates_resolved_paths(self):
        self.path.write_bytes(packed({'1234_Demo.fbx': FBX}))
        self.assertEqual(len(preflight.inspect_selection([self.path, str(self.path.resolve())])), 1)

    def additional_archive(self, data):
        handle = tempfile.NamedTemporaryFile(suffix='.zip', dir=self.path.parent, delete=False)
        path = Path(handle.name)
        handle.write(data)
        handle.close()
        self.addCleanup(path.unlink, missing_ok=True)
        return preflight.inspect_archive(path)

    def test_nested_digest_skips_separate_inner_selection_in_either_order(self):
        inner_bytes = packed({'1234_Demo.fbx': FBX})
        inner = self.additional_archive(inner_bytes)
        outer = self.inspect({'inner.zip': inner_bytes})
        self.assertEqual(outer['contained_digests'], [inner['digest']])
        for source in ([inner, outer], [outer, inner]):
            rows = preflight.deduplicate(source)
            selected = {row['path']: row for row in rows}
            self.assertEqual(selected[outer['path']]['status'], 'ready')
            self.assertEqual(selected[inner['path']]['reason'], 'Уже входит в выбранный общий ZIP')
        self.assertEqual(inner['status'], 'ready')
        self.assertEqual(outer['status'], 'ready')

    def test_identical_archives_keep_first_copy(self):
        original = self.inspect({'1234_Demo.fbx': FBX})
        copied = self.additional_archive(self.path.read_bytes())
        result = preflight.deduplicate([original, copied])
        self.assertEqual([row['status'] for row in result], ['ready', 'skipped'])
        self.assertEqual(result[1]['reason'], 'Этот архив уже выбран')
        self.assertEqual(copied['status'], 'ready')
        self.assertIsNot(result[0], original)

    def test_distinct_archives_with_same_model_names_are_kept(self):
        original = self.inspect({'1234_Demo.fbx': FBX})
        other = self.additional_archive(packed({'1234_Demo.fbx': FBX + b'different geometry'}))
        self.assertEqual([row['status'] for row in preflight.deduplicate([original, other])],
                         ['ready', 'ready'])

    def test_skipped_container_does_not_hide_ready_inner(self):
        inner_bytes = packed({'1234_Demo.fbx': FBX})
        inner = self.additional_archive(inner_bytes)
        outer = self.inspect({'inner.zip': inner_bytes, 'bad.fbx': b'broken'})
        self.assertEqual([row['status'] for row in preflight.deduplicate([outer, inner])],
                         ['skipped', 'ready'])

    def test_nested_digests_include_both_supported_levels(self):
        leaf_bytes = packed({'1234_Demo.fbx': FBX})
        middle_bytes = packed({'leaf.zip': leaf_bytes})
        result = self.inspect({'middle.zip': middle_bytes})
        self.assertEqual(result['contained_digests'], [hashlib.sha256(middle_bytes).hexdigest(),
                                                      hashlib.sha256(leaf_bytes).hexdigest()])

    def test_partial_overlap_keeps_both_containers(self):
        shared = packed({'1234_Demo.fbx': FBX})
        first = self.inspect({'shared.zip': shared, '5678_First.fbx': FBX})
        other = self.additional_archive(packed({'shared.zip': shared, '9012_Other.fbx': FBX}))
        self.assertEqual([row['status'] for row in preflight.deduplicate([first, other])],
                         ['ready', 'ready'])

    def test_unavailable_archive_has_empty_digest_fields(self):
        self.path.unlink()
        row = preflight.inspect_archive(self.path)
        self.assertEqual(row['digest'], '')
        self.assertEqual(row['contained_digests'], [])

    def test_top_level_hash_is_chunked_and_cancellable(self):
        self.path.write_bytes(packed({'1234_Demo.fbx': FBX}))
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 4
        with mock.patch.object(preflight, '_CHUNK', 8), \
             mock.patch.object(preflight, '_inspect', side_effect=AssertionError('must cancel before inspection')):
            with self.assertRaises(InterruptedError):
                preflight.inspect_archive(self.path, cancelled)

    def test_global_limits(self):
        with mock.patch.object(preflight.archive, 'MAX_FILES', 2):
            result = self.inspect({'inner.zip': packed({'1234_Demo.fbx': FBX}), 'image.png': b'pixel'})
            self.assertEqual(result['status'], 'skipped')
        with mock.patch.object(preflight.archive, 'MAX_BYTES', 32):
            self.assertEqual(self.inspect({'1234_Demo.fbx': FBX * 2})['status'], 'skipped')


if __name__ == '__main__':
    unittest.main()
