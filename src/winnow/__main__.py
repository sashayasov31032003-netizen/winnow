"""Точка входа для собранного приложения.

Нужна отдельным файлом, потому что PyInstaller собирает точку входа, а не
пакет: при запуске .exe рядом нет каталога src, и обычный `python -m winnow`
не сработает.
"""
from winnow.main import main

if __name__ == "__main__":
    raise SystemExit(main())
