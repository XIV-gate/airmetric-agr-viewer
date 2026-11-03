"""Complete real projects; all original ZIP files remain read-only."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy
import airmetric_agr_viewer as addon
from airmetric_agr_viewer import importer, agr

root = Path(os.environ['AGR_VIEWER_TEST_ROOT'])
fixtures = Path(os.environ['AGR_VIEWER_FIXTURES'])
container = os.environ.get('AGR_VIEWER_PROJECT_CONTAINER')
paths = [fixtures/container] if container else sorted(fixtures.glob('*.zip'))
assert paths
source_state = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}
addon.register()
before = set((root/'temp').iterdir())
result = importer.import_archives(paths, scratch_directory=root/'temp')
assert before == set((root/'temp').iterdir())
assert source_state == {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}
objects = [o for o in bpy.context.scene.objects if o.get('airmetric_kind')]
assert any(o['airmetric_kind'] == 'HP' for o in objects)
assert any(o['airmetric_kind'] == 'LP' for o in objects)
images = [i for i in bpy.data.images if i.get('airmetric_owned')]
assert images and all(i.packed_file for i in images)
for image in images:
    if image.source == 'TILED':
        assert {t.number for t in image.tiles} == {p.tile_number for p in image.packed_files}
        assert all(str(p.tile_number) in p.filepath for p in image.packed_files)
# Every HP root must match the GeoJSON coordinates retained on its collection.
settings = bpy.context.scene.airmetric_agr
settings.show_hp = False
assert all(o.hide_get() for o in objects if o['airmetric_kind'] == 'HP')
assert any(not o.hide_get() for o in objects if o['airmetric_kind'] == 'LP')
settings.show_hp = True; settings.show_lp = False
assert all(o.hide_get() for o in objects if o['airmetric_kind'] == 'LP')
name = fixtures.parent.name
summary = {'project': name, 'input_archives': [p.name for p in paths], 'result': result,
           'images': len(images), 'udim_tiles': sum(len(i.tiles) for i in images if i.source == 'TILED'),
           'source_files_unchanged': True, 'no_extraction_leftovers': True}
(root/('real_'+name+'.json')).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(root/('real_'+name+'.blend')))
print('AGR_VIEWER_REAL_PROJECT_OK', json.dumps(summary, ensure_ascii=False), flush=True)
addon.unregister()
