"""Comprueba que cada bloque ```jp de docs/jp-en-20-minutos.md es un programa.

El tutorial no se puede quedar obsoleto: si un ejemplo deja de compilar, esto
falla. Uso:

    python herramientas/tutorial.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOC = RAIZ / "docs" / "jp-en-20-minutos.md"


def _ejecutar(archivo: Path) -> subprocess.CompletedProcess:
    entorno = dict(os.environ)
    entorno["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "jp", str(archivo)],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=entorno,
    )


def main() -> int:
    if not DOC.exists():
        print(f"falta {DOC}")
        return 2
    bloques = re.findall(r"```jp\n(.*?)```", DOC.read_text(encoding="utf-8"), re.S)
    print(f"{len(bloques)} bloques jp en el tutorial")
    fallos = 0
    with tempfile.TemporaryDirectory() as carpeta:
        for numero, bloque in enumerate(bloques, start=1):
            archivo = Path(carpeta) / f"bloque{numero}.jp"
            archivo.write_text(bloque, encoding="utf-8")
            proceso = _ejecutar(archivo)
            if proceso.returncode == 0:
                primera = (proceso.stdout.strip().splitlines() or [""])[0]
                print(f"  bloque {numero}: OK  -> {primera[:60]}")
            else:
                print(f"  bloque {numero}: FALLO (código {proceso.returncode})")
                print("    " + (proceso.stderr.strip()[:600] or "sin salida de error"))
                fallos += 1
    print("RESULTADO:", "OK" if fallos == 0 else f"{fallos} bloque(s) con fallos")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
