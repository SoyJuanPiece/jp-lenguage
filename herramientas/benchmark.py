"""Vigila que el rendimiento no se caiga: 10% más lento y el CI falla.

Corre `ejemplos/benchmark.jp` con el motor en C varias veces, se queda con la
mediana y la compara con la línea base guardada en
`pruebas/linea-base-rendimiento.json`.

La línea base es **por plataforma**: los números de un runner de Linux no se
comparan con los de Windows. La primera vez que se corre en una plataforma sin
línea base, se graba y se avisa (una línea base puesta a mano es una mentira:
tiene que salir de la máquina donde se mide).

Uso:
    python herramientas/benchmark.py              # mide y compara
    python herramientas/benchmark.py --regrabar   # fija la línea base actual
    python herramientas/benchmark.py --json       # salida para otras herramientas
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PROGRAMA = RAIZ / "ejemplos" / "benchmark.jp"
LINEA = RAIZ / "pruebas" / "linea-base-rendimiento.json"
REPETICIONES = 5
MARGEN = 1.10          # 10% de regresión y falla
CALENTAMIENTO = 1


def _motor() -> Path | None:
    candidatos = []
    if os.environ.get("JPVM"):
        candidatos.append(Path(os.environ["JPVM"]))
    en_windows = RAIZ / "motor-c" / "jpvm.exe"
    candidatos += [en_windows, RAIZ / "motor-c" / "jpvm"] if os.name == "nt" else [
        RAIZ / "motor-c" / "jpvm",
        en_windows,
    ]
    return next((ruta for ruta in candidatos if ruta.is_file()), None)


def _clave_plataforma() -> str:
    return f"{sys.platform}-{platform.machine().lower()}"


def medir() -> float:
    """Mediana en ms de varias corridas del benchmark, con el motor en C."""
    motor = _motor()
    if motor is None:
        raise SystemExit("jp: falta el motor en C: compílalo con `make -C motor-c`")
    for _ in range(CALENTAMIENTO):
        subprocess.run([str(motor), str(PROGRAMA)], cwd=str(RAIZ), capture_output=True)
    tiempos = []
    for _ in range(REPETICIONES):
        inicio = time.perf_counter()
        proceso = subprocess.run([str(motor), str(PROGRAMA)], cwd=str(RAIZ), capture_output=True)
        if proceso.returncode != 0:
            raise SystemExit(
                "jp: el benchmark falló: " + proceso.stderr.decode("utf-8", "replace")[:200]
            )
        tiempos.append((time.perf_counter() - inicio) * 1000)
    return statistics.median(tiempos)


def _leer_linea() -> dict:
    if not LINEA.is_file():
        return {}
    try:
        return json.loads(LINEA.read_text(encoding="utf-8"))
    except ValueError as error:
        print(f"jp: {LINEA.name} no es JSON válido ({error}); se ignora", file=sys.stderr)
        return {}


def _grabar(linea: dict, clave: str, ms: float) -> None:
    linea[clave] = {
        "ms": round(ms, 1),
        "fecha": time.strftime("%Y-%m-%d"),
        "motor": "jpvm (C11)",
        "programa": PROGRAMA.name,
    }
    LINEA.write_text(json.dumps(linea, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    argumentos = argv if argv is not None else sys.argv[1:]
    como_json = "--json" in argumentos

    clave = _clave_plataforma()
    linea = _leer_linea()
    ms = medir()
    base = linea.get(clave)

    if "--regrabar" in argumentos or base is None:
        _grabar(linea, clave, ms)
        if como_json:
            print(json.dumps({"plataforma": clave, "ms": round(ms, 1), "linea_base": "nueva"}, ensure_ascii=False))
        else:
            estado = "regrabada" if "--regrabar" in argumentos else "creada"
            print(f"benchmark: {ms:.1f} ms · línea base {estado} para {clave} ({LINEA.name})")
        return 0

    limite = base["ms"] * MARGEN
    regresion = ms > limite
    if como_json:
        print(
            json.dumps(
                {
                    "plataforma": clave,
                    "ms": round(ms, 1),
                    "linea_base": base["ms"],
                    "limite": round(limite, 1),
                    "regresion": regresion,
                },
                ensure_ascii=False,
            )
        )
    else:
        veces = ms / base["ms"]
        print(
            f"benchmark: {ms:.1f} ms · línea base {base['ms']:.1f} ms ({base['fecha']}) · "
            f"{veces:.2f}x · límite {limite:.1f} ms"
        )
        if regresion:
            print(
                f"jp: regresión de rendimiento: {(veces - 1) * 100:.0f}% más lento que la línea base",
                file=sys.stderr,
            )
        elif ms < base["ms"] * 0.9:
            print("pista: vas más rápido; actualiza la línea base con --regrabar")
    return 1 if regresion else 0


if __name__ == "__main__":
    raise SystemExit(main())
