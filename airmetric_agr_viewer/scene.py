"""Remove scene content without touching files, Preferences or other scenes."""
import hashlib
import os
from pathlib import Path
import bpy

_KINDS = ('objects', 'collections', 'meshes', 'materials', 'images', 'actions',
          'armatures', 'cameras', 'lights', 'curves', 'node_groups', 'textures',
          'worlds', 'metaballs', 'lattices', 'speakers', 'volumes', 'pointclouds',
          'hair_curves', 'grease_pencils', 'shape_keys')


def source_key(path):
    value = os.path.normcase(str(Path(path).resolve()))
    return hashlib.sha256(value.encode('utf8')).hexdigest()


def archive_groups(scene, path, digest=None):
    key = source_key(path)
    return [c for c in scene.collection.children_recursive
            if c.get('airmetric_source') == key
            or digest and c.get('airmetric_digest') == digest]


def _dependencies(seeds):
    allowed = {item for kind in _KINDS for item in getattr(bpy.data, kind, ())}
    dependencies = {}
    for item, users in bpy.data.user_map().items():
        for user in users:
            dependencies.setdefault(user, set()).add(item)
    result, visited, pending = set(), set(), list(seeds)
    while pending:
        item = pending.pop()
        if item in visited or not (item in allowed or isinstance(item, bpy.types.NodeTree)):
            continue
        visited.add(item)
        if item in allowed:
            result.add(item)
        tree = getattr(item, 'node_tree', None)
        if tree:
            pending.append(tree)
        pending.extend(dependencies.get(item, ()))
    return result


def _purge(candidates):
    # A cycle of parents/constraints can keep users > 0 without any scene user.
    owners = {item.node_tree: item for kind in ('materials', 'worlds', 'lights', 'scenes')
              for item in getattr(bpy.data, kind) if getattr(item, 'node_tree', None)}
    users = {item: {owners.get(user, user) for user in refs}
             for item, refs in bpy.data.user_map().items()}
    live = {item for item in candidates if any(user not in candidates for user in users.get(item, ()))}
    changed = True
    while changed:
        added = {item for item in candidates - live if users.get(item, set()) & live}
        changed = bool(added)
        live.update(added)
    unused = candidates - live
    for item in unused:
        item.use_fake_user = False
    if unused:
        bpy.data.batch_remove(ids=unused)
    return len(unused)


def remove_groups(scene, groups):
    """Replacement only removes groups still directly attached to this scene."""
    groups = list(groups)
    if any(c.name not in scene.collection.children for c in groups):
        raise ValueError('Архив перемещён в другую коллекцию. Сначала очистите сцену или пропустите повтор.')
    candidates = _dependencies(groups)
    for collection in groups:
        scene.collection.children.unlink(collection)
    bpy.context.view_layer.update()
    return _purge(candidates)


def clear(scene):
    if bpy.context.mode != 'OBJECT':
        raise ValueError('Завершите редактирование объекта перед очисткой')
    seeds = list(scene.objects) + list(scene.collection.children_recursive)
    if scene.world:
        seeds.append(scene.world)
    candidates = _dependencies(seeds)
    count = len(scene.objects)
    # Detaching the root preserves objects/collections linked to other scenes.
    for obj in list(scene.collection.objects):
        scene.collection.objects.unlink(obj)
    for collection in list(scene.collection.children):
        scene.collection.children.unlink(collection)
    scene.camera = None
    scene.world = None
    if scene.animation_data:
        scene.animation_data_clear()
    # Refresh view-layer bases before consulting the ID user graph (Blender 5.x).
    bpy.context.view_layer.objects.active = None
    bpy.context.view_layer.update()
    removed = _purge(candidates)
    settings = scene.airmetric_agr
    for name in ('show_hp', 'show_lp', 'show_glass', 'show_lights', 'show_collisions'):
        settings.property_unset(name)
    settings.status = 'Сцена очищена. Выберите архивы следующего проекта.'
    return {'objects': count, 'data': removed}
