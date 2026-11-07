"""Аналитические проверки, которые не зависят от ИИ и Qt."""

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
