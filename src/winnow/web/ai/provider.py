"""Провайдеры моделей: один интерфейс, разные поставщики.

Агент не знает, откуда пришёл ответ. Ему важны только текст и запрошенные
вызовы инструментов. Поэтому смена OpenRouter на локальный сервер (Ollama,
vLLM) или на другого поставщика — это новый класс на 40 строк, а не правка
цикла рассуждений.

Формат сообщений и инструментов — OpenAI-совместимый: его понимают OpenRouter,
локальные серверы и большинство API. Это снижает риск, что при смене модели
придётся переписывать промпты.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, Sequence

import httpx

from winnow.web.ai.config import AISettings


class AIProviderError(RuntimeError):
    """Провайдер не смог ответить. Текст показывается пользователю как есть."""


@dataclass(frozen=True)
class ToolSpec:
    """Описание инструмента в формате, который понимает модель."""

    name: str
    description: str
    parameters: dict[str, Any]

    def as_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolCall:
    """Запрошенный моделью вызов инструмента."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    #: Ошибка разбора JSON от модели: агент вернёт её как результат вызова,
    #: чтобы модель исправилась, а не падала вся сессия.
    parse_error: str = ""


@dataclass(frozen=True)
class Reply:
    """Ответ модели: либо текст, либо намерение вызвать инструменты."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class ChatProvider(Protocol):
    """Минимальный контракт провайдера."""

    name: str

    async def complete(
        self, messages: list[dict[str, Any]], tools: Sequence[ToolSpec]
    ) -> Reply: ...


def _parse_arguments(raw: Any) -> tuple[dict[str, Any], str]:
    """Разбирает аргументы вызова, не роняя сессию на плохом JSON."""
    if isinstance(raw, dict):
        return raw, ""
    if raw is None or raw == "":
        return {}, ""
    if not isinstance(raw, str):
        return {}, f"Аргументы должны быть JSON-объектом, пришло {type(raw).__name__}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"Не удалось разобрать аргументы как JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        return {}, "Аргументы должны быть JSON-объектом"
    return parsed, ""


class OpenRouterProvider:
    """OpenAI-совместимый HTTP-провайдер (OpenRouter и совместимые серверы)."""

    name = "openrouter"

    def __init__(self, settings: AISettings) -> None:
        self.settings = settings

    async def complete(
        self, messages: list[dict[str, Any]], tools: Sequence[ToolSpec]
    ) -> Reply:
        if not self.settings.api_key:
            raise AIProviderError(
                "Ключ ИИ не задан. Укажите WINNOW_AI_KEY на сервере "
                "или включите демо-режим WINNOW_AI_PROVIDER=fake."
            )

        body: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if tools:
            body["tools"] = [tool.as_openai() for tool in tools]
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://winnow.local",
            "X-Title": "Winnow Research Intelligence",
        }

        failures: list[str] = []
        async with httpx.AsyncClient(timeout=self.settings.timeout) as client:
            for model in self.settings.models:
                body["model"] = model
                try:
                    response = await client.post(
                        f"{self.settings.base_url}/chat/completions",
                        json=body,
                        headers=headers,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    failures.append(f"{model}: сеть недоступна ({exc.__class__.__name__})")
                    continue

                if response.status_code in (401, 403):
                    raise AIProviderError(
                        "Провайдер отклонил ключ ИИ. Проверьте WINNOW_AI_KEY "
                        "и доступ к выбранной модели."
                    )
                if response.status_code == 400:
                    raise AIProviderError(
                        "Провайдер отклонил запрос (400). Проверьте имя модели "
                        "и совместимость API."
                    )
                if response.status_code == 404:
                    failures.append(f"{model}: модель не найдена")
                    continue
                if response.status_code == 429:
                    failures.append(f"{model}: лимит запросов")
                    continue
                if response.status_code >= 500:
                    failures.append(f"{model}: ошибка провайдера {response.status_code}")
                    continue
                if response.status_code != 200:
                    failures.append(f"{model}: HTTP {response.status_code}")
                    continue

                try:
                    data = response.json()
                except ValueError:
                    failures.append(f"{model}: ответ не JSON")
                    continue

                choices = data.get("choices") or []
                if not choices:
                    failures.append(f"{model}: пустой ответ")
                    continue
                message = choices[0].get("message") or {}
                text = message.get("content") or ""
                if isinstance(text, list):
                    # Некоторые провайдеры отдают содержание массивом частей.
                    text = "".join(
                        part.get("text", "") for part in text if isinstance(part, dict)
                    )

                tool_calls: list[ToolCall] = []
                for index, raw_call in enumerate(message.get("tool_calls") or []):
                    function = raw_call.get("function") or {}
                    arguments, parse_error = _parse_arguments(
                        function.get("arguments")
                    )
                    tool_calls.append(
                        ToolCall(
                            id=str(raw_call.get("id") or f"call_{index + 1}"),
                            name=str(function.get("name") or ""),
                            arguments=arguments,
                            raw_arguments=str(function.get("arguments") or ""),
                            parse_error=parse_error,
                        )
                    )

                return Reply(
                    text=str(text),
                    tool_calls=tool_calls,
                    model=str(data.get("model") or model),
                    usage=dict(data.get("usage") or {}),
                )

        detail = "; ".join(failures[-3:]) if failures else "нет доступных моделей"
        raise AIProviderError(
            f"Не удалось получить ответ от модели ({detail}). "
            "Попробуйте ещё раз через минуту или смените модель в настройках."
        )


#: Текст демо-провайдера. Он не притворяется моделью и не выдумывает числа:
#: без ключа человек должен понимать, что именно не работает.
DEMO_TEXT = (
    "Сейчас включён демо-режим без подключённой модели: сервер не отправляет "
    "запросы наружу и не считает статистику сам. Чтобы включить агента, задайте "
    "на сервере ключ OpenRouter в переменной WINNOW_AI_KEY и перезапустите "
    "приложение. Бесплатные модели подходят для разработки; для реальных данных "
    "лучше выбрать модель, которая не обучается на промптах."
)


class FakeProvider:
    """Детерминированный провайдер для тестов и демо-режима.

    В тестах ему передают сценарий ответов: сначала вызов инструмента, потом
    текст. В приложении без ключа он отвечает одним честным сообщением.
    """

    name = "fake"

    def __init__(self, replies: Iterable[Reply] | None = None) -> None:
        self._replies: deque[Reply] = deque(replies or ())
        self.calls: list[list[dict[str, Any]]] = []

    async def complete(
        self, messages: list[dict[str, Any]], tools: Sequence[ToolSpec]
    ) -> Reply:
        self.calls.append(list(messages))
        if self._replies:
            return self._replies.popleft()
        return Reply(text=DEMO_TEXT, model="fake")


def create_provider(settings: AISettings) -> ChatProvider:
    """Собирает провайдера по настройкам. Ошибка — понятная, не трейсбек."""
    if settings.provider == "fake":
        return FakeProvider()
    if settings.provider in {"openrouter", "openai", "openai-compatible"}:
        if not settings.api_key:
            raise AIProviderError(
                "Для провайдера OpenRouter нужен ключ WINNOW_AI_KEY на сервере."
            )
        return OpenRouterProvider(settings)
    raise AIProviderError(
        f"Неизвестный провайдер «{settings.provider}». "
        "Поддерживаются: fake, openrouter."
    )


__all__ = [
    "AIProviderError",
    "ChatProvider",
    "DEMO_TEXT",
    "FakeProvider",
    "OpenRouterProvider",
    "Reply",
    "ToolCall",
    "ToolSpec",
    "create_provider",
]
