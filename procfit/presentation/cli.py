"""Compatibilidade: ponto de entrada estável `procfit.presentation.cli:main`.

A implementação foi fatiada em módulos coesos (app, container, rendering,
concurrency, commands/*). Este shim preserva o entry point histórico.
"""
from __future__ import annotations

from procfit.presentation.app import app, main

__all__ = ["app", "main"]


if __name__ == "__main__":
    main()
