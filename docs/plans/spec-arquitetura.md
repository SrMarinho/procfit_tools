# Spec de Arquitetura — procfit-cli

## 1. Princípios

- **Separação de responsabilidades** (layered architecture)
- **Inversão de dependência**: domínio não depende de infra
- **Imutabilidade** onde possível (dataclasses frozen)
- **Type hints** rigorosos (Python typing + `mypy --strict` ready)
- **Zero estado global**: config, db, tudo injetado

## 2. Camadas

### 2.1 Domain Layer (`src/domain/`)

Núcleo do negócio, sem dependências externas. Apenas Python stdlib.

**Entities:**

```python
@dataclass(frozen=True)
class QueryParametro:
    nome: str              # ex: "DATA_INI"
    ordem: int             # ex: 30
    titulo: str            # ex: "Data Inicial Fat"
    tamanho: int | None    # ex: 15
    lookup: str | None     # ex: "DATA", "TIPOS_OLS", None

@dataclass
class SqlQuery:
    nome: str              # ex: "OL_APURACOES_MARCAS"
    sql: str               # SQL com placeholders :PARAM (vazio na listagem)
    descricao: str = ""    # coluna DESCRICAO da CONSULTAS
    parametros: list[QueryParametro] = field(default_factory=list)  # da CONSULTAS_PARAMS
```

**Enums:**

```python
class ExportFormato(Enum):
    CSV = "csv"
    XLSX = "xlsx"
```

**Interfaces (ports):**

```python
class QueryRepository(ABC):
    """Acesso à tabela CONSULTAS (PBS_NAZARIA_DADOS_DEVELOPER)"""
    @abstractmethod
    def listar(self) -> list[SqlQuery]: ...
    @abstractmethod
    def buscar(self, nome: str) -> SqlQuery | None: ...

class ParametroRepository(ABC):
    """Acesso à tabela CONSULTAS_PARAMS (PBS_NAZARIA_DICIONARIO_DEVELOPER)"""
    @abstractmethod
    def listar_por_consulta(self, nome_consulta: str) -> list[QueryParametro]: ...

class QueryExecutor(ABC):
    """Execução de SQL no banco de dados"""
    @abstractmethod
    def executar(self, sql: str, params: dict[str, str]) -> pa.Table: ...

class Exporter(ABC):
    """Exportação de Arrow Table para arquivo"""
    @abstractmethod
    def exportar(self, table: pa.Table, output: Path) -> int: ...  # return row count
```

### 2.2 Application Layer (`src/application/`)

Casos de uso, depende apenas de `domain` e `dto`.

```python
class ListarConsultasUseCase:
    """Lista as consultas (nome + descrição), com filtro LIKE opcional"""
    def __init__(self, repo: QueryRepository): ...
    def execute(self, filtro: str | None = None) -> list[ConsultaDto]: ...

class DescreverConsultaUseCase:
    """Detalhes de uma consulta + seus parâmetros"""
    def __init__(self, repo: QueryRepository, param_repo: ParametroRepository): ...
    def execute(self, nome: str) -> ConsultaDetalheDto | None: ...

class ExecutarConsultaUseCase:
    """Executa + exporta com streaming"""
    def __init__(self, repo: QueryRepository, param_repo: ParametroRepository,
                 executor: QueryExecutor, exporters: dict[ExportFormato, Exporter]): ...
    def execute(self, nome: str, params: dict[str, str],
                formato: ExportFormato, output: Path) -> ResultadoDto: ...
```

### 2.3 Infrastructure Layer (`src/infrastructure/`)

Implementações concretas das interfaces do domínio.

| Classe | Interface | Descrição |
|--------|-----------|-----------|
| `SqlServerQueryRepo` | `QueryRepository` | Lê CONSULTAS via connectorx em `PBS_NAZARIA_DADOS_DEVELOPER` |
| `SqlServerParamRepo` | `ParametroRepository` | Lê CONSULTAS_PARAMS via connectorx em `PBS_NAZARIA_DICIONARIO_DEVELOPER` |
| `ConnectorXExecutor` | `QueryExecutor` | Substitui placeholders e executa via connectorx |
| `CsvExporter` | `Exporter` | Streaming CSV (`csv.writer` em buffer) |
| `XlsxExporter` | `Exporter` | Streaming XLSX (`openpyxl write_only`) |
| `EnvConfig` | — | Carrega `.env` com `python-dotenv` |

**Não há mais `ParameterDetector`** — os parâmetros vêm prontos da `CONSULTAS_PARAMS`.

### 2.4 Presentation Layer (`src/presentation/cli.py`)

Typer app com comandos. Responsabilidades:
- Parsear args/opts
- Para `run`: ler CONSULTAS_PARAMS e gerar flags dinamicamente
- Chamar use cases
- Exibir output no terminal (tabelas, mensagens de erro)
- Invocar exportação

## 3. Fluxo Completo

```
usuário: procfit run OL_APURACOES_MARCAS --tipo "1" --empresa "01" --data-ini "2024-01-01" --data-fim "2024-12-31" -f xlsx -o marcas.xlsx

1. CLI parseia → nome="OL_APURACOES_MARCAS"
2. CLI detecta parâmetros:
   2a. ParametroRepository.listar_por_consulta("OL_APURACOES_MARCAS")
   2b. Gera flags --tipo, --empresa, --data-ini, --data-fim, etc.
   2c. Parseia sys.argv pra extrair valores dessas flags
3. ExecutarConsultaUseCase.execute(nome, params, formato, output):
   3a. QueryRepository.buscar("OL_APURACOES_MARCAS") → SqlQuery com SQL
   3b. Valida params fornecidos vs obrigatórios
   3c. QueryExecutor.executar(sql, {"TIPO": "1", "EMPRESA": "01", ...}) → pa.Table
   3d. exporters[ExportFormato.XLSX].exportar(table, Path("marcas.xlsx"))
4. CLI exibe: "✓ Concluído! marcas.xlsx (1.234 linhas)"
```

## 4. Estrutura de Diretórios Final

```
src/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── entities.py         # SqlQuery, QueryParametro
│   ├── enums.py            # ExportFormato
│   └── interfaces.py       # QueryRepository, ParametroRepository, etc.
├── application/
│   ├── __init__.py
│   ├── dto.py              # ConsultaDto, ConsultaDetalheDto, ResultadoDto
│   └── use_cases.py        # ListarConsultas, DescreverConsulta, ExecutarConsulta
├── infrastructure/
│   ├── __init__.py
│   ├── config.py           # EnvConfig, DbConfig
│   ├── database.py         # SqlServerQueryRepo, SqlServerParamRepo, ConnectorXExecutor
│   └── exporters.py        # CsvExporter, XlsxExporter
└── presentation/
    ├── __init__.py
    └── cli.py              # Typer app
```

## 5. Comparativo: Antes vs Depois da Descoberta

| Aspecto | Antes (chute) | Depois (real) |
|---------|--------------|---------------|
| Fonte dos parâmetros | Regex no SQL | Tabela `CONSULTAS_PARAMS` |
| Metadados | Nenhum | Título, tamanho, lookup, ordem |
| Precisão | Média (placeholders variam) | Alta (dados catalogados) |
| Complexity | `ParameterDetector` removido | `ParametroRepository` adicionado |
| Bancos | 1 | 2 (dados + dicionário) |