# Spec CLI — Comandos Typer do procfit-cli

## 1. Estrutura do App

A base é Click (sobre o qual o Typer roda). `list`/`show` usam `@click.command`;
`run` usa a subclasse `DynamicRunCommand` para injetar flags dinâmicas (ver §5).

```python
@click.group(help="CLI para executar consultas do Procfit ERP direto no SQL Server.")
def cli() -> None:
    ...

# entry point: uv run main.py (main.py adiciona src/ ao path e chama
# procfit.presentation.cli:main). O projeto não é instalado como pacote.
```

## 2. Comando: `list`

Lista as consultas da tabela CONSULTAS (nome + descrição). Aceita um
**filtro LIKE** opcional.

```bash
uv run main.py list                       # todas
uv run main.py list "B2B_CLIENTES%"       # NOME começa com B2B_CLIENTES
uv run main.py list "%PAGAMENTO%"         # NOME contém PAGAMENTO
uv run main.py list -d "%cliente%"        # DESCRIÇÃO contém cliente
uv run main.py list "B2B%" -d "%cliente%" # NOME e DESCRIÇÃO (AND)
```

Dois filtros `LIKE` independentes:
- argumento posicional `FILTRO` → `CONSULTA LIKE p`
- opção `-d/--descricao` → `DESCRICAO LIKE p`

Quando ambos são informados, combinam com **AND**
(`WHERE CONSULTA LIKE pn AND DESCRICAO LIKE pd`). Valores escapados como
literal (injection-safe); curinga `%` preservado; case-insensitive conforme a
collation do banco.

**Exemplo de output** (renderizado com `rich`):
```
        Consultas Procfit (filtro: B2B_CLIENTES%)
┌────────────────────────┬───────────────────────┐
│ Consulta               │ Descrição             │
├────────────────────────┼───────────────────────┤
│ B2B_CLIENTES           │ Consulta de Clientes  │
│ B2B_CLIENTES_DETALHES  │ Detalhes Clientes     │
└────────────────────────┴───────────────────────┘
Total: 2 consultas
```

A listagem consulta apenas o banco DADOS (nome + descrição); não lê
`CONSULTAS_PARAMS` nem o corpo SQL.

## 3. Comando: `show`

Mostra detalhes de uma consulta: nome, descrição e parâmetros esperados
(ordenados pela coluna `ORDEM` de `CONSULTAS_PARAMS`).
O **SQL não é exibido por padrão**.

- `-s/--sql` → exibe o SQL **formatado** (rich Syntax) junto dos detalhes
- `--raw` → imprime **apenas o SQL cru** (sem cabeçalho, sem cor), pipeable

```bash
uv run main.py show OL_APURACOES_MARCAS          # nome + descrição + parâmetros
uv run main.py show OL_APURACOES_MARCAS -s       # detalhes + SQL formatado
uv run main.py show OL_APURACOES_MARCAS --raw    # só o SQL cru (pipeable)
uv run main.py show OL_APURACOES_MARCAS --raw > consulta.sql
uv run main.py show OL_APURACOES_MARCAS --raw | sqlcmd ...
```

**Exemplo de output:**
```
Consulta: relatorio_vendas
Descrição: Vendas por período com filtro opcional de cliente
SQL:
  SELECT v.data, v.cliente, v.valor, v.status
  FROM VENDAS v
  WHERE v.data BETWEEN :data_ini AND :data_fim
    AND (:cod_cliente IS NULL OR v.cod_cliente = :cod_cliente)

Parâmetros detectados (3):
  ┌──────────────┬──────────┬─────────────┐
  │ Parâmetro    │ Obrigatório │ Padrão    │
  ├──────────────┼──────────┼─────────────┤
  │ data_ini     │ sim      │ :data_ini   │
  │ data_fim     │ sim      │ :data_fim   │
  │ cod_cliente  │ não      │ :cod_cliente│
  └──────────────┴──────────┴─────────────┘
```

Um parâmetro é **obrigatório** quando o seu `TITULO` (em `CONSULTAS_PARAMS`)
termina em `*` — convenção do Procfit. Sem o `*`, é opcional (omitido → `''`,
semântica Vazio=Todos). Os parâmetros são exibidos na ordem da coluna `ORDEM`.

