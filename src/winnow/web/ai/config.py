"""Настройки ИИ-слоя: провайдер, модель, лимиты, политика данных.

Правила, которые здесь закреплены:

* **Ключ живёт только в окружении сервера.** В коде, в базе и в ответах API его
  нет; клиент получает лишь имя модели и остаток квоты.
* **По умолчанию — демо-провайдер.** Без ключа приложение работает, но не ходит
  в сеть: это честнее, чем падать при первом сообщении.
* **Провайдер выбирается переменной, а не кодом.** OpenRouter, VseGPT, Yandex AI
  Studio, DeepSeek и локальный Ollama говорят на OpenAI-совместимом протоколе;
  отличается только адрес, схема авторизации и имя модели.
* **Политика данных — «агрегаты».** Сырые строки не уходят модели, пока у
  набора явно не разрешён полный доступ.

Почему пресеты, а не свободная настройка всего: у российских провайдеров
разные схемы авторизации (`Bearer` у VseGPT и DeepSeek, `Api-Key` у Yandex AI
Studio) и разные формы имени модели. Ошибка в одном заголовке выглядит как
«модель не отвечает», поэтому типовые связки описаны здесь и проверяются тестами.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Бесплатные модели OpenRouter с поддержкой вызова инструментов.
#: Список проверялся 28.10.2026; каталог меняется, поэтому модель задаётся
#: переменной окружения, а эти значения — только разумная отправная точка.
FREE_MODELS: tuple[str, ...] = (
    "xingchen-agi/xing4.0-29b-a4b:free",
    "dots-studio/dots-3-note-preview:free",
    "cohere/north-mini-code:free",
)

DEFAULT_MODEL = FREE_MODELS[0]

#: Готовые связки «провайдер → адрес, схема авторизации, модель по умолчанию».
#: Модели для Yandex подставляются вместе с каталогом (folder_id): без него
#: платформа не знает, в каком проекте искать модель.
PRESETS: dict[str, dict[str, str]] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "auth_scheme": "Bearer",
        "model": DEFAULT_MODEL,
    },
    # Российский агрегатор с OpenAI-совместимым API: работает без VPN,
    # поддерживает tools у моделей с соответствующим бейджем.
    "vsegpt": {
        "base_url": "https://api.vsegpt.ru/v1",
        "auth_scheme": "Bearer",
        "model": "openai/gpt-4o-mini",
    },
    # Yandex AI Studio: Alice AI / YandexGPT, оплата в рублях, данные не
    # используются для обучения. Авторизация — заголовок Api-Key.
    "yandex": {
        "base_url": "https://ai.api.cloud.yandex.net/v1",
        "auth_scheme": "Api-Key",
        "model": "gpt://{folder}/aliceai-llm-flash/latest",
    },
    # Локальный Ollama: бесплатно, без сети и ключа. Модель должна уметь tools.
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "auth_scheme": "Bearer",
        "model": "qwen3:8b",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "auth_scheme": "Bearer",
        "model": "deepseek-chat",
    },
}

#: Провайдеры, которые говорят на OpenAI-совместимом /chat/completions.
COMPATIBLE_PROVIDERS = frozenset(
    {"openrouter", "vsegpt", "yandex", "ollama", "deepseek", "custom"}
)


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


def _key() -> str:
    """Ключ любого поддерживаемого провайдера, без привязки к одному имени."""
    for name in (
        "WINNOW_AI_KEY",
        "WINNOW_OPENROUTER_API_KEY",
        "YANDEX_API_KEY",
        "VSEGPT_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        value = _env(name)
        if value:
            return value
    return ""


def _folder() -> str:
    return _env("WINNOW_AI_FOLDER_ID") or _env("YANDEX_FOLDER_ID")


@dataclass(frozen=True)
class AISettings:
    """Всё, что агент должен знать о провайдере и ограничениях."""

    provider: str = "fake"
    model: str = DEFAULT_MODEL
    fallback_models: tuple[str, ...] = ()
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    #: Как подписывать ключ: `Bearer` (OpenAI-совместимые) или `Api-Key` (Yandex).
    auth_scheme: str = "Bearer"
    #: Заголовок OpenAI-Project: нужен части совместимых платформ (Yandex).
    project: str = ""
    timeout: float = 60.0
    max_steps: int = 6
    max_tokens: int = 1400
    temperature: float = 0.2
    daily_turns: int = 20

    @property
    def enabled(self) -> bool:
        """Можно ли отвечать: демо и локальной модели ключ не нужен."""
        if self.provider == "fake":
            return True
        if self.provider == "ollama":
            return bool(self.model and self.base_url)
        if self.provider == "custom":
            return bool(self.model and self.base_url and self.api_key)
        if self.provider == "yandex":
            return bool(self.api_key and self.model and "{folder}" not in self.model)
        return bool(self.api_key and self.model and self.base_url)

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
    key = _key()
    provider = _env("WINNOW_AI_PROVIDER").lower()
    if not provider:
        provider = "openrouter" if key else "fake"

    preset = PRESETS.get(provider, {})
    folder = _folder()

    model = _env("WINNOW_AI_MODEL") or preset.get("model", "")
    if provider == "yandex":
        if "{folder}" in model:
            model = model.replace("{folder}", folder) if folder else ""
        elif folder and model and not model.startswith("gpt://"):
            model = f"gpt://{folder}/{model}/latest"

    if provider == "ollama" and not key:
        # Ollama не проверяет ключ, но HTTP-клиент должен что-то отправить.
        key = "ollama"

    base_url = (_env("WINNOW_AI_BASE_URL") or preset.get("base_url", "")).rstrip("/")
    auth_scheme = _env("WINNOW_AI_AUTH_SCHEME") or preset.get("auth_scheme", "Bearer")
    project = _env("WINNOW_AI_PROJECT") or (folder if provider == "yandex" else "")

    raw_fallbacks = os.environ.get("WINNOW_AI_FALLBACKS")
    if raw_fallbacks is None:
        fallbacks = (
            tuple(name for name in FREE_MODELS if name != model)
            if provider == "openrouter"
            else ()
        )
    else:
        fallbacks = tuple(
            item.strip() for item in raw_fallbacks.split(",") if item.strip()
        )

    return AISettings(
        provider=provider,
        model=model,
        fallback_models=fallbacks,
        base_url=base_url,
        api_key=key,
        auth_scheme=auth_scheme,
        project=project,
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
    "COMPATIBLE_PROVIDERS",
    "DEFAULT_MODEL",
    "FREE_MODELS",
    "PRESETS",
    "describe",
    "load_settings",
    "raw_text_allowed",
]
