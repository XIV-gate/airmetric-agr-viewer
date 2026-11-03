"""Russian N-panel with descriptions on every interactive control."""
from pathlib import Path
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, PointerProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler
from math import radians
from . import importer, viewport, updater


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
        return context.mode == 'OBJECT' and not updater.busy() and not updater.RESTART

    def execute(self, context):
        paths = [Path(self.directory) / item.name for item in self.files] or [Path(self.filepath)]
        wm = context.window_manager
        settings = context.scene.airmetric_agr
        try:
            wm.progress_begin(0, len(paths))
            result = importer.import_archives(paths, progress=lambda i, n, name: wm.progress_update(i))
            settings.status = f"Загружено архивов: {result['archives']}; объектов: {result['objects']}"
            if context.area and context.area.type == 'VIEW_3D':
                try:
                    viewport.frame(context)
                except ValueError:
                    # A successful import remains successful with both switches off.
                    settings.status += '. Включите ВПМ или НПМ для просмотра.'
                context.space_data.shading.type = 'MATERIAL'
            self.report({'INFO'}, settings.status)
            return {'FINISHED'}
        except Exception as error:
            settings.status = 'Не удалось загрузить: ' + str(error)
            self.report({'ERROR'}, settings.status)
            return {'CANCELLED'}
        finally:
            wm.progress_end()


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
    bl_label = 'Инструкция со скриншотами'
    bl_description = 'Открыть пошаговую русскую инструкцию: установка, загрузка архивов, просмотр и обновления'

    def execute(self, context):
        bpy.ops.wm.url_open(url='https://github.com/XIV-gate/airmetric-agr-viewer/blob/main/docs/USER_GUIDE_RU.md')
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
        self.layout.label(text='Airmetric AGR Viewer 0.1.0')


class AIRMETRIC_OT_check_update(bpy.types.Operator):
    bl_idname = 'airmetric.check_update'
    bl_label = 'Проверить обновления'
    bl_description = 'Получить с GitHub список опубликованных версий плагина. Модели и сцена никуда не отправляются'

    def execute(self, context):
        try:
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
        col.enabled = not updater.busy() and not updater.RESTART
        col.operator('airmetric.check_update', icon='FILE_REFRESH')
        if updater.RELEASES:
            col.prop(context.scene.airmetric_agr, 'update_version')
            row = col.row()
            info = updater.selected(context.scene)
            row.enabled = bool(info and info['version'] != updater.current_version())
            row.operator('airmetric.install_update', icon='IMPORT')
        for line in textwrap.wrap(updater.MESSAGE, width=max(24, int(context.region.width / 7))):
            layout.label(text=line)


CLASSES = (AIRMETRIC_PG_settings, AIRMETRIC_OT_import, AIRMETRIC_OT_frame,
           AIRMETRIC_OT_shading, AIRMETRIC_OT_view, AIRMETRIC_OT_help,
           AIRMETRIC_PT_viewer, AIRMETRIC_PT_extra, AIRMETRIC_OT_check_update,
           AIRMETRIC_OT_install_update, AIRMETRIC_PT_updates)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.airmetric_agr = PointerProperty(type=AIRMETRIC_PG_settings)


def unregister():
    updater.stop()
    del bpy.types.Scene.airmetric_agr
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
