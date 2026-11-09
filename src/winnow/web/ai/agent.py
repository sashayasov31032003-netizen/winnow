"""Цикл рассуждений агента: сообщение → инструменты → ответ.

Цикл живёт на сервере по трём причинам: ключ не попадает в браузер, каждый
вызов инструмента можно проверить и записать в аудит, а числа в ответе всегда
приходят из расчёта, а не из текста модели.

Один ход — это не более `max_steps` обращений к модели. Если модель не
уложилась, делается последний вызов без инструментов: «сформулируй итог по уже
полученным данным». Так человек получает ответ, а не обрыв.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import anyio

from winnow.web.ai import store
from winnow.web.ai.config import AISettings
from winnow.web.ai.guardrails import (
    AIGuardError,
    ToolArgumentsError,
    check_message,
    unverified_numbers,
)
from winnow.web.ai.prompts import system_prompt
from winnow.web.ai.provider import AIProviderError, ChatProvider, ToolCall
from winnow.web.ai.serialization import run_summary
from winnow.web.ai.tools import ToolContext, execute_tool, get_tool, tool_specs


def _tool_message(call: ToolCall, content: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "name": call.name,
        "content": json.dumps(content, ensure_ascii=False),
    }


async def run_turn(
    *,
    user_id: int,
    dataset_id: int,
    conversation_id: int | None,
    message: str,
    settings: AISettings,
    provider: ChatProvider,
) -> AsyncIterator[dict[str, Any]]:
    """Один ход диалога. Отдаёт события, которые API превращает в SSE."""
    message = check_message(message)

    if conversation_id is None:
        conversation_id = store.create_conversation(
            user_id, dataset_id, title=message[:80]
        )
    else:
        conversation = store.get_conversation(user_id, conversation_id)
        if conversation.dataset_id not in (None, dataset_id):
            raise AIGuardError("Диалог относится к другому набору данных")

    history = store.history(conversation_id, limit=12)
    store.add_message(conversation_id, "user", message)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt()},
        *history,
        {"role": "user", "content": message},
    ]
    tools = tool_specs()
    context = ToolContext(user_id=user_id, dataset_id=dataset_id, settings=settings)

    collected: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    warnings: list[str] = []
    steps = 0
    final_text = ""
    model_name = settings.model
    usage: dict[str, Any] = {}

    yield {
        "type": "start",
        "conversation_id": conversation_id,
        "model": settings.model,
        "provider": provider.name,
    }

    for step in range(settings.max_steps):
        steps = step + 1
        try:
            reply = await provider.complete(messages, tools)
        except AIProviderError as exc:
            text = f"Не удалось получить ответ модели: {exc}"
            store.add_message(conversation_id, "assistant", text)
            yield {"type": "error", "message": text}
            return

        model_name = reply.model or model_name
        usage = reply.usage or usage

        if not reply.tool_calls:
            final_text = (reply.text or "").strip()
            if reply.tool_fallback:
                warnings.append(
                    "Модель не поддерживает вызов инструментов: ответ дан без "
                    "расчётов, числам из него доверять нельзя."
                )
                yield {"type": "warning", "message": warnings[-1]}
            break

        calls = list(reply.tool_calls)
        assistant_message = {
            "role": "assistant",
            "content": reply.text or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.raw_arguments
                        or json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in calls
            ],
        }
        messages.append(assistant_message)

        for call in calls:
            yield {
                "type": "tool_call",
                "id": call.id,
                "name": call.name,
                "arguments": call.arguments,
            }
            call_id = store.add_tool_call(conversation_id, call.name, call.arguments)
            started = time.perf_counter()
            error = ""
            result: dict[str, Any] = {}

            if call.parse_error:
                error = call.parse_error
            elif get_tool(call.name) is None:
                error = f"Инструмента «{call.name}» нет"
            else:
                try:
                    result = await anyio.to_thread.run_sync(
                        execute_tool, context, call.name, call.arguments
                    )
                except ToolArgumentsError as exc:
                    error = str(exc)
                except AIGuardError as exc:
                    error = str(exc)
                except Exception as exc:  # noqa: BLE001 - текст уйдёт модели и человеку
                    error = f"Ошибка инструмента: {exc}"

            duration_ms = int((time.perf_counter() - started) * 1000)
            run_id = result.get("run_id") if isinstance(result, dict) else None
            store.finish_tool_call(
                call_id,
                status="error" if error else "ok",
                error=error,
                run_id=run_id if isinstance(run_id, int) else None,
                duration_ms=duration_ms,
            )

            if error:
                yield {
                    "type": "tool_result",
                    "id": call.id,
                    "name": call.name,
                    "ok": False,
                    "error": error,
                }
                messages.append(_tool_message(call, {"error": error}))
                continue

            collected.append(result)
            summary = run_summary(result) if result.get("run_id") else None
            if summary:
                runs.append(summary)
                yield {
                    "type": "run",
                    "run_id": summary["run_id"],
                    "procedure": summary["procedure"],
                    "title": summary["title"],
                    "n_tables": summary["n_tables"],
                    "warnings": summary["warnings"],
                }
            yield {
                "type": "tool_result",
                "id": call.id,
                "name": call.name,
                "ok": True,
                "run_id": result.get("run_id"),
                "summary": summary,
                "duration_ms": duration_ms,
            }
            messages.append(_tool_message(call, result))

    if not final_text:
        # Шаги кончились, а текста нет: просим модель подвести итог без новых
        # вызовов. Это лучше, чем показать человеку пустой ответ после работы.
        messages.append(
            {
                "role": "user",
                "content": (
                    "Сформулируй итог по уже полученным результатам. Новые "
                    "инструменты не вызывай; если данных не хватает — так и скажи."
                ),
            }
        )
        try:
            reply = await provider.complete(messages, [])
            final_text = (reply.text or "").strip()
            model_name = reply.model or model_name
        except AIProviderError as exc:
            final_text = f"Не удалось сформулировать итог: {exc}"

    if not final_text:
        final_text = (
            "Не удалось получить итоговый ответ. Попробуйте переформулировать "
            "вопрос или задать его по частям."
        )

    unverified = unverified_numbers(final_text, collected)
    if unverified:
        warnings.append(
            "Проверка чисел: не удалось подтвердить расчётом — "
            + ", ".join(unverified[:8])
        )
        yield {"type": "warning", "message": warnings[-1]}

    store.add_message(
        conversation_id,
        "assistant",
        final_text,
        model=model_name,
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
    )

    yield {"type": "text", "text": final_text}
    yield {
        "type": "done",
        "conversation_id": conversation_id,
        "model": model_name,
        "steps": steps,
        "runs": runs,
        "warnings": warnings,
    }


__all__ = ["run_turn"]
