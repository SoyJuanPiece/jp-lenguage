"""Dónde están los archivos que JP necesita además del código Python.

En el repositorio `biblioteca/` y `motor-c/` viven en la raíz, junto a `jp/`.
Cuando el paquete se instala con pip sólo existe `jp/`, así que la
construcción del wheel copia esas dos carpetas a `jp/datos/` y aquí se busca
en los dos sitios: primero junto al código (instalado), después la raíz
(desarrollo). `JP_RAIZ` manda sobre todo, para probar sin reinstalar.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_CANDIDATOS = (_AQUI / "datos", _AQUI.parent)


def raiz() -> Path:
    """Carpeta que contiene `biblioteca/` y `motor-c/`."""
    forzada = os.environ.get("JP_RAIZ")
    if forzada:
        return Path(forzada).expanduser()
    for candidato in _CANDIDATOS:
        if (candidato / "biblioteca").is_dir() and (candidato / "motor-c").is_dir():
            return candidato
    # Sin recursos: devolvemos la raíz del paquete para que el mensaje de error
    # enseñe la ruta que se esperaba.
    return _AQUI.parent


def archivo(*partes: str) -> Path:
    """Ruta a un recurso: `archivo("biblioteca", "pruebas.jp")`."""
    return raiz().joinpath(*partes)


def carpeta_cache() -> Path:
    """Caché de JP: el `jpvm` compilado en el primer uso, y demás."""
    if os.environ.get("JP_CACHE"):
        return Path(os.environ["JP_CACHE"]).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "jp"


def _nombre_binario() -> str:
    return "jpvm.exe" if sys.platform == "win32" else "jpvm"


def binario_motor() -> Path:
    """El `jpvm` ejecutable aquí: el del repositorio si existe, si no el de caché.

    Se mira sólo el nombre de esta plataforma: un `motor-c/jpvm` copiado de
    Linux no se puede ejecutar en Windows (WindowsError 193), así que ahí se
    ignora y se usa (o se compila) el de la caché.
    """
    ruta = raiz() / "motor-c" / _nombre_binario()
    if ruta.is_file():
        return ruta
    return carpeta_cache() / _nombre_binario()


def compilador() -> str | None:
    """El compilador de C a usar: `$CC` si está, si no el primero que haya."""
    pedido = os.environ.get("CC")
    if pedido and shutil.which(pedido):
        return pedido
    for candidato in ("cc", "gcc", "clang", "zig"):
        if shutil.which(candidato):
            return candidato
    return None


# Fuentes del motor: la VM y el frontend (lexer, parser y compilador a .jpb).
FUENTES_MOTOR = ("jpvm.c", "ast.c", "parser.c", "lexer.c", "compilar.c")


def compilar_motor(*, silencioso: bool = True) -> Path | None:
    """Compila el motor en la caché si hace falta.

    Devuelve la ruta del binario, o None si no hay compilador o falla. Sólo
    recompila cuando el binario no existe o es más viejo que algún fuente, así
    que las ejecuciones siguientes no pagan nada.
    """
    fuentes = [archivo("motor-c", nombre) for nombre in FUENTES_MOTOR]
    destino = carpeta_cache() / _nombre_binario()
    if not all(fuente.is_file() for fuente in fuentes):
        return None
    if destino.is_file() and all(
        destino.stat().st_mtime >= fuente.stat().st_mtime for fuente in fuentes
    ):
        return destino
    compilador_c = compilador()
    if compilador_c is None:
        return None
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        proceso = subprocess.run(
            [compilador_c, "-O2", "-std=c11", "-w", *map(str, fuentes),
             "-o", str(destino), "-lm"],
            stdout=subprocess.DEVNULL if silencioso else None,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return None
    if proceso.returncode != 0 or not destino.is_file():
        return None
    return destino
