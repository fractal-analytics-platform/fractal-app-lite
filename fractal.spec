# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/backend/shell.py'],
    pathex=['.pixi/envs/default/lib'],
    binaries=[],
    datas=[('src/frontend/build', 'frontend/build')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt6.Qt3D', 'PyQt6.QtMultimedia'],
    noarchive=False,
    optimize=0,
)

# Use the host's C++ runtime instead of the build machine's. The system GPU driver
# (Mesa -> libLLVM) is loaded at runtime and may need a newer libstdc++ than the
# one on the build runner; if ours shadows it, EGL/GLX fail and QtWebEngine aborts.
# The host's copy is always at least as new, since we build on the oldest target.
# Same for glib (the host's GIO modules need a glib at least as new as themselves)
# and libgbm (tied to the host's Mesa drivers).
_HOST_LIBS = (
    "libstdc++.so",
    "libgcc_s.so",
    "libglib-2.0.so",
    "libgio-2.0.so",
    "libgobject-2.0.so",
    "libgmodule-2.0.so",
    "libgthread-2.0.so",
    "libgbm.so",
)
a.binaries = [b for b in a.binaries if not b[0].startswith(_HOST_LIBS)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='fractal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
