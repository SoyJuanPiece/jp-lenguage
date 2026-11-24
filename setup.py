"""Empaquetado: mete `biblioteca/` y `motor-c/` dentro del wheel.

Sin esto, `pip install jp-lang` deja un JP sin biblioteca ni fuentes del motor
en C, y `jp --nuevo`, `jp --c` y `jp --binario` fallan buscando archivos que
sólo existen en el repositorio. La copia se hace al construir (no hay copias
duplicadas en el repositorio): `jp/recursos.py` busca primero en `jp/datos/`
y, si no, en la raíz del repositorio.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

RAIZ = Path(__file__).parent
CARPETAS = ("biblioteca", "motor-c")
# Sólo fuentes y documentación: ni binarios compilados (son de cada máquina)
# ni artefactos de `make`.
SUFIJOS = {".jp", ".c", ".h", ".md", ".txt"}


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        destino = Path(self.build_lib) / "jp" / "datos"
        for carpeta in CARPETAS:
            origen = RAIZ / carpeta
            if not origen.is_dir():
                continue
            for archivo in origen.rglob("*"):
                if not archivo.is_file() or archivo.suffix not in SUFIJOS:
                    continue
                copia = destino / archivo.relative_to(RAIZ)
                copia.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(archivo, copia)


setup(cmdclass={"build_py": BuildPy})
