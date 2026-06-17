# Spec de Banco de Dados — Conexão e Tabelas Reais

## 1. Topologia — Dois Bancos

O Procfit separa os metadados dos dados em bancos diferentes:

| Banco | Conteúdo | Host (exemplo) |
|-------|----------|----------------|
| `PBS_NAZARIA_DADOS_DEVELOPER` | Dados do ERP, tabela `CONSULTAS` com as queries SQL | mesmo host |
| `PBS_NAZARIA_DICIONARIO_DEVELOPER` | Dicionário, tabela `CONSULTAS_PARAMS` com os parâmetros | mesmo host |

Ambos no mesmo SQL Server, mesma connection string — só muda o database name.

## 2. Conexão SQL Server

### 2.1 DSN ConnectorX

```
mssql://username:password@host:port/database?driver=ODBC+Driver+17+for+SQL+Server
```

A connection string será montada a partir de variáveis de ambiente:

```env
PROCFIT_DB_HOST=localhost
PROCFIT_DB_PORT=1433
PROCFIT_DB_DADOS=PBS_NAZARIA_DADOS_DEVELOPER
PROCFIT_DB_DICIONARIO=PBS_NAZARIA_DICIONARIO_DEVELOPER
PROCFIT_DB_USER=sa
PROCFIT_DB_PASSWORD=segredo...ODBC Driver 17 for SQL Server
```

### 2.2 Config (`infrastructure/config.py`)

```python
@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    database_dados: str       # PBS_NAZARIA_DADOS_DEVELOPER
    database_dicionario: str  # PBS_NAZARIA_DICIONARIO_DEVELOPER
    user: str
    password: str
    driver: str = "ODBC Driver 17 for SQL Server"

    def conn_str(self, database: str) -> str:
        base = f"mssql://{self.user}:{self.password}@{self.host}:{self.port}/{database}"
        return f"{base}?driver={self.driver}"

    @property
    def conn_dados(self) -> str:
        return self.conn_str(self.database_dados)

    @property
    def conn_dicionario(self) -> str:
        return self.conn_str(self.database_dicionario)
```

## 3. Tabela CONSULTAS (`PBS_NAZARIA_DADOS_DEVELOPER`)

```sql
-- Descoberta automática:
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'CONSULTAS'
```

**Colunas mapeadas (configuráveis via .env):**

| Coluna | Tipo | Mapeamento | Descrição |
|--------|------|-----------|-----------|
| `CONSULTA` | varchar | `col_id` | Nome único da consulta (ex: `OL_APURACOES_MARCAS`) |
| `SQL` | ntext | `col_query` | SQL bruto com placeholders (a coluna chama-se `SQL`, **não** `QUERY`) |
| `DESCRICAO` | varchar | `col_desc` | Descrição amigável exibida no `list`/`show` |

Mapeamento via .env (defaults entre parênteses):

```env
PROCFIT_COL_ID=CONSULTA
PROCFIT_COL_QUERY=SQL
PROCFIT_COL_DESC=DESCRICAO
PROCFIT_DB_WHERE_EXTRA=
```

### 3.1 Listagem de Consultas

A listagem traz só nome + descrição (a coluna `SQL` é `ntext`, pesada; o corpo
só é lido no `show`/`run` de uma consulta específica). Suporta filtro `LIKE`:

```sql
SELECT CONSULTA, DESCRICAO FROM CONSULTAS
-- filtros LIKE independentes (nome e/ou descrição); ambos → AND:
SELECT CONSULTA, DESCRICAO FROM CONSULTAS
WHERE CONSULTA LIKE 'B2B%' AND DESCRICAO LIKE '%cliente%'
ORDER BY CONSULTA
```

Retorna:

| CONSULTA | DESCRICAO |
|----------|-----------|
| `OL_APURACOES_MARCAS` | `Apuração de marcas` |
| ... | ... |

## 4. Tabela CONSULTAS_PARAMS (`PBS_NAZARIA_DICIONARIO_DEVELOPER`)

```sql
-- Descoberta automática:
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'CONSULTAS_PARAMS'
```

### 4.1 Schema Confirmado

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `CONSULTA` | varchar | FK para CONSULTAS.CONSULTA |
| `ORDEM` | int | Ordem do parâmetro (10, 20, 30...) |
| `PARAMETRO` | varchar | Nome do parâmetro (ex: `DATA_INI`) |
| `TITULO` | varchar | Descrição amigável pro usuário |
| `TAMANHO` | int | Tamanho máximo (ex: 15) |
| `LOOKUP` | varchar? | Tabela de lookup (ex: `DATA`, `TIPOS_OLS`) |

### 4.2 Consulta de Parâmetros

