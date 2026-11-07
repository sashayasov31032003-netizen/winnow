"""Глобальная таблица стилей Qt, собранная из дизайн-токенов.

Здесь нет ни одного «магического» цвета: всё берётся из theme.py. Благодаря
этому смена палитры или добавление новой темы не требует правок в виджетах.
"""

from __future__ import annotations

from winnow.ui.theme import DesignSystem, design_system


def stylesheet(theme: str = "light") -> str:
    """Возвращает таблицу стилей для приложения в выбранной теме."""
    return build_stylesheet(design_system(theme))


def build_stylesheet(ds: DesignSystem) -> str:
    p = ds.palette
    sp = ds.spacing
    r = ds.radii
    t = ds.typography

    return f"""
/* ------------------------------------------------------------------ базовое */

QWidget {{
    color: {p.text};
    font-family: "{t.family}";
    font-size: {t.pt(t.size_base)};
}}

QMainWindow, QDialog {{
    background: {p.canvas};
}}

QToolTip {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {r.sm}px;
    padding: {sp.xs}px {sp.sm}px;
}}

/* ------------------------------------------------------------------- меню */

QMenuBar {{
    background: {p.surface};
    border-bottom: 1px solid {p.border};
    padding: {sp.xxs}px {sp.xs}px;
}}

QMenuBar::item {{
    padding: {sp.xs}px {sp.sm}px;
    border-radius: {r.sm}px;
    background: transparent;
}}

QMenuBar::item:selected {{
    background: {p.accent_soft};
    color: {p.accent};
}}

QMenuBar::item:pressed {{
    background: {p.accent};
    color: {p.text_on_accent};
}}

QMenu {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    padding: {sp.xs}px;
}}

QMenu::item {{
    padding: {sp.xs}px {sp.lg}px {sp.xs}px {sp.md}px;
    border-radius: {r.sm}px;
}}

QMenu::item:selected {{
    background: {p.accent_soft};
    color: {p.accent};
}}

QMenu::item:disabled {{
    color: {p.text_disabled};
}}

QMenu::separator {{
    height: 1px;
    background: {p.border};
    margin: {sp.xs}px {sp.sm}px;
}}

/* --------------------------------------------------------------- панели */

QToolBar {{
    background: {p.surface};
    border-bottom: 1px solid {p.border};
    padding: {sp.xs}px {sp.sm}px;
    spacing: {sp.xs}px;
}}

QToolBar::separator {{
    width: 1px;
    background: {p.border};
    margin: {sp.xs}px {sp.sm}px;
}}

QToolButton {{
    padding: {sp.xs}px {sp.sm}px;
    border-radius: {r.sm}px;
    background: transparent;
    color: {p.text};
}}

QToolButton:hover {{
    background: {p.accent_soft};
    color: {p.accent};
}}

QToolButton:pressed {{
    background: {p.accent};
    color: {p.text_on_accent};
}}

QDockWidget {{
    color: {p.text_muted};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}

QDockWidget::title {{
    background: {p.surface_alt};
    border-bottom: 1px solid {p.border};
    padding: {sp.xs}px {sp.sm}px;
    text-align: left;
    font-size: {t.pt(t.size_small)};
    font-weight: 600;
}}

QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 2px;
}}

QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background: {p.accent_soft};
    border-radius: {r.sm}px;
}}

/* --------------------------------------------------------------- вкладки */

QTabWidget::pane {{
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    background: {p.surface};
    top: -1px;
}}

QTabBar {{
    qproperty-drawBase: 0;
}}

QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    padding: {sp.sm}px {sp.lg}px;
    margin-right: {sp.xxs}px;
    border: 1px solid transparent;
    border-top-left-radius: {r.md}px;
    border-top-right-radius: {r.md}px;
}}

QTabBar::tab:hover {{
    color: {p.accent};
    background: {p.accent_soft};
}}

QTabBar::tab:selected {{
    background: {p.surface};
    color: {p.accent};
    border: 1px solid {p.border};
    border-bottom-color: {p.surface};
    font-weight: 600;
}}

/* -------------------------------------------------------------- кнопки */

QPushButton {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {r.md}px;
    /* Отступы с запасом: при жирном шрифте акцентной кнопки скупые отступы
       приводят к тому, что первая буква упирается в край и выглядит обрезанной.
       Дополнительно ширина кнопок диалогов задаётся программно - см.
       components.action_button_box. */
    padding: {sp.sm}px {sp.xl}px;
    min-height: 24px;
}}

QPushButton:hover {{
    border-color: {p.accent};
    color: {p.accent};
}}

QPushButton:pressed {{
    background: {p.surface_sunken};
}}

QPushButton:disabled {{
    color: {p.text_disabled};
    border-color: {p.border};
}}

QPushButton:default, QPushButton[accent="true"] {{
    background: {p.accent};
    color: {p.text_on_accent};
    border-color: {p.accent};
    font-weight: 600;
}}

QPushButton:default:hover, QPushButton[accent="true"]:hover {{
    background: {p.accent_hover};
    border-color: {p.accent_hover};
    color: {p.text_on_accent};
}}

QPushButton:default:pressed, QPushButton[accent="true"]:pressed {{
    background: {p.accent_pressed};
}}

/* -------------------------------------------------------- поля ввода */

QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox {{
    background: {p.surface_sunken};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    padding: {sp.xs}px {sp.sm}px;
    selection-background-color: {p.accent};
    selection-color: {p.text_on_accent};
}}

QTextBrowser {{
    border: none;
    border-radius: 0;
    background: {p.surface};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {p.accent};
    background: {p.surface};
}}

QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: {p.text_disabled};
}}

QComboBox {{
    background: {p.surface};
    border: 1px solid {p.border_strong};
    border-radius: {r.md}px;
    padding: {sp.xs}px {sp.sm}px;
    min-height: 22px;
}}

QComboBox:hover {{
    border-color: {p.accent};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    padding: {sp.xs}px;
    selection-background-color: {p.accent_soft};
    selection-color: {p.accent};
    outline: none;
}}

/* ------------------------------------------------------------- флажки */

QCheckBox, QRadioButton {{
    spacing: {sp.sm}px;
    padding: {sp.xxs}px 0;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p.border_strong};
    background: {p.surface};
}}

QCheckBox::indicator {{
    border-radius: {r.sm}px;
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {p.accent};
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
}}

QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: {p.surface_sunken};
    border-color: {p.border};
}}

/* -------------------------------------------------------- таблицы данных */

QTableView {{
    background: {p.surface};
    alternate-background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    gridline-color: {p.border};
    selection-background-color: {p.accent_soft};
    selection-color: {p.text};
    outline: none;
}}

QTableView::item {{
    padding: {sp.xxs}px {sp.xs}px;
    border: none;
}}

QTableView::item:selected {{
    background: {p.accent_soft};
    color: {p.text};
}}

QTableView::item:focus {{
    border: 1px solid {p.accent};
}}

QHeaderView {{
    background: {p.surface_alt};
}}

QHeaderView::section {{
    background: {p.surface_alt};
    color: {p.text_muted};
    border: none;
    border-right: 1px solid {p.border};
    border-bottom: 1px solid {p.border};
    padding: {sp.xs + 1}px {sp.sm}px;
    font-weight: 600;
}}

QHeaderView::section:hover {{
    background: {p.accent_soft};
    color: {p.accent};
}}

QTableCornerButton::section {{
    background: {p.surface_alt};
    border: none;
    border-right: 1px solid {p.border};
    border-bottom: 1px solid {p.border};
}}

/* -------------------------------------------------------------- списки */

QListWidget, QListView, QTreeWidget, QTreeView {{
    background: {p.surface_sunken};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    padding: {sp.xxs}px;
    outline: none;
}}

/* Внутренние области прокрутки: Qt по умолчанию берёт для них системный цвет
   (светло-серый) и не наследует фон родителя. Без этих правил в тёмной теме
   остаются крупные светлые участки - заметнее всего в диалогах процедур. */
QScrollArea {{
    background: {p.canvas};
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background: {p.canvas};
}}

QAbstractScrollArea::corner {{
    background: {p.surface_alt};
    border: none;
}}

QWidget#ScrollBody {{
    background: {p.canvas};
}}

/* Переключатель режима: заметная кнопка, а не серый пункт панели. Текущий режим
   подсвечивается заливкой, второй - только рамкой, чтобы было видно и куда
   можно перейти, и где находишься сейчас. */
QPushButton#ModeSwitch {{
    padding: {sp.xs}px {sp.md}px;
    font-weight: 600;
    border: 1px solid {p.accent};
    border-radius: {r.sm}px;
    background: {p.surface_alt};
    color: {p.text};
    margin-left: {sp.sm}px;
}}
QPushButton#ModeSwitch:hover {{
    background: {p.accent_soft};
}}
QPushButton#ModeSwitch:checked {{
    background: {p.accent_soft};
    color: {p.accent};
    border: 2px solid {p.accent};
}}

/* Признак текущего режима в строке состояния: заметная плашка, чтобы человек
   понимал, в каком интерфейсе находится. */
QLabel#ModeBadge {{
    background: {p.accent_soft};
    color: {p.accent};
    border: 1px solid {p.border};
    border-radius: {r.sm}px;
    padding: {sp.xxs}px {sp.sm}px;
    font-weight: 600;
    margin-right: {sp.sm}px;
}}

/* Кнопка очистки вывода стоит в углу вкладок: она должна читаться, но не
   спорить за внимание с заголовком и не выглядеть главной кнопкой окна. */
QPushButton#OutputClear {{
    padding: {sp.xxs}px {sp.sm}px;
    font-size: {t.pt(max(8, t.size_small - 1))};
}}

/* Сообщение о неверных параметрах в окне процедуры. Цвет сочетается с жирным
   шрифтом и словом «Проверьте»: полагаться на один лишь цвет нельзя, часть
   людей его не различает. */
QLabel#DialogError {{
    background: {p.warning_soft};
    color: {p.warning};
    border: 1px solid {p.warning};
    border-radius: {r.sm}px;
    padding: {sp.sm}px {sp.md}px;
    font-weight: 600;
}}

QListWidget::item, QTreeView::item {{
    padding: {sp.xs}px {sp.sm}px;
    border-radius: {r.sm}px;
}}

QListWidget::item:hover, QTreeView::item:hover {{
    background: {p.accent_soft};
}}

QListWidget::item:selected, QTreeView::item:selected {{
    background: {p.accent};
    color: {p.text_on_accent};
}}

/* --------------------------------------------------------- прокрутка */

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 5px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover {{
    background: {p.text_muted};
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 5px;
    min-width: 28px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {p.text_muted};
}}

QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
    border: none;
    height: 0;
    width: 0;
}}

/* ------------------------------------------------------- прочие элементы */

QGroupBox {{
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    margin-top: {sp.md}px;
    padding: {sp.md}px {sp.sm}px {sp.sm}px {sp.sm}px;
    font-weight: 600;
    color: {p.text_muted};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: {sp.sm}px;
    padding: 0 {sp.xs}px;
    background: {p.canvas};
}}

QStatusBar {{
    background: {p.surface};
    border-top: 1px solid {p.border};
    color: {p.text_muted};
    padding: {sp.xxs}px {sp.sm}px;
}}

QStatusBar::item {{
    border: none;
}}

QLabel[role="hint"] {{
    color: {p.text_muted};
    font-size: {t.pt(t.size_small)};
}}

QLabel[role="title"] {{
    font-size: {t.pt(t.size_title)};
    font-weight: 700;
    color: {p.text};
}}

QLabel[role="subtitle"] {{
    font-size: {t.pt(t.size_medium)};
    color: {p.text_muted};
}}

QLabel[role="cardTitle"] {{
    font-size: {t.pt(t.size_large)};
    font-weight: 600;
    color: {p.text};
}}

QProgressBar {{
    background: {p.surface_sunken};
    border: none;
    border-radius: {r.sm}px;
    height: 6px;
    text-align: center;
}}

QProgressBar::chunk {{
    background: {p.accent};
    border-radius: {r.sm}px;
}}

QSplitter::handle {{
    background: {p.border};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}
"""


__all__ = ["build_stylesheet", "stylesheet"]
