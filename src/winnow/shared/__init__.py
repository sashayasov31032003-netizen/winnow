"""Общие данные дизайна и описания процедур для веба и экспорта.

Пакет не импортирует Qt: веб-версия и HTML-экспорт должны работать без PySide6.
"""

from winnow.shared.procedure_specs import DIALOG_SPECS
from winnow.shared.theme import design_system

__all__ = ["DIALOG_SPECS", "design_system"]
