"""Bounded, read-only package screening; FBX geometry is validated on import."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile
import zlib

from . import agr, archive

_CHUNK = 1024 * 1024
_METADATA_LIMIT = 16 * 1024 * 1024


def _check_cancel(cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError('Проверка отменена')


def _inspect(source, cancelled, contained_digests):
    assets = []
    names = set()
    totals = [0, 0]

    def visit(container, depth=0):
        _check_cancel(cancelled)
        if depth > 2:
            raise ValueError('Слишком много уровней вложенных ZIP')
        with zipfile.ZipFile(container) as package:
            selected = archive.members(package)
            totals[1] += len(package.infolist())
            if totals[1] > archive.MAX_FILES:
                raise ValueError('В комплекте слишком много файлов')
            for item in selected:
                _check_cancel(cancelled)
                name = PurePosixPath(item.filename).name
                key = name.casefold()
                if key in names:
                    raise ValueError('В комплекте повторяются имена файлов')
                names.add(key)
                totals[0] += item.file_size
                if totals[0] > archive.MAX_BYTES:
                    raise ValueError('Комплект превышает допустимый размер')
                suffix = PurePosixPath(name).suffix.lower()
                if suffix == '.zip':
                    with tempfile.SpooledTemporaryFile(max_size=8 * _CHUNK, mode='w+b') as nested:
                        digest = hashlib.sha256()
                        with package.open(item) as stream:
                            while True:
                                _check_cancel(cancelled)
                                chunk = stream.read(_CHUNK)
                                if not chunk:
                                    break
                                digest.update(chunk)
                                nested.write(chunk)
                        contained_digests.append(digest.hexdigest())
                        nested.seek(0)
                        visit(nested, depth + 1)
                elif suffix == '.fbx':
                    with package.open(item) as stream:
                        header = stream.read(64)
                    if not (header.startswith(b'Kaydara FBX Binary  \x00\x1a\x00')
                            or header.startswith(b'; FBX')):
                        raise ValueError('Файл FBX имеет неподдерживаемый заголовок')
                    if not (name[:4].isascii() and name[:4].isdigit()
                            or name.casefold().startswith('sm_')):
                        raise ValueError('Имена моделей не соответствуют формату АГР')
                    assets.append((Path(name), None))
                elif suffix == '.geojson':
                    if item.file_size > _METADATA_LIMIT:
                        raise ValueError('GeoJSON превышает допустимый размер')
                    # Read only bounded metadata, never texture contents or whole FBX.
                    with package.open(item) as stream:
                        data = bytearray()
                        while True:
                            _check_cancel(cancelled)
                            chunk = stream.read(min(_CHUNK, _METADATA_LIMIT + 1 - len(data)))
                            if not chunk:
                                break
                            data.extend(chunk)
                            if len(data) > _METADATA_LIMIT:
                                raise ValueError('GeoJSON превышает допустимый размер')
                    assets.append((Path(name), data))
                else:
                    assets.append((Path(name), None))

    visit(source)
    models = [path for path, _ in assets if path.suffix.lower() == '.fbx']
    if not models:
        raise ValueError('В архиве нет модели АГР в формате FBX')
    metadata = [(path, data) for path, data in assets if path.suffix.lower() == '.geojson']
    for model in models:
        _check_cancel(cancelled)
        if agr.model_kind(model.name) != 'HP':
            continue
        stem = model.stem.removesuffix('_Light')
        matches = [(p, data) for p, data in metadata if p.stem.casefold() == stem.casefold()]
        target = matches[0] if len(matches) == 1 else metadata[0] if len(metadata) == 1 else None
        if target is None:
            raise ValueError('Для ВПМ не найден однозначный GeoJSON')
        try:
            payload = json.loads(target[1].decode('utf-8-sig'))
            if not isinstance(payload, dict):
                raise ValueError()
            if not model.stem.lower().endswith('_light') and agr.position(payload) is None:
                raise ValueError('В GeoJSON нет координат и h_relief')
        except (UnicodeError, json.JSONDecodeError, TypeError, AttributeError, IndexError, KeyError) as exc:
            raise ValueError('Некорректный GeoJSON с расположением ВПМ') from exc
    # Texture availability depends on the FBX object roles (glass/light/model).
    # Keep this check in the importer so glass-only packages remain compatible.
    return len(models)


def inspect_archive(path, cancelled=None):
    """Return a queue record; readiness checks packaging, not FBX geometry.

    Cancellation propagates as InterruptedError. Nested ZIPs use automatically
    closed spooled streams in the caller-configured temporary directory.
    """
    _check_cancel(cancelled)
    source = Path(path).expanduser().resolve()
    result = {'path': str(source), 'name': source.name, 'status': 'skipped',
              'reason': '', 'models': 0, 'stamp': None,
              'digest': '', 'contained_digests': []}
    try:
        info = source.stat()
        result['stamp'] = (info.st_size, info.st_mtime_ns)
        digest = hashlib.sha256()
        with source.open('rb') as stream:
            while True:
                _check_cancel(cancelled)
                chunk = stream.read(_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
        result['digest'] = digest.hexdigest()
        result['models'] = _inspect(source, cancelled, result['contained_digests'])
        _check_cancel(cancelled)
        result['status'] = 'ready'
    except InterruptedError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, zlib.error):
        result['reason'] = 'Повреждённый или неподдерживаемый ZIP'
    except (OSError, RuntimeError, NotImplementedError):
        result['reason'] = 'ZIP недоступен, повреждён или защищён паролем'
    except (ValueError, OverflowError) as exc:
        result['reason'] = str(exc) or 'Некорректный GeoJSON с расположением ВПМ'
    return result


def inspect_selection(paths, cancelled=None):
    """Inspect each resolved source once, preserving selection order."""
    results, seen = [], set()
    for path in paths:
        _check_cancel(cancelled)
        source = Path(path).expanduser().resolve()
        key = os.path.normcase(str(source))
        if key not in seen:
            seen.add(key)
            results.append(inspect_archive(source, cancelled))
    return results


def deduplicate(rows):
    """Copy queue records and suppress exact ZIP copies or contained archives.

    Only ready containers cover other rows. Model names and partial overlap do
    not establish archive identity, so they never suppress a selected package.
    """
    result = [dict(row) for row in rows]
    containers = {}
    for index, row in enumerate(result):
        if row.get('status') == 'ready':
            for digest in row.get('contained_digests', ()):
                if digest:
                    containers.setdefault(digest, set()).add(index)
    seen = set()
    for index, row in enumerate(result):
        if row.get('status') != 'ready' or not row.get('digest'):
            continue
        digest = row['digest']
        if containers.get(digest, set()) - {index}:
            row['status'] = 'skipped'
            row['reason'] = 'Уже входит в выбранный общий ZIP'
        elif digest in seen:
            row['status'] = 'skipped'
            row['reason'] = 'Этот архив уже выбран'
        else:
            seen.add(digest)
    return result
