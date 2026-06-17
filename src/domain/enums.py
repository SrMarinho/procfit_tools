"""Enums do domínio."""
from __future__ import annotations

from enum import Enum


class ExportFormato(Enum):
    """Formatos de exportação suportados."""
    CSV = "csv"
    XLSX = "xlsx"

    @classmethod
    def from_str(cls, value: str) -> ExportFormato:
        try:
            return cls(value.lower())
        except ValueError:
            formats = ", ".join(e.value for e in cls)
            raise ValueError(f"Formato inválido '{value}'. Use: {formats}")

    @property
    def extension(self) -> str:
        return self.value