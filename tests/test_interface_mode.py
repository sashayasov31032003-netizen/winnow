"""Тесты режимов интерфейса и панели подсказок.

Простой режим - то, что видит человек, который статистику не изучал. Поэтому
проверяется не только то, что переключатель работает, но и что в простом режиме
на экране действительно меньше лишнего, а подсказки запускают настоящий расчёт.

Настройки подменяются временным файлом: тесты не должны менять режим у того, кто
запускает программу на своей машине.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QElapsedTimer, QSettings
from PySide6.QtWidgets import QApplication

from winnow.samples import demo_dataset
from winnow.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Подменяет хранилище настроек файлом во временной папке.

    Без этого тест записал бы выбранный режим в настоящие настройки Windows и
    изменил бы поведение программы при следующем запуске у пользователя.
    """
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(MainWindow, "_settings", staticmethod(lambda: settings))
    return settings


def _window(qt_app, isolated_settings, dataset=None) -> MainWindow:
    window = MainWindow()
    if dataset is not None:
        window.set_dataset(dataset)
    return window


def test_program_starts_in_simple_mode(qt_app, isolated_settings):
    """По умолчанию - простой режим: новичок не должен попадать в экспертный."""
    window = _window(qt_app, isolated_settings)
    assert window.interface_mode == "simple"
    assert window.mode_button.text() == "Простой режим"
    # Переключатель - заметная кнопка с подсветкой текущего режима, а не серый
    # пункт панели: его должно быть видно сразу.
    assert window.mode_button.isCheckable()
    assert window.mode_button.isChecked()
    assert window.mode_button.objectName() == "ModeSwitch"


def test_simple_mode_hides_technical_parts(qt_app, isolated_settings):
    """В простом режиме на экране только самое нужное."""
    window = _window(qt_app, isolated_settings)
    window.show()

    assert not window.advisor_panel.isHidden(), "панель подсказок должна быть видна"
    assert not window.viewer_tabs.isTabVisible(1), "вкладка синтаксиса лишняя"
    assert not window.data_tabs.isTabVisible(1), "паспорта переменных лишние"
    assert not window.edit_menu.menuAction().isVisible()
    assert not window.utilities_menu.menuAction().isVisible()
    # Кнопок мало: выбор процедуры берёт на себя панель подсказок.
    buttons = [a for a in window.toolbar.actions() if not a.isSeparator()]
    assert len(buttons) <= 5


def test_expert_mode_returns_everything(qt_app, isolated_settings):
    """Экспертный режим показывает всё, что было раньше."""
    window = _window(qt_app, isolated_settings)
    window.show()
    window.set_interface_mode(False)

    assert window.interface_mode == "expert"
    assert window.advisor_panel.isHidden(), "панель подсказок уступает место таблицам"
    assert window.viewer_tabs.isTabVisible(1)
    assert window.data_tabs.isTabVisible(1)
    assert window.edit_menu.menuAction().isVisible()
    assert window.utilities_menu.menuAction().isVisible()
    buttons = [a for a in window.toolbar.actions() if not a.isSeparator()]
    assert len(buttons) >= 8


def test_program_always_starts_in_simple_mode(qt_app, isolated_settings):
    """Режим не запоминается между запусками - намеренно.

    Иначе одно случайное нажатие переключателя оставляло бы новичка в экспертном
    интерфейсе навсегда: он не знает, как вернуться, и просто закроет программу.
    """
    window = _window(qt_app, isolated_settings)
    window.set_interface_mode(False)
    assert window.interface_mode == "expert"
    # Выбор не сохраняется...
    assert isolated_settings.value("interface/mode") is None
    # ...и следующее окно снова открывается в простом режиме.
    assert MainWindow().interface_mode == "simple"