## 4. Comando: `run` — O Coração

Executa uma consulta com parâmetros **diretamente como flags** e exporta o resultado.

```bash
procfit run relatorio_vendas \
    --data-ini "2024-01-01" \
    --data-fim "2024-12-31" \
    --cod-cliente "123" \
    --format xlsx \
    --output vendas.xlsx
```

### 4.1 De onde vêm os parâmetros?

**Da tabela `CONSULTAS_PARAMS`** (banco do dicionário). Quando o comando `run` é
invocado, o CLI:

1. Lê o nome da consulta dos argumentos
2. Consulta `CONSULTAS_PARAMS WHERE CONSULTA = '<nome>' ORDER BY ORDEM`
3. Pra cada linha (`PARAMETRO`, `TITULO`, `TAMANHO`, `LOOKUP`), gera uma opção
   no formato `--nome-do-parametro`, usando `TITULO` como help text

Os parâmetros são **catalogados** no dicionário — não há regex chutando
placeholders no SQL. A fonte é a tabela, não o texto da query.

A leitura roda em thread com timeout de 5s: se o SQL Server não responder,
o `run` segue mostrando apenas as opções fixas (`--format`, `--output`, etc.).

### 4.2 Mapeamento PARAMETRO → flag

| `PARAMETRO` (CONSULTAS_PARAMS) | Flag CLI |
|---|---|
| `DATA_INI` | `--data-ini` |
| `COD_CLIENTE` | `--cod-cliente` |
| `ANO_REF` | `--ano-ref` |
| `TIPO` | `--tipo` |

Regra: underscore (`_`) vira hífen (`-`), minúsculas, padrão Unix.

Na execução, o valor da flag é substituído no SQL via placeholder `:PARAMETRO`
(maiúsculas, com dois-pontos), feito pelo `ConnectorXExecutor`.

### 4.3 Opções fixas (não vêm do banco)

| Flag | Alias | Descrição | Default |
|------|-------|-----------|---------|
| `--format` | `-f` | Formato de exportação: `csv` ou `xlsx` | `csv` |
| `--output` | `-o` | Caminho do arquivo de saída (**obrigatório**, exceto em `--dry-run`). `-o -` → CSV no stdout (métricas no stderr) | — |
| `--verbose` | `-v` | Log detalhado da execução | `false` |
| `--force` | — | Sobrescreve a saída sem perguntar | `false` |
| `--dry-run` | — | Gera o SQL com os parâmetros substituídos e imprime (não executa) | `false` |

Essas são fixas, fazem parte da CLI, não do banco.

#### `--dry-run` — gerar o SQL parametrizado

Monta o SQL final com os valores das flags substituídos (bind seguro via
SQLAlchemy → literais escapados) e imprime no stdout, sem conectar para
executar nem exportar. Por ser inspeção, **não valida obrigatórios**:
parâmetros omitidos viram `''`. Saída crua, pipeable:

```bash
uv run main.py run OL_APURACOES_MARCAS --data-ini 2024-01-01 --data-fim 2024-12-31 --dry-run
uv run main.py run OL_APURACOES_MARCAS --data-ini 2024-01-01 --dry-run > apuracao.sql
```

### 4.4 Validação

- Se parâmetros obrigatórios faltarem → erro + lista dos faltantes
- Se formato for inválido → erro + `--help`
- Se output já existir → perguntar sobrescrita (ou forçar com `--force`)
- Se consulta não existir → erro + sugestão de `procfit list`

### 4.5 Exemplo de output

Ao final de um `run` real (não `--dry-run`), exibe a linha de sucesso + uma
tabela de **métricas** (rich):

```
✔ Concluído! saida/vendas.xlsx
  Linhas             1.234
  Colunas            8
  Tempo consulta     2.3s
  Tempo exportação   0.4s
  Tempo total        2.7s
  Tamanho            45.2 KB
  Vazão              536 linhas/s
```

As pastas do `--output` são criadas automaticamente se não existirem.
`Ctrl+C` cancela a execução mesmo durante o fetch (exit code 130).

