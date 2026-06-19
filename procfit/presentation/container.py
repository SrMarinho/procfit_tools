"""Composition root: monta o grafo de dependências (DI manual).

Padrão Factory: centraliza a construção de repositórios, executor, exporters
e casos de uso, mantendo os comandos livres de detalhes de infraestrutura.
"""
from __future__ import annotations

import logging

from procfit.application.use_cases import (
    DescreverConsultaUseCase,
    ExecutarConsultaUseCase,
    ListarConsultasUseCase,
)
from procfit.domain.enums import ExportFormato
from procfit.infrastructure.config import DbConfig, ExportConfig
from procfit.infrastructure.database import (
    ConnectorXExecutor,
    SqlServerCampoRepo,
    SqlServerParamRepo,
    SqlServerQueryRepo,
)
from procfit.infrastructure.exporters import CsvExporter, XlsxExporter


def init_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")


class Components:
    """Agrega as dependências de infraestrutura construídas a partir do DbConfig."""

    def __init__(self, db_cfg: DbConfig | None = None) -> None:
        cfg = db_cfg or DbConfig.load()
        export_cfg = ExportConfig()
        self.query_repo = SqlServerQueryRepo(cfg)
        self.param_repo = SqlServerParamRepo(cfg)
        self.campo_repo = SqlServerCampoRepo(cfg)
        self.executor = ConnectorXExecutor(cfg)
        self.exporters = {
            ExportFormato.CSV: CsvExporter(delimiter=export_cfg.csv_delimiter),
            ExportFormato.XLSX: XlsxExporter(sheet_name=export_cfg.xlsx_sheet_name),
        }

    def listar_uc(self) -> ListarConsultasUseCase:
        return ListarConsultasUseCase(self.query_repo)

    def descrever_uc(self) -> DescreverConsultaUseCase:
        return DescreverConsultaUseCase(self.query_repo, self.param_repo)

    def executar_uc(self) -> ExecutarConsultaUseCase:
        return ExecutarConsultaUseCase(
            self.query_repo, self.param_repo, self.executor, self.exporters, self.campo_repo
        )
