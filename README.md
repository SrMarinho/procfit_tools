# Procfit CLI

CLI moderna para executar consultas do **Procfit ERP** direto no SQL Server, sem
o desktop legado. Lê as consultas catalogadas nas tabelas `CONSULTAS` /
`CONSULTAS_PARAMS`, expõe os parâmetros como flags e exporta o resultado em
**CSV** ou **XLSX** via streaming (sem materializar tudo na RAM).

## Stack

Python 3.11+ · [uv](https://github.com/astral-sh/uv) · Click/Typer ·
connectorx + pyarrow (Arrow fetch) · openpyxl (XLSX write-only) · python-dotenv

## Arquitetura

Layered (4 camadas):

```
presentation/   CLI (Click) — entrada do usuário
application/    use cases (orquestração) + DTOs
domain/         entidades, enums, interfaces (ports)
infrastructure/ SQL Server (connectorx), exporters, config
```

## Instalação

O projeto não é instalado como pacote — roda direto da árvore de fontes.

```bash
uv sync                # instala as dependências no venv
cp .env.example .env   # preencha host, usuário e senha
```

## Configuração

Variáveis lidas do `.env` (ver `.env.example`):

| Variável | Default | Descrição |
|----------|---------|-----------|
| `PROCFIT_DB_HOST` | `localhost` | Host do SQL Server |
| `PROCFIT_DB_PORT` | `1433` | Porta |
| `PROCFIT_DB_DADOS` | `PBS_NAZARIA_DADOS_DEVELOPER` | Banco das consultas (`CONSULTAS`) |
| `PROCFIT_DB_DICIONARIO` | `PBS_NAZARIA_DICIONARIO_DEVELOPER` | Banco do dicionário (`CONSULTAS_PARAMS`) |
| `PROCFIT_DB_USER` / `PROCFIT_DB_PASSWORD` | — | Credenciais |
| `PROCFIT_DB_DRIVER` | `ODBC Driver 17 for SQL Server` | Driver ODBC |
| `PROCFIT_COL_ID` / `PROCFIT_COL_QUERY` | `CONSULTA` / `QUERY` | Mapeamento de colunas |

## Uso

Invocação via `main.py` (entry point que adiciona `src/` ao path e chama
`procfit.presentation.cli:main`):

```bash
# Lista todas as consultas (com contagem de parâmetros e lookups)
uv run main.py list

# Detalha uma consulta: SQL + parâmetros esperados
uv run main.py show OL_APURACOES_MARCAS

# Executa e exporta. Os parâmetros viram flags dinâmicas vindas do banco.
uv run main.py run OL_APURACOES_MARCAS \
    --data-ini 2024-01-01 \
    --data-fim 2024-12-31 \
    --format xlsx \
    --output apuracao.xlsx
```

Flags fixas do `run`:

| Flag | Alias | Default | Descrição |
|------|-------|---------|-----------|
| `--format` | `-f` | `csv` | `csv` ou `xlsx` |
| `--output` | `-o` | `<consulta>_<timestamp>.<ext>` | Arquivo de saída |
| `--verbose` | `-v` | `false` | Logs de debug |
| `--force` | — | `false` | Sobrescreve a saída sem perguntar |

As demais flags (`--data-ini`, `--empresa`, …) são **injetadas em runtime** a
partir de `CONSULTAS_PARAMS`. Se o banco estiver inacessível, apenas as flags
fixas aparecem (timeout de 5s, sem travar).

## Exit codes

| Código | Significado |
|--------|-------------|
| 0 | Sucesso |
| 1 | Erro de conexão / consulta não encontrada |
| 2 | Erro de parâmetros (faltando ou inválidos) |
| 3 | Erro de execução SQL |
| 4 | Erro de escrita/exportação |

## Testes

```bash
uv run pytest
```

## Documentação

Specs e plano de design em [`docs/plans/`](docs/plans/):

| Doc | Conteúdo |
|-----|----------|
| [plano-cli-procfit.md](docs/plans/plano-cli-procfit.md) | Visão geral, arquitetura layered, fases de implementação |
| [spec-arquitetura.md](docs/plans/spec-arquitetura.md) | Camadas, interfaces (ports), fluxo de dados, estrutura final |
| [spec-banco.md](docs/plans/spec-banco.md) | Topologia dos 2 bancos, tabelas `CONSULTAS` / `CONSULTAS_PARAMS`, substituição de placeholders |
| [spec-cli.md](docs/plans/spec-cli.md) | Comandos `list`/`show`/`run`, flags dinâmicas (`DynamicRunCommand`), exit codes |

Progresso em [`docs/progress/`](docs/progress/).
