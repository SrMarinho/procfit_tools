# Plano: CLI Moderna para Procfit ERP

## 1. Visão Geral

Criar uma CLI moderna que se conecta diretamente ao banco SQL Server do Procfit ERP,
lê as consultas armazenadas na tabela `CONSULTAS`, detecta parâmetros dinamicamente,
permite execução com substituição de parâmetros, e exporta resultados via stream
para CSV/XLSX.

**Stack:** Python 3.11+ · uv · Typer · python-dotenv · connectorx · pyarrow

## 2. Arquitetura — Layered (Camadas)

```
┌─────────────────────────────────────┐
│         presentation/cli.py         │  ← Typer CLI (entrada do usuário)
├─────────────────────────────────────┤
│           application/              │  ← Casos de uso (orquestração)
│            use_cases.py             │
├─────────────────────────────────────┤
│             domain/                 │  ← Entidades, regras de negócio
│    entities.py · interfaces.py      │
├─────────────────────────────────────┤
│          infrastructure/            │  ← DB, exportadores, detectores
│  database.py · exporters.py · ...   │
└─────────────────────────────────────┘
```

**Fluxo de dados:**
1. CLI recebe comando + parâmetros
2. Use case orquestra: carrega query → detecta params → substitui → executa → exporta
3. Infra cuida do banco (connectorx + arrow_fetch) e escrita em disco (stream)

## 3. Estrutura de Diretórios

```
procfit_tools/
├── docs/
│   └── plans/
│       ├── plano-cli-procfit.md         ← este arquivo
│       ├── spec-arquitetura.md           ← especificação das camadas
│       ├── spec-banco.md                 ← esquema CONSULTAS + conexão
│       └── spec-cli.md                   ← comandos Typer
├── src/                          # pacote (importado como `src`), não instalado
│   ├── __init__.py
│   ├── __main__.py               # python -m src
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── entities.py           # SqlQuery, QueryParametro
│   │   ├── enums.py              # ExportFormato
│   │   └── interfaces.py         # QueryRepository, ParametroRepository, QueryExecutor, Exporter
│   ├── application/
│   │   ├── __init__.py
│   │   ├── dto.py                # ConsultaDto, ConsultaDetalheDto, ResultadoDto
│   │   └── use_cases.py          # Listar, Descrever, Executar
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── config.py             # DbConfig, ExportConfig
│   │   ├── database.py           # SqlServerQueryRepo, SqlServerParamRepo, ConnectorXExecutor
│   │   └── exporters.py          # CsvExporter, XlsxExporter
│   └── presentation/
│       ├── __init__.py
│       └── cli.py                # Click group + DynamicRunCommand
├── tests/
│   ├── __init__.py
│   ├── test_domain.py            # repos + ConnectorXExecutor + QueryParametro
│   ├── test_use_cases.py
│   └── test_exporters.py
├── main.py                       # entry point: uv run main.py
├── pyproject.toml
├── .env.example
└── README.md
```

> Nota: não há `parameter_detector.py` nem `value_objects.py`. Os parâmetros vêm
> catalogados de `CONSULTAS_PARAMS` (ver §5), não de regex sobre o SQL.

## 4. Fases de Implementação

### Fase 1 — Fundação (projeto + domínio)
- `uv init`, `pyproject.toml` com deps
- Entidades: `SqlQuery`, `QueryParameter`, `QueryResult`
- Interface do repositório (`QueryRepository`)
- Value objects: `ExportFormat`, `ConnectionConfig`

### Fase 2 — Infraestrutura
- **database.py**: `SqlServerQueryRepo` (lê CONSULTAS), `SqlServerParamRepo` (lê
  CONSULTAS_PARAMS), `ConnectorXExecutor` (substitui placeholders + executa)
- **exporters.py**: CSV streaming (`csv.writer` por batch), XLSX streaming (`openpyxl write-only`)
- **config.py**: carregar `.env` com variáveis de conexão (`DbConfig`, `ExportConfig`)

### Fase 3 — Casos de Uso
- `ListQueriesUseCase` — lista consultas disponíveis
- `DescribeQueryUseCase` — mostra parâmetros de uma consulta
- `ExecuteAndExportUseCase` — executa + exporta em streaming

### Fase 4 — CLI (Typer)
- `procfit list` — lista consultas
- `procfit show <nome>` — mostra detalhes + parâmetros esperados
- `procfit run <nome> [--param key=value ...] [--format csv|xlsx] [--output arquivo]`

### Fase 5 — Testes + Ajustes
- Testes unitários dos repositórios + `ConnectorXExecutor` (connectorx mockado)
- Testes dos use cases com repositórios mockados
- Testes de exportação CSV/XLSX com dados simulados

## 5. Parâmetros — Estratégia (catálogo, não regex)

Os parâmetros de cada consulta são **catalogados** na tabela `CONSULTAS_PARAMS`
(banco do dicionário). O CLI não advinha placeholders no SQL — ele lê a tabela.

Pra cada linha de `CONSULTAS_PARAMS` (`PARAMETRO`, `ORDEM`, `TITULO`, `TAMANHO`,
`LOOKUP`), o `DynamicRunCommand` injeta uma flag `--parametro`:

| `PARAMETRO` | Flag CLI | help (`TITULO`) |
|-------------|----------|-----------------|
| `DATA_INI` | `--data-ini` | Data Inicial Fat |
| `EMPRESA` | `--empresa` | Empresa/CD |
| `TIPO` | `--tipo` | 1=OL, 2=Normal, Vazio=Todos |

Na execução, o valor vira `:PARAMETRO` no SQL via `ConnectorXExecutor._substituir`
(connectorx não suporta bind params no MSSQL). Detalhes em `spec-banco.md §5`.

## 6. Exportação Streaming — Estratégia

- **CSV**: `csv.writer` escrevendo linha a linha em um `BufferedWriter` (~não carrega tudo na RAM)
- **XLSX**: `openpyxl` modo `write_only=True` — dados vão direto pro disco
- **Stream**: a lib `connectorx` com `return_type="arrow"` devolve um `pyarrow.Table`.
  Iteramos sobre as batches do Arrow e escrevemos sem materializar tudo em pandas.

## 7. Decisões Técnicas

| Decisão | Justificativa |
|---------|---------------|
| connectorx + arrow_fetch | Conexão direta ao SQL Server, performance via Rust, zero ORM overhead, arrow como formato intermediário eficiente |
| Typer vs Click | Typer usa type hints, gera --help automático, perfeito para CLI parameterizada |
| Layered Architecture | Separa responsabilidades, permite adicionar outras interfaces (API, GUI) sem tocar no domínio |
| UV | Gerenciamento moderno, rápido, compatível com pyproject.toml |
| .env | Senhas/credenciais fora do repositório |
| streaming write | Essencial para consultas grandes — sem streaming uma query de 5M linhas derruba a RAM |

## 8. Riscos e Mitigações

| Risco | Mitigação |
|-------|-----------|
| connectorx não suportar MSSQL parameterized | ConnectorX suporta SQL Server via `mssql://` DSN. Parâmetros serão substituídos na string SQL antes de passar ao connectorx |
| Banco do dicionário offline ao rodar `run` | Leitura de CONSULTAS_PARAMS em thread com timeout de 5s; segue só com flags fixas |
| XLSX stream pode ser limitado | openpyxl write-only resolve para até ~1M linhas. Acima disso, CSV é a recomendação |
| Nome de parâmetro com underscore vs hífen | CLI converterá `_` para `-` automaticamente (padrão Typer) |