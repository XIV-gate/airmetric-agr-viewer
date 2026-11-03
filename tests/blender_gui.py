"""Synthetic architecture screenshots from an isolated real Blender GUI."""
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Euler
from math import radians
import airmetric_agr_viewer as addon
addon.register()

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)


def material(name, color, metallic=0.):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Metallic'].default_value = metallic
    shader.inputs['Roughness'].default_value = .32 if metallic else .65
    return mat


wall = material('Светлый фасад', (.64, .59, .48))
glass = material('Стекло', (.06, .14, .2), .5)
ground = material('Газон', (.13, .23, .12))
roof = material('Кровля', (.12, .14, .16))


def box(name, location, scale, mat, role='model'):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    obj['airmetric_kind'] = 'HP'
    obj['airmetric_role'] = role
    return obj


box('Демонстрационный участок', (0, 0, -.15), (24, 18, .3), ground)
box('Демонстрационное здание', (0, 0, 6), (12, 7, 12), wall)
box('Кровля', (0, 0, 12.2), (12.3, 7.3, .4), roof)
for floor in range(4):
    for x in range(6):
        for side in (-1, 1):
            box('Окно', (-5 + x*2, side*3.51, 1.5 + floor*2.8), (1.2, .04, 1.8), glass, 'glass')
for floor in range(4):
    for y in range(3):
        for side in (-1, 1):
            box('Боковое окно', (side*6.01, -2.4+y*2.4, 1.5+floor*2.8), (.04, 1.2, 1.8), glass, 'glass')
bpy.ops.object.select_all(action='DESELECT')
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            space = area.spaces.active
            space.show_region_ui = True
            space.overlay.show_overlays = False
            space.shading.type = 'MATERIAL'
            space.region_3d.view_location = (0, 0, 5)
            space.region_3d.view_distance = 35
            space.region_3d.view_rotation = Euler((radians(65), 0, radians(35))).to_quaternion()
            space.region_3d.view_perspective = 'PERSP'
            for region in area.regions:
                if region.type == 'UI':
                    try:
                        region.active_panel_category = 'Airmetric'
                    except AttributeError:
                        pass
            print('UI_REGION_PROPERTIES', [p.identifier for r in area.regions if r.type == 'UI' for p in r.bl_rna.properties])
bpy.context.scene.airmetric_agr.status = 'Пример: демонстрационное здание'
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.show_tooltips = False


def capture():
    path = ROOT / 'docs' / 'images' / 'viewer.png'
    bpy.ops.screen.screenshot(filepath=str(path))
    print('AGR_VIEWER_SCREENSHOT', str(path), flush=True)
    return None


def solid():
    for area in bpy.context.window.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.shading.type = 'SOLID'
    return None


def capture_solid():
    bpy.ops.screen.screenshot(filepath=str(ROOT / 'docs' / 'images' / 'solid.png'))
    return None


def finish():
    bpy.ops.wm.quit_blender()
    return None

def activate():
    for area in bpy.context.window.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'UI':
                    region.active_panel_category = 'Airmetric'
            area.tag_redraw()
    return None

bpy.app.timers.register(activate, first_interval=3)
bpy.app.timers.register(capture, first_interval=12)
bpy.app.timers.register(solid, first_interval=14)
bpy.app.timers.register(capture_solid, first_interval=17)
bpy.app.timers.register(finish, first_interval=19)
