"""Run with --background --python, only with isolated Blender environment."""
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
import airmetric_agr_viewer as addon
from airmetric_agr_viewer import importer, viewport

work = Path(os.environ['AGR_VIEWER_TEST_ROOT'])
source = Path(os.environ['AGR_VIEWER_FIXTURES'])
hp_archive = source / os.environ['AGR_VIEWER_HP_ARCHIVE']
lp_archive = source / os.environ['AGR_VIEWER_LP_ARCHIVE']
addon.register()
assert not bpy.data.filepath
sentinel = bpy.data.objects.get('Cube')
sentinel['viewer_test'] = 'preserved'
mat = bpy.data.materials.new('Viewer_existing_material')
mat.diffuse_color = (.1, .2, .3, 1.)
scratch_before = set((work / 'temp').iterdir())
bpy.context.scene.render.fps = 48
bpy.context.scene.render.fps_base = 1.001
fps_before = (bpy.context.scene.render.fps, bpy.context.scene.render.fps_base)
result = importer.import_archives([
    hp_archive, lp_archive],
    scratch_directory=work / 'temp')
assert sentinel['viewer_test'] == 'preserved'
assert (bpy.context.scene.render.fps, bpy.context.scene.render.fps_base) == fps_before, 'FBX changed scene FPS'
assert tuple(round(v, 3) for v in mat.diffuse_color) == (.1, .2, .3, 1.)
assert not bpy.data.filepath
assert set((work / 'temp').iterdir()) == scratch_before, 'Extraction leftovers'
owned = [o for o in bpy.context.scene.objects if o.get('airmetric_kind')]
assert any(o['airmetric_kind'] == 'HP' for o in owned)
assert any(o['airmetric_kind'] == 'LP' for o in owned)
settings = bpy.context.scene.airmetric_agr
settings.show_hp = False
settings.show_lp = True
assert all(o.hide_get() for o in owned if o['airmetric_kind'] == 'HP')
assert any(not o.hide_get() for o in owned if o['airmetric_kind'] == 'LP')
settings.show_hp = True
settings.show_lp = False
assert all(o.hide_get() for o in owned if o['airmetric_kind'] == 'LP')
images = [i for i in bpy.data.images if i.get('airmetric_owned')]
assert images and all(i.packed_file for i in images)
tiled = [i for i in images if i.source == 'TILED']
assert len(tiled) == 3
assert all(len(i.tiles) == len(i.packed_files) == 12 for i in tiled)
assert all(str(p.tile_number) in p.filepath for i in tiled for p in i.packed_files)
before = {kind: len(getattr(bpy.data, kind)) for kind in ('objects', 'meshes', 'materials', 'images', 'collections')}
try:
    importer.import_archives([lp_archive, work / 'missing.zip'],
                             scratch_directory=work / 'temp')
    raise AssertionError('Missing input accepted')
except (FileNotFoundError, RuntimeError):
    pass
assert before == {kind: len(getattr(bpy.data, kind)) for kind in before}, 'Rollback leaked data'
assert (bpy.context.scene.render.fps, bpy.context.scene.render.fps_base) == fps_before
# Import operator must not report failure after committing data with switches off.
settings.show_hp = False
settings.show_lp = False
area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
state = importer.snapshot()
with bpy.context.temp_override(area=area):
    status = bpy.ops.airmetric.open_archives(filepath=str(lp_archive))
assert status == {'FINISHED'}, status
importer.rollback(state)
settings.show_hp = True
summary = {'blender': bpy.app.version_string, 'objects': len(owned),
           'images': len(images), 'tiles': [len(i.tiles) for i in tiled], 'result': result}
(work / 'integration.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(work / 'viewer_test.blend'))
addon.unregister()
addon.register()
addon.unregister()
print('AGR_VIEWER_INTEGRATION_OK', json.dumps(summary, ensure_ascii=False))
