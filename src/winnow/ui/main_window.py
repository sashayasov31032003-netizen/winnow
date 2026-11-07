"""Главное окно: рабочее пространство в духе SPSS с современным оформлением.

Структура окна повторяет привычную логику SPSS - редактор данных слева, вывод
справа, меню сгруппировано по задачам, - но исполнение современное: единая
палитра, скругления, тёмная тема, дерево вывода и строка формул.

Три вещи здесь принципиальны:
  1) вид задаётся дизайн-системой, а не разбросанными по коду цветами;
  2) меню показывает и то, что ещё не сделано, но честно помечает такие пункты:
     пользователь видит план развития, а не пустоту;
  3) расчёты идут в отдельном потоке, иначе окно «зависает» на больших данных.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableView,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from winnow.core.dataset import Dataset
from winnow.data.io.registry import (
    file_dialog_filters,
    format_for_path,
    read_dataset,
    save_dialog_filters,
    write_dataset,
)
from winnow.export import report_to_html
from winnow.stats.command import Command
from winnow.stats.engine import REGISTRY, REGISTRY_BY_KEY
from winnow.ui.advisor_panel import AdvisorPanel
from winnow.ui.components import EmptyState, FormulaBar
from winnow.ui.dialogs import ProcedureDialog
from winnow.ui.models import DataTableModel, VariableTableModel
from winnow.ui.output_tree import OutputTree
from winnow.ui.styles import stylesheet
from winnow.ui.theme import THEMES, design_system, qt_palette
from winnow.ui.variable_dialog import VariableDialog

# Пункты меню, которые ещё не реализованы. Их полезно показывать: видно план
# развития, а не пустоту. Но они честно отключены и не притворяются рабочими.
PLANNED: dict[str, str] = {
    "compute": "Вычисление переменной — следующая волна развития",
    "recode": "Перекодирование — следующая волна развития",
    "weight": "Веса поддерживаются в модели данных, диалог появится позже",
    "select": "Отбор кейсов поддерживается в модели данных, диалог появится позже",
    "anova": "Однофакторный ANOVA — следующая по плану процедура",
    "regression": "Регрессия — следующая по плану процедура",
    "nonparametric": "Непараметрические критерии — следующая по плану процедура",
    "reliability": "Надёжность (альфа Кронбаха) — третья волна",
    "factor": "Факторный анализ — третья волна",
    "charts": "Графики — третья волна",
}


class ProcedureTask(QRunnable):
    """Запуск процедуры в отдельном потоке."""

    class Signals(QObject):
        done = Signal(object)     # Result
        failed = Signal(object)   # Exception

    def __init__(self, command: Command) -> None:
        super().__init__()
        self.command = command
        self.signals = ProcedureTask.Signals()

    @Slot()
    def run(self) -> None:  # pragma: no cover - требует потока
        try:
            result = self.command.execute()
        except Exception as exc:  # noqa: BLE001 - текст показываем пользователю
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


def _accepted(dialog: QDialog) -> bool:
    """Проверяет, что пользователь нажал «Выполнить».

    Через истинность результата exec(), а не через перечисление DialogCode: имя
    этого перечисления менялось между версиями PySide6, и обращение к нему —
    лишний риск получить AttributeError вместо диалога.
    """
    return bool(dialog.exec())


class MainWindow(QMainWindow):
    def __init__(self, dataset: Dataset | None = None, theme: str = "light") -> None:
        super().__init__()
        self.setWindowTitle("Winnow")
        self.resize(1440, 900)

        self.dataset: Dataset | None = None
        self.current_path: Path | None = None
        # Последняя папка, из которой открывали или куда сохраняли. Диалог должен
        # открываться там же: иначе каждый раз начинается с папки программы, и
        # файл приходится искать заново.
        self._last_dir: str = ""
        self.results: list[Any] = []
        self.syntax_log: list[str] = []
        # Открытые окна графиков: без ссылки они закрылись бы сразу после показа.
        self._chart_windows: list[Any] = []
        self.theme_name = theme if theme in THEMES else "light"
        # Режим интерфейса: простой или экспертный. По умолчанию простой -
        # программа рассчитана в том числе на человека, который не знает, чем
        # t-критерий отличается от корреляции, и четырнадцать процедур в меню ему
        # ничего не подскажут.
        self.interface_mode = self._load_interface_mode()
        self._pool = QThreadPool.globalInstance()

        self.data_model = DataTableModel()
        self.variable_model = VariableTableModel()

        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self.apply_theme(self.theme_name)
        self._apply_interface_mode()

        if dataset is not None:
            self.set_dataset(dataset)
        else:
            self._show_welcome()

    # ------------------------------------------------------------------ тема

    def apply_theme(self, theme: str) -> None:
        """Применяет тему ко всему приложению и перерисовывает вывод.

        кроме таблицы стилей задаётся и палитра Qt: часть внутренних элементов
        (область прокрутки диалога, вьюпорт, подсказки) берёт цвет именно из неё,
        и без палитры в тёмной теме остаются светлые участки.
        """
        self.theme_name = theme if theme in THEMES else "light"
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet(self.theme_name))
            app.setPalette(qt_palette(self.theme_name))
        self._refresh_output()
        self._sync_theme_actions()
        if hasattr(self, "toolbar"):
            self._refresh_toolbar_icons()
        if hasattr(self, "advisor_panel"):
            self.advisor_panel.set_theme(self.theme_name)
        # Открытые окна графиков рисуются своим кодом, поэтому таблицы стилей им
        # мало: тему нужно передать им явно, иначе график останется в старой.
        for window in getattr(self, "_chart_windows", []):
            try:
                window.apply_theme(self.theme_name)
            except AttributeError:
                continue

    def _sync_theme_actions(self) -> None:
        for name, action in getattr(self, "_theme_actions", {}).items():
            action.setChecked(name == self.theme_name)

    # -------------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        # --- редактор данных: данные | переменные ---------------------------
        self.data_view = QTableView()
        self.data_view.setModel(self.data_model)
        self.data_view.setAlternatingRowColors(True)
        self.data_view.setSortingEnabled(False)
        self.data_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self.data_view.horizontalHeader().setStretchLastSection(True)
        self.data_view.verticalHeader().setDefaultSectionSize(24)
        self.data_view.selectionModel().currentChanged.connect(self._on_cell_changed)

        self.variable_view = QTableView()
        self.variable_view.setModel(self.variable_model)
        self.variable_view.setAlternatingRowColors(True)
        self.variable_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.variable_view.horizontalHeader().setStretchLastSection(True)
        self.variable_view.verticalHeader().setDefaultSectionSize(24)
        self.variable_view.doubleClicked.connect(self._edit_variable_at)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        self.formula_bar = FormulaBar(theme=self.theme_name)
        self.formula_bar.valueEdited.connect(self._apply_formula_value)
        editor_layout.addWidget(self.formula_bar)

        self.data_tabs = QTabWidget()
        self.data_tabs.addTab(self.data_view, "Данные")
        self.data_tabs.addTab(self.variable_view, "Переменные")
        editor_layout.addWidget(self.data_tabs, 1)

        self.editor_dock = QDockWidget("Редактор данных", self)
        self.editor_dock.setWidget(editor)
        self.editor_dock.setMinimumWidth(620)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.editor_dock)

        # --- вывод: дерево | таблицы ---------------------------------------
        self.output_tree = OutputTree()
        self.output_tree.nodeSelected.connect(self._on_output_node)

        self.output_browser = QTextBrowser()
        self.output_browser.setOpenExternalLinks(False)

        self.syntax_edit = QPlainTextEdit()
        self.syntax_edit.setReadOnly(True)
        self.syntax_edit.setPlaceholderText(
            "Здесь появляется синтаксис выполненных процедур"
        )

        viewer_split = QSplitter(Qt.Orientation.Horizontal)
        viewer_split.addWidget(self.output_tree)
        viewer_split.addWidget(self.output_browser)
        viewer_split.setStretchFactor(0, 0)
        viewer_split.setStretchFactor(1, 1)
        viewer_split.setSizes([220, 760])

        viewer_tabs = QTabWidget()
        viewer_tabs.addTab(viewer_split, "Вывод")
        viewer_tabs.addTab(self.syntax_edit, "Синтаксис")
        self.viewer_tabs = viewer_tabs

        # Кнопка очистки стоит в самой панели вывода, а не только на панели
        # инструментов: чистить вывод человек ищет там, куда смотрит, - рядом с
        # самими результатами, а не среди кнопок запуска процедур.
        self.clear_output_button = QPushButton("Очистить вывод")
        self.clear_output_button.setObjectName("OutputClear")
        self.clear_output_button.setToolTip(
            "Убрать из вывода все результаты, чтобы начать заново"
        )
        self.clear_output_button.clicked.connect(self.clear_output)
        viewer_tabs.setCornerWidget(
            self.clear_output_button, Qt.Corner.TopRightCorner
        )

        self.output_dock = QDockWidget("Вывод", self)
        self.output_dock.setWidget(viewer_tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.output_dock)

        # --- центральная область -------------------------------------------
        self.central = QWidget()
        self.central_layout = QVBoxLayout(self.central)
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(self.central)

        # Панель подсказок живёт в центральной области: она и есть ответ на
        # вопрос «что мне делать с этими данными». Показывается в простом режиме.
        self.advisor_panel = AdvisorPanel(theme=self.theme_name)
        self.advisor_panel.openDataRequested.connect(self.open_dataset)
        self.advisor_panel.demoRequested.connect(self.load_demo_dataset)
        self.advisor_panel.scenarioRequested.connect(self.run_scenario)
        # Кнопка в карточке уже объяснила, что произойдёт, поэтому лишний вопрос
        # «а точно разбить?» здесь только мешает.
        self.advisor_panel.splitRequested.connect(
            lambda: self.split_multi_answer(confirm=False)
        )
        self.central_layout.addWidget(self.advisor_panel, 1)

        # --- строка состояния ----------------------------------------------
        self.status_label = QLabel("Данные не загружены")
        self.statusBar().addWidget(self.status_label)
        # Признак режима стоит в строке состояния постоянно: подпись на кнопке
        # видно, только если смотреть на кнопку, а человеку нужно сразу понимать,
        # в каком интерфейсе он находится.
        self.mode_badge = QLabel("Простой режим")
        self.mode_badge.setObjectName("ModeBadge")
        self.statusBar().addPermanentWidget(self.mode_badge)
        self.statusBar().addPermanentWidget(QLabel("Winnow 0.1"))

    def _clear_central(self) -> None:
        """Убирает из центральной области всё, кроме панели подсказок.

        Панель подсказок создаётся один раз и живёт всё время работы программы:
        если её удалить, ссылка останется на уничтоженный объект, и следующее
        обращение к ней уронит программу.

        Важно: `takeAt` вынимает виджет из раскладки, поэтому панель нужно
        вернуть обратно. Иначе она остаётся без раскладки, висит в стороне
        размером по умолчанию и не растягивается на своё место.
        """
        panel = getattr(self, "advisor_panel", None)
        while self.central_layout.count():
            item = self.central_layout.takeAt(0)
            widget = item.widget()
            if widget is None or widget is panel:
                continue
            widget.setParent(None)
            widget.deleteLater()
        if panel is not None and self.central_layout.indexOf(panel) == -1:
            self.central_layout.addWidget(panel, 1)

    def _show_welcome(self) -> None:
        """Приветственный экран: первое, что видит открывший программу.

        Панели данных и вывода на время скрываются: пока данных нет, они пусты,
        а приветствие должно занимать всё окно, иначе оно выглядит зажатым.

        В простом режиме отдельного приветствия нет: панель подсказок сама
        объясняет, с чего начать, и предлагает те же кнопки. Два приветствия
        подряд человек читать не станет.
        """
        self.editor_dock.setVisible(False)
        self.output_dock.setVisible(False)
        if self.interface_mode == "simple" and hasattr(self, "advisor_panel"):
            self._clear_central()
            self.advisor_panel.set_dataset(None)
            self.central.setVisible(True)
            return

        self._clear_central()
        self.central.setVisible(True)
        welcome = EmptyState(
            title="Winnow",
            subtitle=(
                "Статистический анализ данных с привычной логикой SPSS\n"
                "и современным интерфейсом"
            ),
            actions=[
                (
                    "Открыть данные",
                    "SPSS (.sav), Excel, CSV или набор Winnow",
                    self.open_dataset,
                ),
                (
                    "Демонстрационный набор",
                    "Опрос из 200 респондентов с готовыми метками переменных",
                    self.load_demo_dataset,
                ),
                (
                    "Пустой набор данных",
                    "Создать переменные вручную",
                    self.new_empty_dataset,
                ),
            ],
            theme=self.theme_name,
        )
        self.central_layout.addWidget(welcome)

    # ------------------------------------------------------------------ меню

    def _add_action(
        self,
        menu: Any,
        title: str,
        callback: Callable[[], None] | None = None,
        shortcut: str | QKeySequence | None = None,
        planned_key: str | None = None,
        tip: str = "",
    ) -> QAction:
        """Добавляет пункт меню.

        Если callback не задан и указан planned_key, пункт отключается и
        подсказывает, когда появится.
        """
        action = QAction(title, self)
        if shortcut:
            action.setShortcut(shortcut)
        if tip:
            action.setStatusTip(tip)
            action.setToolTip(tip)

        if callback is not None:
            action.triggered.connect(lambda _checked=False, fn=callback: fn())
        elif planned_key is not None:
            action.setEnabled(False)
            action.setStatusTip(PLANNED.get(planned_key, "В разработке"))
            action.setToolTip(PLANNED.get(planned_key, "В разработке"))
        menu.addAction(action)
        return action

    def _build_menus(self) -> None:
        bar = self.menuBar()

        # ------------------------------------------------------------- Файл
        file_menu = bar.addMenu("&Файл")
        self._add_action(
            file_menu,
            "&Открыть данные…",
            self.open_dataset,
            QKeySequence.StandardKey.Open,
            tip="Открыть .sav, Excel, CSV или набор Winnow",
        )
        self._add_action(file_menu, "&Демонстрационные данные", self.load_demo_dataset)
        self._add_action(file_menu, "&Новый пустой набор", self.new_empty_dataset)
        file_menu.addSeparator()
        self._add_action(
            file_menu,
            "&Сохранить как…",
            self.save_dataset_as,
            QKeySequence.StandardKey.SaveAs,
        )
        self._add_action(file_menu, "&Экспорт вывода в Word…", lambda: self.export_output("docx"))
        self._add_action(file_menu, "Экспорт вывода в Excel…", lambda: self.export_output("xlsx"))
        self._add_action(file_menu, "Экспорт вывода в &HTML…", lambda: self.export_output("html"))
        file_menu.addSeparator()
        self._add_action(file_menu, "&Выход", self.close, QKeySequence.StandardKey.Quit)

        # ----------------------------------------------------- Редактирование
        # Ссылки на меню хранятся: в простом режиме часть из них скрывается.
        self.edit_menu = bar.addMenu("&Редактирование")
        edit_menu = self.edit_menu
        self._add_action(
            edit_menu, "&Копировать", self.copy_selection, QKeySequence.StandardKey.Copy
        )
        self._add_action(
            edit_menu, "&Вставить", self.paste_into_data, QKeySequence.StandardKey.Paste
        )
        self._add_action(
            edit_menu, "&Удалить содержимое", self.clear_selection, QKeySequence.StandardKey.Delete
        )
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Свойства переменной…", self.edit_current_variable)

        # -------------------------------------------------------------- Вид
        view_menu = bar.addMenu("&Вид")
        theme_menu = view_menu.addMenu("Тема оформления")
        self._theme_actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for key, palette in THEMES.items():
            action = QAction(palette.name, self)
            action.setCheckable(True)
            action.setChecked(key == self.theme_name)
            action.triggered.connect(lambda _checked=False, name=key: self.apply_theme(name))
            group.addAction(action)
            theme_menu.addAction(action)
            self._theme_actions[key] = action

        view_menu.addSeparator()
        self._add_action(
            view_menu, "Показать редактор данных", lambda: self.editor_dock.setVisible(True)
        )
        self._add_action(view_menu, "Показать вывод", lambda: self.output_dock.setVisible(True))
        view_menu.addSeparator()
        self._add_action(view_menu, "Увеличить вывод", lambda: self._zoom_output(1))
        self._add_action(view_menu, "Уменьшить вывод", lambda: self._zoom_output(-1))
        self._add_action(
            view_menu, "Обычный размер", lambda: self.output_browser.setZoomFactor(1.0)
        )
        view_menu.addSeparator()
        self._add_action(
            view_menu,
            "Очистить вывод",
            self.clear_output,
            tip="Убрать из вывода все результаты, чтобы начать заново",
        )
        self._add_action(
            view_menu,
            "Переключить режим интерфейса",
            lambda: self.set_interface_mode(self.interface_mode != "simple"),
            tip="Простой режим оставляет только самое нужное, экспертный "
            "показывает все возможности",
        )

        # ------------------------------------------------------------ Данные
        data_menu = bar.addMenu("&Данные")
        self._add_action(
            data_menu,
            "Свойства переменной…",
            self.edit_current_variable,
            tip="Метка, метки значений, пропущенные значения, уровень измерения",
        )
        self._add_action(data_menu, "&Добавить переменную", self.add_variable)
        self._add_action(data_menu, "&Удалить переменную", self.delete_variable)
        self._add_action(
            data_menu,
            "Разбить вопросы с несколькими ответами…",
            self.split_multi_answer,
            tip="Превратить «выберите всё подходящее» в отдельные переменные "
            "1/0, пригодные для частот и таблиц сопряжённости",
        )
        data_menu.addSeparator()
        self._add_action(
            data_menu,
            "Разбить файл…",
            self.split_file,
            tip="Считать все процедуры отдельно по категориям переменной",
        )
        self._add_action(data_menu, "Отменить разбиение файла", self.clear_split)

        # ---------------------------------------------------- Преобразование
        transform_menu = bar.addMenu("&Преобразование")
        self.transform_menu = transform_menu
        self._add_action(
            transform_menu,
            "Вычислить переменную…",
            lambda: self.run_procedure("compute"),
            tip="Новая переменная по выражению: индекс, пересчёт шкалы, группы",
        )
        self._add_action(
            transform_menu,
            "Перекодировать в новую переменную…",
            self.recode_variable,
            tip="Объединить категории, собрать диапазоны, заменить коды",
        )
        transform_menu.addSeparator()
        self._add_action(transform_menu, "Отбор кейсов…", planned_key="select")
        self._add_action(transform_menu, "Веса кейсов…", planned_key="weight")

        # ------------------------------------------------------------- Анализ
        analysis_menu = bar.addMenu("&Анализ")
        for group_name in (
            "Описательные статистики",
            "Таблицы",
            "Сравнение средних",
            "Связи",
            "Преобразование данных",
            "Масштабирование",
        ):
            submenu = analysis_menu.addMenu(group_name)
            for info in REGISTRY:
                if info.group != group_name:
                    continue
                self._add_action(
                    submenu,
                    info.title,
                    lambda _checked=False, key=info.key: self.run_procedure(key),
                    tip=info.description,
                )

        # Здесь раньше стояли отключённые дубли уже готовых процедур (ANOVA,
        # непараметрические критерии, регрессии, надёжность, факторный анализ), а
        # «Масштабирование» создавалось второй раз. Пользователь видел два
        # одинаковых подменю, из которых одно мертво, и не понимал, какое
        # работает. Пункты из реестра строятся выше и всегда доступны - этого
        # достаточно.

        # ----------------------------------------------------------- Графики
        graphs_menu = bar.addMenu("&Графики")
        chart_items = [
            ("Гистограмма…", "histogram", "Распределение одной числовой переменной"),
            ("Ящик с усами…", "boxplot", "Медиана, квартили и выбросы"),
            ("Диаграмма рассеяния…", "scatter", "Связь двух числовых переменных"),
            ("Столбиковая диаграмма…", "bar", "Частоты категорий"),
            ("Круговая диаграмма…", "pie", "Доли категорий"),
            ("Линия средних…", "line", "Среднее по категориям со стандартной ошибкой"),
        ]
        for title, kind, tip in chart_items:
            self._add_action(
                graphs_menu,
                title,
                lambda _checked=False, key=kind: self.show_chart(key),
                tip=tip,
            )

        # ------------------------------------------------------------ Утилиты
        utilities_menu = bar.addMenu("&Утилиты")
        self.utilities_menu = utilities_menu
        self._add_action(
            utilities_menu, "Сведения о переменных", lambda: self.data_tabs.setCurrentIndex(1)
        )
        self._add_action(
            utilities_menu, "Показать синтаксис", lambda: self.viewer_tabs.setCurrentIndex(1)
        )
        utilities_menu.addSeparator()
        self._add_action(utilities_menu, "Сохранить синтаксис в файл…", self.save_syntax)
        self._add_action(
            utilities_menu,
            "Открыть и выполнить синтаксис…",
            self.open_syntax,
            tip="Прочитать файл .sps и выполнить его команды на текущем наборе",
        )

        # ------------------------------------------------------------ Справка
        help_menu = bar.addMenu("&Справка")
        self._add_action(help_menu, "О программе", self.show_about)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Основные действия")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(18, 18))
        self.toolbar = toolbar
        self.addToolBar(toolbar)
        self._fill_toolbar(toolbar)
        self._refresh_toolbar_icons()

    def _fill_toolbar(self, toolbar: QToolBar) -> None:
        toolbar.clear()
        simple = self.interface_mode == "simple"
        if simple:
            # В простом режиме кнопок мало: выбор процедуры берёт на себя панель
            # подсказок, а быстрые ссылки на четырнадцать процедур только
            # отвлекают и заставляют гадать, чем они отличаются.
            self._toolbar_specs: list[tuple[str, str, Callable[[], None]]] = [
                ("open", "Открыть", self.open_dataset),
                ("sheet", "Демо-данные", self.load_demo_dataset),
                ("", "", lambda: None),  # разделитель
                ("export", "Экспорт в Word", lambda: self.export_output("docx")),
            ]
        else:
            self._toolbar_specs = [
                ("open", "Открыть", self.open_dataset),
                ("sheet", "Демо-данные", self.load_demo_dataset),
                ("", "", lambda: None),  # разделитель
                ("bars", "Частоты", lambda: self.run_procedure("frequencies")),
                ("curve", "Описательные", lambda: self.run_procedure("descriptives")),
                ("grid", "Сопряжённость", lambda: self.run_procedure("crosstabs")),
                ("table", "t-критерий", lambda: self.run_procedure("ttest")),
                ("scatter", "Корреляции", lambda: self.run_procedure("correlations")),
                ("", "", lambda: None),  # разделитель
                ("export", "Экспорт в Word", lambda: self.export_output("docx")),
                ("clear", "Очистить вывод", self.clear_output),
            ]
        for icon_kind, title, callback in self._toolbar_specs:
            if not icon_kind:
                toolbar.addSeparator()
                continue
            action = QAction(title, self)
            action.triggered.connect(lambda _checked=False, fn=callback: fn())
            toolbar.addAction(action)

        # Кнопка переключения режима: не пункт панели, а заметная кнопка с
        # подсветкой. Обычный пункт панели инструментов теряется среди соседних и
        # не читается как переключатель, а человек должен замечать его сразу.
        toolbar.addSeparator()
        self.mode_button = QPushButton(
            "Простой режим" if simple else "Экспертный режим"
        )
        self.mode_button.setObjectName("ModeSwitch")
        self.mode_button.setCheckable(True)
        # Состояние выставляется ДО подключения сигнала: иначе переключение
        # вызвало бы само себя при построении панели.
        self.mode_button.setChecked(simple)
        self.mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_button.setToolTip(
            "Сейчас простой режим: на экране только самое нужное. "
            "Нажмите, чтобы показать все возможности программы."
            if simple
            else "Сейчас экспертный режим: доступны все процедуры и синтаксис. "
            "Нажмите, чтобы оставить только самое нужное."
        )
        self.mode_button.toggled.connect(self.set_interface_mode)
        toolbar.addWidget(self.mode_button)

    def _refresh_toolbar_icons(self) -> None:
        """Перекрашивает иконки под текущую тему."""
        from winnow.ui.icons import toolbar_icons

        icons = toolbar_icons(design_system(self.theme_name).palette.text_muted)
        actions = [a for a in self.toolbar.actions() if not a.isSeparator()]
        specs = [spec for spec in self._toolbar_specs if spec[0]]
        for action, (icon_kind, _title, _callback) in zip(actions, specs):
            action.setIcon(icons[icon_kind])

    # ---------------------------------------------------------------- режим

    @staticmethod
    def _settings() -> QSettings:
        return QSettings("Winnow", "Winnow")

    def _load_interface_mode(self) -> str:
        """Программа всегда открывается в простом режиме.

        Раньше выбранный режим запоминался между запусками, и это оказалось
        ловушкой: одно случайное нажатие переключателя оставляло новичка в
        экспертном интерфейсе навсегда, потому что вернуться он не умел. Новичок,
        попавший в экспертный интерфейс, просто закроет программу - ради этого
        простой режим и делался.

        Значение, оставшееся от прежних версий, удаляется: иначе оно снова
        переключило бы режим. Внутри одного запуска режим переключается свободно -
        теряется только выбор между запусками.
        """
        settings = self._settings()
        if settings.value("interface/mode") is not None:
            settings.remove("interface/mode")
            settings.sync()
        return "simple"

    def set_interface_mode(self, simple: bool) -> None:
        """Переключает режим интерфейса."""
        mode = "simple" if simple else "expert"
        if mode == self.interface_mode:
            return
        self.interface_mode = mode
        self._apply_interface_mode()
        self.statusBar().showMessage(
            "Простой режим: на экране только самое нужное"
            if simple
            else "Экспертный режим: доступны все процедуры, синтаксис и паспорта переменных",
            5000,
        )

    def _apply_interface_mode(self) -> None:
        """Показывает то, что нужно выбранному режиму, и прячет остальное."""
        simple = self.interface_mode == "simple"

        # Панель подсказок - лицо простого режима. Опытному пользователю она
        # место занимает, поэтому в экспертном режиме скрыта.
        self.advisor_panel.setVisible(simple)

        # Синтаксис и таблица паспортов переменных - инструменты опытного
        # пользователя: в простом режиме это только отвлекает.
        self.viewer_tabs.setTabVisible(1, not simple)
        self.data_tabs.setTabVisible(1, not simple)
        # Дерево результатов служит для перехода между десятком таблиц. Пока
        # расчётов мало, оно стоит пустой полосой и отнимает место у самого
        # результата.
        self.output_tree.setVisible(not simple)
        if simple:
            self.viewer_tabs.setCurrentIndex(0)
            self.data_tabs.setCurrentIndex(0)

        for menu in (
            getattr(self, "edit_menu", None),
            getattr(self, "utilities_menu", None),
            getattr(self, "transform_menu", None),
        ):
            if menu is not None:
                menu.menuAction().setVisible(not simple)

        # Панель инструментов собирается заново: набор кнопок в режимах разный.
        self._fill_toolbar(self.toolbar)
        self._refresh_toolbar_icons()
        # Вывод перерисовывается: в простом режиме из него убирается синтаксис.
        self._refresh_output()

        # Панели и центральная область зависят не только от режима, но и от того,
        # есть ли данные. Без этого при переходе в экспертный режим таблица данных
        # оставалась скрытой, а в центре висела пустая область - выглядело так,
        # будто данные пропали и их нужно загружать заново. Загружать ничего не
        # требовалось: набор всё это время лежал в памяти, просто его не показывали.
        if self.dataset is not None:
            if simple:
                self.central.setVisible(True)
            else:
                self._clear_central()
                self.central.setVisible(False)
            self._resize_panels()

        # Режим виден постоянно, а не только по подписи кнопки: человек должен
        # понимать, в каком интерфейсе находится, не наводя курсор.
        self.mode_badge.setText("Простой режим" if simple else "Экспертный режим")
        self.mode_badge.setToolTip(
            "Простой режим: на экране только самое нужное. "
            "Переключить — кнопка в правом конце панели инструментов."
            if simple
            else "Экспертный режим: доступны все процедуры, синтаксис и паспорта "
            "переменных. Переключить — кнопка в правом конце панели инструментов."
        )
        self._update_title()

    def _update_title(self) -> None:
        """В заголовке окна видно и набор данных, и текущий режим."""
        mode = "Простой режим" if self.interface_mode == "simple" else "Экспертный режим"
        if self.dataset is not None:
            self.setWindowTitle(f"Winnow — {mode} — {self.dataset.name}")
        else:
            self.setWindowTitle(f"Winnow — {mode}")

    # --------------------------------------------------------------- данные

    def run_scenario(self, procedure: str, params: dict[str, Any]) -> None:
        """Выполняет готовый сценарий советчика.

        Отличие от `run_procedure` в том, что диалога нет: переменные уже
        подставлены, и человеку остаётся только посмотреть результат. Именно
        ради этого панель подсказок и существует.
        """
        if self.dataset is None:
            QMessageBox.information(
                self,
                "Нет данных",
                "Сначала откройте данные или загрузите демонстрационный набор.",
            )
            return

        info = REGISTRY_BY_KEY.get(procedure)
        if info is None:
            QMessageBox.information(
                self, "Недоступно", f"Процедура «{procedure}» не найдена."
            )
            return

        try:
            command = info.command_type(dataset=self.dataset, **params)
            command.validate()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Проверьте параметры", str(exc))
            return

        self._append_syntax(command.syntax())
        self.statusBar().showMessage(f"Выполняется: {info.title}…")
        self.viewer_tabs.setCurrentIndex(0)

        task = ProcedureTask(command)
        task.signals.done.connect(self._on_procedure_done)
        task.signals.failed.connect(self._on_procedure_failed)
        self._pool.start(task)

    # --------------------------------------------------------------- данные

    def set_dataset(self, dataset: Dataset, path: Path | None = None) -> None:
        self.dataset = dataset
        self.current_path = path
        self.data_model.set_dataset(dataset)
        self.variable_model.set_dataset(dataset)
        self.data_view.resizeColumnsToContents()
        self.variable_view.resizeColumnsToContents()
        self.formula_bar.clear_value()
        self._refresh_status()
        self._update_title()
        self.data_tabs.setCurrentIndex(0)

        # Панель подсказок обновляется вместе с данными: она показывает, что в
        # наборе есть и какие исследования в нём возможны.
        self.advisor_panel.set_dataset(dataset)

        if self.interface_mode == "simple":
            # В простом режиме центральная область остаётся: в ней живут
            # подсказки, а они нужны именно тогда, когда данные уже загружены.
            self.central.setVisible(True)
        else:
            # В экспертном режиме место отдаётся таблицам данных и вывода, как в
            # SPSS: подсказки опытному пользователю только мешают.
            self._clear_central()
            self.central.setVisible(False)
        self._resize_panels()

    def _resize_panels(self) -> None:
        """Задаёт разумные пропорции панелей: данные слева, вывод справа."""
        self.output_dock.setVisible(True)
        width = max(self.width(), 1200)

        if self.interface_mode == "simple":
            # В простом режиме таблица данных по умолчанию не показывается:
            # новичку полезнее подсказки и результат, чем сырые строки, а места
            # в окне на всё сразу не хватает - панель подсказок сжималась так,
            # что текст обрезался на полуслове. Вернуть таблицу можно через
            # «Вид → Показать редактор данных».
            # Проверяется явное скрытие, а не isVisible(): у невидимого окна
            # isVisible() ложно у всех детей, и тогда разбивка панелей зависит от
            # того, успели ли показать окно до загрузки данных.
            if not self.central.isHidden():
                self.editor_dock.setVisible(False)
                self.resizeDocks(
                    [self.output_dock],
                    [int(width * 0.46)],
                    Qt.Orientation.Horizontal,
                )
                return
            self.editor_dock.setVisible(True)
            self.resizeDocks(
                [self.editor_dock, self.output_dock],
                [int(width * 0.42), int(width * 0.58)],
                Qt.Orientation.Horizontal,
            )
            return

        self.editor_dock.setVisible(True)
        self.resizeDocks(
            [self.editor_dock, self.output_dock],
            [int(width * 0.42), int(width * 0.58)],
            Qt.Orientation.Horizontal,
        )

    def new_empty_dataset(self) -> None:
        """Создаёт пустой набор, чтобы переменные можно было задать вручную."""
        import pandas as pd

        dataset = Dataset.from_dataframe(pd.DataFrame(), name="Набор1")
        self.set_dataset(dataset)
        QMessageBox.information(
            self,
            "Пустой набор",
            "Набор создан. Добавьте переменные: меню «Данные» → «Добавить переменную».",
        )

    def open_dataset(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "Открыть данные", self._last_dir, file_dialog_filters()
        )
        if not path:
            return
        try:
            dataset = read_dataset(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Не удалось открыть файл", str(exc))
            return
        self._remember_dir(path)
        self.set_dataset(dataset, Path(path))

    def _remember_dir(self, path: str) -> None:
        """Запоминает папку выбранного файла для следующего диалога."""
        parent = Path(path).parent
        if parent.is_dir():
            self._last_dir = str(parent)

    def save_dataset_as(self) -> None:
        if self.dataset is None:
            QMessageBox.information(self, "Нет данных", "Сначала откройте или создайте набор.")
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Сохранить данные",
            str(Path(self._last_dir) / f"{self.dataset.name}.wndata")
            if self._last_dir
            else f"{self.dataset.name}.wndata",
            save_dialog_filters(),
        )
        if not path:
            return
        fmt = format_for_path(path)
        try:
            write_dataset(self.dataset, path, fmt)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Не удалось сохранить", str(exc))
            return
        self._remember_dir(path)
        self.current_path = Path(path)
        self.statusBar().showMessage(f"Сохранено: {path}", 4000)

    def load_demo_dataset(self) -> None:
        from winnow.samples import demo_dataset

        self.set_dataset(demo_dataset())

    # ------------------------------------------------ редактирование данных

    def _on_cell_changed(self, current: Any, _previous: Any) -> None:
        if not current.isValid() or self.dataset is None:
            self.formula_bar.clear_value()
            return
        name = self.dataset.names()[current.column()]
        self.formula_bar.set_reference(f"{name} · кейс {current.row() + 1}")
        value = self.dataset.frame.iat[current.row(), current.column()]
        self.formula_bar.set_value("" if value is None else str(value))

    def _apply_formula_value(self) -> None:
        """Применяет значение из строки формул к текущей ячейке."""
        index = self.data_view.currentIndex()
        if not index.isValid():
            return
        self._set_cell(index.row(), index.column(), self.formula_bar.editor.text())

    def _set_cell(self, row: int, column: int, text: str) -> None:
        if self.dataset is None:
            return
        name = self.dataset.names()[column]
        variable = self.dataset.var(name)
        try:
            if variable.is_numeric:
                stripped = text.strip()
                if stripped == "" or stripped.lower() in ("нет ответа", "na", "nan", "."):
                    value: Any = float("nan")
                else:
                    value = float(stripped.replace(",", "."))
            else:
                value = text
        except ValueError:
            QMessageBox.warning(
                self,
                "Неверное значение",
                f"Для переменной «{name}» ожидается число, получено: {text!r}",
            )
            return
        self.dataset.frame.iat[row, column] = value
        top_left = self.data_model.index(row, column)
        self.data_model.dataChanged.emit(top_left, top_left)
        self.statusBar().showMessage(f"Изменено: {name}, кейс {row + 1}", 3000)

    def copy_selection(self) -> None:
        """Копирует выделенные ячейки в буфер как таблицу с разделителями табуляции."""
        variable_tab = self.data_tabs.currentIndex() == 1
        view = self.variable_view if variable_tab else self.data_view
        selection = view.selectionModel().selectedIndexes()
        if not selection:
            return
        model = view.model()
        rows = sorted({index.row() for index in selection})
        columns = sorted({index.column() for index in selection})
        lines = []
        for row in rows:
            cells = []
            for column in columns:
                value = model.data(model.index(row, column), Qt.ItemDataRole.DisplayRole)
                cells.append("" if value is None else str(value))
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage(f"Скопировано строк: {len(rows)}", 3000)

    def paste_into_data(self) -> None:
        """Вставляет таблицу из буфера, начиная с текущей ячейки."""
        if self.dataset is None:
            return
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        index = self.data_view.currentIndex()
        start_row = index.row() if index.isValid() else 0
        start_col = index.column() if index.isValid() else 0

        lines = [line for line in text.replace("\r\n", "\n").split("\n") if line != ""]
        pasted = 0
        for row_offset, line in enumerate(lines):
            if start_row + row_offset >= self.dataset.n_cases:
                break
            for col_offset, cell in enumerate(line.split("\t")):
                column = start_col + col_offset
                if column >= self.dataset.n_vars:
                    break
                self._set_cell(start_row + row_offset, column, cell.strip())
                pasted += 1
        self.statusBar().showMessage(f"Вставлено ячеек: {pasted}", 4000)

    def clear_selection(self) -> None:
        view = self.variable_view if self.data_tabs.currentIndex() == 1 else self.data_view
        for index in view.selectionModel().selectedIndexes():
            self._set_cell(index.row(), index.column(), "")

    def edit_current_variable(self) -> None:
        """Открывает свойства переменной под курсором."""
        if self.dataset is None or self.dataset.n_vars == 0:
            return
        if self.data_tabs.currentIndex() == 1:
            row = self.variable_view.currentIndex().row()
        else:
            row = self.data_view.currentIndex().column()
        if row < 0:
            return
        self._open_variable_dialog(self.dataset.names()[row])

    def _edit_variable_at(self, index: Any) -> None:
        if self.dataset is None or not index.isValid():
            return
        self._open_variable_dialog(self.dataset.names()[index.row()])

    def _open_variable_dialog(self, name: str) -> None:
        if self.dataset is None:
            return
        dialog = VariableDialog(self.dataset.var(name), theme=self.theme_name, parent=self)
        if _accepted(dialog):
            dialog.apply()
            self.variable_model.refresh()
            self.data_model.layoutChanged.emit()
            self.statusBar().showMessage(f"Свойства переменной «{name}» обновлены", 4000)

    def recode_variable(self) -> None:
        """Открывает диалог перекодирования (у него своя таблица правил)."""
        if self.dataset is None:
            QMessageBox.information(self, "Нет данных", "Сначала откройте или создайте набор.")
            return
        from winnow.ui.recode_dialog import RecodeDialog

        dialog = RecodeDialog(self.dataset, theme=self.theme_name, parent=self)
        if not _accepted(dialog):
            return
        try:
            command = dialog.build_command()
            command.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Проверьте правила", str(exc))
            return

        self._append_syntax(command.syntax())
        try:
            result = command.execute()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка перекодирования", str(exc))
            return
        self._after_data_change(result)

    def _after_data_change(self, result: Any) -> None:
        """Обновляет редактор данных после появления новой переменной."""
        self.data_model.set_dataset(self.dataset)
        self.variable_model.set_dataset(self.dataset)
        self.data_view.resizeColumnsToContents()
        self.variable_view.resizeColumnsToContents()
        self._append_result(result)
        self._refresh_status()
        self.data_tabs.setCurrentIndex(0)
        self.statusBar().showMessage(result.title, 5000)

    def split_file(self) -> None:
        """Включает разбиение файла по переменной."""
        if self.dataset is None:
            QMessageBox.information(self, "Нет данных", "Сначала откройте или создайте набор.")
            return
        from winnow.ui.split_dialog import SplitFileDialog

        dialog = SplitFileDialog(self.dataset, theme=self.theme_name, parent=self)
        if not _accepted(dialog):
            return
        try:
            dialog.apply()
        except ValueError as exc:
            QMessageBox.warning(self, "Проверьте разбиение", str(exc))
            return
        self._refresh_status()
        if self.dataset.has_split:
            self.statusBar().showMessage(
                f"Разбиение включено: {self.dataset.split_var} "
                f"({len(self.dataset.split_values)} групп)",
                6000,
            )
        else:
            self.statusBar().showMessage("Разбиение файла выключено", 4000)

    def clear_split(self) -> None:
        if self.dataset is None:
            return
        self.dataset.clear_split()
        self._refresh_status()
        self.statusBar().showMessage("Разбиение файла выключено", 4000)

    def _refresh_status(self) -> None:
        """Обновляет строку состояния: там же видно активное разбиение."""
        if self.dataset is None:
            self.status_label.setText("Данные не загружены")
            return
        self.status_label.setText(f"{self.dataset.name}  ·  {self.dataset.summary()}")

    def add_variable(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        if self.dataset is None:
            QMessageBox.information(self, "Нет данных", "Сначала откройте или создайте набор.")
            return
        name, ok = QInputDialog.getText(
            self, "Новая переменная", "Имя переменной (латиницей):"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.dataset.variables:
            QMessageBox.warning(self, "Имя занято", f"Переменная «{name}» уже существует.")
            return
        self.dataset.add_variable(name, [0.0] * max(self.dataset.n_cases, 1))
        self.variable_model.set_dataset(self.dataset)
        self.data_model.set_dataset(self.dataset)
        self.statusBar().showMessage(f"Добавлена переменная «{name}»", 4000)

    def delete_variable(self) -> None:
        if self.dataset is None or self.dataset.n_vars == 0:
            return
        variable_tab = self.data_tabs.currentIndex() == 1
        view = self.variable_view if variable_tab else self.data_view
        index = view.currentIndex()
        if not index.isValid():
            return
        position = index.row() if variable_tab else index.column()
        name = self.dataset.names()[position]
        answer = QMessageBox.question(
            self, "Удалить переменную", f"Удалить переменную «{name}» со всеми данными?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.dataset.drop_variable(name)
        self.variable_model.set_dataset(self.dataset)
        self.data_model.set_dataset(self.dataset)
        self.statusBar().showMessage(f"Удалена переменная «{name}»", 4000)

    # ---------------------------------------------------------------- вывод

    def _append_syntax(self, text: str) -> None:
        self.syntax_log.append(text)
        self.syntax_edit.setPlainText("\n\n".join(self.syntax_log))

    def split_multi_answer(self, confirm: bool = True) -> None:
        """Разбивает вопросы с несколькими ответами на переменные-отметки.

        Анкетные сервисы пишут «выберите всё подходящее» в одну ячейку, склеивая
        варианты. Анализировать такую переменную нельзя: у неё десятки уникальных
        значений. Здесь она превращается в набор отметок 1/0 - по одной на каждый
        вариант, как это делают в SPSS.
        """
        from winnow.stats.multianswer import detect_multi_answer, split_all

        if self.dataset is None:
            QMessageBox.information(
                self, "Нет данных", "Сначала откройте данные или загрузите демонстрационный набор."
            )
            return
        found = detect_multi_answer(self.dataset)
        if not found:
            QMessageBox.information(
                self,
                "Множественных ответов нет",
                "Вопросов с несколькими ответами не найдено: в ячейках нет "
                "нескольких вариантов через «;» или запятой с номером.",
            )
            return

        listed = "\n".join(f"• {item.summary()}" for item in found[:10])
        if len(found) > 10:
            listed += f"\n… и ещё {len(found) - 10}"
        if confirm:
            answer = QMessageBox.question(
                self,
                "Разбить вопросы с несколькими ответами",
                f"Найдено вопросов: {len(found)}\n\n{listed}\n\n"
                "Добавить отдельные переменные-отметки (1 — выбрано, 0 — нет)?\n"
                "Исходные переменные останутся на месте.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        created, _handled = split_all(self.dataset)
        # Набор изменился, поэтому обновляются и таблица данных, и паспорта
        # переменных, и подсказки: в них появились новые переменные.
        self.data_model.set_dataset(self.dataset)
        self.variable_model.set_dataset(self.dataset)
        self.data_view.resizeColumnsToContents()
        self.variable_view.resizeColumnsToContents()
        self._refresh_status()
        self.advisor_panel.set_dataset(self.dataset)
        self.statusBar().showMessage(
            f"Добавлено переменных-отметок: {len(created)}", 8000
        )

    def clear_output(self) -> None:
        """Очищает вывод.

        Подтверждение спрашивается только когда есть что терять: результаты
        восстановить нельзя, а кнопка стоит рядом с экспортом, и промахнуться по
        ней легко.
        """
        if not self.results:
            self.statusBar().showMessage("Вывод уже пуст", 4000)
            return
        answer = QMessageBox.question(
            self,
            "Очистить вывод",
            f"Удалить все результаты ({len(self.results)})? "
            "Отменить это действие нельзя.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.results.clear()
        self.syntax_log.clear()
        self.syntax_edit.clear()
        self.output_tree.clear_all()
        self._refresh_output()
        self.statusBar().showMessage("Вывод очищен", 4000)

    def _refresh_output(self) -> None:
        if not hasattr(self, "output_browser"):
            return
        # Кнопка очистки активна только когда есть что чистить: неактивная
        # кнопка честнее вопроса «вывод уже пуст».
        if hasattr(self, "clear_output_button"):
            self.clear_output_button.setEnabled(bool(self.results))
        # В окне вывода заголовок отчёта не нужен: его роль выполняет заголовок
        # панели. Заголовок уместен только в файле отчёта.
        # Синтаксис SPSS скрывается в простом режиме: это инструмент опытного
        # пользователя, а начинающего команды только сбивают с толку.
        self.output_browser.setHtml(
            report_to_html(
                self.results,
                theme=self.theme_name,
                show_title=False,
                include_syntax=self.interface_mode != "simple",
            )
        )

    def _append_result(self, result: Any) -> None:
        self.results.append(result)
        self.output_tree.add_result(result)
        self._refresh_output()

    def _on_output_node(self, result_index: int, _table_index: int) -> None:
        """Прокручивает вывод к выбранной процедуре."""
        if 0 <= result_index < len(self.results):
            self.output_browser.scrollToAnchor(f"result-{result_index + 1}")

    def _zoom_output(self, delta: int) -> None:
        factor = max(0.6, min(2.0, self.output_browser.zoomFactor() + 0.1 * delta))
        self.output_browser.setZoomFactor(factor)

    def show_chart(self, kind: str) -> None:
        """Открывает окно построения графика и затем окно с самим графиком.

        График показывается отдельным окном, а в дерево вывода добавляется
        таблица с теми числами, по которым он построен: по рисунку значения не
        проверить, а по таблице можно.
        """
        if self.dataset is None:
            QMessageBox.information(
                self,
                "Нет данных",
                "Сначала откройте данные или загрузите демонстрационный набор.",
            )
            return

        from winnow.stats.charts import ChartCommand, CHART_TITLES, build_chart_data
        from winnow.ui.chart_window import ChartWindow
        from winnow.ui.procedure_specs import DIALOG_SPECS

        spec = DIALOG_SPECS.get("graph")
        if spec is None:
            QMessageBox.information(self, "Недоступно", "Описание окна графиков не найдено.")
            return

        dialog = ProcedureDialog(spec, self.dataset, self, theme=self.theme_name)
        # Вид графика задаётся пунктом меню, пользователю остаётся выбрать данные.
        for field in spec.fields:
            if field.name == "kind":
                dialog.set_value("kind", kind)
        # Окно само не закроется при неверных параметрах: сообщение появится в
        # нём, а выбранные переменные останутся на месте.
        command = dialog.build_command()
        if command is None:
            return

        self._append_syntax(command.syntax())
        try:
            result = command.execute()
        except Exception as exc:  # noqa: BLE001 - показываем понятный текст
            QMessageBox.critical(self, "Не удалось построить график", str(exc))
            return
        self._append_result(result)

        if not any(table.rows for table in result.tables):
            QMessageBox.information(
                self,
                CHART_TITLES.get(kind, "График"),
                "Для графика не осталось данных: проверьте пропуски и отбор кейсов.",
            )
            return

        data = build_chart_data(command)
        window = ChartWindow(data, theme=self.theme_name, parent=self)
        # Ссылку нужно сохранить: иначе окно закроется сразу после показа.
        self._chart_windows.append(window)
        window.finished.connect(lambda _code, w=window: self._forget_chart(w))
        window.show()
        self.statusBar().showMessage(f"График построен: {data.title}", 5000)

    def _forget_chart(self, window: Any) -> None:
        """Убирает ссылку на закрытое окно графика."""
        if window in self._chart_windows:
            self._chart_windows.remove(window)

    def run_procedure(self, key: str) -> None:
        if self.dataset is None:
            QMessageBox.information(
                self,
                "Нет данных",
                "Сначала откройте данные или загрузите демонстрационный набор.",
            )
            return

        from winnow.ui.procedure_specs import DIALOG_SPECS

        spec = DIALOG_SPECS.get(key)
        if spec is None:
            QMessageBox.information(self, "Недоступно", f"Окно для «{key}» ещё не описано.")
            return

        dialog = ProcedureDialog(spec, self.dataset, self, theme=self.theme_name)
        # Окно само не закроется при неверных параметрах: сообщение появится в
        # нём, а заполненная форма останется на месте.
        command = dialog.build_command()
        if command is None:
            return

        self._append_syntax(command.syntax())
        self.statusBar().showMessage(f"Выполняется: {spec.title}…")
        self.viewer_tabs.setCurrentIndex(0)

        task = ProcedureTask(command)
        task.signals.done.connect(self._on_procedure_done)
        task.signals.failed.connect(self._on_procedure_failed)
        self._pool.start(task)

    @Slot(object)
    def _on_procedure_done(self, result: Any) -> None:
        # Процедуры преобразования меняют сам набор данных, поэтому редактор
        # нужно обновить - иначе пользователь не увидит новую переменную.
        if getattr(result, "procedure", "") in ("COMPUTE", "RECODE"):
            self._after_data_change(result)
            return
        self._append_result(result)
        self.statusBar().showMessage(
            f"Готово: {result.title} · таблиц: {len(result.tables)}", 5000
        )

    @Slot(object)
    def _on_procedure_failed(self, error: Exception) -> None:
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "Ошибка расчёта", str(error))

    def save_syntax(self) -> None:
        if not self.syntax_log:
            QMessageBox.information(self, "Нет синтаксиса", "Сначала выполните процедуру.")
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Сохранить синтаксис",
            "winnow.sps",
            "Синтаксис Winnow (*.sps);;Текст (*.txt)",
        )
        if not path:
            return
        # Собранный текст приводится к виду, который программа сможет прочитать
        # обратно: каждая команда оканчивается точкой. Иначе файл выглядел бы как
        # синтаксис, но не читался.
        from winnow.syntax.sps import build_syntax

        blocks = []
        for text in self.syntax_log:
            block = text.strip()
            if not block:
                continue
            if not block.endswith("."):
                block += "."
            blocks.append(block)
        title = self.dataset.name if self.dataset is not None else ""
        # Комментарий с названием набора помогает понять, для каких данных писался
        # файл: синтаксис без этого через месяц становится загадкой.
        header = f"* {title}.\n\n" if title else ""
        Path(path).write_text(header + "\n\n".join(blocks) + "\n", encoding="utf-8")
        self.statusBar().showMessage(f"Синтаксис сохранён: {path}", 4000)

    def open_syntax(self) -> None:
        """Открывает файл `.sps` и выполняет его команды.

        Открытый синтаксис сначала показывается в своей вкладке: пользователь
        должен видеть, что именно будет выполнено, прежде чем это выполнится.
        Файл мог быть написан для другого набора данных, и молчаливое выполнение
        дало бы ошибки в самом неожиданном месте.
        """
        if self.dataset is None:
            QMessageBox.information(
                self, "Нет данных", "Сначала откройте данные или загрузите набор."
            )
            return
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Открыть синтаксис",
            "",
            "Синтаксис Winnow (*.sps);;Текст (*.txt);;Все файлы (*)",
        )
        if not path:
            return

        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, "Не удалось прочитать", str(exc))
            return

        from winnow.syntax.sps import SyntaxError_, parse_syntax

        try:
            commands = parse_syntax(text, self.dataset)
        except SyntaxError_ as exc:
            QMessageBox.warning(self, "Ошибка в синтаксисе", str(exc))
            return

        if not commands:
            QMessageBox.information(
                self, "Пустой синтаксис", "В файле нет ни одной команды."
            )
            return

        names = ", ".join(command.TITLE for command in commands)
        answer = QMessageBox.question(
            self,
            "Выполнить синтаксис?",
            f"В файле команд: {len(commands)}\n{names}\n\nВыполнить их на текущем наборе?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.syntax_log.append(text)
        # Показываем файл целиком, без пересборки: пользователь должен видеть то,
        # что лежит на диске, а не то, что программа из него поняла.
        self.syntax_edit.setPlainText("\n\n".join(
            block.strip() for block in self.syntax_log
        ))
        self.viewer_tabs.setCurrentIndex(1)

        for command in commands:
            try:
                result = command.execute()
            except Exception as exc:  # noqa: BLE001 - показываем понятный текст
                QMessageBox.critical(self, "Ошибка выполнения", str(exc))
                return
            self._append_result(result)
        self.statusBar().showMessage(
            f"Синтаксис выполнен: {len(commands)} команд из {Path(path).name}", 6000
        )

    def export_output(self, fmt: str) -> None:
        if not self.results:
            QMessageBox.information(
                self, "Нет вывода", "Сначала выполните хотя бы одну процедуру."
            )
            return
        filters = {
            "docx": "Документ Word (*.docx)",
            "xlsx": "Книга Excel (*.xlsx)",
            "html": "Веб-страница (*.html)",
        }
        path, _selected = QFileDialog.getSaveFileName(
            self, "Экспорт вывода", f"Отчёт Winnow.{fmt}", filters[fmt]
        )
        if not path:
            return
        try:
            if fmt == "docx":
                from winnow.export import result_to_docx

                result_to_docx(self.results, path)
            elif fmt == "xlsx":
                from winnow.export import result_to_xlsx

                result_to_xlsx(self.results, path)
            else:
                Path(path).write_text(
                    report_to_html(self.results, theme=self.theme_name), encoding="utf-8"
                )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Не удалось экспортировать", str(exc))
            return
        self.statusBar().showMessage(f"Экспортировано: {path}", 5000)

    def show_about(self) -> None:
        from winnow import __version__

        QMessageBox.about(
            self,
            "О программе Winnow",
            f"<h3>Winnow {__version__}</h3>"
            "<p>Статистический анализ данных с логикой SPSS и современным интерфейсом.</p>"
            "<p>Реализовано: частоты, описательные статистики, таблицы сопряжённости "
            "с хи-квадратом, t-критерий, корреляции. Экспорт в Word, Excel и HTML.</p>"
            "<p>Числа в отчётах сверены с эталонами: расхождение со SPSS в третьем "
            "знаке недопустимо.</p>",
        )


def run() -> int:
    """Запускает приложение. Возвращает код выхода."""
    from winnow.ui.fonts import apply_base_font
    from winnow.ui.icons import app_icon

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Winnow")
    # Значок задаётся явно: в собранной программе он берётся из ресурсов .exe, но
    # при запуске из исходников значка нет вовсе, и в панели задач появляется
    # стандартный значок Python.
    app.setWindowIcon(app_icon())
    # Шрифт подбирается до применения стилей: Qt перестал поставлять шрифты, и в
    # некоторых окружениях библиотека шрифтов пуста - тогда текст не отрисуется.
    apply_base_font(app)
    window = MainWindow()
    window.show()
    return app.exec()


__all__ = ["MainWindow", "ProcedureTask", "run"]
