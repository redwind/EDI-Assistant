# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: one-folder, windowed. Build: pyinstaller packaging/edi_assistant.spec --clean --noconfirm
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821  (SPECPATH is provided by PyInstaller)
PKG = os.path.join(ROOT, "edi_assistant")
RES = os.path.join(PKG, "app", "resources")

datas = [
    (os.path.join(PKG, "automation", "selectors.yaml"), "edi_assistant/automation"),
    (os.path.join(PKG, "automation", "picker.js"), "edi_assistant/automation"),
    (os.path.join(RES, "*"), "edi_assistant/app/resources"),
    (os.path.join(ROOT, "README.md"), "."),
    (os.path.join(ROOT, "README_VI.md"), "."),
]

a = Analysis(  # noqa: F821
    [os.path.join(PKG, "__main__.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["edi_assistant.app.strings_en", "edi_assistant.app.strings_vi",   # loaded via importlib
                   "edi_assistant.mock_edi", "edi_assistant.mock_edi.server", "pypdf", "winsound"],
    hookspath=[os.path.join(ROOT, "packaging", "hooks")],
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
              "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
              "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
              "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf",
              "PySide6.QtPdfWidgets"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="EDI Assistant",
    console=False,
    upx=False,
    icon=os.path.join(RES, "app.ico"),
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
)
coll = COLLECT(  # noqa: F821
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="EDI Assistant",
)