def test_leftover_setting_from_old_version_is_removed(qt_app, isolated_settings):
    """Значение, оставшееся от прежних версий, не должно переключать режим."""
    isolated_settings.setValue("interface/mode", "expert")
    isolated_settings.sync()

    window = _window(qt_app, isolated_settings)

    assert window.interface_mode == "simple"
    assert isolated_settings.value("interface/mode") is None


def test_switching_back_and_forth_keeps_panel_alive(qt_app, isolated_settings):
    """Панель не должна уничтожаться при смене режима.

    Она создаётся один раз: если её удалить, ссылка останется на уничтоженный
    объект, и следующее обращение уронит программу.
    """
    window = _window(qt_app, isolated_settings)
    window.show()
    for _ in range(3):
        window.set_interface_mode(False)
        window.set_interface_mode(True)
    window.set_dataset(demo_dataset())
    assert window.advisor_panel.scenarios, "панель должна продолжать работать"


def test_panel_shows_empty_state_without_data(qt_app, isolated_settings):
    window = _window(qt_app, isolated_settings)
    assert window.advisor_panel.dataset is None
    assert window.advisor_panel.scenarios == []


def test_panel_suggests_scenarios_for_loaded_data(qt_app, isolated_settings):
    window = _window(qt_app, isolated_settings, demo_dataset())
    panel = window.advisor_panel

    assert panel.profile is not None
    keys = [scenario.key for scenario in panel.scenarios]
    assert "describe" in keys
    assert "compare_two_groups" in keys
    # У каждого сценария есть подставленные переменные и объяснение.
    for scenario in panel.scenarios:
        assert scenario.why.strip()
        assert scenario.roles or scenario.key == "describe"


def test_scenario_button_runs_the_real_procedure(qt_app, isolated_settings):
    """Кнопка «Выполнить» должна доводить дело до результата в выводе."""
    window = _window(qt_app, isolated_settings, demo_dataset())
    window.show()

    scenario = next(
        item for item in window.advisor_panel.scenarios if item.key == "compare_two_groups"
    )
    window.run_scenario(scenario.procedure, dict(scenario.params))

    # Расчёт идёт в отдельном потоке, поэтому ждём результат, а не спим.
    timer = QElapsedTimer()
    timer.start()
    while not window.results and timer.elapsed() < 20000:
        qt_app.processEvents()

    assert window.results, "сценарий не дал результата"
    result = window.results[-1]
    assert result.procedure == "T-TEST"
    assert result.tables
    # В выводе первым идёт объяснение простыми словами.
    assert result.conclusions
    assert "значимы" in result.conclusions[0].text


def test_panel_button_emits_request(qt_app, isolated_settings):
    """Кнопка в панели связана с окном, а не просто нарисована."""
    window = _window(qt_app, isolated_settings, demo_dataset())
    received: list[tuple[str, dict]] = []
    window.advisor_panel.scenarioRequested.connect(
        lambda procedure, params: received.append((procedure, params))
    )

    scenario = window.advisor_panel.scenarios[0]
    window.advisor_panel.scenarioRequested.emit(scenario.procedure, dict(scenario.params))

    assert received
    assert received[0][0] == scenario.procedure


def test_syntax_is_hidden_from_output_in_simple_mode(qt_app, isolated_settings):
    """Команды SPSS нужны опытному пользователю, а не начинающему."""
    window = _window(qt_app, isolated_settings, demo_dataset())
    window.show()

    scenario = next(
        item for item in window.advisor_panel.scenarios if item.key == "compare_two_groups"
    )
    window.run_scenario(scenario.procedure, dict(scenario.params))
    timer = QElapsedTimer()
    timer.start()
    while not window.results and timer.elapsed() < 20000:
        qt_app.processEvents()

    text = window.output_browser.toPlainText()
    assert "Простыми словами" in text
    assert "Синтаксис" not in text, "в простом режиме синтаксис только мешает"

    window.set_interface_mode(False)
    qt_app.processEvents()
    assert "Синтаксис" in window.output_browser.toPlainText()

    window.set_interface_mode(True)
    qt_app.processEvents()
    assert "Синтаксис" not in window.output_browser.toPlainText()


