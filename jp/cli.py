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

    Sin archivos: descubre pruebas/**/*_prueba.jp y ./*_prueba.jp. Devuelve 0 si
    todo pasa y 1 si algo falla, como cualquier corredor de pruebas.
    """
    rutas: list[Path] = []
    if archivos:
        rutas = [Path(a) for a in archivos]
    else:
        vistas: set[Path] = set()
        for patron in ("pruebas/**/*_prueba.jp", "*_prueba.jp"):
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


class _FinDepuracion(Exception):
    """El usuario pidio salir del depurador con 'q'."""


def _modo_depurar(ruta: str) -> int:
    """Depurador paso a paso sobre el interprete de arbol.

    Pausa antes de cada sentencia: s=siguiente, c=continuar, v <var>=ver,
    e <expr>=evaluar, l=listar variables, p <linea>=punto de interrupcion,
    q=salir. Sin terminal (EOF), sigue hasta el final sin bloquearse.
    """
    from .arbol import NodoExpresion

    try:
        fuente = Path(ruta).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"jp: no se encontró el archivo: {ruta}", file=sys.stderr)
        return 66
    except IsADirectoryError:
        print(f"jp: es un directorio: {ruta}", file=sys.stderr)
        return 66

    lineas = fuente.splitlines()
    interprete = Interprete()
    estado = {"paso": True, "puntos": set()}

    def al_paso(nodo, entorno) -> None:
        linea = getattr(nodo, "linea", 0)
        if not estado["paso"] and linea not in estado["puntos"]:
            return
        estado["paso"] = True
        texto = lineas[linea - 1].strip() if 1 <= linea <= len(lineas) else ""
        print(f"\n🐞 línea {linea}: {texto}")
        while True:
            try:
                comando = input("🐞 (s/c/v/e/l/p/q) > ").strip()
            except EOFError:
                estado["paso"] = False
                return
            except KeyboardInterrupt:
                raise _FinDepuracion from None
            if not comando or comando == "s":
                return
            orden, _, resto = comando.partition(" ")
            resto = resto.strip()
            if orden == "c":
                estado["paso"] = False
                return
            if orden == "q":
                raise _FinDepuracion
            if orden == "v" and resto:
                try:
                    print(f"  {resto} = {jp_a_texto(entorno.obtener(resto))}")
                except ErrorEjecucion:
                    print(f"  ({resto} no existe todavia)")
            elif orden == "e" and resto:
                try:
                    sentencia = parsear(tokenizar(resto)).sentencias[0]
                    if not isinstance(sentencia, NodoExpresion):
                        print("  (escribe una expresion, ej: e x + 1)")
                    else:
                        print(f"  = {jp_a_texto(interprete._evaluar(sentencia.expresion, entorno))}")
                except Exception as error:  # evaluar no debe tumbar el depurador
                    print(f"  (no se pudo: {error})")
            elif orden == "l":
                visibles: dict[str, object] = {}
                cadena = entorno
                while cadena is not None:
                    for nombre, valor in cadena.variables.items():
                        visibles.setdefault(nombre, valor)
                    cadena = cadena.padre
                for nombre in sorted(visibles):
                    resumen = jp_a_texto(visibles[nombre])
                    if len(resumen) > 60:
                        resumen = resumen[:57] + "..."
                    print(f"  {nombre} = {resumen}")
            elif orden == "p" and resto.isdigit():
                numero = int(resto)
                if numero in estado["puntos"]:
                    estado["puntos"].discard(numero)
                    print(f"  punto de interrupcion quitado de la linea {numero}")
                else:
                    estado["puntos"].add(numero)
                    print(f"  punto de interrupcion en la linea {numero} (con 'c' corres hasta el)")
            else:
                print("  s=siguiente · c=continuar · v <var> · e <expr> · l=listar · p <linea> · q=salir")

    interprete.gancho_paso = al_paso
    print(f"🐞 Depurando {ruta} (intérprete de árbol). 's' avanza, 'c' continúa, 'q' sale.")
    try:
        ok = ejecutar_fuente(fuente, interprete, ruta)
    except _FinDepuracion:
        print("\n🐞 depuración terminada")
        return 0
    return 0 if ok else 65


def _modo_formatear(ruta: str, en_sitio: bool) -> int:
    """Reimprime el archivo con el estilo de la casa (jp/formateador.py)."""
    from .formateador import formatear

    try:
        fuente = Path(ruta).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"jp: no se encontró el archivo: {ruta}", file=sys.stderr)
        return 66
    except IsADirectoryError:
        print(f"jp: es un directorio: {ruta}", file=sys.stderr)
        return 66
    try:
        texto = formatear(parsear(tokenizar(fuente)))
    except ErrorJP as error:
        print(error.formatear(fuente) if hasattr(error, "formatear") else f"{error.titulo}: {error.mensaje}", file=sys.stderr)
        return 65
    if en_sitio:
        Path(ruta).write_text(texto, encoding="utf-8")
        print(f"✔ formateado: {ruta}")
    else:
        sys.stdout.write(texto)
    return 0


