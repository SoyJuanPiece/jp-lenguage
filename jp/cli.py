"""CLI de JP: ejecuta archivos .jp y ofrece un REPL interactivo.

Uso:
    python -m jp hola.jp          # ejecuta un archivo
    python -m jp                  # abre el REPL
    python -m jp --codigo "muestra(1 + 2)"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .errores import ErrorEjecucion, ErrorJP, ErrorLexico, ErrorSintaxis
from .interprete import Interprete, jp_a_texto
from .lexer import tokenizar
from .parser import parsear
from .vm import MaquinaVM

_USA_VM = "--interprete" not in sys.argv[1:]
_TURBO = "--turbo" in sys.argv[1:]
_NATIVO = "--nativo" in sys.argv[1:]
_MOTOR_C = "--c" in sys.argv[1:]

RAIZ = Path(__file__).resolve().parent.parent
MOTOR_C = RAIZ / "motor-c" / "jpvm"


def _compilar_nativo(fuente: str, ruta: str, codigo: str):
    """Compila a bytecode .jpb; devuelve None si el motor nativo no lo soporta."""
    from .compilar_nativo import NoSoportadoNativo, compilar_a_bytes

    try:
        programa = parsear(tokenizar(fuente))
        return compilar_a_bytes(programa, ruta, fuente)
    except NoSoportadoNativo as error:
        return error


def _ejecutar_motor_c(blob: bytes, aviso: bool = False) -> tuple[bool, str]:
    """Ejecuta bytecode en el motor nativo. Devuelve (ok, motivo_del_fallo)."""
    if not MOTOR_C.exists():
        return False, (
            f"no encuentro el motor nativo ({MOTOR_C}).\n"
            "Compílalo una vez con:  make -C motor-c"
        )
    with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
        archivo.write(blob)
        ruta_jpb = archivo.name
    try:
        proceso = subprocess.run([str(MOTOR_C), ruta_jpb])
    finally:
        os.unlink(ruta_jpb)
    return proceso.returncode == 0, f"el programa terminó con código {proceso.returncode}"

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
        if _NATIVO and _USA_VM:
            # JIT: compila a código de máquina las funciones numéricas que
            # califican (falla en silencio y quedan en la VM las demás).
            from .nativo import instalar

            instalar(programa, interprete)
        # 'importar' resuelve las rutas desde la carpeta del archivo actual
        # (en el REPL y con -c, desde el directorio de trabajo).
        directorio = None
        if ruta not in ("<código>", "<repl>"):
            candidato = Path(ruta).resolve().parent
            if candidato.is_dir():
                directorio = candidato
        interprete.ejecutar(programa, directorio=directorio)
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

    # Motor nativo en C: compila a .jpb y ejecuta el binario independiente.
    # Si el programa usa algo que el motor nativo aún no tiene, se avisa y
    # sigue el camino normal (los motores de Python), sin romper nada.
    if _MOTOR_C:
        compilado = _compilar_nativo(fuente, ruta, fuente)
        if isinstance(compilado, bytes):
            ok, motivo = _ejecutar_motor_c(compilado)
            return 0 if ok else 65
        print(
            f"jp: el motor nativo aún no soporta esto: {compilado.que} "
            f"(línea {compilado.linea}). Uso el motor de Python, sin problema.",
            file=sys.stderr,
        )

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


def _modo_probar(archivos: list[str]) -> int:
    """Corre archivos de prueba .jp (con biblioteca/pruebas.jp) y resume.

    Sin archivos: descubre pruebas/**/*.jp y ./*_prueba.jp. Devuelve 0 si
    todo pasa y 1 si algo falla, como cualquier corredor de pruebas.
    """
    rutas: list[Path] = []
    if archivos:
        rutas = [Path(a) for a in archivos]
    else:
        vistas: set[Path] = set()
        for patron in ("pruebas/**/*.jp", "*_prueba.jp"):
            for ruta in sorted(Path(".").glob(patron)):
                if ruta not in vistas:
                    vistas.add(ruta)
                    rutas.append(ruta)
    if not rutas:
        print("jp --probar: no encontre pruebas (pasa archivos o crea pruebas/*.jp)", file=sys.stderr)
        return 66
    pasan = 0
    for ruta in rutas:
        print(f"▶ {ruta}")
        try:
            fuente = ruta.read_text(encoding="utf-8")
        except OSError:
            print(f"jp: no se encontro el archivo: {ruta}", file=sys.stderr)
            continue
        if ejecutar_fuente(fuente, MaquinaVM(), str(ruta)):
            pasan += 1
        else:
            print(f"✗ fallo: {ruta}", file=sys.stderr)
    print(f"\n{pasan}/{len(rutas)} archivos de prueba pasan")
    return 0 if pasan == len(rutas) else 1


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
                    "mientras, para...en, clase/hereda (con 'este'), lanzar, importar, y, o, no\n"
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


def _modo_check(ruta: str) -> int:
    """--check: tokeniza y parsea sin ejecutar (para editores y CI)."""
    try:
        fuente = Path(ruta).read_text(encoding="utf-8")
    except OSError as error:
        print(f"jp: no puedo leer {ruta}: {error}", file=sys.stderr)
        return 66
    try:
        parsear(tokenizar(fuente))
    except ErrorJP as error:
        print(error.formatear(fuente) if hasattr(error, "formatear") else str(error), file=sys.stderr)
        return 65
    print(f"jp: {ruta}: sintaxis correcta")
    return 0


