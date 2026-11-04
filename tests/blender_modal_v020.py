"""Exercise the actual window timer and modal operator on synthetic archives."""
import os
from pathlib import Path
import sys
import time
import zipfile
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
import airmetric_agr_viewer as addon
from airmetric_agr_viewer import jobs, scene, ui
addon.register()
work = Path(os.environ['AGR_VIEWER_TEST_ROOT'])/'temp'
files = [work/'0000_Demo_01.fbx', work/'demo_modal_first.zip', work/'demo_modal_second.zip']
assert all(not p.exists() for p in files)
scene.clear(bpy.context.scene)
bpy.ops.mesh.primitive_cube_add()
bpy.ops.export_scene.fbx(filepath=str(files[0]), use_selection=True)
for archive in files[1:]:
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(files[0], '0000_Demo_01.fbx')
scene.clear(bpy.context.scene)
state = {'step': 0, 'started': time.monotonic()}


def open_archive(path):
    area = next(a for a in bpy.context.window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(area=area, region=region):
        assert bpy.ops.airmetric.open_archives(filepath=str(path)) == {'FINISHED'}


def finish():
    jobs.stop()
    for p in files:
        p.unlink(missing_ok=True)
    bpy.ops.wm.quit_blender()


def tick():
    try:
        assert time.monotonic() - state['started'] < 35, 'Modal timer timeout'
        step = state['step']
        if step == 0:
            open_archive(files[1]); state['step'] = 1
        elif step == 1 and not jobs.busy():
            print('MODAL_FIRST_RESULT', jobs.LAST.message if jobs.LAST else 'no result', bpy.context.scene.airmetric_agr.status, flush=True)
            if jobs.LAST:
                print('MODAL_ROWS', [(r['name'], r['reason']) for r in jobs.LAST.rows], flush=True)
            assert jobs.LAST and jobs.LAST.loaded == 1
            assert len(bpy.context.scene.objects) == 1
            # A copied ZIP must be recognized by content, not only path.
            open_archive(files[2]); state['step'] = 2
        elif step == 2 and jobs.ACTIVE and jobs.ACTIVE.phase == 'review':
            assert jobs.ACTIVE.duplicates
            bpy.ops.airmetric.stop_queue(); state['step'] = 3
        elif step == 3 and not jobs.busy():
            assert len(bpy.context.scene.objects) == 1
            open_archive(files[1]); ui.stop_before_scene_change(None)
            state['step'] = 4
        elif step == 4 and not jobs.busy():
            assert bpy.ops.airmetric.clear_scene('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
            assert len(bpy.context.scene.objects) == 1
            assert bpy.ops.airmetric.clear_scene() == {'FINISHED'}
            assert not bpy.context.scene.objects
            print('VIEWER_020_MODAL_OK', flush=True)
            finish(); return None
        return .08
    except Exception:
        import traceback
        traceback.print_exc()
        print('VIEWER_020_MODAL_FAILED', flush=True)
        finish()
        return None


bpy.app.timers.register(tick, first_interval=1)
