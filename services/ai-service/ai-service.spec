# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

SPECPATH = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821  # SPEC 由 PyInstaller 注入
sys.path.insert(0, SPECPATH)

# uvicorn 以字符串动态导入 app.main:app，PyInstaller 静态分析看不见，需整包收集。
hiddenimports = (
    collect_submodules("app")
    + collect_submodules("qiling_contracts")
    + [
        "uvicorn.logging",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.websockets_impl",
    ]
)
assert any(m == "app.main" for m in hiddenimports), "app 包未被收集，检查构建工作目录"

a = Analysis(
    ['sidecar_entry.py'],
    pathex=[SPECPATH, os.path.join(SPECPATH, '..', '..', 'packages', 'contracts', 'py')],
    binaries=[],
    datas=[],
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
    [],
    exclude_binaries=True,
    name='ai-service',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ai-service',
)
