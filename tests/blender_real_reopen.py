import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy
import airmetric_agr_viewer as addon
addon.register()
root = Path(os.environ['AGR_VIEWER_TEST_ROOT'])
summary = json.loads(Path(bpy.data.filepath).with_suffix('.json').read_text(encoding='utf8'))
images = [i for i in bpy.data.images if i.get('airmetric_owned')]
assert len(images) == summary['images']
tiles = 0
for image in images:
    assert image.packed_file, image.name
    if image.source == 'TILED':
        assert {p.tile_number for p in image.packed_files} == {t.number for t in image.tiles}
        tiles += len(image.tiles)
    image.buffers_free()
    assert image.size[0] > 0 and image.has_data, image.name
    image.buffers_free()
assert tiles == summary['udim_tiles']
print('AGR_VIEWER_REAL_REOPEN_OK', summary['project'], len(images), 'images', tiles, 'UDIM tiles')
addon.unregister()
