"""AGR naming and metadata rules. No Blender dependency."""
import math
from pathlib import Path
import re

_TEXTURE = re.compile(
    r'^(.*?)[_ ](diffuse|base[ _]?color|erm|normal)(?:[_ ](\d+))?\.(1\d{3})\.(png|jpg|jpeg|tga|tif|tiff)$',
    re.IGNORECASE)


def number(value):
    result = float(str(value).replace(',', '.'))
    if not math.isfinite(result):
        raise ValueError('В метаданных обнаружено некорректное число')
    return result


def position(payload):
    """Return AGR coordinates, or None when no positioning metadata is present."""
    features = payload.get('features', [])
    if not features:
        return None
    feature = features[0]
    coordinates = feature.get('geometry', {}).get('coordinates', [])
    if len(coordinates) < 2 or isinstance(coordinates[0], (list, tuple)):
        return None
    height = feature.get('properties', {}).get('h_relief')
    if height in (None, ''):
        return None
    return number(coordinates[0]), number(coordinates[1]), number(height)


def glass_values(payload):
    rgb = payload.get('color_RGB', {'Red': 255, 'Green': 255, 'Blue': 255})
    return {'Base Color': tuple(number(rgb[key]) / 255 for key in ('Red', 'Green', 'Blue')) + (1.,),
            'Metallic': number(payload.get('metallicity', .6)),
            'Roughness': number(payload.get('roughness', 0)),
            'IOR': number(payload.get('refraction', 1.45)),
            'Alpha': number(payload.get('transparency', .4))}


def glass_materials(payload):
    features = payload.get('features', [])
    if not features:
        return {}
    glasses = features[0].get('Glasses', [])
    return glasses[0] if glasses and isinstance(glasses[0], dict) else {}


def model_kind(filename):
    return 'LP' if Path(filename).name[:4].isdigit() else 'HP'


def object_role(name):
    name = name.lower()
    if name.startswith('ucx'):
        return 'collision'
    if 'glass' in name:
        return 'glass'
    if 'light' in name:
        return 'light'
    return 'model'


def texture_sets(paths):
    groups = {}
    for path in paths:
        match = _TEXTURE.fullmatch(path.name)
        if not match:
            continue
        prefix, channel, slot, tile, _ = match.groups()
        channel = channel.lower().replace(' ', '').replace('_', '')
        if channel == 'basecolor':
            channel = 'diffuse'
        group = prefix.lower() + ('#' + slot if slot and int(slot) != 1 else '')
        slots = groups.setdefault(group, {}).setdefault(channel, {})
        tile = int(tile)
        if tile in slots:
            raise ValueError(f'Две текстуры для одного канала и UDIM: {path.name}')
        slots[tile] = path
    return groups


def textures_for_model(groups, filename):
    stem = Path(filename).stem.lower().removeprefix('sm_').removesuffix('_light')
    matches = {name: channels for name, channels in groups.items()
               if name.split('#')[0].removeprefix('t_') == stem}
    if not matches and len({n.split('#')[0] for n in groups}) == 1:
        matches = groups
    return {int(name.split('#')[1]) if '#' in name else 1: channels
            for name, channels in matches.items()}