def _modo_bytecode(ruta: str, escribir: str | None, desensamblar: bool = False) -> int:
    """Compila a .jpb (y opcionalmente lo desensambla). Nunca ejecuta."""
    from .compilar_nativo import NoSoportadoNativo, desensamblar_blob

    try:
        fuente = Path(ruta).read_text(encoding="utf-8")
    except OSError as error:
        print(f"jp: no puedo leer {ruta}: {error}", file=sys.stderr)
        return 66
    compilado = _compilar_nativo(fuente, ruta, fuente)
    if isinstance(compilado, NoSoportadoNativo):
        print(f"jp: el motor nativo aún no soporta esto: {compilado.que} (línea {compilado.linea})")
        return 3
    if escribir is not None:
        Path(escribir).write_bytes(compilado)
        print(f"jp: {ruta} -> {escribir} ({len(compilado)} bytes)")
    if desensamblar or escribir is None:
        print(desensamblar_blob(compilado))
    return 0


def _modo_binario(ruta: str, salida: str) -> int:
    """Crea un ejecutable independiente: sin Python, sin JP, solo el binario."""
    import shutil

    fuente_path = Path(ruta)
    try:
        fuente = fuente_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"jp: no puedo leer {ruta}: {error}", file=sys.stderr)
        return 66
    compilado = _compilar_nativo(fuente, ruta, fuente)
    if not isinstance(compilado, bytes):
        print(f"jp: el motor nativo aún no soporta esto: {compilado.que} (línea {compilado.linea})")
        return 3
    compilador = os.environ.get("CC", "cc")
    if shutil.which(compilador) is None:
        print(f"jp: no encuentro un compilador de C ({compilador})", file=sys.stderr)
        return 69
    with tempfile.TemporaryDirectory() as carpeta:
        embebido = Path(carpeta) / "jp_chunk.c"
        bytes_c = ",".join(str(b) for b in compilado)
        embebido.write_text(
            "/* Generado por jp --binario: el bytecode del programa, pegado. */\n"
            f"const unsigned char jp_chunk_embebido[] = {{{bytes_c}}};\n"
            "const unsigned long jp_chunk_largo = sizeof(jp_chunk_embebido);\n",
            encoding="utf-8",
        )
        orden = [
            compilador, "-O2", "-std=c11", "-w",
            str(RAIZ / "motor-c" / "jpvm.c"), str(embebido), "-o", salida, "-lm",
        ]
        proceso = subprocess.run(orden)
    if proceso.returncode != 0:
        print("jp: falló la compilación del binario", file=sys.stderr)
        return 70
    mostrado = salida if salida.startswith("/") else f"./{salida}"
    print(f"jp: ejecutable creado: {mostrado}  (no necesita Python ni JP)")
    return 0


def main(argv: list[str] | None = None) -> int:
    global _USA_VM, _TURBO, _NATIVO, _MOTOR_C
    argumentos = argv if argv is not None else sys.argv[1:]
    _USA_VM = "--interprete" not in argumentos
    _TURBO = "--turbo" in argumentos
    _NATIVO = "--nativo" in argumentos
    _MOTOR_C = "--c" in argumentos or os.environ.get("JP_MOTOR") == "c"
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
    parser.add_argument(
        "--nativo",
        action="store_true",
        help="JIT: compila funciones numéricas a código de máquina x86-64",
    )
    parser.add_argument("-c", "--codigo", help="ejecuta una línea de código JP")
    parser.add_argument(
        "--probar",
        nargs="*",
        metavar="PRUEBA",
        help="corre archivos de prueba .jp (sin archivos: descubre pruebas/ y *_prueba.jp)",
    )
    parser.add_argument(
        "--c",
        action="store_true",
        help="ejecuta con el motor nativo en C (compila a bytecode .jpb y lo corre)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="solo comprueba la sintaxis del archivo, sin ejecutarlo",
    )
    parser.add_argument(
        "--compilar",
        action="store_true",
        help="compila el archivo .jp a bytecode nativo (.jpb)",
    )
    parser.add_argument(
        "--binario",
        action="store_true",
        help="crea un ejecutable independiente (sin Python y sin JP)",
    )
    parser.add_argument(
        "--bytecode",
        action="store_true",
        help="desensambla el bytecode del archivo (sin ejecutarlo)",
    )
    parser.add_argument("-o", "--salida", help="nombre del archivo de salida")
    parser.add_argument("-V", "--version", action="version", version=f"jp {__version__}")
    args = parser.parse_args(argv)

    if args.check:
        if args.archivo is None:
            parser.error("--check necesita un archivo .jp")
        return _modo_check(args.archivo)
    if args.compilar or args.bytecode or args.binario:
        if args.archivo is None:
            parser.error("--compilar/--bytecode/--binario necesitan un archivo .jp")
        if args.bytecode:
            return _modo_bytecode(args.archivo, escribir=None)
        if args.compilar:
            salida = args.salida or (args.archivo + ".jpb")
            return _modo_bytecode(args.archivo, escribir=salida)
        return _modo_binario(args.archivo, args.salida or "programa")
    if args.probar is not None:
        return _modo_probar(args.probar)
    if args.codigo is not None:
        return _modo_codigo(args.codigo)
    if args.archivo is not None:
        return _modo_archivo(args.archivo)
    return _repl()


if __name__ == "__main__":
    raise SystemExit(main())
