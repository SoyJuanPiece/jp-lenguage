"""Paridad de lexers: `jp/lexer.py` (Python) contra `motor-c/lexer.c` (C).

Es el marcador de la primera pieza del frontend nativo. Tokeniza cada `.jp` del
repositorio con los dos lexers y compara tipo, lexema, línea, columna y
literal. Si divergen, el motor en C todavía no puede sustituir al de Python.

Uso:
    python herramientas/lexer_paridad.py            # todos los .jp
    python herramientas/lexer_paridad.py ejemplos   # sólo una carpeta

El binario se busca en `motor-c/jptokens` (`jptokens.exe` en Windows) o en la
ruta que diga `JPTOKENS`. Se compila con `make -C motor-c jptokens`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.errores import ErrorLexico  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.tokens import TToken  # noqa: E402

CARPETAS = ("ejemplos", "biblioteca", "pruebas", "paquetes", "docs")


def binario() -> Path:
    ruta = os.environ.get("JPTOKENS")
    if ruta:
        return Path(ruta)
    nombre = "jptokens.exe" if os.name == "nt" else "jptokens"
    return RAIZ / "motor-c" / nombre


def literal_python(token) -> object:
    """El literal como lo ve el lexer de Python, en forma comparable con el JSON."""
    if token.tipo == TToken.NUMERO:
        # El valor va en el campo `numero`; el literal no aplica.
        return None
    if token.tipo in (TToken.VERDADERO, TToken.FALSO):
        return "1" if token.literal else "0"
    if isinstance(token.literal, str):
        return token.literal
    if token.literal is None:
        return None
    return str(token.literal)


def tokens_python(ruta: Path):
    fuente = ruta.read_text(encoding="utf-8")
    try:
        lista = tokenizar(fuente)
    except ErrorLexico as error:
        return None, (error.mensaje, error.linea, error.columna)
    return [
        {
            "tipo": t.tipo.name,
            "lexema": t.lexema,
            "literal": literal_python(t),
            "numero": float(t.literal) if t.tipo == TToken.NUMERO else None,
            "linea": t.linea,
            "columna": t.columna,
        }
        for t in lista
    ], None


def tokens_c(ejecutable: Path, ruta: Path):
    proceso = subprocess.run(
        [str(ejecutable), str(ruta)], capture_output=True, text=True, encoding="utf-8"
    )
    if proceso.returncode != 0:
        partes = (proceso.stderr or "").strip().rsplit("|", 2)
        if len(partes) == 3 and partes[1].isdigit() and partes[2].isdigit():
            return None, (partes[0], int(partes[1]), int(partes[2]))
        return None, (proceso.stderr.strip(), 0, 0)
    datos = json.loads(proceso.stdout)
    for token in datos:
        if "numero" in token:
            token["numero"] = float(token["numero"])
        else:
            token["numero"] = None
    return datos, None


def comparar(python_tokens, c_tokens) -> str | None:
    if len(python_tokens) != len(c_tokens):
        return f"{len(python_tokens)} tokens en Python, {len(c_tokens)} en C"
    for indice, (a, b) in enumerate(zip(python_tokens, c_tokens)):
        for campo in ("tipo", "lexema", "literal", "linea", "columna", "numero"):
            if a[campo] != b[campo]:
                return (
                    f"token {indice}: {campo} difiere — "
                    f"Python {a[campo]!r} / C {b[campo]!r} "
                    f"(tipo {a['tipo']}, lexema {a['lexema']!r}, línea {a['linea']})"
                )
    return None


def main(argv: list[str]) -> int:
    ejecutable = binario()
    if not ejecutable.is_file():
        print(f"lexer_paridad: falta el binario {ejecutable}", file=sys.stderr)
        print("  compílalo con:  make -C motor-c jptokens", file=sys.stderr)
        return 2

    carpetas = argv[1:] or CARPETAS
    archivos: list[Path] = []
    for carpeta in carpetas:
        base = RAIZ / carpeta
        if base.is_dir():
            archivos.extend(sorted(base.rglob("*.jp")))
    if not archivos:
        print("lexer_paridad: no encontré archivos .jp", file=sys.stderr)
        return 2

    fallos = 0
    for ruta in archivos:
        python_tokens, error_python = tokens_python(ruta)
        c_tokens, error_c = tokens_c(ejecutable, ruta)
        relativa = ruta.relative_to(RAIZ)
        if error_python or error_c:
            if error_python and error_c:
                if error_python[1:] != error_c[1:]:
                    print(f"✗ {relativa}: error en línea/columna distinta ({error_python[1:]} vs {error_c[1:]})")
                    fallos += 1
                continue
            quien = "Python" if error_python else "C"
            print(f"✗ {relativa}: sólo falla en {quien}: {(error_python or error_c)[0]}")
            fallos += 1
            continue
        diferencia = comparar(python_tokens, c_tokens)
        if diferencia:
            print(f"✗ {relativa}: {diferencia}")
            fallos += 1

    total = len(archivos)
    print()
    if fallos:
        print(f"{fallos}/{total} archivos difieren entre los lexers")
        return 1
    print(f"{total}/{total} archivos tokenizan igual en Python y en C")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
