"""Paridad del parser: `jp/parser.py` (Python) contra `motor-c/parser.c` (C).

Vuelca el AST de cada `.jp` del repositorio con los dos parsers, en un formato
de texto idéntico, y compara. Es el segundo marcador del frontend nativo: sin
el mismo árbol, el bytecode generado después no puede coincidir.

Uso:
    python herramientas/ast_paridad.py            # todos los .jp
    python herramientas/ast_paridad.py ejemplos    # sólo una carpeta

El binario se busca en `motor-c/jpast` (`jpast.exe` en Windows) o en la ruta
que diga `JPAST`. Se compila con `make -C motor-c jpast`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.arbol import (  # noqa: E402
    NodoAsignacion,
    NodoAsignacionLista,
    NodoAsignarIndice,
    NodoBinario,
    NodoBloque,
    NodoBooleano,
    NodoCadena,
    NodoClase,
    NodoDeclaracionLista,
    NodoDeclaracionVar,
    NodoDiccionario,
    NodoElegir,
    NodoExpresion,
    NodoFuncion,
    NodoImportar,
    NodoIndice,
    NodoIntentar,
    NodoInterpolacion,
    NodoLanzar,
    NodoLista,
    NodoLlamada,
    NodoMientras,
    NodoNulo,
    NodoNumero,
    NodoPara,
    NodoPrograma,
    NodoRango,
    NodoRetorna,
    NodoRomper,
    NodoContinuar,
    NodoSi,
    NodoUnario,
    NodoVariable,
)
from jp.errores import ErrorJP  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402

CARPETAS = ("ejemplos", "biblioteca", "pruebas", "paquetes", "docs")


def binario() -> Path:
    ruta = os.environ.get("JPAST")
    if ruta:
        return Path(ruta)
    nombre = "jpast.exe" if os.name == "nt" else "jpast"
    return RAIZ / "motor-c" / nombre


def escapar(texto: str | None) -> str:
    if texto is None:
        return "null"
    trozos = ['"']
    for caracter in texto:
        if caracter == '"':
            trozos.append('\\"')
        elif caracter == "\\":
            trozos.append("\\\\")
        elif caracter == "\n":
            trozos.append("\\n")
        elif caracter == "\t":
            trozos.append("\\t")
        elif caracter == "\r":
            trozos.append("\\r")
        elif ord(caracter) < 0x20:
            trozos.append(f"\\x{ord(caracter):02x}")
        else:
            trozos.append(caracter)
    trozos.append('"')
    return "".join(trozos)


def nombre_de_parametros(nodo: NodoFuncion):
    defectos = list(nodo.defectos or [])
    tipos = list(nodo.tipos or [])
    for indice, nombre in enumerate(nodo.parametros):
        defecto = defectos[indice] if indice < len(defectos) else None
        tipo = tipos[indice] if indice < len(tipos) else None
        yield nombre, tipo, defecto


def detalle(nodo) -> str:
    if isinstance(nodo, NodoDeclaracionVar):
        extra = f",tipo={nodo.tipo}" if nodo.tipo else ""
        return f"({nodo.nombre}{extra})"
    if isinstance(nodo, NodoVariable):
        return f"({nodo.nombre})"
    if isinstance(nodo, NodoAsignacion):
        return f"({nodo.nombre})"
    if isinstance(nodo, (NodoDeclaracionLista, NodoAsignacionLista)):
        return "(" + ",".join(nodo.nombres) + ")"
    if isinstance(nodo, (NodoBinario, NodoUnario)):
        return f"({nodo.operador})"
    if isinstance(nodo, (NodoLlamada, NodoIndice)):
        return f"(seguro={1 if nodo.seguro else 0})"
    if isinstance(nodo, (NodoLista, NodoDiccionario, NodoInterpolacion)):
        return f"({len(nodo.elementos if isinstance(nodo, NodoLista) else nodo.partes if isinstance(nodo, NodoInterpolacion) else nodo.pares)})"
    if isinstance(nodo, NodoRango):
        return f"(paso={1 if nodo.paso is not None else 0})"
    if isinstance(nodo, NodoFuncion):
        return f"({escapar(nodo.nombre)},{len(nodo.parametros)})"
    if isinstance(nodo, NodoNumero):
        if isinstance(nodo.valor, int) and not isinstance(nodo.valor, bool):
            return f"(int:{int(nodo.valor)})"
        return f"(double:{float(nodo.valor):.17g})"
    if isinstance(nodo, NodoCadena):
        return f"({escapar(nodo.valor)})"
    if isinstance(nodo, NodoBooleano):
        return f"({1 if nodo.valor else 0})"
    if isinstance(nodo, NodoClase):
        return f"({nodo.nombre},{nodo.padre or '-'})"
    if isinstance(nodo, NodoPara):
        return f"({nodo.variable},{nodo.variable2 or '-'})"
    if isinstance(nodo, NodoImportar):
        return f"({nodo.ruta},{nodo.alias or '-'})"
    if isinstance(nodo, NodoIntentar):
        return f"({nodo.nombre_error or '-'})"
    return ""


def nombre_nodo(nodo) -> str:
    if isinstance(nodo, NodoPrograma):
        return "PROGRAMA"
    if isinstance(nodo, NodoBloque):
        return "BLOQUE"
    if isinstance(nodo, NodoExpresion):
        return "EXPRESION"
    if isinstance(nodo, NodoDeclaracionVar):
        return "DECLVAR"
    if isinstance(nodo, NodoDeclaracionLista):
        return "DECLLISTA"
    if isinstance(nodo, NodoAsignacion):
        return "ASIGNA"
    if isinstance(nodo, NodoAsignacionLista):
        return "ASIGNALISTA"
    if isinstance(nodo, NodoAsignarIndice):
        return "ASIGINDICE"
    if isinstance(nodo, NodoBinario):
        return "BINARIO"
    if isinstance(nodo, NodoUnario):
        return "UNARIO"
    if isinstance(nodo, NodoLlamada):
        return "LLAMADA"
    if isinstance(nodo, NodoIndice):
        return "INDICE"
    if isinstance(nodo, NodoLista):
        return "LISTA"
    if isinstance(nodo, NodoRango):
        return "RANGO"
    if isinstance(nodo, NodoDiccionario):
        return "DICT"
    if isinstance(nodo, NodoInterpolacion):
        return "INTERPOLACION"
    if isinstance(nodo, NodoFuncion):
        return "FUNCION"
    if isinstance(nodo, NodoRetorna):
        return "RETORNA"
    if isinstance(nodo, NodoRomper):
        return "ROMPER"
    if isinstance(nodo, NodoContinuar):
        return "CONTINUAR"
    if isinstance(nodo, NodoLanzar):
        return "LANZAR"
    if isinstance(nodo, NodoImportar):
        return "IMPORTAR"
    if isinstance(nodo, NodoClase):
        return "CLASE"
    if isinstance(nodo, NodoSi):
        return "SI"
    if isinstance(nodo, NodoMientras):
        return "MIENTRAS"
    if isinstance(nodo, NodoPara):
        return "PARA"
    if isinstance(nodo, NodoElegir):
        return "ELEGIR"
    if isinstance(nodo, NodoIntentar):
        return "INTENTAR"
    if isinstance(nodo, NodoNumero):
        return "NUMERO"
    if isinstance(nodo, NodoCadena):
        return "CADENA"
    if isinstance(nodo, NodoBooleano):
        return "BOOLEANO"
    if isinstance(nodo, NodoNulo):
        return "NULO"
    if isinstance(nodo, NodoVariable):
        return "VARIABLE"
    raise AssertionError(f"nodo desconocido: {type(nodo).__name__}")


def volcar(nodo, nivel: int, lineas: list[str]) -> None:
    sangria = "  " * nivel
    if nodo is None:
        lineas.append(f"{sangria}(null)")
        return
    lineas.append(f"{sangria}{nombre_nodo(nodo)}{detalle(nodo)}@{nodo.linea}")

    def hijo(valor, subnivel=nivel + 1):
        volcar(valor, subnivel, lineas)

    if isinstance(nodo, (NodoPrograma, NodoBloque)):
        for sentencia in nodo.sentencias:
            hijo(sentencia)
    elif isinstance(nodo, NodoExpresion):
        hijo(nodo.expresion)
    elif isinstance(nodo, NodoDeclaracionVar):
        hijo(nodo.inicializador)
    elif isinstance(nodo, NodoDeclaracionLista):
        hijo(nodo.inicializador)
    elif isinstance(nodo, NodoAsignacionLista):
        hijo(nodo.valor)
    elif isinstance(nodo, NodoAsignacion):
        hijo(nodo.valor)
    elif isinstance(nodo, NodoAsignarIndice):
        hijo(nodo.objeto)
        hijo(nodo.indice)
        hijo(nodo.valor)
    elif isinstance(nodo, NodoBinario):
        hijo(nodo.izquierda)
        hijo(nodo.derecha)
    elif isinstance(nodo, NodoUnario):
        hijo(nodo.operando)
    elif isinstance(nodo, NodoLlamada):
        hijo(nodo.callee)
        for argumento in nodo.argumentos:
            hijo(argumento)
    elif isinstance(nodo, NodoIndice):
        hijo(nodo.objeto)
        hijo(nodo.indice)
    elif isinstance(nodo, NodoLista):
        for elemento in nodo.elementos:
            hijo(elemento)
    elif isinstance(nodo, NodoDiccionario):
        for clave, valor in nodo.pares:
            hijo(clave)
            hijo(valor)
    elif isinstance(nodo, NodoInterpolacion):
        for parte in nodo.partes:
            hijo(parte)
    elif isinstance(nodo, NodoRango):
        hijo(nodo.izquierda)
        hijo(nodo.derecha)
        if nodo.paso is not None:
            hijo(nodo.paso)
    elif isinstance(nodo, NodoFuncion):
        for nombre, tipo, defecto in nombre_de_parametros(nodo):
            extra = ",defecto" if defecto is not None else ""
            lineas.append(f"{'  ' * (nivel + 1)}PARAM({nombre},{tipo or '-'}{extra})@{nodo.linea}")
            if defecto is not None:
                volcar(defecto, nivel + 2, lineas)
        hijo(nodo.cuerpo)
    elif isinstance(nodo, NodoRetorna):
        if nodo.valor is not None:
            hijo(nodo.valor)
    elif isinstance(nodo, NodoLanzar):
        if nodo.expresion is not None:
            hijo(nodo.expresion)
    elif isinstance(nodo, NodoClase):
        for metodo in nodo.metodos:
            hijo(metodo)
    elif isinstance(nodo, NodoSi):
        hijo(nodo.condicion)
        hijo(nodo.entonces)
        if nodo.sino is not None:
            hijo(nodo.sino)
    elif isinstance(nodo, NodoMientras):
        hijo(nodo.condicion)
        hijo(nodo.cuerpo)
    elif isinstance(nodo, NodoPara):
        hijo(nodo.iterable)
        hijo(nodo.cuerpo)
    elif isinstance(nodo, NodoElegir):
        hijo(nodo.expresion)
        for valores, cuerpo in nodo.casos:
            lineas.append(f"{'  ' * (nivel + 1)}CASO({len(valores)})@{valores[0].linea}")
            for valor in valores:
                volcar(valor, nivel + 2, lineas)
            volcar(cuerpo, nivel + 2, lineas)
        if nodo.sino is not None:
            hijo(nodo.sino)
    elif isinstance(nodo, NodoIntentar):
        hijo(nodo.cuerpo)
        if nodo.captura is not None:
            hijo(nodo.captura)
        if nodo.finalmente is not None:
            hijo(nodo.finalmente)


def volcado_python(fuente: str) -> str:
    lineas: list[str] = []
    volcar(parsear(tokenizar(fuente)), 0, lineas)
    return "\n".join(lineas) + "\n"


def volcado_c(ejecutable: Path, ruta: Path) -> tuple[str | None, str | None]:
    proceso = subprocess.run(
        [str(ejecutable), str(ruta)], capture_output=True, text=True, encoding="utf-8"
    )
    if proceso.returncode != 0:
        partes = (proceso.stderr or "").strip().rsplit("|", 2)
        if len(partes) == 3 and partes[1].isdigit() and partes[2].isdigit():
            return None, "|".join(partes)
        return None, (proceso.stderr or "").strip()
    return proceso.stdout, None


def main(argv: list[str]) -> int:
    ejecutable = binario()
    if not ejecutable.is_file():
        print(f"ast_paridad: falta el binario {ejecutable}", file=sys.stderr)
        print("  compílalo con:  make -C motor-c jpast", file=sys.stderr)
        return 2

    carpetas = argv[1:] or CARPETAS
    archivos: list[Path] = []
    for carpeta in carpetas:
        base = RAIZ / carpeta
        if base.is_dir():
            archivos.extend(sorted(base.rglob("*.jp")))
    if not archivos:
        print("ast_paridad: no encontré archivos .jp", file=sys.stderr)
        return 2

    fallos = 0
    for ruta in archivos:
        fuente = ruta.read_text(encoding="utf-8")
        relativa = ruta.relative_to(RAIZ)
        try:
            esperado = volcado_python(fuente)
            error_python = None
        except ErrorJP as error:
            esperado = None
            error_python = f"{error.mensaje}|{error.linea}|{error.columna}"
        obtenido, error_c = volcado_c(ejecutable, ruta)

        if error_python or error_c:
            if error_python and error_c:
                if error_python != error_c:
                    print(f"✗ {relativa}: error distinto")
                    print(f"    Python: {error_python}")
                    print(f"    C:      {error_c}")
                    fallos += 1
                continue
            print(f"✗ {relativa}: sólo falla en {'Python' if error_python else 'C'}")
            print(f"    {error_python or error_c}")
            fallos += 1
            continue

        if esperado != obtenido:
            fallos += 1
            print(f"✗ {relativa}: el AST difiere")
            esperadas = esperado.splitlines()
            obtenidas = (obtenido or "").splitlines()
            for indice in range(max(len(esperadas), len(obtenidas))):
                a = esperadas[indice] if indice < len(esperadas) else "<falta>"
                b = obtenidas[indice] if indice < len(obtenidas) else "<falta>"
                if a != b:
                    print(f"    línea {indice + 1}:")
                    print(f"      Python: {a!r}")
                    print(f"      C:      {b!r}")
                    break

    total = len(archivos)
    print()
    if fallos:
        print(f"{fallos}/{total} archivos difieren entre los parsers")
        return 1
    print(f"{total}/{total} archivos producen el mismo AST")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
