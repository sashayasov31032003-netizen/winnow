"""Работа с синтаксисом SPSS: сохранение и разбор файлов `.sps`."""

from winnow.syntax.sps import (
    SyntaxError_,
    build_syntax,
    execute_syntax,
    load_syntax,
    parse_syntax,
    save_syntax,
)

__all__ = [
    "SyntaxError_",
    "build_syntax",
    "execute_syntax",
    "load_syntax",
    "parse_syntax",
    "save_syntax",
]
