import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy
import airmetric_agr_viewer as addon
addon.register()
root = Path(os.environ['AGR_VIEWER_TEST_ROOT'])
images = [i for i in bpy.data.images if i.get('airmetric_owned')]
assert len(images) == 30
for image in images:
    assert image.packed_file
    if image.source == 'TILED':
        assert len(image.packed_files) == len(image.tiles) == 12
    image.buffers_free()
    assert image.size[0] > 0 and image.has_data, image.name
assert not any(p.suffix.lower() in ('.png', '.fbx', '.geojson') for p in (root / 'temp').iterdir())
assert bpy.data.objects['Cube']['viewer_test'] == 'preserved'
print('AGR_VIEWER_REOPEN_OK', len(images), 'packed images; all tiles remain packed')
addon.unregister()