Ou, com `--verbose`:

```
[CONFIG] Host: srv-procfit:1433 / Procfit
[QUERY] SELECT v.data... WHERE v.data BETWEEN :data_ini AND :data_fim
[PARAM] data_ini=2024-01-01, data_fim=2024-12-31
[FETCH] connectorx → arrow → 1.234 rows em 2.3s
[EXPORT] openpyxl write-only → vendas_20250101_120000.xlsx (streaming)
[DONE] 45.2 KB em 0.4s
```

## 5. Geração Dinâmica de Opções (Click)

O coração técnico: como transformar linhas de `CONSULTAS_PARAMS` em flags.

### 5.1 Estratégia: `DynamicRunCommand` (subclasse de `click.Command`)

O `run` usa Click diretamente (base do Typer) para ter acesso ao mecanismo de
parse e injetar opções antes do parse dos argumentos.

`DynamicRunCommand` sobrescreve `parse_args`:

1. Extrai o nome da consulta dos `args` (primeiro token não-opção)
2. Lê `CONSULTAS_PARAMS` daquela consulta (thread + timeout de 5s)
3. Pra cada parâmetro, faz `self.params.append(click.Option([f"--{flag}"], ...))`
4. Delega pro `super().parse_args()`, que agora reconhece as flags injetadas

```python
class DynamicRunCommand(click.Command):
    DB_TIMEOUT = 5  # segundos

    def parse_args(self, ctx, args):
        consulta = self._extract_consulta(args)
        if consulta and self._param_repo:
            self._load_params_threaded(consulta)   # injeta as flags
        return super().parse_args(ctx, args)
```

Vantagem sobre callback Typer: as opções ficam visíveis no `--help` e o parse
nativo do Click valida tudo. Se o banco cair, o timeout libera e o comando
funciona só com as flags fixas.

### 5.2 Efeito no `--help`

```bash
procfit run OL_APURACOES_MARCAS --help
```

Gera (quando o banco está acessível):
```
Usage: procfit run [OPTIONS] CONSULTA

Options:
  --tipo TEXT              1=OL, 2=Normal, 3=Clientes, Vazio=Todos
  --empresa TEXT           Empresa/CD
  --data-ini TEXT          Data Inicial Fat
  --data-fim TEXT          Data Final Fat
  -f, --format [csv|xlsx]  Formato de exportação  [default: csv]
  -o, --output PATH        Arquivo de saída
  -v, --verbose            Modo verboso
  --force                  Sobrescreve a saída sem perguntar
  --help                   Show this message and exit.
```

Note que `--tipo`, `--empresa`, `--data-ini` NÃO são fixos no código —
aparecem porque o `DynamicRunCommand` leu `CONSULTAS_PARAMS` e os injetou.
O help de cada um vem da coluna `TITULO`.

## 6. Tratamento de Erros

| Situação | Comportamento |
|----------|---------------|
| Conexão falhou | `✖ Erro de conexão: [detalhe]` + exit code 1 |
| Consulta não encontrada | `✖ Consulta "x" não encontrada. Use 'procfit list'` + exit 1 |
| Parâmetro obrigatório faltando | `✖ Parâmetros obrigatórios: data_ini, data_fim` + exit 1 |
| Parâmetro extra fornecido (flag que não existe na query) | `⚠ O parâmetro "--foo" não é usado nesta consulta` (warning, ignora) |
| Erro SQL | `✖ Erro na execução: [mensagem do SQL Server]` + exit 3 |
| Falha de escrita | `✖ Erro ao escrever arquivo: [detalhe]` + exit 4 |
| Ctrl+C durante o run | `⚠ Cancelado pelo usuário.` + exit 130 |

## 7. Exit Codes

| Código | Significado |
|--------|-------------|
| 0 | Sucesso |
| 1 | Erro geral (conexão, consulta não encontrada) |
| 2 | Erro de parâmetros (faltando ou inválidos) |
| 3 | Erro de execução SQL |
| 4 | Erro de escrita/exportação |
| 130 | Cancelado pelo usuário (Ctrl+C) |