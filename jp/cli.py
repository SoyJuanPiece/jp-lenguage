"""CLI de JP: ejecuta archivos .jp y ofrece un REPL interactivo.

Uso:
    python -m jp hola.jp          # ejecuta un archivo
    python -m jp                  # abre el REPL
    python -m jp --codigo "muestra(1 + 2)"
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .errores import ErrorEjecucion, ErrorJP, ErrorLexico, ErrorSintaxis
from .interprete import Interprete, jp_a_texto
from .lexer import tokenizar
from .parser import parsear
from .vm import MaquinaVM

_USA_VM = "--interprete" not in sys.argv[1:]
_TURBO = "--turbo" in sys.argv[1:]

_BANNER = r"""
     ██╗██╗
     ██║██║
     ██║██║
██   ██║██║
╚█████╔╝██║
 ╚════╝ ╚═╝  v{version} — tu lenguaje, tus reglas

Escribe 'ayuda' para ver trucos fáciles.
"""


def ejecutar_fuente(fuente: str, interprete: Interprete | MaquinaVM, ruta: str = "<código>") -> bool:
    """Tokeniza, parsea y ejecuta el código; imprime errores con formato bonito.

    Por defecto usa la VM de bytecode (--interprete cambia al intérprete de
    árbol, útil para comparar). Devuelve True si no hubo errores.
    """
    try:
        tokens = tokenizar(fuente)
        programa = parsear(tokens)
        interprete.ejecutar(programa)
        return True
    except (ErrorLexico, ErrorSintaxis, ErrorEjecucion) as error:
        print(error.formatear(fuente), file=sys.stderr)
    except ErrorJP as error:
        print(f"{error.titulo}: {error.mensaje}", file=sys.stderr)
    except RecursionError:
        print(f"Error de ejecución: desbordamiento de pila (¿recursión infinita?) en {ruta}", file=sys.stderr)
    except KeyboardInterrupt:
        raise
    return False


def _modo_archivo(ruta: str) -> int:
    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            fuente = archivo.read()
    except FileNotFoundError:
        run_turbo = False
        print(f"jp: no se encontró el archivo: {ruta}", file=sys.stderr)
        return 66
    except IsADirectoryError:
        run_turbo = False
        print(f"jp: es un directorio: {ruta}", file=sys.stderr)
        return 66

    # Modo turbo: cache total del programa si es puro (ver jp/turbo.py)
    if run_turbo := (_TURBO and _USA_VM):
        from .turbo import ejecutar_turbo

        ok = ejecutar_turbo(ruta, fuente)
        return 0 if ok else 65

    interprete: Interprete | MaquinaVM = MaquinaVM() if _USA_VM else Interprete()
    try:
        ok = ejecutar_fuente(fuente, interprete, ruta)
    except KeyboardInterrupt:
        print("\njp: interrumpido", file=sys.stderr)
        return 130
    return 0 if ok else 65


def _modo_codigo(codigo: str) -> int:
    ok = ejecutar_fuente(codigo, MaquinaVM() if _USA_VM else Interprete())
    return 0 if ok else 65


def _repl() -> int:
    print(_BANNER.format(version=__version__))
    print("Escribe tu código JP. Ctrl+D o 'salir()' para terminar.\n")

    interprete: Interprete | MaquinaVM = MaquinaVM() if _USA_VM else Interprete()
    buffer_multilinea: list[str] = []
    numero_linea = 1

    while True:
        prompt = "... " if buffer_multilinea else "jp> "
        try:
            linea = input(prompt)
        except EOFError:
            print("\n¡Hasta pronto! 👋")
            return 0
        except KeyboardInterrupt:
            print("\n(entrada cancelada)")
            buffer_multilinea.clear()
            continue

        if not buffer_multilinea:
            if linea.strip() in ("salir()", "exit()", "salir"):
                print("¡Hasta pronto! 👋")
                return 0
            if linea.strip() == "ayuda":
                print(
                    "Funciones: muestra()/imprime(), longitud(), entero(), numero(), texto(), rango(), leer(), azar()\n"
                    "Red y datos: http_get(), http_post(), json_leer(), json_texto(), tiene(), claves(), esperar()\n"
                    "Bots: telegram_leer(token), telegram_responder(token, de, texto)\n"
                    "Palabras clave: var/variable, fun/funcion, retorna/devuelve, si/sino, "
                    "mientras, para...en, y, o, no\n"
                    "Trucos fáciles: 'si cond: una_sentencia' sin llaves · rangos '1..10' "
                    "inclusivos · comillas simples 'hola' · diccionarios {clave: valor}"
                )
                continue
        else:
            numero_linea += 1

        buffer_multilinea.append(linea)
        fuente = "\n".join(buffer_multilinea)

        # Si está desbalanceada la llave, seguir leyendo líneas
        if _llaves_desbalanceadas(fuente):
            continue

        buffer_multilinea.clear()
        numero_linea = 1
        ok = ejecutar_fuente(fuente, interprete, "<repl>")
        # En el REPL, el valor de la última expresión se muestra como en Python
        if ok and interprete.ultimo_valor is not None:
            print(f"=> {jp_a_texto(interprete.ultimo_valor)}")
        print()  # línea en blanco entre entradas


def _llaves_desbalanceadas(fuente: str) -> bool:
    """Cuenta llaves/paréntesis/corchetes fuera de cadenas y comentarios."""
    balance = 0
    en_cadena = False
    escape = False
    i = 0
    while i < len(fuente):
        c = fuente[i]
        if en_cadena:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                en_cadena = False
        else:
            if c == "#":
                while i < len(fuente) and fuente[i] != "\n":
                    i += 1
                continue
            if c == '"':
                en_cadena = True
            elif c in "([{":
                balance += 1
            elif c in ")]}":
                balance -= 1
        i += 1
    return balance > 0


def main(argv: list[str] | None = None) -> int:
    global _USA_VM, _TURBO
    argumentos = argv if argv is not None else sys.argv[1:]
    _USA_VM = "--interprete" not in argumentos
    _TURBO = "--turbo" in argumentos
    parser = argparse.ArgumentParser(
        prog="jp",
        description="JP — un pequeño lenguaje de programación en español.",
    )
    parser.add_argument("archivo", nargs="?", help="archivo .jp a ejecutar")
    parser.add_argument(
        "--interprete",
        action="store_true",
        help="usa el intérprete de árbol en vez de la VM de bytecode",
    )
    parser.add_argument(
        "--turbo",
        action="store_true",
        help="cache total: programas puros corren en microsegundos (ver jp/turbo.py)",
    )
    parser.add_argument("-c", "--codigo", help="ejecuta una línea de código JP")
    parser.add_argument("-V", "--version", action="version", version=f"jp {__version__}")
    args = parser.parse_args(argv)

    if args.codigo is not None:
        return _modo_codigo(args.codigo)
    if args.archivo is not None:
        return _modo_archivo(args.archivo)
    return _repl()


if __name__ == "__main__":
    raise SystemExit(main())
