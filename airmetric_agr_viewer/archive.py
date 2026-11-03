"""Operation-owned extraction, never beside the source archive."""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

FORMATS = {'.fbx', '.geojson', '.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff', '.zip'}
MAX_BYTES = 8 * 1024**3
MAX_FILES = 12000


def members(archive):
    selected, names, total = [], set(), 0
    entries = archive.infolist()
    if len(entries) > MAX_FILES:
        raise ValueError('В архиве слишком много файлов')
    for item in entries:
        name = item.orig_filename  # zipfile can normalize separators and truncate NUL.
        path = PurePosixPath(name)
        if ('\\' in name or ':' in name or '\x00' in name or path.is_absolute()
                or '..' in path.parts or any(ord(c) < 32 for c in name)):
            raise ValueError('Небезопасный путь в ZIP: ' + name)
        mode = item.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError('Символические ссылки в ZIP не поддерживаются')
        if item.is_dir():
            continue
        if (path.name.endswith((' ', '.')) or re.match(r'(?i)^(con|prn|aux|nul|com\d|lpt\d)(\.|$)', path.name)):
            raise ValueError('Недопустимое имя файла в ZIP: ' + name)
        if path.suffix.lower() not in FORMATS:
            continue
        key = path.name.casefold()
        if key in names:
            raise ValueError('В архиве повторяется имя файла: ' + path.name)
        names.add(key)
        total += item.file_size
        if total > MAX_BYTES or item.flag_bits & 1:
            raise ValueError('Архив слишком большой либо защищён паролем')
        selected.append(item)
    return selected


@contextmanager
def extracted(source, *, directory=None):
    """Flatten one AGR archive; optionally use an existing test-owned directory."""
    temporary = tempfile.TemporaryDirectory(prefix='airmetric_agr_') if directory is None else None
    root = Path(temporary.name if temporary else directory).resolve()
    created = []
    assets = []
    totals = [0, 0]

    def unpack(container, depth=0):
        if depth > 2:
            raise ValueError('Слишком много уровней вложенных ZIP-архивов')
        with zipfile.ZipFile(container) as archive:
            for item in members(archive):
                totals[0] += item.file_size
                totals[1] += 1
                if totals[0] > MAX_BYTES or totals[1] > MAX_FILES:
                    raise ValueError('Общий размер комплекта АГР превышает допустимый')
                target = root / PurePosixPath(item.filename).name
                with target.open('xb') as dest:
                    created.append(target)
                    with archive.open(item) as src:
                        shutil.copyfileobj(src, dest, length=1024 * 1024)
                if target.suffix.lower() == '.zip':
                    unpack(target, depth + 1)
                else:
                    assets.append(target)
    try:
        unpack(source)
        if not any(p.suffix.lower() == '.fbx' for p in assets):
            raise ValueError('В архиве нет модели FBX')
        yield root, tuple(assets)
    finally:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        if temporary:
            temporary.cleanup()
