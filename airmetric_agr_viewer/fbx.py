"""Blender FBX adapter and source-material recovery, without external packages.

Blender's bundled FBX reader supplies the binary format parser. Native FBX import
supports Max Physical Material maps, but may omit Phong opacity. The older Python
importer needs missing Physical Material texture connections restored as well.
"""
from pathlib import Path
import bpy

_MAPS = {
    'Base Color': ('DiffuseColor', '3dsMax|maps|texmap_diffuse', '3dsMax|Parameters|base_color_map'),
    'Metallic': ('ReflectionFactor', 'ReflectionColor', '3dsMax|maps|texmap_reflection', '3dsMax|Parameters|metalness_map'),
    'Roughness': ('ShininessExponent', '3dsMax|Parameters|roughness_map'),
    'Alpha': ('TransparentColor', 'TransparencyFactor', '3dsMax|Parameters|cutout_map'),
    'Normal': ('NormalMap', 'Bump', '3dsMax|maps|texmap_bump', '3dsMax|Parameters|bump_map'),
}


def text(value):
    return value.decode('utf8', errors='replace') if isinstance(value, bytes) else str(value)


def child(element, identifier):
    return next((c for c in element.elems if c.id == identifier), None)


def properties(element):
    group = child(element, b'Properties70')
    result = {}
    for item in group.elems if group else ():
        if item.id == b'P' and len(item.props) > 4:
            values = item.props[4:]
            result[text(item.props[0])] = values[0] if len(values) == 1 else tuple(values)
    return result


def image_key(value):
    return value.replace('\\', '/').rsplit('/', 1)[-1].casefold()


def source_materials(path):
    from io_scene_fbx import parse_fbx
    root, _version = parse_fbx.parse(str(path))
    objects, connections = child(root, b'Objects'), child(root, b'Connections')
    if objects is None:
        return {}
    by_id = {item.props[0]: item for item in objects.elems if item.props}
    templates = {}
    definitions = child(root, b'Definitions')
    for item in definitions.elems if definitions else ():
        if item.id == b'ObjectType' and item.props[0] == b'Material':
            for template in item.elems:
                if template.id == b'PropertyTemplate':
                    templates.update(properties(template))
    material_links, video_links = {}, {}
    for link in connections.elems if connections else ():
        if link.id != b'C' or len(link.props) < 3:
            continue
        source, target = by_id.get(link.props[1]), by_id.get(link.props[2])
        if source is None or target is None:
            continue
        if source.id == b'Texture' and target.id == b'Material' and len(link.props) > 3:
            material_links.setdefault(target.props[0], {})[text(link.props[3])] = source
        if source.id == b'Video' and target.id == b'Texture':
            video_links[target.props[0]] = source
    result = {}
    for element in objects.elems:
        if element.id != b'Material':
            continue
        own = properties(element)
        merged = templates | own
        def scalar(name, default=0.):
            value = merged.get(name, default)
            return float(value[0] if isinstance(value, tuple) else value)
        alpha = 1 - scalar('TransparencyFactor')
        if alpha in (0., 1.):
            alpha = float(own['Opacity']) if 'Opacity' in own else 1 - scalar('TransparentColor')
        maps = {}
        for prop, texture in material_links.get(element.props[0], {}).items():
            video = video_links.get(texture.props[0])
            filename = None
            for owner in (texture, video):
                if owner is None:
                    continue
                for field in (b'RelativeFilename', b'FileName', b'Filename'):
                    node = child(owner, field)
                    if node and node.props and node.props[0]:
                        filename = text(node.props[0]); break
                if filename:
                    break
            content = child(video, b'Content') if video else None
            if filename:
                maps[prop] = (filename, content.props[0] if content and content.props else None)
        name = text(element.props[1]).split('\x00\x01')[0]
        result[name] = (max(0., min(1., alpha)), maps)
    return result


def recover_materials(path, new_materials, owned_images):
    from .materials import shader
    import re
    source = source_materials(path)
    # Only this FBX's newly created images are candidates. A previous package may
    # embed a different image with the same basename (e.g. diffuse.png).
    candidates = {}
    for image in owned_images:
        for key in {image_key(image.filepath or image.name), image_key(image.name)}:
            candidates.setdefault(key, []).append(image)
    for material in new_materials:
        name = material.name
        entry = source.get(name, source.get(re.sub(r'\.\d{3}$', '', name)))
        if entry is None:
            continue
        alpha, maps = entry
        bsdf = shader(material)
        if not bsdf.inputs['Alpha'].is_linked:
            bsdf.inputs['Alpha'].default_value = alpha
        for socket, candidates in _MAPS.items():
            data = next((maps[p] for p in candidates if p in maps), None)
            if data is None:
                continue
            target = bsdf.inputs[socket]
            if target.is_linked:
                previous = target.links[0].from_node
                if previous.type != 'NORMAL_MAP' or previous.inputs['Color'].is_linked:
                    continue
                target = previous.inputs['Color']
            filename, embedded = data
            key = image_key(filename)
            choices = candidates.get(key, [])
            image = choices[0] if len(choices) == 1 else None
            if image is None and embedded:
                image = next((i for i in choices if i.packed_file and i.packed_file.data == embedded), None)
            if image is None and embedded:
                from bpy_extras import image_utils
                image = image_utils.load_image(key, dirname=str(Path(path).parent),
                                               place_holder=True, recursive=False, check_existing=False)
                image.pack(data=embedded, data_len=len(embedded))
                candidates[key] = [image]
            if image is None:
                external = Path(path).parent / Path(filename.replace('\\', '/')).name
                if external.is_file():
                    image = bpy.data.images.load(str(external), check_existing=False)
                    candidates[key] = [image]
            if image is None:
                raise RuntimeError('В FBX отсутствует необходимая текстура: ' + filename)
            image.colorspace_settings.name = 'sRGB' if socket == 'Base Color' else 'Non-Color'
            node = material.node_tree.nodes.new('ShaderNodeTexImage')
            node.image = image
            node.location = (-600, 100)
            if socket == 'Normal' and target == bsdf.inputs['Normal']:
                normal = material.node_tree.nodes.new('ShaderNodeNormalMap')
                material.node_tree.links.new(normal.outputs['Normal'], target)
                target = normal.inputs['Color']
            material.node_tree.links.new(node.outputs['Color'], target)


def load(path, previous_materials, previous_images):
    try:
        bpy.ops.wm.fbx_import.get_rna_type()
        native = True
    except (AttributeError, KeyError, RuntimeError):
        native = False
    if native:
        status = bpy.ops.wm.fbx_import(filepath=str(path), mtl_name_collision_mode='MAKE_UNIQUE',
                                        use_custom_props=True)
    else:
        status = bpy.ops.import_scene.fbx(filepath=str(path), use_image_search=False)
    if 'FINISHED' in status:
        recover_materials(path, set(bpy.data.materials)-previous_materials,
                          set(bpy.data.images)-previous_images)
    return status
