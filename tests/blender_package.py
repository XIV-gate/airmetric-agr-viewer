"""Register the actual ZIP payload in an existing isolated package directory."""
import importlib.util
import os
from pathlib import Path
import sys
import zipfile
sys.dont_write_bytecode = True
root = Path(os.environ['AGR_VIEWER_TEST_ROOT'])
source = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_validator', source/'airmetric_agr_viewer'/'updates.py')
updates = importlib.util.module_from_spec(spec); spec.loader.exec_module(updates)
data = (root/'packages'/'airmetric_agr_viewer-0.1.0.zip').read_bytes()
files = updates.validate_package(data, '0.1.0')
destination = root/'scripts'
created = []
try:
    for name, content in files.items():
        path = destination/name
        with path.open('xb') as stream:
            stream.write(content)
        created.append(path)
    spec = importlib.util.spec_from_file_location('airmetric_installed', destination/'__init__.py',
                                                 submodule_search_locations=[str(destination)])
    addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
    addon.register()
    import bpy
    assert bpy.types.Scene.airmetric_agr
    assert addon.bl_info['version'] == (0,1,0)
    addon.unregister()
    print('AGR_VIEWER_PACKAGE_REGISTER_OK', len(files), 'verified payload files')
finally:
    for path in created:
        path.unlink(missing_ok=True)
