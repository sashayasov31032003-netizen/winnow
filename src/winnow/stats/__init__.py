"""Движок статистических процедур Winnow."""

from winnow.stats.command import (
    Command,
    CommandError,
    CorrelationsCommand,
    CrosstabsCommand,
    DescriptivesCommand,
    FrequenciesCommand,
    TTestCommand,
)
from winnow.stats.engine import REGISTRY, REGISTRY_BY_KEY, ProcedureInfo, execute
from winnow.stats.result import Column, Result, Table

__all__ = [
    "REGISTRY",
    "REGISTRY_BY_KEY",
    "Column",
    "Command",
    "CommandError",
    "CorrelationsCommand",
    "CrosstabsCommand",
    "DescriptivesCommand",
    "FrequenciesCommand",
    "ProcedureInfo",
    "Result",
    "Table",
    "TTestCommand",
    "execute",
]
