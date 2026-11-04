"""Airmetric AGR Viewer — XIVgate."""
bl_info = {
    'name': 'Airmetric AGR Viewer',
    'author': 'XIVgate',
    'version': (0, 2, 0),
    'blender': (4, 2, 0),
    'location': '3D View → N → Airmetric',
    'description': 'Простой просмотр архивов АГР: ВПМ, НПМ, материалы и виды',
    'category': '3D View',
    'doc_url': 'https://github.com/XIV-gate/airmetric-agr-viewer/blob/main/docs/USER_GUIDE_0.2.0_RU.md',
}


def register():
    from . import ui
    ui.register()


def unregister():
    from . import ui
    ui.unregister()
