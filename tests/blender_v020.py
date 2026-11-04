"""Isolated real-host coverage; private inputs are supplied only by environment."""
import os
from pathlib import Path
import sys
import time
import zipfile
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy
import airmetric_agr_viewer as addon
from airmetric_agr_viewer import scene, importer, jobs, preflight, ui

root = Path(os.environ['AGR_VIEWER_TEST_ROOT'])
assert all(Path(os.environ[key]).resolve().is_relative_to(root.resolve()) for key in
           ('BLENDER_USER_CONFIG', 'BLENDER_USER_SCRIPTS', 'BLENDER_USER_DATAFILES', 'BLENDER_USER_EXTENSIONS', 'TEMP'))
addon.register()
assert not bpy.data.filepath
assert addon.bl_info['version'] == (0, 2, 0)
assert 'confirm_text' in bpy.types.WindowManager.invoke_confirm.__doc__
current = bpy.context.scene
scene.clear(current)

# A private resource must be released, while shared resources survive.
mesh = bpy.data.meshes.new('DemoPrivateMesh')
private = bpy.data.objects.new('DemoPrivate', mesh)
current.collection.objects.link(private)
mat = bpy.data.materials.new('DemoPrivateMaterial'); mat.use_nodes = True
image = bpy.data.images.new('DemoPrivateImage', width=4, height=4)
image.pack(); image.use_fake_user = True
mat.node_tree.nodes.new('ShaderNodeTexImage').image = image
private.data.materials.append(mat)
other = bpy.data.scenes.new('DemoOtherScene')
shared_mesh = bpy.data.meshes.new('DemoSharedMesh')
shared = bpy.data.objects.new('DemoShared', shared_mesh)
current.collection.objects.link(shared); other.collection.objects.link(shared)
shared_mat = bpy.data.materials.new('DemoSharedMaterial'); shared_mat.use_nodes = True
shared_image = bpy.data.images.new('DemoSharedImage', width=4, height=4); shared_image.pack()
shared_mat.node_tree.nodes.new('ShaderNodeTexImage').image = shared_image
mesh.materials.append(shared_mat); shared_mesh.materials.append(shared_mat)
shared_world = bpy.data.worlds.new('DemoSharedWorld')
current.world = shared_world; other.world = shared_world
cyclic_a = bpy.data.objects.new('DemoCycleA', None)
cyclic_b = bpy.data.objects.new('DemoCycleB', None)
current.collection.objects.link(cyclic_a); current.collection.objects.link(cyclic_b)
cyclic_a.constraints.new('COPY_LOCATION').target = cyclic_b
cyclic_b.constraints.new('COPY_LOCATION').target = cyclic_a
current.airmetric_agr.show_hp = False
scene.clear(current)
assert not current.objects and not current.collection.children
if 'DemoPrivateMesh' in bpy.data.meshes:
    for data, refs in bpy.data.user_map().items():
        if data.name in {'DemoPrivate', 'DemoPrivateMesh', 'DemoPrivateMaterial', 'DemoPrivateImage'}:
            print('CLEAR_RESOURCE_USERS', data.name, [(r.bl_rna.identifier, r.name) for r in refs], flush=True)
assert 'DemoPrivateMesh' not in bpy.data.meshes
assert 'DemoPrivateMaterial' not in bpy.data.materials
assert 'DemoPrivateImage' not in bpy.data.images
assert 'DemoCycleA' not in bpy.data.objects and 'DemoCycleB' not in bpy.data.objects
assert shared.name in other.objects and shared_mesh.name in bpy.data.meshes
assert shared_mat.name in bpy.data.materials and shared_image.name in bpy.data.images
assert other.world == shared_world
assert current.airmetric_agr.show_hp and current.airmetric_agr.show_lp
scene.clear(current)
assert shared.name in other.objects
print('VIEWER_CLEAR_SHARED_DATA_OK', flush=True)

# FBX recovery regression: aliases must not shadow the image lookup dictionary.
from airmetric_agr_viewer import fbx
original_source = fbx.source_materials
try:
    test_mat = bpy.data.materials.new('DemoRecovery'); test_mat.use_nodes = True
    fbx.source_materials = lambda p: {'DemoRecovery': (1., {'DiffuseColor': ('missing.png', None)})}
    try:
        fbx.recover_materials(root/'missing.fbx', [test_mat], set())
        raise AssertionError('Missing texture accepted')
    except RuntimeError as error:
        assert 'текстура' in str(error)