_PLANTILLA_PRINCIPAL = '''# {nombre} — un proyecto JP
#
# Correlo con:  python -m jp principal.jp
# Y sus pruebas:  python -m jp --probar   (desde esta carpeta)

funcion fibonacci(n) {{
    si n < 2 {{ devuelve n }}
    devuelve fibonacci(n - 1) + fibonacci(n - 2)
}}

imprime("¡Hola desde {nombre}!")
para i en 1..8 {{
    imprime("fibonacci(", i, ") =", fibonacci(i))
}}
'''

_PLANTILLA_PRUEBA = '''importar "pruebas.jp" como p

p.afirmar_igual(2, 1 + 1)
p.afirmar(3 > 2, "tres es mas que dos")
p.resumen()
'''

_PLANTILLA_LEEME = '''# {nombre}

Un proyecto [JP](https://github.com/SoyJuanPiece/jp-lenguage).

- `principal.jp` — el programa. Correlo con `python -m jp principal.jp`.
- `pruebas/` — las pruebas. Correlas con `python -m jp --probar`.

## Ideas para seguir

- Datos que se quedan: `abrir_bd("datos.db")` (SQLite).
- Una web: la clase `Aplicacion` de la biblioteca (`web.jp`).
- Graficas SVG: `grafica_barras(...)` de `graficas.jp`.
'''


def _modo_proyecto(nombre: str) -> int:
    """Crea la carpeta de un proyecto JP nuevo con programa y pruebas."""
    destino = Path(nombre)
    if destino.exists():
        print(f"jp: ya existe '{nombre}', no toco nada", file=sys.stderr)
        return 66
    try:
        (destino / "pruebas").mkdir(parents=True)
        (destino / "principal.jp").write_text(
            _PLANTILLA_PRINCIPAL.format(nombre=nombre), encoding="utf-8")
        (destino / "LEEME.md").write_text(
            _PLANTILLA_LEEME.format(nombre=nombre), encoding="utf-8")
        (destino / "pruebas" / "principal_prueba.jp").write_text(
            _PLANTILLA_PRUEBA, encoding="utf-8")
        # La mini-biblioteca de pruebas viaja con el proyecto.
        (destino / "pruebas" / "pruebas.jp").write_text(
            (RAIZ / "biblioteca" / "pruebas.jp").read_text(encoding="utf-8"),
            encoding="utf-8")
    except OSError as error:
        print(f"jp: no pude crear el proyecto: {error}", file=sys.stderr)
        return 66
    print(f"✔ proyecto '{nombre}' creado:")
    print(f"    {nombre}/principal.jp")
    print(f"    {nombre}/pruebas/ (corre: cd {nombre} && python -m jp --probar)")
    print(f"    {nombre}/LEEME.md")
    return 0


def _modo_instalar(origen: str | None, aqui: bool) -> int:
    """jp --instalar [origen]: instala paquetes JP (ver jp/paquetes.py)."""
    from .paquetes import carpeta_global, instalar, instalar_dependencias

    destino = Path("paquetes") if aqui else carpeta_global()
    try:
        if origen is None:
            nombres = instalar_dependencias(Path.cwd(), destino)
        else:
            nombres = [instalar(origen, destino)]
    except ErrorEjecucion as error:
        print(f"jp: {error.mensaje}", file=sys.stderr)
        return 65
    except OSError as error:
        print(f"jp: no se pudo instalar: {error}", file=sys.stderr)
        return 66
    for nombre in nombres:
        print(f"✔ paquete '{nombre}' instalado en {destino}")
    print('úsalo con: importar "@' + nombres[0] + '" como ' + nombres[0])
    return 0


def _modo_paquetes() -> int:
    from .paquetes import listar

    paquetes = listar()
    if not paquetes:
        print("no hay paquetes instalados (instala con: jp --instalar github:usuario/repo)")
        return 0
    for nombre, version, carpeta in paquetes:
        print(f"{nombre} {version}  ({carpeta})")
    return 0


def _modo_quitar_paquete(nombre: str) -> int:
    from .paquetes import quitar

    quitado = quitar(nombre)
    if quitado is None:
        print(f"jp: el paquete '{nombre}' no está instalado", file=sys.stderr)
        return 66
    print(f"✔ paquete '{nombre}' quitado ({quitado})")
    return 0


