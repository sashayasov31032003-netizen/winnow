"""Аналитические проверки, которые не зависят от ИИ и интерфейса."""

from winnow.analysis.quality import (
    QualityIssue,
    QualityReport,
    RegressionQuality,
    VariableQuality,
    quality_report,
)

__all__ = [
    "QualityIssue",
    "QualityReport",
    "RegressionQuality",
    "VariableQuality",
    "quality_report",
]
