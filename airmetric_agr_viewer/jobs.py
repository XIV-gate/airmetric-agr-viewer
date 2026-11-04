"""ZIP inspection uses no Blender API; scene mutations run between timer events."""
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from . import preflight

ACTIVE = None
LAST = None


class Job:
    def __init__(self, paths, scene):
        self.paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
        self.scene = scene
        self.phase = 'checking'
        self.rows = []
        self.pending = []
        self.loaded = 0
        self.objects = 0
        self.index = 0
        self.duplicates = set()
        self.replace = False
        self.cancelled = Event()
        self.events = Queue()
        self.message = 'Проверка выбранных архивов…'
        self.thread = Thread(target=self._inspect, daemon=True)

    def _inspect(self):
        try:
            for path in self.paths:
                self.events.put(('checking', Path(path).name))
                row = preflight.inspect_archive(path, cancelled=self.cancelled.is_set)
                self.events.put(('row', row))
            self.events.put(('done', None))
        except InterruptedError:
            self.events.put(('cancelled', None))
        except Exception:
            self.events.put(('error', 'Не удалось завершить проверку архивов. Повторите выбор.'))

    def poll(self):
        from . import scene as scene_data
        while True:
            try:
                event, value = self.events.get_nowait()
            except Empty:
                break
            if event == 'checking':
                self.message = f'Проверка {len(self.rows) + 1} из {len(self.paths)}: {value}'
            elif event == 'row':
                self.rows.append(value)
            elif event == 'done':
                if self.cancelled.is_set():
                    self.phase = 'done'
                    self.message = 'Проверка остановлена. Сцена не изменена.'
                    continue
                self.rows = preflight.deduplicate(self.rows)
                self.duplicates = {r['path'] for r in self.rows if r['status'] == 'ready'
                                   and scene_data.archive_groups(self.scene, r['path'], r.get('digest'))}
                self.phase = 'review' if self.duplicates or any(r['status'] != 'ready' for r in self.rows) else 'loading'
                self.prepare()
            elif event in {'cancelled', 'error'}:
                self.phase = 'done'
                self.message = value or 'Проверка остановлена. Сцена не изменена.'

    def prepare(self):
        self.pending = []
        for row in self.rows:
            if row['status'] == 'ready':
                if row['path'] in self.duplicates and not self.replace:
                    row['reason'] = 'Уже загружен — повтор пропущен'
                else:
                    row['reason'] = 'Уже загружен — будет заменён' if row['path'] in self.duplicates else ''
                    self.pending.append(row)
        self.message = f'Готово к загрузке: {len(self.pending)}. Пропущено: {len(self.rows) - len(self.pending)}.'

    def load_next(self):
        from . import importer, scene as scene_data
        if self.cancelled.is_set() or self.index >= len(self.pending):
            self.finish()
            return
        row = self.pending[self.index]
        self.message = f'Загрузка {self.index + 1} из {len(self.pending)}: {row["name"]}'
        path = Path(row['path'])
        before = None
        try:
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != tuple(row['stamp']):
                raise ValueError('Архив изменился после проверки. Выберите его заново.')
            old = scene_data.archive_groups(self.scene, path, row.get('digest'))
            if old and not self.replace:
                row['reason'] = 'Уже загружен — повтор пропущен'
                self.index += 1
                return
            if any(c.name not in self.scene.collection.children for c in old):
                raise ValueError('Коллекция архива перемещена. Очистите сцену или пропустите повтор.')
            before = importer.snapshot()
            result = importer.import_archives([path])
            for collection in importer.snapshot()['collections'] - before['collections']:
                if collection.get('airmetric_source'):
                    collection['airmetric_digest'] = row.get('digest', '')
            if old:
                scene_data.remove_groups(self.scene, old)
            row['status'] = 'loaded'
            row['reason'] = 'Загружен'
            self.loaded += 1
            self.objects += result['objects']
        except Exception as error:
            if before is not None:
                importer.rollback(before)
            row['status'] = 'error'
            row['reason'] = str(error) or 'Не удалось прочитать модель'
        self.index += 1

    def finish(self):
        self.phase = 'done'
        for row in self.rows:
            if row['status'] == 'ready' and (not row['reason'] or self.cancelled.is_set() and row in self.pending):
                row['reason'] = 'Не загружен — операция остановлена'
        skipped = len(self.rows) - self.loaded
        self.message = f'Загружено архивов: {self.loaded}. Пропущено: {skipped}.'
        if self.cancelled.is_set():
            self.message += ' Загрузка остановлена; готовые модели сохранены.'


def busy():
    return ACTIVE is not None


def scene_valid(job):
    import bpy
    try:
        return job.scene.as_pointer() != 0 and any(s == job.scene for s in bpy.data.scenes)
    except ReferenceError:
        return False


def start(paths, scene):
    global ACTIVE, LAST
    if busy():
        raise RuntimeError('Дождитесь окончания текущей загрузки')
    job = Job(paths, scene)
    if not job.paths:
        raise ValueError('Выберите хотя бы один ZIP-архив')
    ACTIVE = job
    LAST = None
    job.thread.start()
    return job


def complete():
    global ACTIVE, LAST
    LAST = ACTIVE
    ACTIVE = None


def stop():
    global ACTIVE
    if ACTIVE:
        ACTIVE.cancelled.set()
        ACTIVE.thread.join(timeout=2)
        ACTIVE = None