def _modo_cobertura(ruta: str) -> int:
    """Ejecuta midiendo cobertura de líneas (jp/cobertura.py)."""
    from .cobertura import InformeCobertura, lineas_ejecutables
    from .interprete import Interprete

    try:
        fuente = Path(ruta).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"jp: no se encontró el archivo: {ruta}", file=sys.stderr)
        return 66
    excepcion: Exception | None = None
    try:
        programa = parsear(tokenizar(fuente))
    except ErrorJP as error:
        print(error.formatear(fuente) if hasattr(error, "formatear") else f"{error.titulo}: {error.mensaje}", file=sys.stderr)
        return 65
    informe = InformeCobertura(ejecutables=lineas_ejecutables(programa))
    maquina = Interprete()
    maquina.gancho_paso = lambda nodo, entorno: informe.ejecutadas.add(nodo.linea)
    try:
        maquina.ejecutar(programa, directorio=str(Path(ruta).resolve().parent))
    except ErrorJP as error:
        excepcion = error
    if excepcion is not None:
        print(excepcion.formatear(fuente) if hasattr(excepcion, "formatear") else excepcion, file=sys.stderr)
    print(informe.texto(ruta))
    return 65 if excepcion is not None else 0


def _modo_revisar(ruta: str) -> int:
    """Analisis estatico: variables sin declarar o sin usar (jp/revisor.py)."""
    from .revisor import revisar

    try:
        fuente = Path(ruta).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"jp: no se encontró el archivo: {ruta}", file=sys.stderr)
        return 66
    except IsADirectoryError:
        print(f"jp: es un directorio: {ruta}", file=sys.stderr)
        return 66
    try:
        programa = parsear(tokenizar(fuente))
    except ErrorJP as error:
        print(error.formatear(fuente) if hasattr(error, "formatear") else f"{error.titulo}: {error.mensaje}", file=sys.stderr)
        return 65
    avisos = revisar(programa)
    for aviso in avisos:
        print(f"{ruta}: {aviso}")
    if avisos:
        return 1
    print(f"✔ {ruta}: sin avisos")
    return 0


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
        help="corre archivos de prueba .jp (sin archivos: descubre los *_prueba.jp)",
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
        "--depurar",
        action="store_true",
        help="depurador paso a paso: pausa en cada sentencia (s/c/v/e/l/p/q)",
    )
    parser.add_argument(
        "--formatear",
        action="store_true",
        help="imprime el archivo con el estilo de la casa (ojo: pierde los comentarios)",
    )
    parser.add_argument(
        "--en-sitio",
        action="store_true",
        help="con --formatear: reescribe el archivo en vez de imprimirlo",
    )
    parser.add_argument(
        "--revisar",
        action="store_true",
        help="analisis estatico: avisa de variables sin declarar o sin usar, sin ejecutar",
    )
    parser.add_argument(
        "--cobertura",
        action="store_true",
        help="ejecuta y mide qué líneas llegaron a correr (con el intérprete de árbol)",
    )
    parser.add_argument(
        "--proyecto",
        metavar="NOMBRE",
        help="crea un proyecto JP nuevo: NOMBRE/principal.jp + pruebas + LEEME",
    )
    parser.add_argument(
        "--instalar",
        nargs="?",
        const="",
        default=None,
        metavar="ORIGEN",
        help="instala un paquete JP (github:usuario/repo, carpeta local...); sin origen, las dependencias de paquete.json",
    )
    parser.add_argument(
        "--aqui",
        action="store_true",
        help="con --instalar: instala en ./paquetes en vez de en ~/.jp/paquetes",
    )
    parser.add_argument(
        "--paquetes",
        action="store_true",
        help="lista los paquetes JP instalados",
    )
    parser.add_argument(
        "--quitar-paquete",
        metavar="NOMBRE",
        help="desinstala un paquete JP",
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

    if args.cobertura:
        if args.archivo is None:
            parser.error("--cobertura necesita un archivo .jp")
        return _modo_cobertura(args.archivo)
    if args.revisar:
        if args.archivo is None:
            parser.error("--revisar necesita un archivo .jp")
        return _modo_revisar(args.archivo)
    if args.instalar is not None:
        return _modo_instalar(args.instalar or None, args.aqui)
    if args.paquetes:
        return _modo_paquetes()
    if args.quitar_paquete:
        return _modo_quitar_paquete(args.quitar_paquete)
    if args.proyecto:
        return _modo_proyecto(args.proyecto)
    if args.formatear:
        if args.archivo is None:
            parser.error("--formatear necesita un archivo .jp")
        return _modo_formatear(args.archivo, args.en_sitio)
    if args.depurar:
        if args.archivo is None:
            parser.error("--depurar necesita un archivo .jp")
        return _modo_depurar(args.archivo)
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
