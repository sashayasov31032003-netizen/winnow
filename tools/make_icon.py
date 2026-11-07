"""Создаёт значок программы (assets/winnow.ico) из логотипа, нарисованного кодом.

Зачем отдельный файл: Windows берёт значок файла .exe и ярлыка из ресурсов, а
туда картинку нужно положить готовой. Рисовать её второй раз «руками» нельзя -
два рисунка рано или поздно разойдутся, поэтому значок берётся ровно из того же
кода, что и значок окна (winnow.ui.icons.draw_logo).

Запуск:
    QT_QPA_PLATFORM=offscreen python tools/make_icon.py

Результат:
    assets/winnow.ico  - многоразмерный значок для .exe и ярлыка;
    assets/winnow.png  - крупная картинка для документации.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Значок рисуется без окна: инструмент запускается из консоли и в сборке.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from winnow.ui.icons import LOGO_SIZES, draw_logo, logo_pixmap  # noqa: E402

ASSETS = ROOT / "assets"
# Размеры внутри .ico. 256 нужен для крупных значков в проводнике, 16 и 20 -
# для панели задач и списка файлов.
ICON_SIZES = tuple(sorted({16, 20, 24, 32, 48, 64, 128, 256}))
PREVIEW_SIZE = 256


def _pil_image(size: int) -> Image.Image:
    """Рисует логотип указанного размера и возвращает его как картинку Pillow."""
    pixmap = logo_pixmap(size)
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    stride = image.bytesPerLine()
    raw = bytes(image.constBits())
    # Строка может быть выровнена с запасом: тогда лишние байты в конце каждой
    # строки нужно убрать, иначе картинка «съезжает» по диагонали.
    if stride != width * 4:
        rows = [raw[row * stride : row * stride + width * 4] for row in range(height)]
        raw = b"".join(rows)
    return Image.frombytes("RGBA", (width, height), raw)


def _write_ico(images: list[tuple[int, Image.Image]], path: Path) -> None:
    """Собирает многоразмерный .ico из готовых картинок.

    Формат ICO простой: заголовок, таблица записей и сами картинки. Каждая
    картинка кладётся в PNG - так делают все современные программы, и Windows
    понимает такой файл начиная с Vista.
    """
    import io

    payloads: list[bytes] = []
    for _size, image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        payloads.append(buffer.getvalue())

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for (size, _image), payload in zip(images, payloads):
        # Для 256 в записи пишется ноль: в байт число не помещается.
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII",
            dimension,
            dimension,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        offset += len(payload)

    path.write_bytes(header + entries + b"".join(payloads))


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - нужен для QPixmap
    ASSETS.mkdir(parents=True, exist_ok=True)

    images = [(size, _pil_image(size)) for size in ICON_SIZES]
    icon_path = ASSETS / "winnow.ico"
    _write_ico(images, icon_path)

    preview_path = ASSETS / "winnow.png"
    _pil_image(PREVIEW_SIZE).save(preview_path)

    print(f"значок собран: {icon_path} ({icon_path.stat().st_size} байт)")
    print(f"  размеры: {', '.join(str(size) for size in ICON_SIZES)}")
    print(f"картинка для документации: {preview_path}")
    # Пустая проверка: значок обязан быть непустым, иначе сборка .exe пройдёт
    # «успешно», а иконка в проводнике останется стандартной.
    if icon_path.stat().st_size < 1024:
        print("ОШИБКА: файл значка подозрительно мал", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
