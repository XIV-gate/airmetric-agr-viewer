"""Tests for real archive and AGR behavior, independent of Blender."""
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1] / 'airmetric_agr_viewer'


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def archive_bytes(names):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name in names:
            info = zipfile.ZipInfo('entry')
            info.filename = name  # Keep hostile separators; Windows otherwise normalizes them.
            z.writestr(info, b'example')
    stream.seek(0)
    return stream


class CoreTests(unittest.TestCase):
    def test_zip_rejects_traversal_windows_paths_and_case_collisions(self):
        arc = module('archive')
        for names in [['../a.fbx'], ['C:/a.fbx'], ['dir/../../a.fbx'], ['a.fbx', 'A.fbx'],
                      ['one/a.fbx', 'two/a.fbx'], ['a:stream.fbx']]:
            with self.subTest(names=names), zipfile.ZipFile(archive_bytes(names)) as z:
                with self.assertRaises(ValueError):
                    arc.members(z)

    def test_zip_accepts_nested_model_and_ignores_unneeded_documents(self):
        arc = module('archive')
        with zipfile.ZipFile(archive_bytes(['folder/a.fbx', 'folder/a.geojson', 'readme.pdf'])) as z:
            self.assertEqual([i.filename for i in arc.members(z)], ['folder/a.fbx', 'folder/a.geojson'])

    def test_project_container_opens_nested_archives_and_cleans_all_files(self):
        arc = module('archive')
        inner = archive_bytes(['SM_House.fbx', 'SM_House.geojson'])
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, 'w') as z:
            z.writestr('SM_House.zip', inner.getvalue())
        outer.seek(0)
        directory = Path(os.environ['AGR_VIEWER_TEST_ROOT']) / 'packages'
        before = set(directory.iterdir())
        with arc.extracted(outer, directory=directory) as (_, paths):
            self.assertEqual({p.name for p in paths}, {'SM_House.fbx', 'SM_House.geojson'})
            self.assertTrue(all(p.exists() for p in paths))
        self.assertEqual(set(directory.iterdir()), before)

    def test_geojson_numbers_and_decimal_commas(self):
        agr = module('agr')
        for height in [187.9, '187,9']:
            payload = {'features': [{'geometry': {'coordinates': [1234, '5678,5']},
                                     'properties': {'h_relief': height}}]}
            self.assertEqual(agr.position(payload), (1234., 5678.5, 187.9))
        self.assertIsNone(agr.position({'features': []}))

    def test_glass_accepts_numbers_and_strings_without_changing_rgb_encoding(self):
        agr = module('agr')
        glass = {'color_RGB': {'Red': 128, 'Green': '64', 'Blue': 255},
                 'metallicity': '0,6', 'roughness': 0.1, 'refraction': '1,45',
                 'transparency': '0,4'}
        result = agr.glass_values(glass)
        self.assertEqual(result['Base Color'], (128/255, 64/255, 1., 1.))
        self.assertEqual(result['Alpha'], .4)
        self.assertEqual(result['IOR'], 1.45)
        self.assertEqual(agr.glass_materials({'features': [{'Glasses': [{'M_Glass': glass}]}]}),
                         {'M_Glass': glass})

    def test_udim_groups_are_separate_and_missing_numbers_are_preserved(self):
        agr = module('agr')
        names = ['T_a_Diffuse_1.1001.png', 'T_a_Diffuse_1.1003.png',
                 'T_a_ERM_1.1001.png', 'T_a_Normal_1.1001.png', 'T_b_Diffuse_1.1001.png']
        groups = agr.texture_sets([Path(n) for n in names])
        self.assertEqual(len(groups), 2)
        self.assertEqual(sorted(groups['t_a']['diffuse']), [1001, 1003])
        self.assertEqual(agr.model_kind('1234_Demo_01.fbx'), 'LP')
        self.assertEqual(agr.model_kind('SM_House_001.fbx'), 'HP')
        self.assertEqual(agr.object_role('UCX_SM_House_001'), 'collision')

    def test_multiple_material_slots_can_have_the_same_udim_number(self):
        agr = module('agr')
        names = [Path(f'T_House_{channel}_{slot}.1001.png')
                 for slot in (1, 2) for channel in ('Diffuse', 'ERM', 'Normal')]
        sets = agr.textures_for_model(agr.texture_sets(names), 'SM_House.fbx')
        self.assertEqual(set(sets), {1, 2})
        self.assertEqual(sets[2]['diffuse'][1001].name, 'T_House_Diffuse_2.1001.png')


if __name__ == '__main__':
    unittest.main()