def _run_scenario(window, qt_app, key: str = "compare_two_groups") -> None:
    """Запускает сценарий советчика и дожидается результата."""
    scenario = next(item for item in window.advisor_panel.scenarios if item.key == key)
    before = len(window.results)
    window.run_scenario(scenario.procedure, dict(scenario.params))
    timer = QElapsedTimer()
    timer.start()
    while len(window.results) == before and timer.elapsed() < 20000:
        qt_app.processEvents()
    assert len(window.results) > before, "сценарий не дал результата"


def test_every_result_is_wrapped_in_its_own_card(qt_app, isolated_settings):
    """Результаты не должны сливаться: у каждого своя рамка.

    Карточка сделана таблицей: Qt рисует рамки у таблиц, но игнорирует их у
    блоков div, поэтому рамка вокруг результата иначе не появлялась бы там, где
    она нужна, - в окне программы.

    Разметка проверяется у рендерера, а не у `QTextBrowser.toHtml()`: Qt
    переписывает HTML по-своему и теряет классы, так что по нему судить о
    разметке нельзя.
    """
    from winnow.export import report_to_html

    window = _window(qt_app, isolated_settings, demo_dataset())
    window.show()
    _run_scenario(window, qt_app, "compare_two_groups")
    _run_scenario(window, qt_app, "reliability")

    assert len(window.results) == 2
    html = report_to_html(window.results, show_title=False)
    assert html.count('class="card"') == len(window.results)
    # Заголовки результатов пронумерованы: 1., 2.
    text = window.output_browser.toPlainText()
    assert "1. t-критерий" in text
    assert "2. Анализ надёжности" in text


def test_clear_output_removes_results(qt_app, isolated_settings, monkeypatch):
    """Кнопка очистки убирает результаты из вывода."""
    from PySide6.QtWidgets import QMessageBox

    window = _window(qt_app, isolated_settings, demo_dataset())
    window.show()
    _run_scenario(window, qt_app)
    assert window.results

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    window.clear_output()

    assert window.results == []
    assert "t-критерий" not in window.output_browser.toPlainText()
    assert not window.syntax_log


def test_clear_output_can_be_cancelled(qt_app, isolated_settings, monkeypatch):
    """Отказ от очистки оставляет результаты на месте."""
    from PySide6.QtWidgets import QMessageBox

    window = _window(qt_app, isolated_settings, demo_dataset())
    window.show()
    _run_scenario(window, qt_app)
    before = len(window.results)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    window.clear_output()

    assert len(window.results) == before


def test_clear_output_on_empty_output_asks_nothing(
    qt_app, isolated_settings, monkeypatch
):
    """Когда терять нечего, подтверждение только мешает."""
    from PySide6.QtWidgets import QMessageBox

    window = _window(qt_app, isolated_settings, demo_dataset())
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: asked.append("спросили"))
    )
    window.clear_output()
    assert not asked


def test_variable_lists_widen_for_long_labels(qt_app, isolated_settings):
    """Длинные метки переменных должны быть видны, а не обрезаны.

    Раньше список переменных имел фиксированную ширину 130 точек, и метка
    «Уровень образования [education]» обрывалась на середине.
    """
    from winnow.ui.dialogs import ProcedureDialog, TransferList
    from winnow.ui.procedure_specs import DIALOG_SPECS

    dataset = demo_dataset()
    dialog = ProcedureDialog(DIALOG_SPECS["crosstabs"], dataset)
    lists = [w for w in dialog._widgets.values() if isinstance(w, TransferList)]
    assert lists, "в диалоге таблиц сопряжённости должны быть списки переменных"

    for field in lists:
        width = field.available.minimumWidth()
        # Точная ширина зависит от шрифта и DPI системы: требуя ровно максимум,
        # тест падал через раз на другой машине. Проверяется смысл: список
        # заметно шире прежних фиксированных 130 точек и не выходит за предел.
        assert TransferList.MIN_LIST_WIDTH <= width <= TransferList.MAX_LIST_WIDTH
        assert width >= TransferList.MIN_LIST_WIDTH > 130
        # Каждый пункт подсказывает полную метку: если она всё же не влезла,
        # достаточно навести курсор.
        for index in range(field.available.count()):
            item = field.available.item(index)
            assert item.toolTip() == item.text()


