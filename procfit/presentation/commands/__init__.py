"""Comandos da CLI — um módulo por responsabilidade.

Cada módulo expõe `register(app)` (Typer) ou `build_*` (Click), evitando
import circular com o app raiz.
"""
