"""User-triggered updates. Workers never access Blender API."""
from pathlib import Path
import queue
import threading
import bpy
from . import updates

PHASE = 'IDLE'
MESSAGE = 'Проверка выполняется только по вашей кнопке'
RELEASES = []
ITEMS = [('NONE', 'Нет списка версий', 'Нажмите «Проверить обновления»')]
RESULTS = queue.Queue()
GENERATION = 0
RESTART = False


def current_version():
    from . import bl_info
    return '.'.join(map(str, bl_info['version']))


def version_items(self, context):
    return ITEMS


def busy():
    return PHASE in {'CHECKING', 'INSTALLING'}


def redraw():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def worker(operation, function):
    generation = GENERATION
    def run():
        try:
            result = (True, function())
        except Exception as error:
            result = (False, str(error))
        RESULTS.put((generation, operation, *result))
    threading.Thread(target=run, name='Airmetric update', daemon=True).start()
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=.1)


def tick():
    global PHASE, MESSAGE, RELEASES, ITEMS, RESTART
    try:
        generation, operation, success, result = RESULTS.get_nowait()
    except queue.Empty:
        return .1 if busy() else None
    if generation != GENERATION:
        return .1 if busy() else None
    if not success:
        PHASE, MESSAGE = 'ERROR', result
    elif operation == 'catalog':
        RELEASES = result
        ITEMS = [(r['version'], r['version'] + (' — предварительная' if r['early'] else ''),
                  'Установить опубликованную версию ' + r['version']) for r in result]
        if not ITEMS:
            ITEMS = [('NONE', 'Нет доступных релизов', 'Установочные релизы ещё не опубликованы')]
        default = next((r['version'] for r in result if not r['early']), ITEMS[0][0])
        for scene in bpy.data.scenes:
            scene.airmetric_agr.update_version = default
        PHASE, MESSAGE = 'IDLE', 'Выберите версию для установки' if result else 'Опубликованных установочных версий пока нет'
    else:
        RESTART = True
        PHASE, MESSAGE = 'DONE', 'Обновление установлено. Сохраните сцену и перезапустите Blender.'
    redraw()
    return .1 if busy() else None


def require_online():
    if not bpy.app.online_access:
        raise ValueError('В Blender отключён интернет. Разрешите доступ в настройках сети и повторите проверку.')
    if busy() or RESTART:
        raise ValueError('Дождитесь завершения обновления или перезапустите Blender')


def check():
    global PHASE, MESSAGE
    require_online()
    PHASE, MESSAGE = 'CHECKING', 'Получаю список опубликованных версий…'
    worker('catalog', updates.fetch_catalog)
    redraw()


def selected(scene):
    return next((r for r in RELEASES if r['version'] == scene.airmetric_agr.update_version), None)


def install(info):
    global PHASE, MESSAGE
    require_online()
    root = Path(__file__).resolve().parent
    if (root.parent / '.git').exists() or not (root / updates.MANIFEST).is_file():
        raise ValueError('Самообновление доступно в установленном ZIP-пакете, а не в исходниках разработки')
    PHASE, MESSAGE = 'INSTALLING', 'Скачиваю и проверяю выбранную версию…'
    worker('install', lambda: updates.install(root, updates.download(info)))
    redraw()


def stop():
    global GENERATION, PHASE
    GENERATION += 1
    PHASE = 'IDLE'
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
