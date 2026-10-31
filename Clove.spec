# PyInstaller spec for Clove on Windows.
# Build: pyinstaller Clove.spec
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
hidden = collect_submodules("google.genai") + collect_submodules("sounddevice") + ["numpy", "PIL", "websockets", "dotenv"]

a = Analysis(
    ["agent.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=[("ui", "ui"), ("chrome_extension", "chrome_extension"), ("helpers", "helpers"), (".env.example", ".")],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Clove",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed app; use console=True for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="ui/clove.ico" if os.path.exists("ui/clove.ico") else None,
    manifest="clove.manifest" if os.path.exists("clove.manifest") else None,
)