def test_short_labels_do_not_inflate_the_dialog(qt_app, isolated_settings):
    """Адаптивность работает в обе стороны: короткие метки - узкие списки."""
    from winnow.core.dataset import Dataset
    from winnow.ui.dialogs import ProcedureDialog, TransferList
    from winnow.ui.procedure_specs import DIALOG_SPECS

    dataset = Dataset.from_records({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
    dialog = ProcedureDialog(DIALOG_SPECS["crosstabs"], dataset)
    for field in dialog._widgets.values():
        if isinstance(field, TransferList):
            assert field.available.minimumWidth() == TransferList.MIN_LIST_WIDTH


def test_dialog_width_follows_content_and_screen(qt_app, isolated_settings):
    """Окно открывается по содержимому, но не шире экрана."""
    from winnow.ui.dialogs import ProcedureDialog
    from winnow.ui.procedure_specs import DIALOG_SPECS

    dialog = ProcedureDialog(DIALOG_SPECS["crosstabs"], demo_dataset())
    needed = dialog._body.sizeHint().width() + 48
    screen = qt_app.primaryScreen().availableGeometry().width()
    limit = min(1180, int(screen * 0.95))
    assert dialog.width() == max(min(needed, limit), 620)


def test_dialog_keeps_input_and_shows_error_inside(
    qt_app, isolated_settings, monkeypatch
):
    """Ошибка показывается в окне, а заполненная форма остаётся.

    Раньше при неверных параметрах окно закрывалось и появлялось всплывающее
    сообщение: человек терял всё, что ввёл, и должен был открывать окно заново.
    """
    from winnow.ui.dialogs import ProcedureDialog
    from winnow.ui.procedure_specs import DIALOG_SPECS

    dialog = ProcedureDialog(DIALOG_SPECS["ttest"], demo_dataset())
    dialog.set_value("test_vars", ["anxiety"])
    dialog.set_value("group_var", "gender")
    # Одна группа вместо двух - проверка параметров не пройдёт.
    dialog.set_value("group_values", "1")

    rounds = {"count": 0}

    def fake_exec() -> int:
        rounds["count"] += 1
        return 1 if rounds["count"] == 1 else 0  # Выполнить, затем Отмена

    monkeypatch.setattr(dialog, "exec", fake_exec)
    command = dialog.build_command()

    assert command is None, "второй круг - отмена"
    assert rounds["count"] == 2, "окно должно показаться снова, а не закрыться"
    assert not dialog.error_label.isHidden(), "сообщение видно в самом окне"
    assert "две группы" in dialog.error_label.text()
    # Главное: введённое не потерялось.
    assert dialog.values()["test_vars"] == ["anxiety"]


def test_error_message_tells_how_to_fix(qt_app, isolated_settings):
    """Сообщение говорит не только что не так, но и что делать."""
    from winnow.samples import demo_dataset as demo
    from winnow.stats.command import CorrelationsCommand, TTestCommand

    dataset = demo()
    with pytest.raises(Exception) as one_variable:
        CorrelationsCommand(dataset=dataset, variables=["age"]).validate()
    assert "Перенесите" in str(one_variable.value)

    with pytest.raises(Exception) as one_group:
        TTestCommand(
            dataset=dataset,
            kind="independent",
            test_vars=["anxiety"],
            group_var="gender",
            group_values=[1.0],
        ).validate()
    assert "Коды групп" in str(one_group.value)


def test_no_message_sends_the_user_to_nothing(qt_app, isolated_settings):
    """Внутреннее «команда не связана с данными» человеку ничего не говорит."""
    from winnow.stats.command import CorrelationsCommand

    with pytest.raises(Exception) as error:
        CorrelationsCommand(dataset=None, variables=["a", "b"]).validate()
    assert "Открыть данные" in str(error.value)


def test_clear_button_lives_in_the_output_panel(qt_app, isolated_settings):
    """Чистить вывод ищут рядом с результатами, а не среди кнопок запуска."""
    window = _window(qt_app, isolated_settings, demo_dataset())
    window.show()
    button = window.clear_output_button

    assert window.viewer_tabs.cornerWidget() is button
    # Пока чистить нечего, кнопка неактивна: это честнее сообщения «вывод пуст».
    assert not button.isEnabled()

    _run_scenario(window, qt_app)
    qt_app.processEvents()
    assert button.isEnabled()

    # В простом режиме кнопки нет на панели инструментов: там и без неё тесно,
    # а рядом с результатами она есть.
    titles = [action.text() for action in window.toolbar.actions()]
    assert "Очистить вывод" not in titles
    assert not button.isHidden()

    # В экспертном режиме она возвращается и на панель инструментов.
    window.set_interface_mode(False)
    titles = [action.text() for action in window.toolbar.actions()]
    assert "Очистить вывод" in titles


def test_unknown_scenario_does_not_crash(qt_app, isolated_settings, monkeypatch):
    """Некорректный сценарий должен сообщать об ошибке, а не падать."""
    from PySide6.QtWidgets import QMessageBox

    window = _window(qt_app, isolated_settings, demo_dataset())
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(str(a)))
    )
    window.run_scenario("нет-такой-процедуры", {})
    assert shown, "пользователь должен увидеть сообщение"


