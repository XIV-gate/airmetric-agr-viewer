"""AGR shaders, addressed by socket names for Blender 4.2 and later."""
import re
import bpy
from . import agr


def shader(material):
    material.use_nodes = True
    nodes = material.node_tree.nodes
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if output is None:
        output = nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return bsdf


def tiled_image(tiles, channel):
    first_number = min(tiles)
    first = tiles[first_number]
    image = bpy.data.images.load(str(first), check_existing=False)
    image['airmetric_owned'] = True
    image.colorspace_settings.name = 'sRGB' if channel == 'diffuse' else 'Non-Color'
    image.source = 'TILED'
    image.filepath = str(first).replace(f'.{first_number}.', '.<UDIM>.')
    existing = {t.number for t in image.tiles}
    for number in sorted(tiles):
        if number not in existing:
            image.tiles.new(number)
    # Blender creates 1001 by default, even when the supplied set starts later.
    for tile in list(image.tiles):
        if tile.number not in tiles:
            image.tiles.remove(tile)
    image.reload()
    image.pack()
    packed = {p.tile_number for p in image.packed_files}
    if packed != set(tiles):
        raise RuntimeError('Не удалось встроить все UDIM-тайлы: ' + first.name)
    # Packed files retain their own tile paths. This portable display path no longer
    # points into the deleted extraction directory; Blender reads packed bytes.
    image.filepath_raw = '//' + first.name.replace(f'.{first_number}.', '.<UDIM>.')
    for packed_file in image.packed_files:
        packed_file.filepath = '//' + tiles[packed_file.tile_number].name
    return image


def apply_textures(material, images):
    bsdf = shader(material)
    nodes, links = material.node_tree.nodes, material.node_tree.links
    for node in list(nodes):
        if node != bsdf and node.type != 'OUTPUT_MATERIAL':
            nodes.remove(node)
    bsdf.location = (400, 120)
    texture_nodes = {}
    for index, (channel, image) in enumerate(images.items()):
        node = nodes.new('ShaderNodeTexImage')
        node.image = image
        node.label = {'diffuse': 'Цвет', 'erm': 'ERM', 'normal': 'Нормали DirectX'}[channel]
        node.location = (-700, 400 - index * 340)
        texture_nodes[channel] = node
    if 'diffuse' in texture_nodes:
        node = texture_nodes['diffuse']
        for socket in ('Base Color', 'Emission Color'):
            links.new(node.outputs['Color'], bsdf.inputs[socket])
        links.new(node.outputs['Alpha'], bsdf.inputs['Alpha'])
    if 'erm' in texture_nodes:
        separate = nodes.new('ShaderNodeSeparateColor')
        separate.location = (-350, 0)
        links.new(texture_nodes['erm'].outputs['Color'], separate.inputs['Color'])
        for channel, socket in [('Red', 'Emission Strength'), ('Green', 'Roughness'), ('Blue', 'Metallic')]:
            links.new(separate.outputs[channel], bsdf.inputs[socket])
    if 'normal' in texture_nodes:
        separate = nodes.new('ShaderNodeSeparateColor')
        inverse = nodes.new('ShaderNodeMath')
        inverse.operation = 'SUBTRACT'
        inverse.inputs[0].default_value = 1.
        combine = nodes.new('ShaderNodeCombineColor')
        normal = nodes.new('ShaderNodeNormalMap')
        separate.location, inverse.location = (-450, -400), (-250, -450)
        combine.location, normal.location = (-50, -350), (180, -250)
        links.new(texture_nodes['normal'].outputs['Color'], separate.inputs['Color'])
        links.new(separate.outputs['Green'], inverse.inputs[1])
        links.new(separate.outputs['Red'], combine.inputs['Red'])
        links.new(inverse.outputs[0], combine.inputs['Green'])
        links.new(separate.outputs['Blue'], combine.inputs['Blue'])
        links.new(combine.outputs[0], normal.inputs['Color'])
        links.new(normal.outputs['Normal'], bsdf.inputs['Normal'])


def configure(objects, payload, channels, kind):
    """Touch only materials belonging to this import transaction."""
    glass = agr.glass_materials(payload)
    slot_images = {slot: {channel: tiled_image(tiles, channel) for channel, tiles in group.items()}
                   for slot, group in channels.items()}
    done = set()
    for obj in objects:
        if obj.type != 'MESH':
            continue
        role = agr.object_role(obj.name)
        if role in {'light', 'collision'}:
            continue
        for index, material in enumerate(obj.data.materials, start=1):
            if material is None or material in done:
                continue
            done.add(material)
            if role == 'glass' or material.name.lower().startswith('m_glass'):
                bsdf = shader(material)
                original_name = re.sub(r'\.\d{3}$', '', material.name)
                entry = glass.get(material.name, glass.get(original_name, {}))
                if kind == 'HP':
                    for socket, value in agr.glass_values(entry).items():
                        # Remove imported links which would override metadata values.
                        for link in list(bsdf.inputs[socket].links):
                            material.node_tree.links.remove(link)
                        bsdf.inputs[socket].default_value = value
                material.surface_render_method = 'DITHERED'
            elif kind == 'HP' and slot_images:
                name = re.sub(r'\.\d{3}$', '', material.name)
                match = re.search(r'_(\d{1,2})$', name)
                slot = int(match.group(1)) if match else index
                if slot in slot_images:
                    apply_textures(material, slot_images[slot])
            if kind == 'LP':
                material.surface_render_method = 'DITHERED'


def pack_referenced(objects, new_images):
    used = set()
    for obj in objects:
        if obj.type != 'MESH':
            continue
        for material in obj.data.materials:
            if material and material.use_nodes:
                used.update(n.image for n in material.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image)
    for image in used:
        if image not in new_images:
            continue
        if not image.packed_file:
            if not image.has_data:
                raise RuntimeError('Не найдена текстура: ' + image.name)
            image.pack()
        if not image.packed_file:
            raise RuntimeError('Не удалось встроить текстуру: ' + image.name)
        image['airmetric_owned'] = True
        if image.source == 'TILED':
            continue  # Preserve each packed tile's concrete filename.
        image.filepath_raw = '//' + bpy.path.basename(image.filepath)
        for packed_file in image.packed_files:
            packed_file.filepath = image.filepath_raw
