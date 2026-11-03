"""Transactional import into the current scene, including unsaved scenes."""
import json
from pathlib import Path
import bpy
from . import agr, archive, materials, fbx

_DATA = ('objects', 'collections', 'meshes', 'materials', 'images', 'actions',
         'armatures', 'cameras', 'lights', 'curves')


def snapshot():
    return {name: set(getattr(bpy.data, name)) for name in _DATA}


def rollback(before):
    for name in _DATA:
        collection = getattr(bpy.data, name)
        for item in set(collection) - before[name]:
            collection.remove(item, do_unlink=True)


def metadata_for(path, files):
    stem = path.stem.removesuffix('_Light')
    candidates = [p for p in files if p.suffix.lower() == '.geojson']
    exact = [p for p in candidates if p.stem.casefold() == stem.casefold()]
    target = exact[0] if len(exact) == 1 else candidates[0] if len(candidates) == 1 else None
    if target is None:
        if agr.model_kind(path.name) == 'HP':
            raise ValueError(f'Для ВПМ {path.name} не найден однозначный GeoJSON с расположением')
        return {}
    return json.loads(target.read_text(encoding='utf-8-sig'))


def import_archives(paths, *, scratch_directory=None, progress=None):
    if bpy.context.mode != 'OBJECT':
        raise RuntimeError('Завершите редактирование объекта перед загрузкой')
    before = snapshot()
    selection = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    active_collection = bpy.context.view_layer.active_layer_collection
    timing = (bpy.context.scene.render.fps, bpy.context.scene.render.fps_base)
    imported = []
    paths = list(dict.fromkeys(Path(p).resolve() for p in paths))
    if not paths:
        raise ValueError('Выберите хотя бы один ZIP-архив')
    try:
        for index, source in enumerate(paths):
            if progress:
                progress(index, len(paths), source.name)
            with archive.extracted(source, directory=scratch_directory) as (root, files):
                groups = agr.texture_sets(files)
                for path in sorted(p for p in files if p.suffix.lower() == '.fbx'):
                    payload = metadata_for(path, files)
                    kind = agr.model_kind(path.name)
                    state = snapshot()
                    collection = bpy.data.collections.new(path.stem)
                    collection['airmetric_kind'] = kind
                    collection['airmetric_archive'] = source.name
                    bpy.context.scene.collection.children.link(collection)
                    bpy.context.view_layer.update()
                    layer = bpy.context.view_layer.layer_collection.children[collection.name]
                    bpy.context.view_layer.active_layer_collection = layer
                    status = fbx.load(path, state['materials'], state['images'])
                    if 'FINISHED' not in status:
                        raise RuntimeError('Не удалось прочитать FBX: ' + path.name)
                    objects = set(bpy.data.objects) - state['objects']
                    optional_lights = path.stem.lower().endswith('_light')
                    if not objects and optional_lights:
                        bpy.data.collections.remove(collection)
                        continue  # Valid AGR packages may contain an empty lighting FBX.
                    if not any(o.type == 'MESH' for o in objects) and not optional_lights:
                        raise RuntimeError('В FBX нет геометрии: ' + path.name)
                    # Isolate any reused material before assigning AGR metadata.
                    copies = {}
                    for obj in objects:
                        if obj.type == 'MESH':
                            for slot in obj.material_slots:
                                if slot.material in before['materials']:
                                    original = slot.material
                                    if original not in copies:
                                        copies[original] = original.copy()
                                    slot.material = copies[original]
                        obj['airmetric_kind'] = kind
                        obj['airmetric_role'] = 'light' if path.stem.lower().endswith('_light') else agr.object_role(obj.name)
                    if kind == 'HP':
                        coordinates = agr.position(payload)
                        if coordinates is None:
                            raise ValueError('В GeoJSON нет координат и h_relief: ' + path.name)
                        for obj in objects:
                            if obj.parent not in objects:
                                obj.location = coordinates
                    channels = agr.textures_for_model(groups, path.name)
                    if kind == 'HP' and not channels and any(o['airmetric_role'] == 'model' for o in objects):
                        raise ValueError('Не найдены текстуры ВПМ: ' + path.name)
                    # Light FBX carries its own emission material; do not replace it.
                    if path.stem.lower().endswith('_light'):
                        channels = {}
                    materials.configure(objects, payload, channels, kind)
                    materials.pack_referenced(objects, set(bpy.data.images) - before['images'])
                    imported.extend(objects)
        from .viewport import apply_visibility
        bpy.context.view_layer.update()
        apply_visibility(bpy.context.scene, bpy.context)
        return {'archives': len(paths), 'objects': len(imported),
                'hp': sum(o['airmetric_kind'] == 'HP' for o in imported),
                'lp': sum(o['airmetric_kind'] == 'LP' for o in imported)}
    except Exception:
        rollback(before)
        raise
    finally:
        bpy.context.scene.render.fps, bpy.context.scene.render.fps_base = timing
        bpy.context.view_layer.active_layer_collection = active_collection
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in selection:
            if obj.name in bpy.context.view_layer.objects and not obj.hide_get():
                obj.select_set(True)
        bpy.context.view_layer.objects.active = active
