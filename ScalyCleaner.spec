# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

spec_dir = os.path.dirname(os.path.abspath(SPEC))
assets_dir = os.path.join(spec_dir, 'assets')
logo_ico = os.path.join(assets_dir, 'logo.ico')

datas = [
    (assets_dir, 'assets'),
    (os.path.join(spec_dir, 'release_settings.json'), '.'),
]
binaries = []
hiddenimports = [
    'PIL._tkinter_finder',
    'scalyclean',
    'scalyclean._integrity',
]
hiddenimports += collect_submodules('scalyclean')
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# python312.dll + VC runtime рядом с bootloader (меньше сбоев LoadLibrary в _MEI*)
_py_dll = os.path.join(sys.base_prefix, f'python{sys.version_info.major}{sys.version_info.minor}.dll')
if os.path.isfile(_py_dll):
    binaries.append((_py_dll, '.'))

a = Analysis(
    ['main.py'],
    pathex=[spec_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ScalyCleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=logo_ico if os.path.isfile(logo_ico) else None,
)
