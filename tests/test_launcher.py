"""Тесты точки входа run.py: выбор режима и понятные сообщения об ошибках.

Эти тесты появились по конкретному случаю: при двойном щелчке по run.py
запускался GUI, интерфейса в текущем интерпретаторе не было, окно мгновенно
закрывалось без объяснений. Теперь запуск без аргументов означает GUI, а при
отсутствии PySide6 выводится инструкция, что делать.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN_PY = ROOT / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("winnow_run_entry", RUN_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_py_exists():
    assert RUN_PY.exists()


def test_run_py_is_valid_python():
    """Файл должен компилироваться - иначе двойной щелчок даст молчаливый сбой."""
    source = RUN_PY.read_text(encoding="utf-8")
    compile(source, str(RUN_PY), "exec")


@pytest.mark.parametrize(
    ("argv", "expected_mode", "expected_rest"),
    [
        ([], "gui", []),
        (["gui"], "gui", []),
        (["demo"], "demo", []),
        (["version"], "version", []),
        (["--help"], "help", []),
        (["-h"], "help", []),
        (["GUI"], "gui", []),
        (["что-то"], "gui", ["что-то"]),
    ],
)
def test_default_mode_selection(argv, expected_mode, expected_rest):
    module = _load_run_module()
    mode, rest = module._default_mode(argv)
    assert mode == expected_mode
    assert rest == expected_rest


def test_version_mode_prints_version_without_gui():
    """version и demo не должны требовать PySide6."""
    completed = subprocess.run(
        [sys.executable, str(RUN_PY), "version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(ROOT),
    )
    assert completed.returncode == 0
    assert "Winnow" in completed.stdout


def test_help_mode_prints_usage():
    completed = subprocess.run(
        [sys.executable, str(RUN_PY), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(ROOT),
    )
    assert completed.returncode == 0
    assert "run.py demo" in completed.stdout


def test_demo_bat_file_exists():
    """Демо-режим должен запускаться двойным щелчком без интерфейса."""
    assert (ROOT / "Winnow-demo.bat").exists()
    assert (ROOT / "Winnow.bat").exists()


def test_bat_launcher_pauses_so_errors_stay_visible():
    """Главная защита от "быстро закрылось": окно консоли не исчезает."""
    text = (ROOT / "Winnow.bat").read_text(encoding="utf-8")
    assert "pause" in text.lower()