```sql
SELECT CONSULTA, ORDEM, PARAMETRO, TITULO, TAMANHO, LOOKUP
FROM CONSULTAS_PARAMS
WHERE CONSULTA = 'OL_APURACOES_MARCAS'
ORDER BY ORDEM
```

Retorna:

| CONSULTA | ORDEM | PARAMETRO | TITULO | TAMANHO | LOOKUP |
|----------|-------|-----------|--------|---------|--------|
| OL_APURACOES_MARCAS | 10 | TIPO | 1=OL, 2=Normal, 3=Clientes, Vazio=Todos | 15 | NULL |
| OL_APURACOES_MARCAS | 20 | EMPRESA | Empresa/CD | 15 | NULL |
| OL_APURACOES_MARCAS | 30 | DATA_INI | Data Inicial Fat | 15 | DATA |
| ... | ... | ... | ... | ... | ... |

### 4.3 Mapeamento para a CLI

Cada linha vira uma flag Typer:

| PARAMETRO | Flag CLI | --help mostra |
|-----------|----------|---------------|
| `TIPO` | `--tipo` | `TIPO: 1=OL, 2=Normal, 3=Clientes, Vazio=Todos (lookup: None)` |
| `EMPRESA` | `--empresa` | `EMPRESA: Empresa/CD (lookup: None)` |
| `DATA_INI` | `--data-ini` | `DATA_INI: Data Inicial Fat (lookup: DATA)` |
| `MARCA` | `--marca` | `MARCA: Marcas Separadas por vírgula / Vazio=Todas (lookup: None)` |
| `TIPO_OL` | `--tipo-ol` | `TIPO_OL: Tipo OL Vazio=Todas (lookup: TIPOS_OLS)` |

Regra: `underscore` → `hífen` no nome da flag. O `TITULO` vira a help text.

## 5. Execução com ConnectorX

### 5.1 Bind de Parâmetros (compilado para literal)

ConnectorX **não** suporta bind parameters no driver MSSQL (TDS) — só aceita
uma string SQL completa. Para ter bind seguro mantendo a performance do
connectorx, o `ConnectorXExecutor` usa o **SQLAlchemy apenas como compilador**
(sem engine/conexão): faz o bind nomeado e renderiza o SQL final como literais
escapados pelo dialeto SQL Server, e só então entrega a string ao connectorx.

Os placeholders no SQL da CONSULTAS usam o padrão `:NOME_DO_PARAM` (com dois-pontos),
que corresponde aos nomes em CONSULTAS_PARAMS.PARAMETRO. Variáveis T-SQL (`@var`)
**não** são placeholders e passam intactas.

```python
from sqlalchemy import text
from sqlalchemy.dialects import mssql

def _substituir(sql: str, params: dict[str, str]) -> str:
    stmt = text(sql)
    needed = set(stmt._bindparams.keys())   # :PARAM detectados pelo SQLAlchemy
    if not needed:
        return sql
    # omitido → '' (semântica Vazio=Todos do Procfit)
    binds = {nome: params.get(nome, "") for nome in needed}
    return str(stmt.bindparams(**binds).compile(
        dialect=mssql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))
```

**Por que isso é seguro:** o dialeto escapa cada valor type-aware (aspas simples
dobradas, etc.). Um payload como `'; DROP TABLE x; --` vira o literal inerte
`'''; DROP TABLE x; --'` — texto, nunca SQL executável. Nomes de consulta
(interpolados no `WHERE` de `CONSULTAS`/`CONSULTAS_PARAMS`) passam por whitelist
(`_assert_safe_name`) + escape de literal como defesa em profundidade.

### 5.2 Chamada ConnectorX

```python
def execute(self, nome_consulta: str, params: dict[str, str]) -> pa.Table:
    query = self._carregar_query(nome_consulta)   # SELECT QUERY FROM CONSULTAS WHERE CONSULTA = ?
    final_sql = self._substitute(query.raw_sql, params)
    table = cx.read_sql(
        self.conn_dados,           # ← PBS_NAZARIA_DADOS_DEVELOPER
        final_sql,
        return_type="arrow",
    )
    return table
```

### 5.3 Conexões Diferentes pra Cada Operação

| Operação | Banco | Conn String |
|----------|-------|-------------|
| Listar consultas | `PBS_NAZARIA_DADOS_DEVELOPER` | `conn_dados` |
| Listar parâmetros | `PBS_NAZARIA_DICIONARIO_DEVELOPER` | `conn_dicionario` |
| Executar query | `PBS_NAZARIA_DADOS_DEVELOPER` | `conn_dados` |

## 6. Segurança

- Senha nunca em logs
- Escapamento de aspas simples nos parâmetros (SQL injection prevention)
- .env no `.gitignore`
- Conexão via trusted connection quando disponível