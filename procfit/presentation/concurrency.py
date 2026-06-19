"""Helpers de concorrência: execução com timeout e thread interruptível.

Responsabilidade única: rodar funções bloqueantes em thread daemon, sem
travar o Ctrl+C do usuário.
"""
from __future__ import annotations

import threading
from typing import Callable, TypeVar

T = TypeVar("T")


class TimeoutError_(Exception):
    """Sinaliza que o tempo limite de execução foi excedido."""


def call_with_timeout(func: Callable[[], T], timeout: int = 15) -> T:
    """Executa `func` em thread daemon, abortando após `timeout` segundos."""
    result: list[T] = []
    exception: list[Exception] = []

    def _run() -> None:
        try:
            result.append(func())
        except Exception as e:
            exception.append(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        raise TimeoutError_(f"Timeout de {timeout}s excedido")
    if exception:
        raise exception[0]
    return result[0]


def run_interruptible(func: Callable[[], T]) -> T:
    """Executa `func` em thread daemon mantendo o Ctrl+C responsivo."""
    result: list[T] = []
    exception: list[BaseException] = []

    def _run() -> None:
        try:
            result.append(func())
        except BaseException as e:  # noqa: BLE001
            exception.append(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    while thread.is_alive():
        thread.join(timeout=0.1)

    if exception:
        raise exception[0]
    return result[0]
