"""Mide para qué sirve JP de verdad, dominio por dominio.

Es el marcador del plan de cobertura (`docs/roadmap-cobertura.md`): cada
dominio tiene un programa-puerta real en `pruebas/cobertura/` y aquí se
ejecuta con el **motor en C**, sin Python de por medio. Si falla, se apunta el
motivo exacto (la primera línea del error), que es la lista de tareas.

Uso:
    python herramientas/cobertura.py                  # tabla de 11 dominios
    python herramientas/cobertura.py --solo red,ffi   # sólo esos
    python herramientas/cobertura.py --exigir datos   # falla si no pasan
    python herramientas/cobertura.py --json           # para otras herramientas

El motor se busca en `motor-c/jpvm` o en la variable de entorno `JPVM`. Si no
está, las puertas de programa salen «no» con ese motivo (no se compila solo:
`make -C motor-c` es un paso explícito, como en el CI).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

RAIZ = Path(__file__).resolve().parent.parent
PUERTAS = RAIZ / "pruebas" / "cobertura"
SALIDA = PUERTAS / ".salida"

TIEMPO_MAX = 180.0        # segundos por puerta (datos y matrices son pesadas)
REPETICIONES = 3          # para rendimiento: mejor de 3
VECES_MAX = 3.0           # rendimiento: 3x la línea base en C -O2
_FIB_C = PUERTAS / "fib35.c"


@dataclass
class Resultado:
    dominio: str
    slug: str
    fase: str
    ok: bool
    motivo: str
    ms: float | None = None


# --- motor y ejecución -------------------------------------------------------


def _motor() -> Path | None:
    """Ruta del motor en C, o None si no está compilado."""
    candidatos = []
    if os.environ.get("JPVM"):
        candidatos.append(Path(os.environ["JPVM"]))
    en_windows = RAIZ / "motor-c" / "jpvm.exe"
    candidatos += [en_windows, RAIZ / "motor-c" / "jpvm"] if os.name == "nt" else [
        RAIZ / "motor-c" / "jpvm",
        en_windows,
    ]
    for ruta in candidatos:
        if ruta.is_file():
            return ruta
    return None


def _limpiar_salida() -> None:
    if SALIDA.exists():
        shutil.rmtree(SALIDA)
    SALIDA.mkdir(parents=True)


def _motivo_de(texto: str) -> str:
    """La primera línea con un error, en una frase corta."""
    for linea in texto.splitlines():
        limpia = linea.strip()
        for marca in ("Error de sintaxis", "Error de ejecución", "Error de compilación", "jp:"):
            if marca in limpia:
                return limpia.split("|")[0].replace("Error de ejecución: ", "").replace(
                    "Error de sintaxis: ", ""
                ).replace("Error de compilación: ", "").strip()
    for linea in reversed(texto.splitlines()):
        if linea.strip():
            return linea.strip()[:160]
    return "sin salida"


def _ejecutar(archivo: Path, limite: float = TIEMPO_MAX) -> tuple[int, str, str, float]:
    """(código, stdout, stderr, ms) de una puerta con el motor en C."""
    motor = _motor()
    if motor is None:
        return 127, "", "falta el motor en C: compílalo con `make -C motor-c`", 0.0
    inicio = time.perf_counter()
    try:
        proceso = subprocess.run(
            [str(motor), str(archivo)],
            cwd=str(RAIZ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=limite,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"se pasó de {int(limite)} s", (time.perf_counter() - inicio) * 1000
    ms = (time.perf_counter() - inicio) * 1000
    return proceso.returncode, proceso.stdout, proceso.stderr, ms


def _puerta_de_programa(archivo: str) -> tuple[bool, str, float | None]:
    codigo, salida, error, ms = _ejecutar(PUERTAS / archivo)
    if codigo == 0:
        return True, "", ms
    if codigo == 124:
        return False, error, ms
    return False, _motivo_de(error or salida), ms


# --- puertas especiales ------------------------------------------------------


def _compilador_c() -> list[str] | None:
    """El compilador de C disponible, ya troceado para subprocess."""
    if os.environ.get("CC"):
        return os.environ["CC"].split()
    for nombre in ("cc", "gcc", "clang"):
        if shutil.which(nombre):
            return [nombre]
    if shutil.which("zig"):
        return ["zig", "cc"]
    return None


def _linea_base_c() -> tuple[float | None, str]:
    """Mejor tiempo en ms del fib(35) en C -O2, compilado al momento."""
    compilador = _compilador_c()
    if compilador is None:
        return None, "no hay compilador de C para la línea base"
    destino = RAIZ / ".codebuff_tmp" / "cobertura"
    destino.mkdir(parents=True, exist_ok=True)
    binario = destino / ("fib35.exe" if os.name == "nt" else "fib35")
    if not binario.is_file() or binario.stat().st_mtime < _FIB_C.stat().st_mtime:
        orden = compilador + ["-O2", "-o", str(binario), str(_FIB_C)]
        compilado = subprocess.run(orden, capture_output=True, text=True)
        if compilado.returncode != 0:
            return None, f"no se pudo compilar la línea base: {compilado.stderr.strip()[:120]}"
    tiempos = []
    for _ in range(REPETICIONES):
        inicio = time.perf_counter()
        subprocess.run([str(binario)], capture_output=True)
        tiempos.append((time.perf_counter() - inicio) * 1000)
    return min(tiempos), ""


def _puerta_rendimiento() -> tuple[bool, str, float | None]:
    """fib(35) en JP contra el mismo fib(35) en C -O2 (fase F8)."""
    mejor_jp: float | None = None
    codigo = 0
    error = ""
    for _ in range(REPETICIONES):
        codigo, salida, error, ms = _ejecutar(PUERTAS / "09-rendimiento.jp")
        if codigo != 0:
            return False, _motivo_de(error or salida), None
        mejor_jp = ms if mejor_jp is None else min(mejor_jp, ms)
    base, problema = _linea_base_c()
    if base is None:
        return False, problema, mejor_jp
    veces = mejor_jp / base
    detalle = f"fib(35) en {mejor_jp:.0f} ms (C -O2: {base:.0f} ms, {veces:.1f}x)"
    if veces <= VECES_MAX:
        return True, detalle, mejor_jp
    return False, f"{detalle}; el límite es {VECES_MAX:.0f}x", mejor_jp


def _puerta_paquetes() -> tuple[bool, str, float | None]:
    """Instalar una dependencia con versión y dejar `jp.lock` (fase F6)."""
    carpeta = Path(tempfile.mkdtemp(prefix="jp-puerta-"))
    try:
        (carpeta / "paquete.json").write_text(
            json.dumps(
                {
                    "nombre": "puerta",
                    "version": "1.0.0",
                    "dependencias": {"mates": "1.2.3"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        entorno = dict(os.environ)
        entorno["PYTHONPATH"] = str(RAIZ) + os.pathsep + entorno.get("PYTHONPATH", "")
        inicio = time.perf_counter()
        proceso = subprocess.run(
            [sys.executable, "-m", "jp", "--instalar", "--aqui"],
            cwd=str(carpeta),
            env=entorno,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        ms = (time.perf_counter() - inicio) * 1000
        if proceso.returncode != 0:
            return False, _motivo_de(proceso.stderr or proceso.stdout), ms
        if not (carpeta / "jp.lock").is_file():
            return False, "instaló pero no dejó jp.lock (no hay versiones ni hashes)", ms
        return True, "", ms
    except subprocess.TimeoutExpired:
        return False, "la instalación no terminó en 60 s", None
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


# --- catálogo de dominios ----------------------------------------------------


@dataclass
class Dominio:
    nombre: str
    slug: str
    fase: str
    correr: Callable[[], tuple[bool, str, float | None]]


def _programa(archivo: str) -> Callable[[], tuple[bool, str, float | None]]:
    return lambda: _puerta_de_programa(archivo)


DOMINIOS: list[Dominio] = [
    Dominio("Scripts y automatización", "scripts", "F4", _programa("01-scripts.jp")),
    Dominio("CLI", "cli", "F1", _programa("02-cli.jp")),
    Dominio("API / backend web", "api", "F4", _programa("03-api.jp")),
    Dominio("Datos y estadística", "datos", "F7", _programa("04-datos.jp")),
    Dominio("Cálculo numérico", "numerico", "-", _programa("05-numerico.jp")),
    Dominio("Concurrencia", "concurrencia", "F5", _programa("06-concurrencia.jp")),
    Dominio("Red y protocolos", "red", "F4", _programa("07-red.jp")),
    Dominio("Sistemas / FFI", "ffi", "F3", _programa("08-ffi.jp")),
    Dominio("Rendimiento", "rendimiento", "F8", _puerta_rendimiento),
    Dominio("Escritorio y 2D", "escritorio", "F9", _programa("10-escritorio.jp")),
    Dominio("Paquetes", "paquetes", "F6", _puerta_paquetes),
]


# --- informe -----------------------------------------------------------------


def medir(slugs: list[str] | None = None) -> list[Resultado]:
    _limpiar_salida()
    resultados = []
    for dominio in DOMINIOS:
        if slugs and dominio.slug not in slugs:
            continue
        ok, motivo, ms = dominio.correr()
        resultados.append(Resultado(dominio.nombre, dominio.slug, dominio.fase, ok, motivo, ms))
    return resultados


def _tabla(resultados: list[Resultado]) -> str:
    # el ancho incluye la cabecera para que una tabla de un solo dominio
    # (--solo) siga alineada
    ancho = max([len("Dominio"), *(len(r.dominio) for r in resultados)]) + 2
    lineas = [f"{'Dominio':<{ancho}}{'Pasa':<8}{'Fase':<7}Motivo", "-" * (ancho + 60)]
    for r in resultados:
        estado = "sí" if r.ok else "no"
        motivo = r.motivo if not r.ok else (r.motivo or "")
        lineas.append(f"{r.dominio:<{ancho}}{estado:<8}{r.fase:<7}{motivo}")
    pasan = sum(1 for r in resultados if r.ok)
    lineas.append("-" * (ancho + 60))
    lineas.append(f"{pasan}/{len(resultados)} dominios cubiertos · faltan {len(resultados) - pasan}")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    argumentos = argv if argv is not None else sys.argv[1:]
    slugs = None
    exigidos: list[str] = []
    como_json = "--json" in argumentos
    for i, arg in enumerate(argumentos):
        if arg == "--solo" and i + 1 < len(argumentos):
            slugs = [s.strip() for s in argumentos[i + 1].split(",") if s.strip()]
        if arg == "--exigir" and i + 1 < len(argumentos):
            exigidos = [s.strip() for s in argumentos[i + 1].split(",") if s.strip()]

    if slugs:
        desconocidos = [s for s in slugs if s not in {d.slug for d in DOMINIOS}]
        if desconocidos:
            print(f"jp: no conozco el dominio {', '.join(desconocidos)}", file=sys.stderr)
            return 2

    resultados = medir(slugs)
    if como_json:
        print(json.dumps([r.__dict__ for r in resultados], ensure_ascii=False, indent=2))
    else:
        print(_tabla(resultados))

    fallidos = [r.slug for r in resultados if r.slug in exigidos and not r.ok]
    if fallidos:
        print(f"jp: la puerta no se cierra, faltan {', '.join(fallidos)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
