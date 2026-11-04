"""Russian N-panel with descriptions on every interactive control."""
from pathlib import Path
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, PointerProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler
from math import radians
from . import importer, viewport, updater, jobs, scene as scene_data


def visibility(self, context):
    viewport.apply_visibility(context.scene, context)


class AIRMETRIC_PG_settings(bpy.types.PropertyGroup):
    show_hp: BoolProperty(name='ВПМ', default=True, update=visibility,
                          description='Включить или отключить показ детальной высокополигональной модели')
    show_lp: BoolProperty(name='НПМ', default=True, update=visibility,
                          description='Включить или отключить показ упрощённой низкополигональной модели')
    show_glass: BoolProperty(name='Стекло', default=True, update=visibility,
                             description='Включить или отключить остекление видимых моделей')
    show_lights: BoolProperty(name='Подсветка', default=True, update=visibility,
                              description='Включить или отключить геометрию архитектурной подсветки')
    show_collisions: BoolProperty(name='Коллизии', default=False, update=visibility,
                                  description='Показать или скрыть технические объекты UCX; обычно их оставляют скрытыми')
    status: StringProperty(default='Выберите ZIP-архивы АГР для просмотра')
    update_version: EnumProperty(name='Версия', items=updater.version_items,
                                 description='Выберите любую доступную опубликованную версию, включая предыдущие')


class AIRMETRIC_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = 'airmetric.open_archives'
    bl_label = 'Открыть архивы АГР'
    bl_description = ('Выберите один или несколько ZIP-архивов ВПМ и НПМ. Модели добавятся в текущую сцену; '
                      'сохранять её заранее не нужно. Исходные архивы останутся без изменений')
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.zip'
    filter_glob: StringProperty(default='*.zip', options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype='DIR_PATH')

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and not jobs.busy() and not updater.busy() and not updater.RESTART

    def execute(self, context):
        paths = [Path(self.directory) / item.name for item in self.files] or [Path(self.filepath)]
        try:
            if not self.poll(context):
                raise ValueError('Завершите текущую операцию перед загрузкой')
            jobs.start(paths, context.scene)
            bpy.ops.airmetric.run_queue('INVOKE_DEFAULT')
            return {'FINISHED'}
        except Exception as error:
            jobs.stop()
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


def draw_results(layout, job):
    import textwrap
    layout.label(text=job.message, icon='INFO')
    for row in job.rows[:12]:
        if row['status'] in {'ready', 'loaded'} and row['reason'] in {'', 'Загружен'}:
            layout.label(text=row['name'], icon='CHECKMARK')
            continue
        box = layout.box()
        box.label(text=row['name'], icon='CHECKMARK' if row['status'] in {'ready', 'loaded'} and not row['reason'] else 'INFO')
        for line in textwrap.wrap(row['reason'] or 'Готов к загрузке', width=65):
            box.label(text=line)
    if len(job.rows) > 12:
        layout.label(text=f'Ещё архивов: {len(job.rows) - 12}. Полный список — в «Подробности».')


