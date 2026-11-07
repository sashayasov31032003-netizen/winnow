"""Запуск веб-приложения одной командой: python -m winnow.web

Отдельная точка входа нужна потому, что у `uvicorn` из командной строки две
неприятности на Windows: путь к интерпретатору приходится писать относительно
папки проекта, а адрес страницы нужно помнить. Здесь это спрятано: команда
запускается откуда угодно, сама поднимает сервер и открывает браузер.

Браузер открывается не по таймеру, а после того как сервер ответил: по таймеру
он успевал открыться раньше и показывал ошибку соединения, что выглядит как
«браузер не открылся».
"""

from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request
import webbrowser


def _log_path():
    """Куда писать причину сбоя: рядом с программой, чтобы файл нашёлся."""
    import pathlib
    import sys

    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent / "winnow-web.log"
    return pathlib.Path(__file__).resolve().parents[3] / "winnow-web.log"


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

#: Сколько ждать, пока сервер начнёт отвечать, прежде чем открыть браузер.
STARTUP_TIMEOUT = 40.0


def _wait_until_ready(health_url: str, timeout: float = STARTUP_TIMEOUT) -> bool:
    """Ждёт, пока сервер ответит на запрос здоровья."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.3)
    return False


def _open_browser_when_ready(url: str, health_url: str) -> None:
    """Открывает браузер, когда сервер готов принимать запросы."""

    def worker() -> None:
        ready = _wait_until_ready(health_url)
        if not ready:
            print(f"  Сервер не ответил за {STARTUP_TIMEOUT:.0f} с. Откройте вручную: {url}", flush=True)
            return
        print("  Открываю браузер…", flush=True)
        try:
            if os.name == "nt":
                # Аналог двойного щелчка по ссылке: не зависит от того, какая
                # программа назначена браузером по умолчанию.
                os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606
            else:
                webbrowser.open(url)
        except Exception as exc:  # браузер может отсутствовать
            print(f"  Браузер открыть не удалось ({exc}). Откройте вручную: {url}", flush=True)

    threading.Thread(target=worker, daemon=True).start()


def main() -> int:
    import uvicorn

    from winnow.web.main import app

    host = os.environ.get("WINNOW_HOST", DEFAULT_HOST)
    port = int(os.environ.get("WINNOW_PORT", str(DEFAULT_PORT)))
    app_url = f"http://{host}:{port}/"
    docs_url = f"http://{host}:{port}/docs"
    health_url = f"http://{host}:{port}/api/health"

    print()
    print("  " + "=" * 58)
    print("  Сервер Winnow работает. Это окно закрывать нельзя.")
    print("  Остановить: Ctrl+C")
    print()
    print(f"  Откройте в браузере:  {app_url}")
    print("  Браузер не открылся сам - скопируйте адрес выше")
    print("  или запустите web\\open.cmd")
    print()
    print(f"  Документация API:     {docs_url}")
    print("  " + "=" * 58)
    print()

    # Открывать браузер не всегда нужно: мешает в тестах и на сервере.
    if os.environ.get("WINNOW_OPEN_BROWSER", "1") != "0":
        _open_browser_when_ready(app_url, health_url)

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except Exception:
        # Окно, которое закрылось молча, ничего не объясняет. Пишем причину в
        # файл рядом с программой и ждём нажатия клавиши.
        import traceback

        details = traceback.format_exc()
        log = _log_path()
        try:
            log.write_text(details, encoding="utf-8")
        except OSError:
            pass
        print()
        print("  Сервер не смог запуститься.")
        print(f"  Подробности записаны в: {log}")
        print()
        print(details)
        try:
            input("  Нажмите Enter, чтобы закрыть окно...")
        except EOFError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
