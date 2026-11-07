"""Настройки ИИ-слоя: провайдер, модель, лимиты, политика данных.

Правила, которые здесь закреплены:

* **Ключ живёт только в окружении сервера.** В коде, в базе и в ответах API его
  нет; клиент получает лишь имя модели и остаток квоты.
* **По умолчанию — демо-провайдер.** Без ключа приложение работает, но не ходит
  в сеть: это честнее, чем падать при первом сообщении.
* **Бесплатные модели — для разработки.** Пока ключа нет, модель по умолчанию
  взята из бесплатного каталога OpenRouter; при появлении платного доступа
  достаточно поменять переменные окружения.
* **Политика данных — «агрегаты».** Сырые строки не уходят модели, пока у
  набора явно не разрешён полный доступ.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Бесплатные модели OpenRouter с поддержкой вызова инструментов.
#: Список проверялся 28.10.2026; каталог меняется, поэтому модель задаётся
#: переменной окружения, а эти значения — только разумная отправная точка.
#: Порядок: основная, затем резервные (если основная недоступна).
FREE_MODELS: tuple[str, ...] = (
    "xingchen-agi/xing4.0-29b-a4b:free",
    "dots-studio/dots-3-note-preview:free",
    "cohere/north-mini-code:free",
)

DEFAULT_MODEL = FREE_MODELS[0]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _integer(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


@dataclass(frozen=True)
class AISettings:
    """Всё, что агент должен знать о провайдере и ограничениях."""

    provider: str = "fake"
    model: str = DEFAULT_MODEL
    fallback_models: tuple[str, ...] = FREE_MODELS[1:]
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    timeout: float = 60.0
    max_steps: int = 6
    max_tokens: int = 1400
    temperature: float = 0.2
    daily_turns: int = 20

    @property
    def enabled(self) -> bool:
        """Можно ли отвечать: демо-провайдеру ключ не нужен."""
        return self.provider == "fake" or bool(self.api_key)

    @property
    def models(self) -> tuple[str, ...]:
        """Основная модель и резервные, без повторов."""
        unique: list[str] = []
        for name in (self.model, *self.fallback_models):
            if name and name not in unique:
                unique.append(name)
        return tuple(unique)


def load_settings() -> AISettings:
    """Читает окружение при каждом вызове.

    Так тесты и разработчик могут менять переменные без перезапуска процесса;
    чтение десяти строк окружения дешевле, чем риск закешировать чужой ключ.
    """
    key = _env("WINNOW_AI_KEY") or _env("WINNOW_OPENROUTER_API_KEY")
    provider = _env("WINNOW_AI_PROVIDER").lower()
    if not provider:
        provider = "openrouter" if key else "fake"

    model = _env("WINNOW_AI_MODEL") or DEFAULT_MODEL
    raw_fallbacks = os.environ.get("WINNOW_AI_FALLBACKS")
    if raw_fallbacks is None:
        fallbacks = tuple(name for name in FREE_MODELS if name != model)
    else:
        fallbacks = tuple(
            item.strip() for item in raw_fallbacks.split(",") if item.strip()
        )

    base_url = _env("WINNOW_AI_BASE_URL") or "https://openrouter.ai/api/v1"

    return AISettings(
        provider=provider,
        model=model,
        fallback_models=fallbacks,
        base_url=base_url.rstrip("/"),
        api_key=key,
        timeout=max(5.0, min(180.0, _number("WINNOW_AI_TIMEOUT", 60.0))),
        max_steps=_integer("WINNOW_AI_MAX_STEPS", 6, low=1, high=12),
        max_tokens=_integer("WINNOW_AI_MAX_TOKENS", 1400, low=200, high=8000),
        temperature=max(0.0, min(1.0, _number("WINNOW_AI_TEMPERATURE", 0.2))),
        daily_turns=_integer("WINNOW_AI_DAILY_TURNS", 20, low=1, high=1000),
    )


def describe(settings: AISettings) -> dict:
    """Безопасное описание настроек для клиента: без ключа и без URL с ключом."""
    return {
        "enabled": settings.enabled,
        "provider": settings.provider,
        "model": settings.model,
        "models": list(settings.models),
        "daily_limit": settings.daily_turns,
        "data_policy": "aggregates",
    }


def raw_text_allowed() -> bool:
    """Разрешены ли сырые строки на уровне сервера вообще.

    Основной рубильник — флаг на наборе. Это второй, общий: на публичном
    сервере администратор может запретить передачу строк целиком, даже если
    пользователь включил флаг у себя. Значение по умолчанию — разрешено,
    иначе флаг набора был бы бесполезен.
    """
    return _flag("WINNOW_AI_ALLOW_TEXT", True)


__all__ = [
    "AISettings",
    "DEFAULT_MODEL",
    "FREE_MODELS",
    "describe",
    "load_settings",
    "raw_text_allowed",
]