class AIRMETRIC_OT_run_queue(bpy.types.Operator):
    bl_idname = 'airmetric.run_queue'
    bl_label = 'Загрузка архивов'
    bl_options = {'INTERNAL', 'UNDO'}

    def invoke(self, context, event):
        if not jobs.ACTIVE:
            return {'CANCELLED'}
        self._job = jobs.ACTIVE
        self._announced = -1
        self._reviewed = False
        self._next_poll = 0.
        self._timer = context.window_manager.event_timer_add(.12, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        try:
            return self._step(context, event)
        except Exception as error:
            self._job.cancelled.set()
            self._job.message = 'Загрузка остановлена: ' + str(error)
            jobs.stop()
            jobs.LAST = self._job
            if jobs.scene_valid(self._job):
                self._job.scene.airmetric_agr.status = self._job.message
            return self._finish(context)

    def _step(self, context, event):
        if event.type == 'ESC':
            self._job.cancelled.set()
        if event.ctrl and event.type in {'Z', 'O', 'N'}:
            return {'RUNNING_MODAL'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        import time
        now = time.monotonic()
        if now < self._next_poll:
            return {'PASS_THROUGH'}
        self._next_poll = now + .1
        job = self._job
        if jobs.ACTIVE is not job:
            return self._finish(context)
        if not jobs.scene_valid(job):
            jobs.stop()
            return self._finish(context)
        if context.scene != job.scene or context.mode != 'OBJECT':
            job.cancelled.set()
        if job.phase == 'checking':
            job.poll()
        if job.phase == 'review' and job.cancelled.is_set():
            job.finish()
        if job.phase == 'review' and not self._reviewed:
            self._reviewed = True
            bpy.ops.airmetric.review_queue('INVOKE_DEFAULT')
        elif job.phase == 'loading':
            if job.index < len(job.pending) and not job.cancelled.is_set() and self._announced != job.index:
                self._announced = job.index
                job.message = f'Загрузка {job.index + 1} из {len(job.pending)}: {job.pending[job.index]["name"]}'
            else:
                job.load_next()
        job.scene.airmetric_agr.status = job.message
        for area in context.window.screen.areas:
            area.tag_redraw()
        if job.phase == 'done':
            return self._finish(context)
        return {'PASS_THROUGH'}

    def _finish(self, context):
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (ReferenceError, ValueError):
                pass
            self._timer = None
        job = self._job
        if jobs.ACTIVE is job:
            jobs.complete()
        if job.loaded and jobs.scene_valid(job) and context.scene == job.scene:
            for area in context.window.screen.areas:
                if area.type == 'VIEW_3D':
                    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                    if region:
                        with context.temp_override(area=area, region=region):
                            try:
                                viewport.frame(context)
                            except ValueError:
                                pass
                            area.spaces.active.shading.type = 'MATERIAL'
                        break
        self.report({'INFO'}, job.message)
        return {'FINISHED'} if job.loaded else {'CANCELLED'}

    def cancel(self, context):
        self._job.cancelled.set()
        jobs.stop()
        self._finish(context)


def duplicate_choice(self, context):
    if hasattr(self, '_job') and jobs.ACTIVE is self._job and self._job.phase == 'review':
        self._job.replace = self.duplicate_action == 'REPLACE'
        self._job.prepare()


class AIRMETRIC_OT_review_queue(bpy.types.Operator):
    bl_idname = 'airmetric.review_queue'
    bl_label = 'Проверка перед загрузкой'
    bl_description = 'Просмотреть пригодные архивы, причины пропуска и выбрать действие для повторов'
    duplicate_action: EnumProperty(name='Повторные архивы', default='SKIP', update=duplicate_choice, items=[
        ('SKIP', 'Пропустить', 'Оставить уже загруженную модель'),
        ('REPLACE', 'Заменить', 'Загрузить архив заново и заменить прежнюю модель после успешной загрузки')])

    def invoke(self, context, event):
        if not jobs.ACTIVE or jobs.ACTIVE.phase != 'review':
            return {'CANCELLED'}
        self._job = jobs.ACTIVE
        self.duplicate_action = 'SKIP'
        confirm = 'Загрузить' if any(r['status'] == 'ready' for r in self._job.rows) else 'Закрыть'
        return context.window_manager.invoke_props_dialog(self, width=540, confirm_text=confirm)

    def draw(self, context):
        draw_results(self.layout, self._job)
        if self._job.duplicates:
            self.layout.prop(self, 'duplicate_action', expand=True)

    def execute(self, context):
        if jobs.ACTIVE is self._job and self._job.phase == 'review':
            self._job.replace = self.duplicate_action == 'REPLACE'
            self._job.prepare()
            self._job.phase = 'loading'
        return {'FINISHED'}

    def cancel(self, context):
        self._job.cancelled.set()


class AIRMETRIC_OT_stop_queue(bpy.types.Operator):
    bl_idname = 'airmetric.stop_queue'
    bl_label = 'Остановить загрузку'
    bl_description = 'Остановить проверку или загрузку между архивами. Уже загруженные модели останутся в сцене'

    def execute(self, context):
        if jobs.ACTIVE:
            jobs.ACTIVE.cancelled.set()
        return {'FINISHED'}


class AIRMETRIC_OT_results(bpy.types.Operator):
    bl_idname = 'airmetric.results'
    bl_label = 'Подробности загрузки'
    bl_description = 'Показать результат по каждому выбранному архиву и причины пропуска'
    page: bpy.props.IntProperty(name='Страница', default=1, min=1)

    def invoke(self, context, event):
        self._job = jobs.LAST
        if not self._job:
            return {'CANCELLED'}
        self.page = 1
        return context.window_manager.invoke_props_dialog(self, width=540)

    def draw(self, context):
        from types import SimpleNamespace
        rows = self._job.rows
        total = max(1, (len(rows) + 11) // 12)
        page = min(self.page, total)
        self.layout.prop(self, 'page', text=f'Страница (всего {total})')
        view = SimpleNamespace(message=self._job.message, rows=rows[(page-1)*12:page*12])
        draw_results(self.layout, view)

    def execute(self, context):
        return {'FINISHED'}


class AIRMETRIC_OT_clear_scene(bpy.types.Operator):
    bl_idname = 'airmetric.clear_scene'
    bl_label = 'Очистить сцену'
    bl_description = ('Удалить все объекты текущей сцены и освободить их неиспользуемые материалы и текстуры. '
                      'Исходные ZIP останутся на месте. Перед удалением появится подтверждение')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return AIRMETRIC_OT_import.poll(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title='Очистить текущую сцену?',
            message=f'Будут удалены все объекты этой сцены: {len(context.scene.objects)}.',
            confirm_text='Очистить сцену', icon='WARNING')

    def execute(self, context):
        if not self.poll(context):
            return {'CANCELLED'}
        scene_data.clear(context.scene)
        jobs.LAST = None
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.shading.type = 'SOLID'
                space.region_3d.view_location = (0, 0, 0)
                space.region_3d.view_distance = 10
        self.report({'INFO'}, context.scene.airmetric_agr.status)
        return {'FINISHED'}


class AIRMETRIC_OT_frame(bpy.types.Operator):
    bl_idname = 'airmetric.frame_models'
    bl_label = 'Показать модель целиком'
    bl_description = 'Вернуть все видимые загруженные модели в центр экрана и подобрать удобный масштаб'

    def execute(self, context):
        try:
            viewport.frame(context)
            return {'FINISHED'}
        except ValueError as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}


class AIRMETRIC_OT_shading(bpy.types.Operator):
    bl_idname = 'airmetric.shading'
    bl_label = 'Отображение модели'
    bl_description = 'Изменить способ отображения модели в текущем окне'
    mode: EnumProperty(items=[('SOLID', 'Без материалов', 'Быстрый показ формы однотонными поверхностями'),
                              ('MATERIAL', 'С материалами', 'Показать цвета, текстуры, стекло и отражения')])

    @classmethod
    def description(cls, context, properties):
        if properties.mode == 'SOLID':
            return 'Показать форму однотонными поверхностями. Этот режим быстрее работает на больших моделях.'
        return 'Показать модель с цветами, текстурами и стеклом. Подождите, пока Blender подготовит материалы.'

    def execute(self, context):
        context.space_data.shading.type = self.mode
        context.space_data.overlay.show_face_orientation = False
        return {'FINISHED'}


class AIRMETRIC_OT_view(bpy.types.Operator):
    bl_idname = 'airmetric.view'
    bl_label = 'Показать вид'
    bl_description = 'Посмотреть на модель с выбранной стороны'
    direction: EnumProperty(items=[('FRONT', 'Спереди', 'Показать вид спереди'),
                                   ('RIGHT', 'Сбоку', 'Показать вид справа'),
                                   ('TOP', 'Сверху', 'Показать вид сверху'),
                                   ('ORBIT', 'Объёмный вид', 'Показать модель под углом в перспективе')])

    @classmethod
    def description(cls, context, properties):
        return {'FRONT': 'Посмотреть на модель спереди, без перспективных искажений.',
                'RIGHT': 'Посмотреть на модель справа, без перспективных искажений.',
                'TOP': 'Посмотреть на модель сверху, как на плане.',
                'ORBIT': 'Вернуть объёмный вид под углом. Вращайте модель средней кнопкой мыши.'}[properties.direction]

    def execute(self, context):
        region = next(r for r in context.area.regions if r.type == 'WINDOW')
        with context.temp_override(region=region):
            if self.direction == 'ORBIT':
                context.space_data.region_3d.view_rotation = Euler((radians(65), 0, radians(35))).to_quaternion()
                context.space_data.region_3d.view_perspective = 'PERSP'
            else:
                bpy.ops.view3d.view_axis(type=self.direction, align_active=False)
        return {'FINISHED'}


class AIRMETRIC_OT_help(bpy.types.Operator):
    bl_idname = 'airmetric.help'
    bl_label = 'Инструкция'
    bl_description = 'Открыть пошаговую русскую инструкцию: установка, загрузка архивов, просмотр и обновления'

    def execute(self, context):
        bpy.ops.wm.url_open(url='https://github.com/XIV-gate/airmetric-agr-viewer/blob/main/docs/USER_GUIDE_0.2.0_RU.md')
        return {'FINISHED'}


class AIRMETRIC_PT_viewer(bpy.types.Panel):
    bl_idname = 'AIRMETRIC_PT_viewer'
    bl_label = 'AGR Viewer'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Airmetric'

    def draw(self, context):
        layout = self.layout
        layout.enabled = not updater.busy() and not updater.RESTART
        settings = context.scene.airmetric_agr
        if jobs.busy():
            import textwrap
            for line in textwrap.wrap(settings.status, width=max(24, int(context.region.width / 7))):
                layout.label(text=line)
            layout.operator('airmetric.stop_queue', icon='CANCEL')
            return
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator('airmetric.open_archives', icon='FILE_FOLDER')
        col.operator('airmetric.frame_models', icon='VIEWZOOM')
        layout.separator()
        layout.label(text='Что показать')
        row = layout.row(align=True)
        row.scale_y = 1.25
        row.prop(settings, 'show_hp', toggle=True)
        row.prop(settings, 'show_lp', toggle=True)
        row = layout.row(align=True)
        row.prop(settings, 'show_glass', toggle=True)
        row.prop(settings, 'show_lights', toggle=True)
        layout.separator()
        layout.label(text='Отображение')
        row = layout.row(align=True)
        row.operator('airmetric.shading', text='Без материалов', icon='SHADING_SOLID').mode = 'SOLID'
        row.operator('airmetric.shading', text='С материалами', icon='MATERIAL').mode = 'MATERIAL'
        layout.separator()
        layout.label(text='Показать вид')
        row = layout.row(align=True)
        row.operator('airmetric.view', text='Спереди').direction = 'FRONT'
        row.operator('airmetric.view', text='Сбоку').direction = 'RIGHT'
        row = layout.row(align=True)
        row.operator('airmetric.view', text='Сверху').direction = 'TOP'
        row.operator('airmetric.view', text='Объёмный вид').direction = 'ORBIT'
        layout.separator()
        # Wrap status so long error messages do not widen the beginner panel.
        import textwrap
        for line in textwrap.wrap(settings.status, width=max(24, int(context.region.width / 7))):
            layout.label(text=line)
        if jobs.LAST:
            layout.operator('airmetric.results', text='Подробности', icon='INFO')
        layout.separator()
        row = layout.row()
        row.alert = True
        row.scale_y = 1.7
        row.operator('airmetric.clear_scene', icon='TRASH')
        layout.operator('airmetric.help', icon='HELP')


class AIRMETRIC_PT_extra(bpy.types.Panel):
    bl_label = 'Дополнительно'
    bl_idname = 'AIRMETRIC_PT_extra'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Airmetric'
    bl_parent_id = 'AIRMETRIC_PT_viewer'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        self.layout.prop(context.scene.airmetric_agr, 'show_collisions')
        self.layout.label(text='Airmetric AGR Viewer ' + updater.current_version())


class AIRMETRIC_OT_check_update(bpy.types.Operator):
    bl_idname = 'airmetric.check_update'
    bl_label = 'Проверить обновления'
    bl_description = 'Получить с GitHub список опубликованных версий плагина. Модели и сцена никуда не отправляются'

    def execute(self, context):
        try:
            if jobs.busy():
                raise ValueError('Дождитесь окончания загрузки архивов')
            updater.check()
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class AIRMETRIC_OT_install_update(bpy.types.Operator):
    bl_idname = 'airmetric.install_update'
    bl_label = 'Установить выбранную версию'
    bl_description = 'Скачать и установить выбранную версию с GitHub. После установки сохраните сцену и перезапустите Blender'
    target: StringProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        if jobs.busy():
            return {'CANCELLED'}
        info = updater.selected(context.scene)
        if info is None or info['version'] == updater.current_version():
            self.report({'INFO'}, 'Выберите другую опубликованную версию')
            return {'CANCELLED'}
        self.target = info['version']
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        self.layout.label(text='Будет установлена версия ' + self.target)
        if updater.updates.version_key(self.target) < updater.updates.version_key(updater.current_version()):
            self.layout.label(text='Это возврат на предыдущую версию.', icon='INFO')
        info = next((r for r in updater.RELEASES if r['version'] == self.target), None)
        if info and info['early']:
            self.layout.label(text='Предварительная версия: возможны ошибки.', icon='INFO')
        self.layout.label(text='После установки потребуется перезапуск Blender.')

    def execute(self, context):
        try:
            if jobs.busy():
                raise ValueError('Дождитесь окончания загрузки архивов')
            info = next(r for r in updater.RELEASES if r['version'] == self.target)
            updater.install(info)
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class AIRMETRIC_PT_updates(bpy.types.Panel):
    bl_label = 'Обновления'
    bl_idname = 'AIRMETRIC_PT_updates'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Airmetric'
    bl_parent_id = 'AIRMETRIC_PT_viewer'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        import textwrap
        layout = self.layout
        layout.label(text='Установлена версия ' + updater.current_version())
        col = layout.column()
        col.enabled = not jobs.busy() and not updater.busy() and not updater.RESTART
        col.operator('airmetric.check_update', icon='FILE_REFRESH')
        if updater.RELEASES:
            col.prop(context.scene.airmetric_agr, 'update_version')
            row = col.row()
            info = updater.selected(context.scene)
            row.enabled = bool(info and info['version'] != updater.current_version())
            row.operator('airmetric.install_update', icon='IMPORT')
        for line in textwrap.wrap(updater.MESSAGE, width=max(24, int(context.region.width / 7))):
            layout.label(text=line)


CLASSES = (AIRMETRIC_PG_settings, AIRMETRIC_OT_import, AIRMETRIC_OT_run_queue,
           AIRMETRIC_OT_review_queue, AIRMETRIC_OT_stop_queue, AIRMETRIC_OT_results,
           AIRMETRIC_OT_clear_scene, AIRMETRIC_OT_frame,
           AIRMETRIC_OT_shading, AIRMETRIC_OT_view, AIRMETRIC_OT_help,
           AIRMETRIC_PT_viewer, AIRMETRIC_PT_extra, AIRMETRIC_OT_check_update,
           AIRMETRIC_OT_install_update, AIRMETRIC_PT_updates)


@bpy.app.handlers.persistent
def stop_before_scene_change(_):
    jobs.stop()
    jobs.LAST = None


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.airmetric_agr = PointerProperty(type=AIRMETRIC_PG_settings)
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        handlers.append(stop_before_scene_change)


def unregister():
    jobs.stop()
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if stop_before_scene_change in handlers:
            handlers.remove(stop_before_scene_change)
    updater.stop()
    del bpy.types.Scene.airmetric_agr
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
