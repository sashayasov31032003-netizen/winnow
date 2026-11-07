"""Построитель окон процедур из декларативного описания.

Здесь и только здесь живёт Qt-код диалогов. Сами процедуры описаны данными
(procedure_specs), поэтому добавление новой процедуры не требует нового окна.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from winnow.core.dataset import Dataset
from winnow.core.variable import Variable
from winnow.ui.components import action_button_box
from winnow.ui.procedure_specs import DialogSpec, FieldKind, FieldSpec, VarFilter


def _field_label(text: str) -> QLabel:
    """Подпись поля с переносом строк.

    Длинные подписи («Доверительный интервал для среднего», «Коды групп (через
    запятую)») без переноса требуют своей полной ширины и раздувают окно диалога
    так, что правая колонка уезжает за край. С переносом они занимают две строки
    по 160 точек, и всё помещается.
    """
    label = QLabel(text)
    label.setWordWrap(True)
    label.setMaximumWidth(170)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return label


#: Сколько различных значений ещё считается категорией. Совпадает с порогом
#: профиля данных: «2 значения» и «5 значений» — это ответы, а не измерение.
FEW_VALUES = 12


def _few_distinct_values(dataset: Dataset, name: str) -> bool:
    """Мало различных значений — значит по сути категория.

    Объявленному уровню измерения доверять нельзя: файлы SPSS 19 часто помечают
    количественными всё подряд, включая пол, район и отметки 0/1. На таком файле
    список категорий оказывался почти пустым — в таблицах сопряжённости выбирать
    было нечего.
    """
    try:
        series = dataset.frame[name]
    except (KeyError, AttributeError):
        return False
    unique = int(series.nunique(dropna=True))
    return 0 < unique <= FEW_VALUES


def _matches(dataset: Dataset, variable: Variable, var_filter: VarFilter) -> bool:
    if var_filter is VarFilter.NUMERIC:
        return variable.is_numeric
    if var_filter is VarFilter.CATEGORICAL:
        if variable.measure.is_categorical or not variable.is_numeric:
            return True
        return _few_distinct_values(dataset, variable.name)
    return True


class TransferList(QWidget):
    """Список переменных с переносом между "доступными" и "выбранными".

    Классический элемент SPSS. Пользователи, знающие SPSS, ищут именно его,
    поэтому лучше повторить привычный вид, чем изобретать новый.
    """

    #: Ширина списка доступных переменных подстраивается под самые длинные
    #: метки: «Пользуйтесь ли вы технологиями генеративного искусственного
    #: интеллекта?» в 130 точек не помещается, и человек видел обрывок метки.
    #: Сверху ограничена: в диалоге таких списков до четырёх, и без предела окно
    #: вырастает шире экрана - тогда его размер урезается, и списки, ради которых
    #: всё делалось, снова сжимаются до минимума.
    MIN_LIST_WIDTH = 250
    MAX_LIST_WIDTH = 340
    MIN_SELECTED_WIDTH = 180

    def __init__(self, title_left: str, title_right: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        left_box = QVBoxLayout()
        left_box.addWidget(QLabel(title_left))
        self.available = QListWidget()
        self.available.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.available.setMinimumWidth(self.MIN_LIST_WIDTH)
        self.available.itemDoubleClicked.connect(lambda _item: self.add_selected())
        left_box.addWidget(self.available)

        middle = QVBoxLayout()
        middle.addStretch()
        self.add_button = QPushButton("→")
        self.add_button.setToolTip("Добавить выбранные переменные")
        self.add_button.clicked.connect(self.add_selected)
        self.remove_button = QPushButton("←")
        self.remove_button.setToolTip("Убрать выбранные переменные")
        self.remove_button.clicked.connect(self.remove_selected)
        middle.addWidget(self.add_button)
        middle.addWidget(self.remove_button)
        middle.addStretch()

        right_box = QVBoxLayout()
        right_box.addWidget(QLabel(title_right))
        self.selected = QListWidget()
        self.selected.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        # Список выбранных уже: пока переменные не выбраны, он пуст, и отдавать
        # ему половину ширины незачем.
        self.selected.setMinimumWidth(self.MIN_SELECTED_WIDTH)
        self.selected.itemDoubleClicked.connect(lambda _item: self.remove_selected())
        right_box.addWidget(self.selected)

        layout.addLayout(left_box)
        layout.addLayout(middle)
        layout.addLayout(right_box, 1)

    def mark_multi_answer(self, dataset: Dataset) -> None:
        """Помечает вопросы, где можно было выбрать несколько вариантов.

        Без пометки такой вопрос не отличить от обычного: в списке он выглядит
        так же, а таблица по нему строится по-другому - по вариантам ответа.
        """
        from winnow.stats.multianswer import detect_column

        for index in range(self.available.count()):
            item = self.available.item(index)
            name = item.data(Qt.ItemDataRole.UserRole)
            if detect_column(dataset, name) is None:
                continue
            item.setText(item.text() + "  •  несколько ответов")
            item.setToolTip(
                item.text()
                + "\nВарианты склеены в одной ячейке. В таблицах сопряжённости "
                "такой вопрос показывается по вариантам ответа."
            )

    def populate(self, variables: list[Variable]) -> None:
        self.available.clear()
        for variable in variables:
            item = QListWidgetItem(variable.display_name)
            item.setData(Qt.ItemDataRole.UserRole, variable.name)
            # Подсказка на случай, если метка всё равно не поместилась: навести
            # курсор проще, чем тянуть ползунок.
            item.setToolTip(variable.display_name)
            self.available.addItem(item)
        self._fit_available_width(variables)

    def _fit_available_width(self, variables: list[Variable]) -> None:
        """Подбирает ширину списка под самые длинные метки переменных.

        Это и есть адаптивная вёрстка применительно к списку переменных: ширина
        считается по фактическому тексту, а не задана числом. Сверху ограничена,
        иначе метка в сотню символов растянула бы окно шире экрана.
        """
        if not variables:
            self.available.setMinimumWidth(self.MIN_LIST_WIDTH)
            return
        metrics = QFontMetrics(self.available.font())
        widest = max(metrics.horizontalAdvance(item.display_name) for item in variables)
        # Запас на рамку, полосу прокрутки и отступы внутри строки.
        needed = widest + 36
        self.available.setMinimumWidth(
            max(self.MIN_LIST_WIDTH, min(needed, self.MAX_LIST_WIDTH))
        )

    def add_selected(self) -> None:
        existing = {
            self.selected.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.selected.count())
        }
        for item in list(self.available.selectedItems()):
            name = item.data(Qt.ItemDataRole.UserRole)
            if name in existing:
                continue
            clone = QListWidgetItem(item.text())
            clone.setData(Qt.ItemDataRole.UserRole, name)
            clone.setToolTip(item.text())
            self.selected.addItem(clone)
            existing.add(name)

    def remove_selected(self) -> None:
        for item in list(self.selected.selectedItems()):
            self.selected.takeItem(self.selected.row(item))

    def values(self) -> list[str]:
        return [
            self.selected.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.selected.count())
        ]

    def select_names(self, names: list[str]) -> None:
        for index in range(self.available.count()):
            if self.available.item(index).data(Qt.ItemDataRole.UserRole) in names:
                self.available.item(index).setSelected(True)
        self.add_selected()


class ProcedureDialog(QDialog):
    """Окно процедуры, собранное из DialogSpec."""

    def __init__(
        self,
        spec: DialogSpec,
        dataset: Dataset,
        parent: QWidget | None = None,
        theme: str = "light",
    ) -> None:
        super().__init__(parent)
        self.spec = spec
        self.dataset = dataset
        self.theme_name = theme
        self._widgets: dict[str, Any] = {}
        self._checkbox_groups: dict[str, list[tuple[str, QCheckBox]]] = {}

        self.setWindowTitle(spec.title)
        # Ширина не задаётся жёстко: окно подстраивается под содержимое. Иначе
        # у диалогов с тремя колонками правая колонка уходит под горизонтальную
        # прокрутку и выглядит обрезанной.
        self.setSizeGripEnabled(True)

        outer = QVBoxLayout(self)
        if spec.description:
            hint = QLabel(spec.description)
            hint.setStyleSheet("color: #55636f;")
            outer.addWidget(hint)

        # Сообщение о неверных параметрах показывается здесь, в самом окне, а не
        # во всплывающем поверх него окошке: человек видит его рядом с полями,
        # которые нужно исправить, и не теряет введённые значения.
        self.error_label = QLabel()
        self.error_label.setObjectName("DialogError")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        outer.addWidget(self.error_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body = QWidget()
        # Имя нужно, чтобы таблица стилей покрасила именно это тело диалога:
        # у внутренней области прокрутки Qt берёт системный светлый фон.
        body.setObjectName("ScrollBody")
        self._grid = QGridLayout(body)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(10)
        # Тело запоминается: по нему считается нужная ширина окна. Спрашивать
        # sizeHint у самого диалога бесполезно - область прокрутки внутри
        # сообщает свой собственный небольшой размер и содержимое не учитывает.
        self._body = body

        for field in spec.fields:
            self._add_field(field)

        # Свободное место отдаётся колонкам с полями, а не пустому пространству:
        # при растягивании окна расширяются списки переменных, ради которых его
        # и растягивают.
        for column in sorted({field.column for field in spec.fields}):
            self._grid.setColumnStretch(column * 2 + 1, 1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        buttons, _ok, _cancel = action_button_box(self.theme_name, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._fit_to_content()

    # ------------------------------------------------ показ и проверка

    def show_error(self, text: str) -> None:
        """Показывает сообщение о неверных параметрах прямо в окне."""
        self.error_label.setText(text)
        self.error_label.setVisible(True)

    def clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.setVisible(False)

    def build_command(self) -> Any | None:
        """Показывает окно и возвращает готовую к расчёту команду.

        Возвращает None, если пользователь отказался.

        Окно не закрывается при неверных параметрах: сообщение показывается в нём
        самом, а всё введённое остаётся на месте. Иначе одна опечатка в одном
        поле стоила бы всей заполненной формы - человеку пришлось бы открывать
        окно заново и вводить всё сначала.
        """
        from winnow.stats.command import CommandError

        while True:
            # Истинность результата exec(), а не перечисление DialogCode: имя
            # этого перечисления менялось между версиями PySide6.
            if not self.exec():
                return None
            try:
                command = self.spec.build(self.values(), self.dataset)
                command.validate()
            except (ValueError, CommandError) as exc:
                self.show_error(str(exc))
                continue
            return command

    def _fit_to_content(self) -> None:
        """Открывает окно достаточно широким, чтобы подписи были видны.

        Размер считается по содержимому: списки переменных уже сообщили, сколько
        им нужно под самые длинные метки. Сверху размер ограничен и экраном, и
        разумным пределом: открывать окно во весь монитор неудобно, а дальше
        пользователь растянет его сам - места спискам хватит, потому что
        свободное место отдано их колонкам.
        """
        hint = self._body.sizeHint()
        # Поля вокруг тела: рамка области прокрутки, отступы и полоса прокрутки.
        width = hint.width() + 48
        height = hint.height() + 110
        limit = 1180
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            limit = min(limit, int(available.width() * 0.95))
            height = min(height, int(available.height() * 0.9))
        self.resize(max(min(width, limit), 620), max(height, 420))

    # ---------- построение полей ----------

    def _candidate_variables(self, field: FieldSpec) -> list[Variable]:
        return [
            self.dataset.var(name)
            for name in self.dataset.names()
            if _matches(self.dataset, self.dataset.var(name), field.var_filter)
        ]

    def _add_field(self, field: FieldSpec) -> None:
        if field.kind is FieldKind.VARIABLE_LIST:
            widget = TransferList("Доступные:", "Выбранные:", self)
            widget.populate(self._candidate_variables(field))
            widget.mark_multi_answer(self.dataset)
            if field.tooltip:
                widget.setToolTip(field.tooltip)
            self._grid.addWidget(
                QLabel(field.label), field.row, field.column * 2, Qt.AlignmentFlag.AlignTop
            )
            self._grid.addWidget(widget, field.row, field.column * 2 + 1)
            self._widgets[field.name] = widget
            return

        if field.kind is FieldKind.SINGLE_VARIABLE:
            widget = QComboBox()
            widget.addItem("(не выбрано)", None)
            for variable in self._candidate_variables(field):
                widget.addItem(variable.display_name, variable.name)
                # Полная метка в подсказке: в закрытом списке длинная метка
                # обрезается, и узнать переменную можно только наведя курсор.
                widget.setItemData(
                    widget.count() - 1,
                    variable.display_name,
                    Qt.ItemDataRole.ToolTipRole,
                )
            # Список раскрывается на ширину самого длинного пункта, поэтому даже
            # обрезанная метка читается при выборе.
            widget.view().setMinimumWidth(320)
            if field.tooltip:
                widget.setToolTip(field.tooltip)
            self._grid.addWidget(_field_label(field.label), field.row, field.column * 2)
            self._grid.addWidget(widget, field.row, field.column * 2 + 1)
            self._widgets[field.name] = widget
            return

        if field.kind is FieldKind.CHECKBOX:
            widget = QCheckBox(field.label)
            widget.setChecked(bool(field.default))
            if field.tooltip:
                widget.setToolTip(field.tooltip)
            self._grid.addWidget(widget, field.row, field.column * 2, 1, 2)
            self._widgets[field.name] = widget
            return

        if field.kind is FieldKind.OPTION_GROUP:
            box = QGroupBox(field.label)
            layout = QVBoxLayout(box)
            pairs: list[tuple[str, QCheckBox]] = []
            defaults = set(field.default or [])
            for key, label in field.choices:
                checkbox = QCheckBox(label)
                checkbox.setChecked(key in defaults)
                layout.addWidget(checkbox)
                pairs.append((key, checkbox))
            self._grid.addWidget(box, field.row, field.column * 2, 1, 2)
            self._checkbox_groups[field.name] = pairs
            return

        if field.kind is FieldKind.CHOICE:
            widget = QComboBox()
            for label, value in field.choices:
                widget.addItem(label, value)
            if field.default is not None:
                index = widget.findData(field.default)
                if index >= 0:
                    widget.setCurrentIndex(index)
            self._grid.addWidget(_field_label(field.label), field.row, field.column * 2)
            self._grid.addWidget(widget, field.row, field.column * 2 + 1)
            self._widgets[field.name] = widget
            return

        if field.kind is FieldKind.NUMBER:
            widget = QDoubleSpinBox()
            widget.setRange(field.minimum, field.maximum)
            widget.setDecimals(field.decimals)
            widget.setSingleStep(field.step)
            widget.setValue(float(field.default or 0.0))
            if field.tooltip:
                widget.setToolTip(field.tooltip)
            self._grid.addWidget(_field_label(field.label), field.row, field.column * 2)
            self._grid.addWidget(widget, field.row, field.column * 2 + 1)
            self._widgets[field.name] = widget
            return

        if field.kind is FieldKind.TEXT:
            widget = QLineEdit(str(field.default or ""))
            if field.tooltip:
                widget.setToolTip(field.tooltip)
            self._grid.addWidget(_field_label(field.label), field.row, field.column * 2)
            self._grid.addWidget(widget, field.row, field.column * 2 + 1)
            self._widgets[field.name] = widget
            return

        raise ValueError(f"Неизвестный тип поля: {field.kind}")

    # ---------- сбор значений ----------

    def set_value(self, name: str, value: Any) -> bool:
        """Задаёт значение поля программно.

        Нужно, когда вид процедуры определяется не диалогом, а пунктом меню:
        например, из меню «Графики» открывается одно окно, но вид графика уже
        выбран. Возвращает False, если поля с таким именем нет.
        """
        widget = self._widgets.get(name)
        if widget is None:
            return False
        if isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index < 0:
                index = widget.findText(str(value))
            if index >= 0:
                widget.setCurrentIndex(index)
                return True
            return False
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
            return True
        if isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(value))
            return True
        if isinstance(widget, QLineEdit):
            widget.setText(str(value))
            return True
        if isinstance(widget, TransferList):
            # Список переменных задаётся программно так же часто, как остальные
            # поля (например, при запуске сценария), и без этой ветки вызов
            # молча ничего не делал.
            widget.selected.clear()
            names = [str(item) for item in (value or [])]
            if names:
                widget.select_names(names)
            return True
        return False

    def values(self) -> dict[str, Any]:
        collected: dict[str, Any] = {}
        for name, widget in self._widgets.items():
            if isinstance(widget, TransferList):
                collected[name] = widget.values()
            elif isinstance(widget, QComboBox):
                collected[name] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                collected[name] = widget.isChecked()
            elif isinstance(widget, QDoubleSpinBox):
                collected[name] = widget.value()
            elif isinstance(widget, QLineEdit):
                collected[name] = widget.text()
            else:  # pragma: no cover - защита от нового типа поля
                collected[name] = None

        for name, pairs in self._checkbox_groups.items():
            collected[name] = [key for key, checkbox in pairs if checkbox.isChecked()]
        return collected


__all__ = ["ProcedureDialog", "TransferList"]