finally:
    fbx.source_materials = original_source
    bpy.data.materials.remove(test_mat)
print('VIEWER_MATERIAL_RECOVERY_OK', flush=True)

fixtures = Path(os.environ['AGR_VIEWER_FIXTURES'])
paths = sorted(fixtures.glob('*.zip'))
assert paths
if os.environ.get('AGR_VIEWER_PROJECT_CONTAINER'):
    paths = [fixtures/os.environ['AGR_VIEWER_PROJECT_CONTAINER']]
originals = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}
rows = preflight.inspect_selection(paths)
assert all(row['status'] == 'ready' for row in rows), [(i, r['reason']) for i, r in enumerate(rows)]
rows = preflight.deduplicate(rows)
expected_archives = sum(row['status'] == 'ready' for row in rows)
scratch_before = set((root/'temp').iterdir())
job = jobs.Job(paths, current)
job.rows = rows; job.phase = 'loading'; job.prepare()
while job.phase != 'done':
    job.load_next()
assert job.loaded == expected_archives, [(i, r['reason']) for i, r in enumerate(job.rows)]
assert all(i.packed_file for i in bpy.data.images if i.get('airmetric_owned'))
assert set((root/'temp').iterdir()) == scratch_before
assert originals == {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}
print('VIEWER_REAL_QUEUE_OK', job.loaded, job.objects, flush=True)

first = Path(next(row['path'] for row in rows if row['status'] == 'loaded'))
before = importer.snapshot()
repeat = jobs.Job([first], current)
repeat.rows = preflight.inspect_selection([first])
repeat.duplicates = {str(first.resolve())}; repeat.prepare()
assert not repeat.pending
assert all(set(getattr(bpy.data, key)) == value for key, value in before.items())

# Failure of replacement must keep the exact old data.
old_groups = scene.archive_groups(current, first)
assert old_groups
repeat.replace = True; repeat.prepare(); repeat.phase = 'loading'
original_import = importer.import_archives
def fail_import(*args, **kwargs):
    temp = bpy.data.objects.new('DemoFailedTemporary', None)
    current.collection.objects.link(temp)
    raise ValueError('Демонстрационная ошибка загрузки')
try:
    importer.import_archives = fail_import
    repeat.load_next()
finally:
    importer.import_archives = original_import
assert all(c.name in bpy.data.collections for c in old_groups)
assert 'DemoFailedTemporary' not in bpy.data.objects
assert repeat.rows[0]['status'] == 'error'

# Successful replacement keeps one loaded instance.
repeat = jobs.Job([first], current)
repeat.rows = preflight.inspect_selection([first]); repeat.replace = True
repeat.prepare(); repeat.phase = 'loading'; repeat.load_next()
assert repeat.loaded == 1, repeat.rows[0]['reason']
assert len(scene.archive_groups(current, first)) == len(old_groups)
print('VIEWER_DUPLICATE_REPLACEMENT_OK', flush=True)

# Stop between archives preserves the loaded result.
count = len(current.objects)
stopped = jobs.Job(paths, current); stopped.rows = preflight.inspect_selection(paths)
stopped.prepare(); stopped.phase = 'loading'; stopped.cancelled.set(); stopped.load_next()
assert stopped.phase == 'done' and len(current.objects) == count

# A stale scene reference is detected, and undo/load callbacks release the job.
stale = bpy.data.scenes.new('DemoStaleScene')
stale_job = jobs.Job([], stale); bpy.data.scenes.remove(stale)
assert not jobs.scene_valid(stale_job)
pending = jobs.start(paths, current)
ui.stop_before_scene_change(None)
assert not jobs.busy()

scene.clear(current)
assert not current.objects and not current.collection.children
assert not [i for i in bpy.data.images if i.get('airmetric_owned')]
assert shared.name in other.objects
assert set((root/'temp').iterdir()) == scratch_before
addon.unregister(); addon.register(); addon.unregister()
print('VIEWER_020_INTEGRATION_OK', bpy.app.version_string, flush=True)
