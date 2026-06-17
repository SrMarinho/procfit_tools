"""Data Transfer Objects — comunicação entre camadas.

Padrão: DTO. Desacopla as camadas: a apresentação troca DTOs com a aplicação,
nunca expõe entidades do domínio diretamente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ParametroDto:
    nome: str
    flag: str
    titulo: str
    ordem: int
    obrigatorio: bool
    lookup: Optional[str] = None


@dataclass(frozen=True)
class ConsultaDto:
    """Resumo para listagem."""
    nome: str
    descricao: str


@dataclass(frozen=True)
class ConsultaDetalheDto:
    """Detalhes completos para o comando show."""
    nome: str
    sql: str = ""
    descricao: str = ""
    parametros: list[ParametroDto] = field(default_factory=list)


@dataclass(frozen=True)
class ResultadoDto:
    """Resultado da execução + exportação."""
    arquivo: str
    linhas: int
    tempo_segundos: float
    formato: str