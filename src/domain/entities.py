"""Domain layer - entidades centrais do negócio."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class QueryParametro:
    """
    Representa um parâmetro de consulta catalogado na tabela CONSULTAS_PARAMS.

    Padrão: Value Object (imutável, sem identidade própria).
    """
    nome: str
    ordem: int
    titulo: str
    tamanho: Optional[int] = None
    lookup: Optional[str] = None

    @property
    def flag_name(self) -> str:
        """Nome no formato CLI: DATA_INI → data-ini."""
        return self.nome.lower().replace("_", "-")

    @property
    def is_required(self) -> bool:
        """Convenção do Procfit: TITULO terminado em '*' indica obrigatório."""
        return bool(self.titulo) and self.titulo.rstrip().endswith("*")


@dataclass
class SqlQuery:
    """
    Representa uma consulta da tabela CONSULTAS.

    Possui identidade (nome) e carrega seus parâmetros.
    """
    nome: str
    sql: str
    descricao: str = ""
    parametros: list[QueryParametro] = field(default_factory=list)