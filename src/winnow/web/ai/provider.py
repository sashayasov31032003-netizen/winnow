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
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Protocol, Sequence

import httpx

from winnow.web.ai.config import AISettings, COMPATIBLE_PROVIDERS


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
    #: Провайдер не умеет tools: запрос повторён без них. Агент обязан
    #: предупредить человека, что числа не из расчёта.
    tool_fallback: bool = False
    fallback_reason: str = ""


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


def _tool_error(response: httpx.Response) -> bool:
    """Похоже ли 400/404 на «этот endpoint не умеет tools»."""
    text = (response.text or "").lower()
    if "tool" not in text and "function" not in text:
        return False
    return any(
        marker in text
        for marker in (
            "support tool",
            "no endpoints found",
            "tool_choice",
            "tool choice",
            "function calling",
            "tools are not supported",
        )
    )


def _reply_from_response(response: httpx.Response, model: str) -> Reply | None:
    """Разбирает успешный ответ OpenAI-совместимого API."""
    try:
        data = response.json()
    except ValueError:
        return None
    choices = data.get("choices") or []
    if not choices:
        return None
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
        arguments, parse_error = _parse_arguments(function.get("arguments"))
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


class OpenAICompatibleProvider:
    """OpenAI-совместимый HTTP-провайдер.

    Так работают OpenRouter, VseGPT, Yandex AI Studio, DeepSeek и локальный
    Ollama. Отличаются адрес, схема авторизации и форма имени модели; сам
    протокол один, поэтому отдельный класс на каждого провайдера не нужен.
    """

    def __init__(
        self,
        settings: AISettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.name = settings.provider
        #: Подмена транспорта для тестов: настоящая сеть в тестах не нужна.
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "https://winnow.local",
            "X-Title": "Winnow Research Intelligence",
        }
        if self.settings.api_key:
            headers["Authorization"] = (
                f"{self.settings.auth_scheme} {self.settings.api_key}"
            )
        if self.settings.project:
            headers["OpenAI-Project"] = self.settings.project
        return headers

    async def complete(
        self, messages: list[dict[str, Any]], tools: Sequence[ToolSpec]
    ) -> Reply:
        if not self.settings.api_key and self.settings.provider != "ollama":
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
            # Ollama сама выбирает инструмент; явный tool_choice часть её
            # версий не принимает и отвечает 400.
            if self.settings.provider != "ollama":
                body["tool_choice"] = "auto"

        headers = self._headers()
        tools_requested = bool(tools)

        failures: list[str] = []
        async with httpx.AsyncClient(
            timeout=self.settings.timeout, transport=self._transport
        ) as client:
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
                        "Провайдер отклонил ключ ИИ. Проверьте WINNOW_AI_KEY / "
                        "OPENROUTER_API_KEY и доступ к выбранной модели."
                    )
                if response.status_code == 402:
                    raise AIProviderError(
                        "У аккаунта провайдера закончился баланс или бесплатный "
                        "лимит. Пополните счёт либо выберите другую модель."
                    )
                if (
                    response.status_code in (400, 404)
                    and tools_requested
                    and self.settings.tool_fallback
                    and _tool_error(response)
                ):
                    # Бесплатные endpoint'ы OpenRouter часто не поддерживают
                    # tools. Чтобы человек всё же получил ответ, повторяем без
                    # инструментов — но ответ будет без расчётов.
                    retry_body = {
                        key: value
                        for key, value in body.items()
                        if key not in {"tools", "tool_choice"}
                    }
                    try:
                        retry = await client.post(
                            f"{self.settings.base_url}/chat/completions",
                            json=retry_body,
                            headers=headers,
                        )
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        failures.append(
                            f"{model}: сеть недоступна при повторе ({exc.__class__.__name__})"
                        )
                        continue
                    if retry.status_code == 200:
                        reply = _reply_from_response(retry, model)
                        if reply is not None:
                            return replace(
                                reply,
                                tool_fallback=True,
                                fallback_reason=(
                                    "Провайдер не поддерживает вызов инструментов "
                                    "для этой модели"
                                ),
                            )
                    failures.append(
                        f"{model}: tools не поддерживаются (HTTP {retry.status_code})"
                    )
                    continue
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

                reply = _reply_from_response(response, model)
                if reply is None:
                    failures.append(f"{model}: некорректный ответ")
                    continue
                return reply

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
    if settings.provider in COMPATIBLE_PROVIDERS:
        if not settings.enabled:
            if settings.provider == "yandex":
                raise AIProviderError(
                    "Для Yandex AI Studio нужны ключ (WINNOW_AI_KEY или "
                    "YANDEX_API_KEY), каталог (WINNOW_AI_FOLDER_ID) и модель "
                    "(WINNOW_AI_MODEL, например gpt://<каталог>/aliceai-llm-flash/latest)."
                )
            raise AIProviderError(
                f"Для провайдера «{settings.provider}» не хватает настроек: "
                "проверьте WINNOW_AI_KEY, WINNOW_AI_BASE_URL и WINNOW_AI_MODEL."
            )
        return OpenAICompatibleProvider(settings)
    raise AIProviderError(
        f"Неизвестный провайдер «{settings.provider}». Поддерживаются: "
        "fake, openrouter, vsegpt, yandex, ollama, deepseek, custom."
    )


#: Старое имя класса: на нём завязаны тесты и документация прошлой версии.
OpenRouterProvider = OpenAICompatibleProvider


__all__ = [
    "AIProviderError",
    "ChatProvider",
    "DEMO_TEXT",
    "FakeProvider",
    "OpenAICompatibleProvider",
    "OpenRouterProvider",
    "Reply",
    "ToolCall",
    "ToolSpec",
    "create_provider",
]
