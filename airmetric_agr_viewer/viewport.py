"""Visibility affects viewer-owned objects in the current scene only."""
import bpy
from mathutils import Vector


def apply_visibility(scene, context):
    settings = scene.airmetric_agr
    for obj in scene.objects:
        kind = obj.get('airmetric_kind')
        if not kind or obj.name not in context.view_layer.objects:
            continue
        role = obj.get('airmetric_role', 'model')
        visible = settings.show_hp if kind == 'HP' else settings.show_lp
        if role == 'collision':
            visible = visible and settings.show_collisions
        elif role == 'glass':
            visible = visible and settings.show_glass
        elif role == 'light':
            visible = visible and settings.show_lights
        obj.hide_set(not visible)


def frame(context):
    objects = [o for o in context.scene.objects if o.get('airmetric_kind')
               and o.type == 'MESH' and o.visible_get(view_layer=context.view_layer)]
    if not objects:
        raise ValueError('Нет видимых моделей. Включите ВПМ или НПМ.')
    corners = [o.matrix_world @ Vector(corner) for o in objects for corner in o.bound_box]
    low = Vector(tuple(min(p[i] for p in corners) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in corners) for i in range(3)))
    region = context.space_data.region_3d
    region.view_location = (low + high) * .5
    region.view_distance = max((high - low).length * 1.2, .1)
    context.space_data.clip_end = max(10000., region.view_distance * 10)
    context.space_data.clip_start = .01