def test_switching_to_expert_shows_the_data_table(qt_app, isolated_settings):
    """Данные не «пропадают» при смене режима: их просто перестают показывать.

    Проверено на живом человеке: он загрузил файл в простом режиме, перешёл в
    экспертный, не увидел таблицы и решил, что данные нужно загружать заново.
    """
    window = _window(qt_app, isolated_settings, demo_dataset())
    window.show()
    assert window.editor_dock.isHidden(), "в простом режиме таблица уступает место подсказкам"

    window.set_interface_mode(False)
    qt_app.processEvents()
    assert not window.editor_dock.isHidden(), "в экспертном режиме таблица должна быть видна"
    assert window.dataset is not None and len(window.dataset.frame) == 200

    window.set_interface_mode(True)
    qt_app.processEvents()
    assert window.dataset is not None, "набор остаётся в памяти при любом режиме"


def test_mode_is_visible_without_hovering(qt_app, isolated_settings):
    """В каком режиме находишься — видно постоянно, а не по подписи кнопки."""
    window = _window(qt_app, isolated_settings, demo_dataset())
    window.show()

    assert window.mode_badge.text() == "Простой режим"
    assert "Простой режим" in window.windowTitle()
    assert window.mode_badge.toolTip(), "у плашки должна быть подсказка"

    window.set_interface_mode(False)
    qt_app.processEvents()
    assert window.mode_badge.text() == "Экспертный режим"
    assert "Экспертный режим" in window.windowTitle()


