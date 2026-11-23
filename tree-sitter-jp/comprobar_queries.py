"""Comprueba las queries de tree-sitter contra el árbol que genera la gramática.

No necesita compilador de C: en vez de compilar el parser, cruza los nombres
de nodo y de campo que usan los `.scm` con `src/node-types.json` (que sí
produce `tree-sitter generate`). Detecta el error más común y más caro de
depurar: una query que menciona un nodo o un campo que ya no existe.

Uso:
    python tree-sitter-jp/comprobar_queries.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
QUERIES = RAIZ / "queries"
TIPOS = RAIZ / "src" / "node-types.json"


def _nombres(valor) -> set[str]:
    """Nombres de nodo (y tipos) que aparecen en node-types.json."""
    nombres: set[str] = set()
    pendientes = [valor]
    while pendientes:
        actual = pendientes.pop()
        if isinstance(actual, dict):
            if isinstance(actual.get("type"), str):
                nombres.add(actual["type"])
            pendientes.extend(actual.values())
        elif isinstance(actual, list):
            pendientes.extend(actual)
    return nombres


def _campos(valor) -> set[str]:
    campos: set[str] = set()
    pendientes = [valor]
    while pendientes:
        actual = pendientes.pop()
        if isinstance(actual, dict):
            for clave, contenido in actual.items():
                if clave == "fields":
                    campos.update(contenido.keys())
                pendientes.append(contenido)
        elif isinstance(actual, list):
            pendientes.extend(actual)
    return campos


def _quitar_comentarios(texto: str) -> str:
    return "\n".join(linea.split(";", 1)[0] for linea in texto.splitlines())


def main() -> int:
    if not TIPOS.exists():
        print(f"falta {TIPOS}: corre antes `tree-sitter generate`")
        return 2
    datos = json.loads(TIPOS.read_text(encoding="utf-8"))
    nodos = _nombres(datos)
    campos = _campos(datos)
    fallos = 0

    for ruta in sorted(QUERIES.glob("*.scm")):
        texto = _quitar_comentarios(ruta.read_text(encoding="utf-8"))
        if texto.count("(") != texto.count(")"):
            print(f"{ruta.name}: paréntesis descompensados")
            fallos += 1
        for nombre in re.findall(r"\(([a-zA-Z_][a-zA-Z0-9_]*)", texto):
            if nombre == "_":
                continue
            if nombre not in nodos:
                print(f"{ruta.name}: nodo desconocido '{nombre}' (no está en node-types.json)")
                fallos += 1
        for campo in re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*:", texto):
            if campo not in campos:
                print(f"{ruta.name}: campo desconocido '{campo}:'")
                fallos += 1

    print(f"{len(list(QUERIES.glob('*.scm')))} queries, {len(nodos)} nodos conocidos")
    print("RESULTADO:", "OK" if fallos == 0 else f"{fallos} problema(s)")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
