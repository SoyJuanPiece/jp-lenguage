"""Modo turbo de JP: evaluación completa del programa EN TIEMPO DE COMPILACIÓN.

La idea (la misma de `constexpr` en C++ y del plegado agresivo de constantes):
si un programa no depende de entradas (teclado, red, archivos, azar), su
resultado es siempre el mismo. Entonces el compilador lo ejecuta UNA vez,
cachea la salida, y cada ejecución posterior se reduce a imprimirla.

Es la optimización definitiva: no hacer más rápido el trabajo, sino no
hacerlo. El costo se paga una sola vez (la primera ejecución); las siguientes
son microsegundos. Si el programa usa algo impuro (leer, http, archivos,
azar...), el modo turbo se rinde con gracia y corre en la VM normal.

Cache: junto al archivo se guarda un .jpc con {hash, salida}. El hash cubre
el código fuente y la versión de JP.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from contextlib import redirect_stdout

from . import __version__
from .errores import ErrorEjecucion, ErrorJP
from .lexer import tokenizar
from .parser import parsear
from .vm import MaquinaVM

# Nativas que hacen al programa impuro: dependen del mundo exterior o del
# tiempo. Si el programa las usa (directa o indirectamente), el turbo no
# aplica y se ejecuta en la VM normal.
_NATIVAS_IMPURAS = {
    "leer",            # teclado
    "azar",            # azar
    "http_get", "http_post", "telegram_leer", "telegram_responder",  # red
    "leer_archivo", "escribir_archivo", "agregar_archivo",           # archivos
    "lista_archivos", "tamano_archivo", "existe_archivo",
    "esperar",         # tiempo
}


def _cache_path(ruta: str) -> str:
    return ruta + ".jpc"


# Memo en memoria del proceso: hash -> (salida, error). El disco es para
# entre sesiones; esto es para corridas repetidas dentro del mismo proceso
# (tests, servidores, REPL), donde el hit cuesta microsegundos.
_MEMO: dict[str, tuple[str, bool, str]] = {}


def _hash_fuente(fuente: str) -> str:
    semilla = f"jp:{__version__}:{fuente}"
    return hashlib.sha256(semilla.encode("utf-8")).hexdigest()


class _DetectorImpuras:
    """Envoltorio del entorno global: registra si se llaman nativas impuras."""

    def __init__(self, globals_dict: dict):
        self.globals = globals_dict
        self.impura_usada = False
        self.cual = ""

    def get(self, nombre, _default=None):
        valor = self.globals.get(nombre, _default)
        if nombre in _NATIVAS_IMPURAS and valor is not None:
            self.impura_usada = True
            self.cual = nombre
        return valor

    def __contains__(self, nombre):
        return nombre in self.globals

    def __getitem__(self, nombre):
        return self.get(nombre)

    def __setitem__(self, nombre, valor):
        self.globals[nombre] = valor


def ejecutar_turbo(ruta: str, fuente: str) -> bool:
    """Ejecuta con cache total: 1ª vez compila y corre; siguientes, imprime.

    Devuelve True si no hubo errores (igual que ejecutar_fuente del CLI).
    Imprime en stderr por qué se cayó al modo normal cuando pasa.
    """
    import sys

    hash_actual = _hash_fuente(fuente)
    cache = _cache_path(ruta)

    # 0) hit en memoria (sin disco): el camino más rápido posible
    if hash_actual in _MEMO:
        salida_memo, error_memo, error_texto_memo = _MEMO[hash_actual]
        sys.stdout.write(salida_memo)
        if error_texto_memo:
            print(error_texto_memo, file=sys.stderr)
        return not error_memo

    # 1) ¿hay cache válido en disco?
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as archivo:
                datos = json.load(archivo)
            if datos.get("hash") == hash_actual and isinstance(datos.get("salida"), str):
                _MEMO[hash_actual] = (
                    datos["salida"],
                    bool(datos.get("error")),
                    datos.get("error_texto", ""),
                )
                sys.stdout.write(datos["salida"])
                if datos.get("error_texto"):
                    print(datos["error_texto"], file=sys.stderr)
                return not datos.get("error")
        except (OSError, ValueError, KeyError):
            pass  # cache corrupto: se regenera

    # 2) primera vez: ejecutar de verdad y ver si el programa es puro
    salida = io.StringIO()
    maquina = MaquinaVM()
    detector = _DetectorImpuras(maquina.globals)
    maquina.globals = detector  # la VM lee variables vía .get()
    error = False
    error_texto = ""
    try:
        with redirect_stdout(salida):
            programa = parsear(tokenizar(fuente))
            maquina.ejecutar(programa)
    except (ErrorJP, RecursionError) as exc:
        error = True
        error_texto = _formatear_error(exc, fuente)
        print(error_texto, file=sys.stderr)

    # ¿tocó algo impuro? -> esta corrida ya fue "normal"; sin cache, pero la
    # salida que sí se produjo ANTES de la llamada impura se respeta.
    if detector.impura_usada:
        print(
            f"jp: (turbo desactivado para este archivo: usa {detector.cual}())",
            file=sys.stderr,
        )
        sys.stdout.write(salida.getvalue())
        return not error

    # 3) programa puro: cachear la salida para siempre (o hasta que cambie)
    _MEMO[hash_actual] = (salida.getvalue(), error, error_texto)
    try:
        with open(cache, "w", encoding="utf-8") as archivo:
            json.dump(
                {
                    "hash": hash_actual,
                    "salida": salida.getvalue(),
                    "error": error,
                    "error_texto": error_texto,
                },
                archivo,
            )
    except OSError:
        pass  # sin cache no pasa nada: la salida ya se imprimió

    sys.stdout.write(salida.getvalue())
    return not error


def _formatear_error(error: BaseException, fuente: str) -> str:
    if isinstance(error, ErrorJP) and hasattr(error, "formatear"):
        return error.formatear(fuente)
    if isinstance(error, RecursionError):
        return "Error de ejecución: desbordamiento de pila (¿recursión infinita?)"
    return f"{type(error).__name__}: {error}"