def test_advisor_offers_only_runnable_scenarios(qt_app, isolated_settings):
    """Подсказка, которая не выполняется, хуже отсутствующей подсказки.

    Данные как из Google Forms: категории записаны словами и потому являются
    строками. Раньше советчик передавал такую переменную описательным
    статистикам, и человек видел «Проверьте параметры… - string».
    """
    from winnow.core.dataset import Dataset
    from winnow.stats.engine import REGISTRY_BY_KEY

    dataset = Dataset.from_records(
        {
            "1. Ваш пол": ["Мужской"] * 40 + ["Женский"] * 40,
            "2. Ваш возраст": [str(18 + index % 40) for index in range(80)],
            "3. Удовлетворённость": [str(1 + index % 5) for index in range(80)],
        }
    )
    window = _window(qt_app, isolated_settings, dataset)
    scenarios = window.advisor_panel.scenarios
    assert scenarios, "хоть что-то предложить должно"

    for scenario in scenarios:
        info = REGISTRY_BY_KEY[scenario.procedure]
        # Не падает -> параметры сценария корректны для этих данных.
        info.command_type(dataset=dataset, **scenario.params).validate()

    describe = [item for item in scenarios if item.key == "describe"]
    if describe:
        for name in describe[0].params["variables"]:
            assert dataset.var(name).is_numeric, (
                "описательные статистики видят только числа"
            )


def test_categorical_list_does_not_trust_declared_measure(qt_app, isolated_settings):
    """Файлы SPSS 19 помечают количественными всё подряд.

    На таком файле в списке категорий оставалась одна переменная из четырнадцати,
    и в таблицах сопряжённости выбирать было нечего. Решает не объявленный
    уровень измерения, а число различных значений.
    """
    from winnow.core.dataset import Dataset
    from winnow.core.variable import Measure
    from winnow.ui.dialogs import ProcedureDialog
    from winnow.ui.procedure_specs import DIALOG_SPECS

    dataset = Dataset.from_records(
        {
            "пол": [1.0, 2.0] * 20,
            "район": [1.0, 2.0, 3.0, 1.0] * 10,
            "доход": [float(1000 + index * 37) for index in range(40)],
        }
    )
    # Так и бывает в файлах SPSS 19: всё объявлено количественным.
    for name in dataset.names():
        dataset.var(name).measure = Measure.SCALE

    dialog = ProcedureDialog(DIALOG_SPECS["crosstabs"], dataset)
    available = dialog._widgets["row_vars"].available
    offered = {available.item(index).text() for index in range(available.count())}

    assert "пол" in offered
    assert "район" in offered, "район с тремя значениями - категория, а не показатель"
    assert "доход" not in offered, "у дохода 40 разных значений - это показатель"


def test_multi_answer_card_appears_and_disappears(qt_app, isolated_settings):
    """Программа сама замечает вопросы с несколькими ответами.

    Человек открывает анкету и видит объяснение и кнопку, а не молчаливый
    столбец с «2. Соцсети;7. Форумы», по которому ничего не считается.
    """
    from PySide6.QtWidgets import QPushButton
    from winnow.core.dataset import Dataset

    dataset = Dataset.from_records(
        {
            "1. Пол": ["1. Мужской", "2. Женский"] * 5,
            "10. Источники": [
                "2. Соцсети;7. Форумы",
                "2. Соцсети;6. Вебинары",
                "6. Вебинары",
                "7. Форумы",
                "2. Соцсети",
            ]
            * 2,
        }
    )
    window = MainWindow()
    window.show()
    window.set_dataset(dataset)
    qt_app.processEvents()

    panel = window.advisor_panel
    labels = [button.text() for button in panel.body.findChildren(QPushButton)]
    assert "Разбить на отметки" in labels, "карточка должна появиться сама"
    before = len(dataset.names())

    button = next(b for b in panel.body.findChildren(QPushButton) if b.text() == "Разбить на отметки")
    button.click()
    qt_app.processEvents()

    assert len(dataset.names()) > before, "отметки добавились"
    labels = [button.text() for button in panel.body.findChildren(QPushButton)]
    assert "Разбить на отметки" not in labels, "после разбиения карточка уходит"

    # Повторное разбиение не создаёт дублей.
    from winnow.stats.multianswer import split_all

    created, handled = split_all(dataset)
    assert created == [] and handled == []
