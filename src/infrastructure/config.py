"""Configuração carregada de .env / variáveis de ambiente.

Padrão: Config Object. Centraliza todas as configs em um objeto tipado.
Usa python-dotenv para carregar do .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class DbConfig:
    """Configuração de conexão com os dois bancos SQL Server."""
    host: str
    port: int = 1433
    database_dados: str = "PBS_NAZARIA_DADOS_DEVELOPER"
    database_dicionario: str = "PBS_NAZARIA_DICIONARIO_DEVELOPER"
    user: str = ""
    password: str = ""
    driver: str = "ODBC Driver 17 for SQL Server"

    # Colunas fixas da tabela CONSULTAS
    col_id: str = "CONSULTA"
    col_query: str = "SQL"
    col_desc: str = "DESCRICAO"
    where_extra: str = ""

    def conn_str(self, database: str) -> str:
        """Monta DSN para connectorx no formato mssql://."""
        base = f"mssql://{self.user}:{self.password}@{self.host}:{self.port}/{database}"
        escaped_driver = self.driver.replace(" ", "+")
        return f"{base}?driver={escaped_driver}&connect_timeout=5"

    @property
    def conn_dados(self) -> str:
        return self.conn_str(self.database_dados)

    @property
    def conn_dicionario(self) -> str:
        return self.conn_str(self.database_dicionario)

    @classmethod
    def from_env(cls) -> DbConfig:
        """Factory method: cria DbConfig a partir de variáveis de ambiente."""
        return cls(
            host=os.environ.get("PROCFIT_DB_HOST", "localhost"),
            port=int(os.environ.get("PROCFIT_DB_PORT", "1433")),
            database_dados=os.environ.get("PROCFIT_DB_DADOS", "PBS_NAZARIA_DADOS_DEVELOPER"),
            database_dicionario=os.environ.get("PROCFIT_DB_DICIONARIO", "PBS_NAZARIA_DICIONARIO_DEVELOPER"),
            user=os.environ.get("PROCFIT_DB_USER", ""),
            password=os.environ.get("PROCFIT_DB_PASSWORD", ""),
            driver=os.environ.get("PROCFIT_DB_DRIVER", "ODBC Driver 17 for SQL Server"),
            where_extra=os.environ.get("PROCFIT_DB_WHERE_EXTRA", ""),
        )


@dataclass(frozen=True)
class ExportConfig:
    """Configurações de exportação."""
    csv_delimiter: str = ";"
    xlsx_sheet_name: str = "Dados"