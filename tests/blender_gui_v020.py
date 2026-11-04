"""One real Blender UI image using demonstration geometry and filenames only."""
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
work = Path(os.environ['AGR_VIEWER_TEST_ROOT'])
# Reuse the old demonstration model, without its screenshot or Preferences code.
source = (ROOT/'tests'/'blender_gui.py').read_text(encoding='utf8')
exec(compile(source.split('bpy.context.preferences.view.show_splash')[0], str(ROOT/'tests'/'blender_gui.py'), 'exec'))
from airmetric_agr_viewer import jobs


def activate():
    area = next(a for a in bpy.context.window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.screen.screen_full_area(use_hide_panels=False)
    for area in bpy.context.window.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.show_region_ui = True
            area.spaces.active.show_region_toolbar = False
            for region in area.regions:
                if region.type == 'UI':
                    region.active_panel_category = 'Airmetric'
    return None


def show_review():
    paths = [work/'temp'/f'Здание_{n:02d}.zip' for n in range(1, 8)]
    job = jobs.Job(paths, bpy.context.scene)
    job.thread.start(); job.thread.join()
    job.rows = [{'path': str(p), 'name': p.name, 'status': 'ready', 'reason': '', 'models': 1, 'stamp': (0, 0)} for p in paths]
    job.rows.extend([
        {'path': '', 'name': 'Документы.zip', 'status': 'skipped', 'reason': 'В архиве нет модели АГР в формате FBX'},
        {'path': '', 'name': 'Повреждённый.zip', 'status': 'skipped', 'reason': 'Повреждённый или неподдерживаемый ZIP'}])
    job.prepare(); job.phase = 'review'; jobs.ACTIVE = job
    area = next(a for a in bpy.context.window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.airmetric.review_queue('INVOKE_DEFAULT')
    return None


def capture():
    bpy.ops.screen.screenshot(filepath=str(ROOT/'docs'/'images'/'viewer_0.2.0.png'))
    print('VIEWER_020_SCREENSHOT_OK', flush=True)
    return None


def finish():
    jobs.stop()
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(activate, first_interval=2)
bpy.app.timers.register(lambda: bpy.ops.screen.screenshot(filepath=str(work/'temp'/'clear_v020.png')) and None, first_interval=5)
bpy.app.timers.register(show_review, first_interval=6)
bpy.app.timers.register(capture, first_interval=9)
bpy.app.timers.register(finish, first_interval=11)
