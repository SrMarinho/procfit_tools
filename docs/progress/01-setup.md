# Passo 1: Setup do Projeto

## O que foi feito

Inicialização do projeto Python com `uv init` e configuração do `pyproject.toml`
com todas as dependências.

## Comandos executados

```bash
cd /c/Users/matheus.silva/Documents/projects/procfit_tools
uv init --name procfit --python 3.11
uv add typer python-dotenv connectorx pyarrow openpyxl
```

## Estrutura criada

```
procfit_tools/
├── pyproject.toml
├── src/
│   └── procfit/
│       └── __init__.py
└── .gitignore
```

## Dependências

| Pacote | Finalidade |
|--------|-----------|
| typer | CLI framework (baseado em Click) |
| python-dotenv | Carregar .env com credenciais |
| connectorx | Conexão de altíssima performance ao SQL Server + arrow_fetch |
| pyarrow | Formato intermediário de dados (zero-copy) |
| openpyxl | Exportação XLSX em modo streaming (write_only) |