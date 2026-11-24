"""Paridad del compilador: `.jpb` de Python contra `.jpb` de C, byte a byte.

Es el marcador final del frontend nativo. Si los dos blobs coinciden en todos
los `.jp` del repositorio, el motor en C puede compilar y ejecutar por su
cuenta, sin Python.

Uso:
    python herramientas/jpb_paridad.py             # todos los .jp
    python herramientas/jpb_paridad.py ejemplos     # sólo una carpeta

El binario se busca en `motor-c/jpcompilar` (`jpcompilar.exe` en Windows) o en
la ruta que diga `JPCOMPILAR`. Se compila con `make -C motor-c jpcompilar`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.compilar_nativo import NoSoportadoNativo, compilar_a_bytes  # noqa: E402
from jp.errores import ErrorJP  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402

CARPETAS = ("ejemplos", "biblioteca", "pruebas", "paquetes", "docs")


def binario() -> Path:
    ruta = os.environ.get("JPCOMPILAR")
    if ruta:
        return Path(ruta)
    nombre = "jpcompilar.exe" if os.name == "nt" else "jpcompilar"
    return RAIZ / "motor-c" / nombre


def compilar_python(ruta: Path) -> tuple[bytes | None, str | None]:
    fuente = ruta.read_text(encoding="utf-8")
    try:
        arbol = parsear(tokenizar(fuente))
        return compilar_a_bytes(arbol, nombre=str(ruta), fuente=fuente, directorio=ruta.parent), None
    except NoSoportadoNativo as error:
        return None, f"no soportado: {error}"
    except ErrorJP as error:
        return None, f"{error.mensaje}|{error.linea}|{error.columna}"


def compilar_c(ejecutable: Path, ruta: Path) -> tuple[bytes | None, str | None]:
    with tempfile.TemporaryDirectory() as carpeta:
        salida = Path(carpeta) / "salida.jpb"
        proceso = subprocess.run(
            [str(ejecutable), str(ruta), str(salida)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proceso.returncode != 0:
            return None, (proceso.stderr or "").strip()
        return salida.read_bytes(), None


def describir(blob: bytes) -> str:
    """Contexto legible del blob: cabecera y dónde cae el byte que difiere."""
    import struct

    if len(blob) < 24:
        return f"{len(blob)} bytes"
    _, n_funciones, n_cadenas, n_globales, _ = struct.unpack_from("<IIIII", blob, 4)
    return f"{len(blob)} bytes, {n_funciones} funciones, {n_cadenas} cadenas, {n_globales} globales"


def main(argv: list[str]) -> int:
    ejecutable = binario()
    if not ejecutable.is_file():
        print(f"jpb_paridad: falta el binario {ejecutable}", file=sys.stderr)
        print("  compílalo con:  make -C motor-c jpcompilar", file=sys.stderr)
        return 2

    carpetas = argv[1:] or CARPETAS
    archivos: list[Path] = []
    for carpeta in carpetas:
        base = RAIZ / carpeta
        if base.is_dir():
            archivos.extend(sorted(base.rglob("*.jp")))
    if not archivos:
        print("jpb_paridad: no encontré archivos .jp", file=sys.stderr)
        return 2

    fallos = 0
    no_soportados = 0
    for ruta in archivos:
        relativa = ruta.relative_to(RAIZ)
        python_blob, error_python = compilar_python(ruta)
        c_blob, error_c = compilar_c(ejecutable, ruta)

        if error_python and error_python.startswith("no soportado"):
            no_soportados += 1
            if c_blob is not None:
                print(f"· {relativa}: Python lo rechaza ({error_python}) pero C lo compila")
            continue
        if error_python or error_c:
            if error_python and error_c:
                continue
            print(f"✗ {relativa}: sólo falla en {'Python' if error_python else 'C'}")
            print(f"    {error_python or error_c}")
            fallos += 1
            continue

        if python_blob != c_blob:
            fallos += 1
            print(f"✗ {relativa}: el .jpb difiere")
            print(f"    Python: {describir(python_blob)}")
            print(f"    C:      {describir(c_blob)}")
            for indice in range(min(len(python_blob), len(c_blob))):
                if python_blob[indice] != c_blob[indice]:
                    desde = max(0, indice - 8)
                    print(f"    primer byte distinto en {indice}:")
                    print(f"      Python: {python_blob[desde:indice + 8].hex(' ')}")
                    print(f"      C:      {c_blob[desde:indice + 8].hex(' ')}")
                    break
            else:
                print("    los primeros bytes coinciden; cambia la longitud")

    total = len(archivos)
    print()
    if fallos:
        print(f"{fallos}/{total} archivos producen bytecode distinto")
        if no_soportados:
            print(f"({no_soportados} archivos que Python rechaza, omitidos)")
        return 1
    sufijo = f" ({no_soportados} que Python rechaza, omitidos)" if no_soportados else ""
    print(f"{total - no_soportados}/{total} archivos producen el mismo bytecode{sufijo}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
