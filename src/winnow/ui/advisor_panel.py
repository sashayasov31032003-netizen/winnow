"""Панель подсказок: что можно сделать с загруженными данными.

Зачем она нужна. Программа рассчитана в том числе на человека, который не знает,
чем t-критерий отличается от корреляции. Ему бесполезен список из четырнадцати
процедур: чтобы выбрать, нужно уже понимать, что выбираешь. Панель берёт этот
выбор на себя - она показывает, что в данных есть и какие исследования в них
возможны, а запуск делается одной кнопкой.

Это лицо простого режима: человек открывает программу и видит не пустое окно с
меню, а ответ на вопрос «и что мне теперь делать».
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from winnow.core.dataset import Dataset
from winnow.stats.advisor import Scenario, suggest_scenarios
from winnow.stats.profile import DatasetProfile, profile_dataset
from winnow.ui.theme import design_system


def _variants(count: int) -> str:
    """Согласует слово «вариант» с числом: 1 вариант, 3 варианта, 5 вариантов."""
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} вариант"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} варианта"
    return f"{count} вариантов"


class AdvisorPanel(QWidget):
    """Панель «что можно сделать с этими данными»."""

    #: Запустить сценарий: ключ процедуры и её параметры.
    scenarioRequested = Signal(str, dict)
    openDataRequested = Signal()
    demoRequested = Signal()
    #: Разбить вопросы с несколькими ответами на переменные-отметки.
    splitRequested = Signal()

    def __init__(self, parent: QWidget | None = None, theme: str = "light") -> None:
        super().__init__(parent)
        self.theme_name = theme
        self.dataset: Dataset | None = None
        self.profile: DatasetProfile | None = None
        self.scenarios: list[Scenario] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        self.heading = QLabel("Что можно сделать с этими данными")
        self.heading.setObjectName("advisorHeading")
        outer.addWidget(self.heading)

        self.subheading = QLabel()
        self.subheading.setObjectName("advisorSubheading")
        self.subheading.setWordWrap(True)
        outer.addWidget(self.subheading)

        # Содержимое прокручивается: сценариев и замечаний может быть много, а
        # окно у пользователя не бесконечное.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)

        # По горизонтали панель обязана занимать всю ширину: с «предпочтительной»
        # политикой она сжималась до ширины подсказки, и справа оставалась пустая
        # полоса.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Ниже этого панель становится бесполезной: объяснения не помещаются и
        # текст обрезается на полуслове.
        self.setMinimumWidth(420)
        self.set_theme(theme)
        self.refresh()

    # ------------------------------------------------------------------ тема
    def set_theme(self, theme: str) -> None:
        self.theme_name = theme
        palette = design_system(theme).palette
        # Оформление задаётся здесь, а не в общем стиле: панель должна выглядеть
        # как отдельный экран, а не как ещё одна таблица.
        self.setStyleSheet(
            f"""
            QWidget#advisorBody {{ background: {palette.canvas}; }}
            QLabel#advisorHeading {{ font-size: 16px; font-weight: 600;
                                    color: {palette.text}; }}
            QLabel#advisorSubheading {{ color: {palette.text_muted}; }}
            QFrame#advisorCard {{ background: {palette.surface};
                                  border: 1px solid {palette.border};
                                  border-radius: 6px; }}
            QLabel#cardTitle {{ font-size: 14px; font-weight: 600;
                                color: {palette.text}; }}
            QLabel#cardQuestion {{ color: {palette.text}; }}
            QLabel#cardWhy {{ color: {palette.text_muted}; font-size: 12px; }}
            QLabel#cardCaveat {{ color: {palette.warning}; font-size: 12px; }}
            QLabel#notesTitle {{ font-weight: 600; color: {palette.text}; }}
            QLabel#note {{ color: {palette.text_muted}; font-size: 12px; }}
            """
        )
        self.body.setObjectName("advisorBody")

    # --------------------------------------------------------------- данные
    def set_dataset(self, dataset: Dataset | None) -> None:
        """Показывает подсказки для нового набора."""
        self.dataset = dataset
        self.refresh()

    def refresh(self) -> None:
        """Перестраивает содержимое панели."""
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Сначала отвязываем от родителя, и только потом удаляем:
                # deleteLater() откладывается до цикла событий, а до тех пор
                # старый виджет остаётся видимым и накладывается на новый -
                # содержимое панели выглядело удвоенным.
                widget.setParent(None)
                widget.deleteLater()
            child = item.layout()
            if child is not None:
                self._clear_layout(child)

        if self.dataset is None or not self.dataset.names():
            self.profile = None
            self.scenarios = []
            self.subheading.setText(
                "Загрузите файл с данными — программа посмотрит, что в нём есть, "
                "и предложит подходящие исследования."
            )
            # Пустая панель - это приветствие, а не список: текст и кнопки по
            # центру, иначе они теряются в левом верхнем углу пустого окна.
            self.heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.subheading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._add_empty_state()
        else:
            self.heading.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.subheading.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.profile = profile_dataset(self.dataset)
            self.scenarios = suggest_scenarios(self.dataset, profile=self.profile)
            cases = self.profile.n_cases
            variables = self.profile.n_variables
            self.subheading.setText(
                f"В наборе {cases} случаев и {variables} переменных. "
                "Выберите, что хотите узнать: расчёт выполнится сразу, "
                "а в выводе первым будет объяснение простыми словами."
            )
            self._add_notes()
            self._add_multi_answer()
            self._add_scenarios()

        self.body_layout.addStretch(1)

    def _clear_layout(self, layout: Any) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            child = item.layout()
            if child is not None:
                self._clear_layout(child)

    # ------------------------------------------------------------ наполнение
    def _add_empty_state(self) -> None:
        card = QFrame()
        card.setObjectName("advisorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QLabel("С чего начать")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        for text in (
            "«Открыть данные» — прочитать файл SPSS (.sav), Excel или CSV.",
            "«Демонстрационные данные» — посмотреть, как всё работает, "
            "на готовом наборе опроса.",
        ):
            line = QLabel("• " + text)
            line.setObjectName("note")
            line.setWordWrap(True)
            layout.addWidget(line)

        buttons = QHBoxLayout()
        open_button = QPushButton("Открыть данные…")
        open_button.clicked.connect(self.openDataRequested.emit)
        demo_button = QPushButton("Демонстрационные данные")
        demo_button.clicked.connect(self.demoRequested.emit)
        # Кнопки по центру карточки: это первое, что видит человек, и искать их
        # взглядом по углам он не должен.
        buttons.addStretch(1)
        buttons.addWidget(open_button)
        buttons.addWidget(demo_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        # Карточка ограничена по ширине и стоит по центру панели: растянутая на
        # весь экран, она выглядит пустой, а прижатая влево - потерянной.
        card.setMaximumWidth(620)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        self.body_layout.addStretch(1)
        self.body_layout.addLayout(row)

    def _add_notes(self) -> None:
        assert self.profile is not None
        if not self.profile.notes:
            return
        card = QFrame()
        card.setObjectName("advisorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title = QLabel("Что важно знать об этих данных")
        title.setObjectName("notesTitle")
        layout.addWidget(title)

        for note in self.profile.notes:
            line = QLabel("• " + note)
            line.setObjectName("note")
            line.setWordWrap(True)
            layout.addWidget(line)
        self.body_layout.addWidget(card)

    def _add_multi_answer(self) -> None:
        """Вопросы с несколькими ответами: объяснить и предложить разбить.

        Человек, открывший такую анкету, видит столбец с «2. Соцсети;7. Форумы» и
        не понимает, почему по нему не считаются ни частоты, ни таблицы. Здесь
        написано, в чём дело, какие это вопросы и что с ними делать.
        """
        if self.dataset is None:
            return
        from winnow.stats.multianswer import detect_multi_answer, has_marks

        # Уже разбитые вопросы не показываются: отметки созданы, и предлагать
        # разбить их снова значит плодить дубли.
        found = [
            item for item in detect_multi_answer(self.dataset) if not has_marks(self.dataset, item)
        ]
        if not found:
            return
        total_options = sum(len(item.options) for item in found)

        card = QFrame()
        card.setObjectName("advisorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title = QLabel("Вопросы с несколькими ответами")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        explanation = QLabel(
            f"Найдено вопросов: {len(found)}, вариантов в них: {total_options}. "
            "В этих вопросах человек мог выбрать несколько вариантов, и они "
            "склеены в одну ячейку через «;» или запятую. Поэтому по ним не "
            "строятся ни частоты, ни таблицы сопряжённости: программа видит "
            "десятки уникальных строк вместо вариантов ответа."
        )
        explanation.setObjectName("cardQuestion")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        for item in found[:3]:
            line = QLabel(f"• «{item.label}» — {_variants(len(item.options))}")
            line.setObjectName("note")
            line.setWordWrap(True)
            layout.addWidget(line)
        if len(found) > 3:
            more = QLabel(f"• и ещё {len(found) - 3}")
            more.setObjectName("note")
            layout.addWidget(more)

        what = QLabel(
            "Разбить на отдельные переменные-отметки? Каждый вариант станет "
            "переменной со значениями 1 (выбрано) и 0 (не выбрано), а текст "
            "варианта попадёт в метку. Исходные переменные останутся на месте."
        )
        what.setObjectName("cardWhy")
        what.setWordWrap(True)
        layout.addWidget(what)

        row = QHBoxLayout()
        button = QPushButton("Разбить на отметки")
        button.setToolTip("Создать переменные 1/0 для каждого варианта ответа")
        button.clicked.connect(self.splitRequested.emit)
        row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.body_layout.addWidget(card)

    def _add_scenarios(self) -> None:
        if not self.scenarios:
            card = QFrame()
            card.setObjectName("advisorCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 12, 14, 12)
            message = QLabel(
                "Подсказать нечего: в наборе нет переменных, пригодных для анализа. "
                "Обычно так бывает, если все переменные — номера строк или "
                "одинаковые значения."
            )
            message.setObjectName("note")
            message.setWordWrap(True)
            layout.addWidget(message)
            self.body_layout.addWidget(card)
            return

        for scenario in self.scenarios:
            self.body_layout.addWidget(self._scenario_card(scenario))

    def _scenario_card(self, scenario: Scenario) -> QFrame:
        card = QFrame()
        card.setObjectName("advisorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel(scenario.title)
        title.setObjectName("cardTitle")
        header.addWidget(title)
        header.addStretch(1)

        if scenario.is_confident:
            mark = QLabel("подходит")
            mark.setObjectName("cardWhy")
            header.addWidget(mark)
        layout.addLayout(header)

        question = QLabel(scenario.question)
        question.setObjectName("cardQuestion")
        question.setWordWrap(True)
        layout.addWidget(question)

        why = QLabel("Почему: " + scenario.why)
        why.setObjectName("cardWhy")
        why.setWordWrap(True)
        layout.addWidget(why)

        variables = ", ".join(
            f"{role}: {name}" for role, name in scenario.roles.items()
        )
        if variables:
            names = QLabel("Переменные — " + variables)
            names.setObjectName("cardWhy")
            names.setWordWrap(True)
            layout.addWidget(names)

        for caveat in scenario.caveats[:1]:
            warning = QLabel("Учтите: " + caveat)
            warning.setObjectName("cardCaveat")
            warning.setWordWrap(True)
            layout.addWidget(warning)

        row = QHBoxLayout()
        run_button = QPushButton("Выполнить")
        run_button.setToolTip("Запустить этот расчёт на текущих данных")
        run_button.clicked.connect(
            lambda _checked=False, item=scenario: self.scenarioRequested.emit(
                item.procedure, dict(item.params)
            )
        )
        row.addWidget(run_button)
        row.addStretch(1)
        layout.addLayout(row)
        return card


__all__ = ["AdvisorPanel"]
