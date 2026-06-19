"""Configuração de conexão — lida do Windows Credential Manager (keyring),
com fallback para variáveis de ambiente / .env.

Prioridade: keyring → env var → default hardcoded.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import keyring
from dotenv import load_dotenv

load_dotenv()

_SERVICE = "procfit"


def _get(key: str, env_var: str, default: str = "") -> str:
    """Lê do Credential Manager; cai para env var se não encontrado."""
    return keyring.get_password(_SERVICE, key) or os.environ.get(env_var) or default


def _get_int(key: str, env_var: str, default: int) -> int:
    raw = _get(key, env_var, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


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
    def load(cls) -> DbConfig:
        """Carrega configuração do Credential Manager (fallback: env var / default)."""
        return cls(
            host=_get("host", "PROCFIT_DB_HOST", "localhost"),
            port=_get_int("port", "PROCFIT_DB_PORT", 1433),
            database_dados=_get("database_dados", "PROCFIT_DB_DADOS", "PBS_NAZARIA_DADOS_DEVELOPER"),
            database_dicionario=_get("database_dicionario", "PROCFIT_DB_DICIONARIO", "PBS_NAZARIA_DICIONARIO_DEVELOPER"),
            user=_get("user", "PROCFIT_DB_USER", ""),
            password=_get("password", "PROCFIT_DB_PASSWORD", ""),
            driver=_get("driver", "PROCFIT_DB_DRIVER", "ODBC Driver 17 for SQL Server"),
            where_extra=_get("where_extra", "PROCFIT_DB_WHERE_EXTRA", ""),
        )

    @classmethod
    def from_env(cls) -> DbConfig:
        """Alias de load() para compatibilidade."""
        return cls.load()


@dataclass(frozen=True)
class ExportConfig:
    """Configurações de exportação."""
    csv_delimiter: str = ";"
    xlsx_sheet_name: str = "Dados"