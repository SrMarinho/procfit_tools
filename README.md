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
presentation/   CLI — entrada do usuário
  app.py          monta o app Typer, registra comandos, expõe main()
  cli.py          shim de compatibilidade (entry point histórico)
  container.py    composition root (DI manual / Factory)
  rendering.py    consoles Rich, métricas, preview
  concurrency.py  timeout / thread interruptível
  commands/       um módulo por comando: config, health, listing, details, run
application/    use cases (orquestração) + DTOs
domain/         entidades, enums, interfaces (ports)
infrastructure/ SQL Server (connectorx), exporters, config
```

A camada de apresentação é fatiada por responsabilidade (SRP): cada comando
vive no próprio módulo, o wiring de dependências fica no `container.py` e a
renderização/concorrência são reutilizáveis e isoladas.

## Instalação

### Com uv (recomendado)

```powershell
# Instalar uv (Windows — caso ainda não tenha)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
uv tool install .      # instala o comando `procfit` globalmente
```

Para desenvolvimento (roda direto da árvore de fontes):

```bash
uv sync                # instala as dependências no venv
uv run main.py --help
```

### Sem uv (pip puro)

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -e .
procfit --help
```

Em ambos os casos, copie o `.env.example` se quiser usar fallback via variáveis de ambiente:

```bash
cp .env.example .env
```

## Configuração

As credenciais são armazenadas no **Windows Credential Manager** (criptografado
pelo SO). Configure via CLI:

```bash
procfit config set          # prompt interativo para todos os campos
procfit config set --host 172.25.48.210 --user sa   # flags para campos não-sensíveis
                                                     # senha sempre via prompt mascarado
procfit config show         # exibe configuração atual (senha mascarada)
```

**Prioridade de leitura:** Credential Manager → variável de ambiente → default hardcoded.

Fallback via variáveis de ambiente (`.env` também é lido — ver `.env.example`):

| Variável | Default | Descrição |
|----------|---------|-----------|
| `PROCFIT_DB_HOST` | `localhost` | Host do SQL Server |
| `PROCFIT_DB_PORT` | `1433` | Porta |
| `PROCFIT_DB_DADOS` | `PBS_NAZARIA_DADOS_DEVELOPER` | Banco das consultas (`CONSULTAS`) |
| `PROCFIT_DB_DICIONARIO` | `PBS_NAZARIA_DICIONARIO_DEVELOPER` | Banco do dicionário (`CONSULTAS_PARAMS`) |
| `PROCFIT_DB_USER` / `PROCFIT_DB_PASSWORD` | — | Credenciais |
| `PROCFIT_DB_DRIVER` | `ODBC Driver 17 for SQL Server` | Driver ODBC |

## Uso

Invocação via `main.py` (dev) ou `procfit` (instalado):

```bash
# Lista nome + descrição. Filtro LIKE opcional (estilo SQL Server):
uv run main.py list                          # todas
uv run main.py list "B2B%"                   # NOME LIKE 'B2B%'
uv run main.py list -d "%cliente%"           # DESCRICAO LIKE '%cliente%'
uv run main.py list "B2B%" -d "%cliente%"    # ambos (AND)

# Detalha uma consulta: nome + descrição + parâmetros (ordenados por ORDEM).
# O SQL não aparece por padrão.
uv run main.py show OL_APURACOES_MARCAS          # detalhes + parâmetros
uv run main.py show OL_APURACOES_MARCAS -s       # + SQL formatado
uv run main.py show OL_APURACOES_MARCAS --raw    # só o SQL cru (pipeable)

# Executa e exporta. Os parâmetros viram flags dinâmicas vindas do banco.
uv run main.py run OL_APURACOES_MARCAS \
    --data-ini 2024-01-01 \
    --data-fim 2024-12-31 \
    --format xlsx \
    --output saida/apuracao.xlsx

# Sem -o: resultados como tabela no terminal (preview, até 100 linhas).
uv run main.py run VENDEDORES --inativos N

# CSV cru no stdout (pipeable); métricas vão pro stderr.
uv run main.py run VENDEDORES --inativos N --stdout > vendedores.csv

# Gera o SQL final com os parâmetros substituídos, sem executar (pipeable):
uv run main.py run OL_APURACOES_MARCAS --data-ini 2024-01-01 --dry-run > q.sql
```

Flags fixas do `run`:

| Flag | Alias | Default | Descrição |
|------|-------|---------|-----------|
| `--format` | `-f` | `csv` | `csv` ou `xlsx` |
| `--output` | `-o` | — | Arquivo de saída (pastas criadas se não existirem). **Sem `-o`, os resultados aparecem como tabela no terminal** (preview, até 100 linhas) |
| `--stdout` | — | `false` | Imprime o CSV cru no stdout (pipeable); status e métricas vão pro stderr |
| `--verbose` | `-v` | `false` | Logs de debug |
| `--force` | — | `false` | Sobrescreve a saída sem perguntar |
| `--dry-run` | — | `false` | Gera o SQL parametrizado e imprime, sem executar (não valida obrigatórios) |

As demais flags (`--data-ini`, `--empresa`, …) são **injetadas em runtime** a
partir de `CONSULTAS_PARAMS`. Se o banco estiver inacessível, apenas as flags
fixas aparecem (timeout de 5s, sem travar).

**Parâmetros obrigatórios:** convenção do Procfit — `TITULO` terminado em `*`
em `CONSULTAS_PARAMS` marca o parâmetro como obrigatório. O `run` valida e
aborta listando os faltantes (o `--dry-run` não valida).

**Métricas:** ao final de um `run` real (não `--dry-run`) é exibida uma tabela
com linhas, colunas, tempo de consulta, tempo de exportação, tempo total,
tamanho do arquivo e vazão (linhas/s).

**Cancelamento:** `Ctrl+C` interrompe o `run` mesmo durante o fetch (sai com
código 130).

## Exit codes

| Código | Significado |
|--------|-------------|
| 0 | Sucesso |
| 1 | Erro de conexão / consulta não encontrada |
| 2 | Erro de parâmetros (faltando ou inválidos) |
| 3 | Erro de execução SQL |
| 4 | Erro de escrita/exportação |
| 130 | Cancelado pelo usuário (Ctrl+C) |

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
