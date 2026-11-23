"""Genera `docs/referencia.md` a partir de las funciones nativas reales.

La lista sale del entorno global del intérprete, no de una lista escrita a
mano: si mañana se añade una nativa, la referencia se actualiza sola.

Uso:
    python herramientas/referencia.py            # escribe docs/referencia.md
    python herramientas/referencia.py --ver      # lo imprime por pantalla
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp import __version__  # noqa: E402
from jp.interprete import FuncionNativa, Interprete  # noqa: E402
from jp.tokens import PALABRAS_CLAVE  # noqa: E402

GRUPOS: list[tuple[str, tuple[str, ...]]] = [
    ("Texto", ("mayusculas", "minusculas", "recortar", "separar", "unir", "contiene",
               "reemplazar", "subtexto", "letra", "longitud", "empezar_con", "terminar_con",
               "buscar", "repetir", "invertir", "texto")),
    ("Números", ("entero", "numero", "absoluto", "raiz", "potencia", "piso", "techo",
                 "redondear", "log", "minimo", "maximo", "sumar", "pi", "aleatorio", "azar")),
    ("Listas y diccionarios", ("agregar", "quitar", "insertar", "eliminar", "indice_de",
                               "ordenar", "claves", "valores", "elementos", "rango")),
    ("Funciones de orden superior", ("mapear", "filtrar", "reducir", "para_cada")),
    ("Entrada/salida", ("imprime", "muestra", "leer", "reloj")),
]


def _firma(nombre: str, nativa: FuncionNativa) -> str:
    if nativa.aridad is None:
        return f"{nombre}(...)"
    return f"{nombre}(" + ", ".join(f"a{i + 1}" for i in range(nativa.aridad)) + ")"


def _tabla() -> dict[str, FuncionNativa]:
    interprete = Interprete()
    return {
        nombre: valor
        for nombre, valor in interprete.global_env.variables.items()
        if isinstance(valor, FuncionNativa)
    }


def generar() -> str:
    nativas = _tabla()
    lineas: list[str] = [
        "# Referencia de la biblioteca estándar de JP",
        "",
        f"Generado por `herramientas/referencia.py` a partir de las "
        f"{len(nativas)} funciones nativas del intérprete (JP {__version__}).",
        "No se edita a mano: se regenera.",
        "",
        "La columna «firma» la rellena el propio registro de nativas; el número de",
        "argumentos es el mínimo obligatorio o el total, según la función.",
        "",
        "Un «—» en la descripción significa que esa función todavía no tiene",
        "docstring: es deuda de documentación de la biblioteca, no un error del",
        "generador.",
        "",
    ]

    usadas: set[str] = set()
    for titulo, nombres in GRUPOS:
        presentes = [(n, nativas[n]) for n in nombres if n in nativas]
        if not presentes:
            continue
        lineas += [f"## {titulo}", "", "| Firma | Qué hace |", "|---|---|"]
        for nombre, nativa in presentes:
            usadas.add(nombre)
            ayuda = (nativa.funcion.__doc__ or "").strip().splitlines()
            descripcion = ayuda[0].strip() if ayuda else "—"
            lineas.append(f"| `{_firma(nombre, nativa)}` | {descripcion} |")
        lineas.append("")

    resto = sorted(n for n in nativas if n not in usadas)
    if resto:
        lineas += [
            "## Resto de la biblioteca",
            "",
            "Funciones de los módulos (estadística, matrices, fechas, sistema,",
            "patrones, tablas, servidor, seguridad, gráficos, base de datos, red).",
            "",
            "| Firma | Qué hace |",
            "|---|---|",
        ]
        for nombre in resto:
            nativa = nativas[nombre]
            ayuda = (nativa.funcion.__doc__ or "").strip().splitlines()
            descripcion = ayuda[0].strip() if ayuda else "—"
            lineas.append(f"| `{_firma(nombre, nativa)}` | {descripcion} |")
        lineas.append("")

    lineas += [
        "## Palabras clave",
        "",
        "| Palabra | Alias |",
        "|---|---|",
    ]
    alias: dict[str, list[str]] = {}
    for palabra, token in PALABRAS_CLAVE.items():
        alias.setdefault(token.name, []).append(palabra)
    for _, palabras in sorted(alias.items()):
        principal = palabras[0]
        otros = ", ".join(palabras[1:])
        lineas.append(f"| `{principal}` | {otros or '—'} |")
    lineas.append("")
    return "\n".join(lineas)


def main(argv: list[str]) -> int:
    texto = generar()
    if "--ver" in argv:
        print(texto)
        return 0
    destino = RAIZ / "docs" / "referencia.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    print(f"jp: referencia escrita en {destino.relative_to(RAIZ)} ({len(texto.splitlines())} líneas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
