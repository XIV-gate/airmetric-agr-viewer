"""Bounded GitHub requests, verified packages, reversible installation. No bpy."""
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'XIV-gate/airmetric-agr-viewer'
MODULE = 'airmetric_agr_viewer'
MANIFEST = 'PACKAGE_MANIFEST.json'
MAX_PACKAGE = 4 * 1024**2
MAX_METADATA = 2 * 1024**2
_HOSTS = {'github.com', 'api.github.com', 'release-assets.githubusercontent.com',
          'objects.githubusercontent.com', 'github-releases.githubusercontent.com'}


def version_key(version):
    if not isinstance(version, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', version):
        raise ValueError('Некорректный номер версии')
    return tuple(map(int, version.split('.')))


def asset_name(version):
    version_key(version)
    return f'{MODULE}-{version}.zip'


def catalog(payload):
    if not isinstance(payload, list):
        raise ValueError('GitHub вернул некорректный список версий')
    result = {}
    for release in payload:
        try:
            version = release['tag_name'].removeprefix('v')
            version_key(version)
            base = f'https://github.com/{REPOSITORY}/releases'
            if (release.get('draft') is not False or type(release.get('prerelease')) is not bool
                    or release.get('tag_name') != 'v' + version
                    or not release.get('published_at')
                    or release.get('html_url') != f'{base}/tag/v{version}'):
                continue
            assets = [a for a in release['assets'] if a.get('name') == asset_name(version)]
            if len(assets) != 1:
                continue
            asset = assets[0]
            url = f'{base}/download/v{version}/{asset_name(version)}'
            digest = asset.get('digest', '')
            if (asset.get('state') != 'uploaded' or asset.get('browser_download_url') != url
                    or not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest)
                    or type(asset.get('size')) is not int or not 0 < asset['size'] <= MAX_PACKAGE):
                continue
            result[version] = {'version': version, 'early': release['prerelease'],
                               'url': url, 'sha256': digest[7:], 'size': asset['size']}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return sorted(result.values(), key=lambda r: version_key(r['version']), reverse=True)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in _HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('Недопустимый адрес обновления')


def request(url, limit):
    check_url(url)
    req = urllib.request.Request(url, headers={'User-Agent': 'Airmetric-AGR-Viewer',
                                               'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.build_opener(SafeRedirect).open(req, timeout=20) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ValueError('Источник обновлений пока недоступен. Приватный GitHub-репозиторий не доступен без авторизации.') from error
        if error.code in (403, 429):
            raise ValueError('GitHub временно ограничил запросы. Повторите проверку позже.') from error
        raise ValueError(f'GitHub вернул ошибку {error.code}') from error
    if len(data) > limit:
        raise ValueError('Размер ответа GitHub превышает допустимый')
    return data


def fetch_catalog():
    payload, remaining = [], MAX_METADATA
    for page in range(1, 4):
        data = request(f'https://api.github.com/repos/{REPOSITORY}/releases?per_page=100&page={page}', remaining)
        remaining -= len(data)
        releases = json.loads(data)
        if not isinstance(releases, list):
            raise ValueError('GitHub вернул некорректный ответ')
        payload.extend(releases)
        if len(releases) < 100:
            break
    return catalog(payload)


def download(info):
    data = request(info['url'], MAX_PACKAGE)
    if len(data) != info['size']:
        raise ValueError('Обновление скачалось не полностью')
    return validate_package(data, info['version'], info['sha256'])


def validate_package(data, version, digest=None):
    version_key(version)
    if len(data) > MAX_PACKAGE or (digest and hashlib.sha256(data).hexdigest() != digest):
        raise ValueError('Не совпадает контрольная сумма скачанного обновления')
    files, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 128:
            raise ValueError('Слишком много файлов в обновлении')
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if (len(path.parts) != 2 or path.parts[0] != MODULE or '\\' in info.filename
                    or ':' in info.filename or '..' in path.parts or info.is_dir()
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError('Недопустимая структура установочного ZIP')
            name = path.name
            if (name not in {'VERSION', MANIFEST} and not re.fullmatch(r'[a-z_]+\.py', name)):
                raise ValueError('Неожиданный файл в обновлении: ' + name)
            if name.casefold() in {n.casefold() for n in files}:
                raise ValueError('Повторяющийся файл обновления')
            total += info.file_size
            if total > MAX_PACKAGE:
                raise ValueError('Слишком большой распакованный пакет')
            files[name] = archive.read(info)
    manifest = json.loads(files[MANIFEST])
    if (manifest.get('module') != MODULE or manifest.get('version') != version
            or files['VERSION'].decode().strip() != version
            or manifest.get('blender_min') != [4, 2, 0]):
        raise ValueError('Версия или совместимость пакета не совпадает с релизом')
    hashes = {n: hashlib.sha256(b).hexdigest() for n, b in files.items() if n != MANIFEST}
    if manifest.get('files') != hashes:
        raise ValueError('Содержимое обновления повреждено')
    for name, content in files.items():
        if name.endswith('.py'):
            compile(content, name, 'exec', dont_inherit=True)
    tree = ast.parse(files['__init__.py'])
    info = next(ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in n.targets))
    if info['version'] != version_key(version):
        raise ValueError('Версия bl_info не совпадает с пакетом')
    return files


def install(root, files, *, writer=None):
    """In-memory snapshot: no update archives, backup trees, or Preferences writes."""
    root = Path(root).resolve(strict=True)
    if (root / '.git').exists() or (root.parent / '.git').exists():
        raise ValueError('Это рабочий Git-репозиторий. Обновите установленную копию плагина.')
    manifest = json.loads((root / MANIFEST).read_bytes())
    if manifest.get('module') != MODULE:
        raise ValueError('Не удалось подтвердить установленный плагин')
    owned = set(manifest['files']) | {MANIFEST}
    # Updates never follow foreign paths, including a modified installed manifest.
    if any(Path(n).name != n or '/' in n or '\\' in n or ':' in n for n in owned | set(files)):
        raise ValueError('Повреждён список файлов установленного плагина')
    if any((root / n).is_symlink() for n in owned | set(files)):
        raise ValueError('Установленные файлы содержат символическую ссылку')
    for name in set(files) - owned:
        if (root / name).exists():
            raise ValueError('Обновление перезаписало бы посторонний файл: ' + name)
    snapshot = {n: (root / n).read_bytes() if (root / n).exists() else None for n in owned | set(files)}
    write = writer or (lambda path, data: path.write_bytes(data))
    try:
        for name, data in files.items():
            write(root / name, data)
        for name in owned - set(files):
            (root / name).unlink(missing_ok=True)
    except Exception:
        # Restore through an independent writer, even when the injected/new writer fails.
        for name, data in snapshot.items():
            if data is None:
                (root / name).unlink(missing_ok=True)
            else:
                (root / name).write_bytes(data)
        raise
    # Python must read the new source after the requested Blender restart.
    bytecode = root / '__pycache__'
    if bytecode.is_dir() and not bytecode.is_symlink():
        for path in bytecode.glob('*.pyc'):
            if path.stem.split('.')[0] + '.py' in owned | set(files):
                path.unlink(missing_ok=True)
