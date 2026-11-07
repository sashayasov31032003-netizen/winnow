# -*- mode: python ; coding: utf-8 -*-
"""Сборка веб-версии в один exe: сервер, интерфейс и движок в одном файле."""

from PyInstaller.utils.hooks import collect_submodules

# Движок загружает процедуры по имени (REGISTRY), поэтому сборщик их не видит.
# Без этого в собранном виде падало «No module named winnow.stats.descriptives».
hidden = collect_submodules("uvicorn") + collect_submodules("fastapi")
hidden += collect_submodules("winnow.stats")
hidden += collect_submodules("winnow.export")
hidden += collect_submodules("winnow.data")
hidden += collect_submodules("winnow.core")
hidden += collect_submodules("winnow.syntax")
hidden += ["winnow.ui.procedure_specs", "winnow.ui.theme"]
hidden += [
    "sqlalchemy.dialects.sqlite",
    "email_validator",
    "anyio._backends._asyncio",
    "multipart",
]

a = Analysis(
    ["src/winnow/web/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[("web/frontend/dist", "web/frontend/dist")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Winnow-web",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
