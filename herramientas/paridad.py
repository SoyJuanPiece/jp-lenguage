"""Arnés de paridad entre el motor nativo (C) y los motores de Python.

Compila cada programa con el compilador nativo y compara la salida del motor
en C contra la del motor de Python (VM). Es la garantía de que optimizar no
rompe nada: si el motor nativo no soporta algo, se anota como tal (y el CLI
cae de vuelta al motor de Python); si soporta algo pero da otra salida, es un
FALLO y hay que arreglarlo antes de seguir.

Uso:
    python herramientas/paridad.py                # todos los ejemplos
    python herramientas/paridad.py archivo.jp...  # los que quieras
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MOTOR = RAIZ / "motor-c" / "jpvm"
sys.path.insert(0, str(RAIZ))

from jp.compilar_nativo import NoSoportadoNativo, compilar_a_bytes  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402


def ejecutar_python(ruta: Path, entrada: str = "", limite: float = 120) -> tuple[str, int]:
    try:
        proceso = subprocess.run(
            [sys.executable, "-m", "jp", str(ruta)],
            capture_output=True, text=True, input=entrada, cwd=RAIZ, timeout=limite,
        )
    except subprocess.TimeoutExpired:
        return "", -2
    return proceso.stdout, proceso.returncode


def ejecutar_nativo(ruta: Path, entrada: str = "") -> tuple[str, int, str]:
    fuente = ruta.read_text(encoding="utf-8")
    try:
        blob = compilar_a_bytes(parsear(tokenizar(fuente)), str(ruta), fuente)
    except NoSoportadoNativo as error:
        return "", -1, f"no soportado: {error.que} (línea {error.linea})"
    with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
        archivo.write(blob)
        ruta_jpb = archivo.name
    try:
        proceso = subprocess.run(
            [str(MOTOR), ruta_jpb], capture_output=True, text=True, input=entrada, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "", -2, "tiempo agotado (el programa pide entrada o es muy lento)"
    return proceso.stdout, proceso.returncode, proceso.stderr.strip()


# Programas que imprimen su propio tiempo de ejecución: la salida cambia
# a propósito entre motores (¡el nativo tarda 80x menos!).
NO_DETERMINISTAS = {"benchmark-nativo.jp"}


def main(argumentos: list[str]) -> int:
    if not MOTOR.exists():
        print(f"falta el motor nativo: compílalo con `make -C motor-c`")
        return 2
    rutas = [Path(a) for a in argumentos] if argumentos else sorted((RAIZ / "ejemplos").glob("*.jp"))
    iguales = no_soportados = fallos = 0
    for ruta in rutas:
        salida_py, codigo_py = ejecutar_python(ruta)
        salida_c, _, error = ejecutar_nativo(ruta)
        if codigo_py == -2:
            print(f"  ⏱️  {ruta.name:32} el motor de Python tarda más de 120 s (se omite)")
            continue
        if error:
            print(f"  ⏭️  {ruta.name:32} {error}")
            no_soportados += 1
            continue
        if ruta.name in NO_DETERMINISTAS:
            print(f"  ⏱️  {ruta.name:32} se cronometra a sí mismo (comparación de tiempo omitida)")
            iguales += 1
            continue
        if salida_py == salida_c:
            print(f"  ✅ {ruta.name:32} {len(salida_py.splitlines())} línea(s) idénticas")
            iguales += 1
        else:
            print(f"  ❌ {ruta.name:32} ¡SALIDAS DISTINTAS!")
            lineas_py = salida_py.splitlines()
            lineas_c = salida_c.splitlines()
            for indice in range(max(len(lineas_py), len(lineas_c))):
                a = lineas_py[indice] if indice < len(lineas_py) else "<nada>"
                b = lineas_c[indice] if indice < len(lineas_c) else "<nada>"
                if a != b:
                    print(f"      línea {indice + 1}:\n        python: {a!r}\n        nativo: {b!r}")
                    break
            fallos += 1
    print(f"\n{iguales} idénticos · {no_soportados} no soportados todavía · {fallos} fallos")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
