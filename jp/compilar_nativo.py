"""Compilador de JP a bytecode nativo (.jpb) para el motor en C.

Filosofía (la clave de que esto no rompa nada):

    El frontend (lexer + parser) sigue siendo el mismo, probado con 245 tests.
    Este módulo es un *backend* alternativo: recorre el mismo AST y emite
    bytecode para `motor-c/jpvm`, una máquina virtual en C sin dependencias.

    Si un programa usa algo que el motor nativo todavía no implementa, este
    compilador se NIEGA con un mensaje claro (NoSoportadoNativo) y el CLI cae
    de vuelta al motor de Python. Nunca hay resultados silenciosamente distintos.

Semántica: se replica la del intérprete de referencia al pie de la letra
(división exacta que queda entera, módulo al estilo Python, tipos de error,
formato de impresión de `muestra`, verdad de JP donde 0 es verdadero...).

El formato .jpb es little-endian y está documentado en el encabezado de
`motor-c/jpvm.c`.
"""

from __future__ import annotations

import os
import struct

from .arbol import (
    Nodo,
    NodoAsignacion,
    NodoAsignarIndice,
    NodoBinario,
    NodoBloque,
    NodoBooleano,
    NodoCadena,
    NodoDeclaracionVar,
    NodoDiccionario,
    NodoElegir,
    NodoExpresion,
    NodoAsignacionLista,
    NodoClase,
    NodoDeclaracionLista,
    NodoFuncion,
    NodoImportar,
    NodoIndice,
    NodoIntentar,
    NodoInterpolacion,
    NodoLanzar,
    NodoLista,
    NodoLlamada,
    NodoMientras,
    NodoNumero,
    NodoNulo,
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

# ---------------------------------------------------------------- opcodes
# ¡Deben coincidir con el enum de motor-c/jpvm.c!

OP_NOP = 0
OP_CONST_I = 1        # i64
OP_CONST_D = 2        # f64
OP_CONST_S = 3        # u32 índice en la tabla de cadenas
OP_NULO = 4
OP_VERDADERO = 5
OP_FALSO = 6
OP_GET_LOCAL = 7      # u32 slot
OP_SET_LOCAL = 8      # u32 slot   (popea, deja el valor)
OP_GET_CELDA = 9      # u32 slot   (slot = celda capturada)
OP_SET_CELDA = 10     # u32 slot
OP_GET_GLOBAL = 11    # u32 gidx
OP_SET_GLOBAL = 12    # u32 gidx
OP_DECL_GLOBAL = 13   # u32 gidx
OP_GET_UPVAL = 14     # u32 idx
OP_SET_UPVAL = 15     # u32 idx
OP_POP = 16
OP_DUP = 17
OP_SUMA = 18
OP_RESTA = 19
OP_MULT = 20
OP_DIV = 21
OP_MOD = 22
OP_POT = 23
OP_NEG = 24
OP_NO = 25
OP_IGUAL = 26
OP_DIF = 27
OP_MENOR = 28
OP_MAYOR = 29
OP_MENOR_IG = 30
OP_MAYOR_IG = 31
OP_SALTO = 32                    # i32 relativo (desde la próxima instrucción)
OP_SALTO_FALSO = 33              # i32 rel
OP_SALTO_FALSO_MANTENER = 34     # i32 rel  (para 'y')
OP_SALTO_VERDAD_MANTENER = 35    # i32 rel  (para 'o')
OP_IMPRIMIR = 36                 # u32 argc
OP_LLAMAR = 37                   # u32 argc
OP_RETORNAR = 38
OP_RETORNAR_NULO = 39
OP_LISTA = 40                    # u32 n
OP_RANGO = 41                    # u8 tiene_paso
OP_INDICE = 42
OP_INDICE_ASIG = 43
OP_CIERRE = 44                   # u32 índice de función
OP_CELDA = 45                    # u32 slot -> slot = celda con el valor del slot
OP_ITER_INIT = 46                # u32 slot_iter
OP_ITER_NEXT = 47                # u32 slot_iter, u32 slot_var, i32 rel_si_fin
OP_ITER_NEXT_CELDA = 48          # igual pero slot_var = celda nueva
OP_EXPR_SENT = 49                # pop y guarda como último valor (REPL)
OP_FIN = 50
OP_DICT = 51                     # u32 n: n pares clave/valor en la pila
OP_MANEJAR = 52                  # u32 pc del bloque 'atrapa'
OP_FIN_MANEJAR = 53
OP_ERROR_EN = 54                 # u32 slot: guarda el mensaje del error capturado
OP_SALTO_NO_NULO_MANTENER = 55   # i32 rel  (para '??' y '?.': mira el tope, no popea)
OP_CREAR_CLASE = 56              # cadena nombre, u32 n, n×cadena método: pila [padre, m1..mn] -> clase
OP_DEFECTOS = 57                 # u32 mínimos: prólogo que exige los argumentos sin defecto
OP_SALTAR_SI_HAY_VALOR = 58      # u32 slot, i32 rel: si el slot no guarda el centinela, salta
OP_ITER_NEXT_PAR = 59            # u32 iter, u32 a, u32 b, i32 rel: (índice, valor) o (clave, valor)
OP_ITER_NEXT_PAR_CELDA = 60      # igual + u32 máscara (bit0/bit1 = a/b en celda) antes del salto
OP_DESESTRUCTURAR = 61           # u32 n: lista en la pila -> sus n elementos (en orden)
OP_VERIFICAR_TIPO = 62           # cadena tipo, cadena nombre: el tope debe cumplir el tipo
OP_VERIFICAR_ARG = 63            # u32 slot, cadena tipo, cadena nombre: el parámetro debe cumplirlo
OP_VERIFICAR_RET = 64            # cadena tipo: el tope (lo devuelto) debe cumplirlo

NOMBRES_OP = {
    OP_CONST_I: "CONST_I", OP_CONST_D: "CONST_D", OP_CONST_S: "CONST_S",
    OP_NULO: "NULO", OP_VERDADERO: "VERDADERO", OP_FALSO: "FALSO",
    OP_GET_LOCAL: "GET_LOCAL", OP_SET_LOCAL: "SET_LOCAL",
    OP_GET_CELDA: "GET_CELDA", OP_SET_CELDA: "SET_CELDA",
    OP_GET_GLOBAL: "GET_GLOBAL", OP_SET_GLOBAL: "SET_GLOBAL",
    OP_DECL_GLOBAL: "DECL_GLOBAL", OP_GET_UPVAL: "GET_UPVAL", OP_SET_UPVAL: "SET_UPVAL",
    OP_POP: "POP", OP_DUP: "DUP", OP_SUMA: "SUMA", OP_RESTA: "RESTA",
    OP_MULT: "MULT", OP_DIV: "DIV", OP_MOD: "MOD", OP_POT: "POT", OP_NEG: "NEG",
    OP_NO: "NO", OP_IGUAL: "IGUAL", OP_DIF: "DIF", OP_MENOR: "MENOR",
    OP_MAYOR: "MAYOR", OP_MENOR_IG: "MENOR_IG", OP_MAYOR_IG: "MAYOR_IG",
    OP_SALTO: "SALTO", OP_SALTO_FALSO: "SALTO_FALSO",
    OP_SALTO_FALSO_MANTENER: "SALTO_FALSO_MANTENER",
    OP_SALTO_VERDAD_MANTENER: "SALTO_VERDAD_MANTENER",
    OP_IMPRIMIR: "IMPRIMIR", OP_LLAMAR: "LLAMAR", OP_RETORNAR: "RETORNAR",
    OP_RETORNAR_NULO: "RETORNAR_NULO", OP_LISTA: "LISTA", OP_RANGO: "RANGO",
    OP_INDICE: "INDICE", OP_INDICE_ASIG: "INDICE_ASIG", OP_CIERRE: "CIERRE",
    OP_CELDA: "CELDA", OP_ITER_INIT: "ITER_INIT", OP_ITER_NEXT: "ITER_NEXT",
    OP_ITER_NEXT_CELDA: "ITER_NEXT_CELDA", OP_EXPR_SENT: "EXPR_SENT", OP_FIN: "FIN",
    OP_DICT: "DICT", OP_MANEJAR: "MANEJAR", OP_FIN_MANEJAR: "FIN_MANEJAR",
    OP_ERROR_EN: "ERROR_EN", OP_SALTO_NO_NULO_MANTENER: "SALTO_NO_NULO_MANTENER",
    OP_CREAR_CLASE: "CREAR_CLASE", OP_DEFECTOS: "DEFECTOS",
    OP_SALTAR_SI_HAY_VALOR: "SALTAR_SI_HAY_VALOR", OP_ITER_NEXT_PAR: "ITER_NEXT_PAR",
    OP_ITER_NEXT_PAR_CELDA: "ITER_NEXT_PAR_CELDA", OP_DESESTRUCTURAR: "DESESTRUCTURAR", OP_VERIFICAR_TIPO: "VERIFICAR_TIPO",
    OP_VERIFICAR_ARG: "VERIFICAR_ARG", OP_VERIFICAR_RET: "VERIFICAR_RET",
}

MAGIA = b"JPB1"
VERSION_FORMATO = 1


# Métodos que el motor en C todavía no implementa (se rechazan al compilar para
# que el CLI caiga al motor de Python con un aviso, en vez de fallar al ejecutar).
# Ahora mismo no queda ninguno: las funciones de orden superior ya están en C.
MÉTODOS_PENDIENTES: set[str] = set()


def _nativas_del_motor_c() -> frozenset[str]:
    """Nombres que el motor en C instala (`instalar_nativa(...)` en jpvm.c).

    Se leen de la fuente del motor para no tener dos listas que se
    desincronicen; si el archivo no está, se usa una copia congelada.
    """
    fuente = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "motor-c", "jpvm.c")
    if os.path.exists(fuente):
        import re

        with open(fuente, encoding="utf-8") as archivo:
            nombres = re.findall(r'instalar_nativa\("([a-z_]+)"', archivo.read())
        if nombres:
            return frozenset(nombres)
    return frozenset({
        "absoluto", "agregar", "agregar_archivo", "aleatorio", "azar", "buscar",
        "claves", "contiene", "coseno", "elementos", "eliminar", "empezar_con",
        "entero", "escribir_archivo", "esperar", "existe_archivo", "exp",
        "imprime", "indice_de", "insertar", "invertir", "json_leer", "json_texto",
        "leer", "leer_archivo", "letra", "lista_archivos", "log", "longitud",
        "maximo", "mayusculas", "minimo", "minusculas", "muestra", "numero",
        "pi", "piso", "potencia", "producto_punto", "promedio", "mediana", "norma",
        "distancia", "softmax", "sigmoide", "quitar", "raiz", "rango", "recortar",
        "redondear", "reemplazar", "reloj", "repetir", "seno", "separar",
        "subtexto", "sumar", "tamano_archivo", "techo", "terminar_con", "texto",
        "tiene", "tipo", "unir", "valores",
    })


NATIVAS_EN_C = _nativas_del_motor_c()


class NoSoportadoNativo(Exception):
    """El programa usa algo que el motor nativo en C todavía no implementa."""

    def __init__(self, que: str, linea: int = 0):
        super().__init__(que)
        self.que = que
        self.linea = linea


# ---------------------------------------------------------------- análisis

def _hijos(nodo: Nodo):
    """Recorre los nodos hijos de un nodo del AST (sin importar el campo)."""
    for valor in vars(nodo).values():
        if isinstance(valor, Nodo):
            yield valor
        elif isinstance(valor, list):
            for elemento in valor:
                if isinstance(elemento, Nodo):
                    yield elemento
                elif isinstance(elemento, tuple):
                    for dentro in elemento:
                        if isinstance(dentro, Nodo):
                            yield dentro


def _caminar(raiz: Nodo):
    """Recorre el árbol completo, nodo a nodo."""
    pila = [raiz]
    while pila:
        actual = pila.pop()
        yield actual
        pila.extend(_hijos(actual))


def _nombres_usados(nodo: Nodo, destino: set[str]) -> None:
    """Recorre un nodo juntando TODO nombre referenciado (conservador)."""
    pila: list[Nodo] = [nodo]
    while pila:
        actual = pila.pop()
        if actual is None:
            continue
        if isinstance(actual, NodoVariable):
            destino.add(actual.nombre)
        elif isinstance(actual, NodoAsignacion):
            destino.add(actual.nombre)
            pila.append(actual.valor)
        elif isinstance(actual, NodoDeclaracionVar):
            destino.add(actual.nombre)
            if actual.inicializador is not None:
                pila.append(actual.inicializador)
        elif isinstance(actual, NodoAsignarIndice):
            pila.extend((actual.objeto, actual.indice, actual.valor))
        elif isinstance(actual, NodoBinario):
            pila.extend((actual.izquierda, actual.derecha))
        elif isinstance(actual, NodoUnario):
            pila.append(actual.operando)
        elif isinstance(actual, NodoLlamada):
            pila.append(actual.callee)
            pila.extend(actual.argumentos)
        elif isinstance(actual, NodoIndice):
            pila.extend((actual.objeto, actual.indice))
        elif isinstance(actual, NodoLista):
            pila.extend(actual.elementos)
        elif isinstance(actual, NodoRango):
            pila.extend((actual.izquierda, actual.derecha))
            if actual.paso is not None:
                pila.append(actual.paso)
        elif isinstance(actual, NodoDiccionario):
            for clave, valor in actual.pares:
                pila.extend((clave, valor))
        elif isinstance(actual, NodoInterpolacion):
            pila.extend(actual.partes)
        elif isinstance(actual, NodoExpresion):
            pila.append(actual.expresion)
        elif isinstance(actual, NodoBloque):
            pila.extend(actual.sentencias)
        elif isinstance(actual, NodoPrograma):
            pila.extend(actual.sentencias)
        elif isinstance(actual, NodoDeclaracionVar):
            pass
        elif isinstance(actual, NodoSi):
            pila.extend((actual.condicion, actual.entonces))
            if actual.sino is not None:
                pila.append(actual.sino)
        elif isinstance(actual, NodoMientras):
            pila.extend((actual.condicion, actual.cuerpo))
        elif isinstance(actual, NodoPara):
            pila.extend((actual.iterable, actual.cuerpo))
            destino.add(actual.variable)
        elif isinstance(actual, NodoElegir):
            pila.append(actual.expresion)
            for valores, cuerpo in actual.casos:
                pila.extend(valores)
                pila.append(cuerpo)
            if actual.sino is not None:
                pila.append(actual.sino)
        elif isinstance(actual, NodoIntentar):
            pila.extend((actual.cuerpo, actual.captura))
            if actual.nombre_error:
                destino.add(actual.nombre_error)
        elif isinstance(actual, NodoFuncion):
            pila.append(actual.cuerpo)
            pila.extend(actual.parametros)
        elif isinstance(actual, NodoRetorna):
            if actual.valor is not None:
                pila.append(actual.valor)


def _nombres_declarados(nodo: Nodo) -> set[str]:
    """Nombres que declara un cuerpo: variables, parámetros, bucles y funciones.

    No baja a funciones anidadas (esas declaran lo suyo). Conservador: también
    cuenta lo declarado dentro de bloques, porque el compilador resuelve por
    orden de aparición y cualquier nombre declarado aquí puede acabar siendo
    el que capture una closure.
    """
    resultado: set[str] = set()
    pila = list(_hijos(nodo))
    while pila:
        actual = pila.pop()
        if isinstance(actual, NodoFuncion):
            continue  # frontera: declara en su propio ámbito
        if isinstance(actual, NodoDeclaracionVar):
            resultado.add(actual.nombre)
        elif isinstance(actual, NodoDeclaracionLista):
            resultado.update(actual.nombres)
        elif isinstance(actual, NodoPara):
            resultado.add(actual.variable)
            if actual.variable2:
                resultado.add(actual.variable2)
        elif isinstance(actual, NodoIntentar) and actual.nombre_error:
            resultado.add(actual.nombre_error)
        elif isinstance(actual, (NodoBloque, NodoPrograma)):
            pila.extend(actual.sentencias)
            continue
        pila.extend(_hijos(actual))
    return resultado


def _usados_de_funcion(funcion: NodoFuncion) -> set[str]:
    """Nombres que una función referencia: su cuerpo y, además, las
    expresiones de sus valores por defecto — un defecto puede usar
    parámetros anteriores y variables del ámbito que envuelve a la
    función, así que para encerrar en celdas cuentan igual que el
    cuerpo (v1.25)."""
    usados: set[str] = set()
    _nombres_usados(funcion.cuerpo, usados)
    for defecto in funcion.defectos or []:
        if defecto is None:
            continue
        for interno in _caminar(defecto):
            if isinstance(interno, NodoVariable):
                usados.add(interno.nombre)
            elif isinstance(interno, NodoFuncion):
                _nombres_usados(interno.cuerpo, usados)
    return usados


def _capturadas_por_anidadas(cuerpo: NodoBloque | None) -> set[str]:
    """Nombres de esta función que alguna función anidada podría capturar.

    Conservador a propósito: solo marca nombres que (a) usa alguna función
    anidada y (b) declara esta función. Marcar de más solo cuesta una celda;
    marcar de menos rompería las closures.
    """
    if cuerpo is None:
        return set()
    aqui = _nombres_declarados(cuerpo)
    usados: set[str] = set()
    for nodo in _caminar(cuerpo):
        if isinstance(nodo, NodoFuncion):
            usados |= _usados_de_funcion(nodo)
    return usados & aqui


# ---------------------------------------------------------------- contexto

class _Funcion:
    """Una función (o el programa principal) en construcción."""

    def __init__(self, nombre: str, aridad: int, capturadas: set[str]):
        self.nombre = nombre
        self.aridad = aridad
        self.capturadas = capturadas
        self.palabras: list[int] = []
        self.lineas: list[tuple[int, int]] = []   # (pc, línea)
        self.slots = 0
        self.es_celda: list[bool] = []
        self.upvalues: list[tuple[bool, int]] = []  # (es_local, índice)
        self.const_i: list[int] = []
        self.const_d: list[float] = []
        self.const_s: list[str] = []
        self.scopes: list[dict[str, int]] = [{}]

    # --- emisión (todo el bytecode son palabras de 32 bits) ---
    def emitir(self, op: int, *operandos: object, linea: int = 0) -> int:
        pc = len(self.palabras)
        self.lineas.append((pc, linea))
        self.palabras.append(op)
        for operando in operandos:
            if isinstance(operando, bool):
                raise TypeError("bool no es un operando válido")
            if isinstance(operando, float):
                crudo = struct.unpack("<II", struct.pack("<d", operando))
                self.palabras.extend(crudo)
            elif isinstance(operando, int):
                if not -2**31 <= operando < 2**31:
                    raise ValueError(f"operando fuera de rango: {operando}")
                self.palabras.append(operando & 0xFFFFFFFF)
            elif isinstance(operando, str):
                self.palabras.append(self._cadena(operando))
            else:
                raise TypeError(f"operando no soportado: {operando!r}")
        return pc

    def _cadena(self, texto: str) -> int:
        try:
            return self.const_s.index(texto)
        except ValueError:
            self.const_s.append(texto)
            return len(self.const_s) - 1

    def emitir_i64(self, valor: int, linea: int = 0) -> int:
        pc = len(self.palabras)
        self.lineas.append((pc, linea))
        self.palabras.append(OP_CONST_I)
        self.palabras.append(valor & 0xFFFFFFFF)
        self.palabras.append((valor >> 32) & 0xFFFFFFFF)
        return pc

    def emitir_f64(self, valor: float, linea: int = 0) -> int:
        pc = len(self.palabras)
        self.lineas.append((pc, linea))
        self.palabras.append(OP_CONST_D)
        self.palabras.extend(struct.unpack("<II", struct.pack("<d", valor)))
        return pc

    def emitir_salto(self, op: int, linea: int = 0) -> int:
        """Emite un salto con destino pendiente; devuelve la posición del hueco."""
        self.emitir(op, 0, linea=linea)
        return len(self.palabras) - 1

    def parchar(self, hueco: int, destino: int) -> None:
        """Rellena un salto relativo desde la instrucción siguiente."""
        relativo = destino - (hueco + 1)
        self.palabras[hueco] = relativo & 0xFFFFFFFF

    def parchar_aqui(self, hueco: int) -> None:
        self.parchar(hueco, len(self.palabras))

    def salto_a(self, destino: int, linea: int = 0) -> None:
        """Emite un salto hacia `destino` (posición ya conocida, hacia atrás)."""
        self.emitir(OP_SALTO, 0, linea=linea)
        self.parchar(len(self.palabras) - 1, destino)

    def declarar(self, nombre: str) -> int:
        slot = self.slots
        self.slots += 1
        self.es_celda.append(nombre in self.capturadas)
        self.scopes[-1][nombre] = slot
        return slot

    def reservar(self) -> int:
        """Slot oculto (iteradores): nunca es celda."""
        slot = self.slots
        self.slots += 1
        self.es_celda.append(False)
        return slot

    def buscar_local(self, nombre: str) -> tuple[int, bool] | None:
        for ambito in reversed(self.scopes):
            if nombre in ambito:
                indice = ambito[nombre]
                return indice, self.es_celda[indice]
        return None


class CompiladorNativo:
    """AST de JP -> blob .jpb para el motor en C."""

    def __init__(self, nombre_programa: str = "<código>"):
        self.nombre_programa = nombre_programa
        self.fuente = ""
        self.funciones: list[_Funcion] = []
        self.globales: dict[str, int] = {}
        self.globales_orden: list[str] = []
        self.declarados: set[str] = set()  # globales que el programa define
        self.pila: list[_Funcion] = []
        self.iteradores: list[tuple[int, list[int], int]] = []  # (inicio, saltos_romper, fin_esperado)
        self._retorno_esperado: str | None = None  # tipo de retorno de la función en curso

    # ------------------------------------------------------------ público

    def compilar(self, programa: NodoPrograma) -> bytes:
        principal = _Funcion("<programa>", 0, _capturadas_por_anidadas(programa))
        self.funciones.append(principal)
        self.pila.append(principal)
        self._bloque(programa.sentencias)
        principal.emitir(OP_RETORNAR_NULO)
        self.pila.pop()
        return self._empaquetar()

    # ----------------------------------------------------------- ayudas

    @property
    def actual(self) -> _Funcion:
        return self.pila[-1]

    def _global(self, nombre: str) -> int:
        if nombre not in self.globales:
            self.globales[nombre] = len(self.globales_orden)
            self.globales_orden.append(nombre)
        return self.globales[nombre]

    def _resolver(self, nombre: str) -> tuple[str, int]:
        """('local'|'celda'|'upval'|'global', índice).

        Reglas (idénticas a las del compilador de Python): un nombre declarado
        en alguna función que envuelve a la actual es una upvalue; si no está
        en ninguna, es global.
        """
        for nivel, funcion in enumerate(reversed(self.pila)):
            hallado = funcion.buscar_local(nombre)
            if hallado is None:
                continue
            indice, es_celda = hallado
            if nivel == 0:
                return ("celda" if es_celda else "local"), indice
            return ("upval", self._crear_upvalue(self.pila[-1], nombre))
        return ("global", self._global(nombre))

    def _crear_upvalue(self, funcion: _Funcion, nombre: str) -> int:
        """Índice de la upvalue `nombre` en `funcion`, creando la cadena si hace falta."""
        posicion = self.pila.index(funcion)
        if posicion == 0:
            raise NoSoportadoNativo(f"no encuentro la variable '{nombre}' para la closure")
        padre = self.pila[posicion - 1]
        hallado = padre.buscar_local(nombre)
        if hallado is not None:
            indice_slot, _ = hallado
            padre.es_celda[indice_slot] = True  # seguro: ya venía premarcado
            descripcion = (True, indice_slot)
        else:
            descripcion = (False, self._crear_upvalue(padre, nombre))
        if descripcion in funcion.upvalues:
            return funcion.upvalues.index(descripcion)
        funcion.upvalues.append(descripcion)
        return len(funcion.upvalues) - 1

    def _abrir(self) -> None:
        self.actual.scopes.append({})

    def _cerrar(self) -> None:
        self.actual.scopes.pop()

    # ------------------------------------------------------- sentencias

    def _bloque(self, sentencias: list[Nodo], ambito_nuevo: bool = False) -> None:
        if ambito_nuevo:
            self._abrir()
        for sentencia in sentencias:
            self._sentencia(sentencia)
        if ambito_nuevo:
            self._cerrar()

    def _sentencia(self, nodo: Nodo) -> None:
        actual = self.actual
        linea = getattr(nodo, "linea", 0)
        tipo = type(nodo)

        if tipo is NodoPrograma:
            self._bloque(nodo.sentencias)

        elif tipo is NodoDeclaracionVar:
            self._declarar(nodo.nombre, nodo.inicializador, linea, getattr(nodo, "tipo", None))

        elif tipo is NodoFuncion:
            self._declarar_funcion(nodo)

        elif tipo is NodoImportar:
            raise NoSoportadoNativo("los módulos ('importar') aún no están en el motor nativo", linea)

        elif tipo is NodoClase:
            self._declarar_clase(nodo)

        elif tipo is NodoLanzar:
            raise NoSoportadoNativo("'lanzar' aún no está en el motor nativo", linea)

        elif tipo is NodoDeclaracionLista:
            self._expresion(nodo.inicializador)
            actual.emitir(OP_DESESTRUCTURAR, len(nodo.nombres), linea=linea)
            self._guardar_desestructurado(nodo.nombres, linea, declarar=True)

        elif tipo is NodoExpresion:
            self._expresion(nodo.expresion)
            actual.emitir(OP_EXPR_SENT, linea=linea)

        elif tipo is NodoBloque:
            self._bloque(nodo.sentencias, ambito_nuevo=True)

        elif tipo is NodoSi:
            self._expresion(nodo.condicion)
            salto_sino = actual.emitir_salto(OP_SALTO_FALSO, linea)
            self._bloque(nodo.entonces.sentencias, ambito_nuevo=True)
            if nodo.sino is not None:
                salto_fin = actual.emitir_salto(OP_SALTO, linea)
                actual.parchar_aqui(salto_sino)
                self._bloque(nodo.sino.sentencias, ambito_nuevo=True)
                actual.parchar_aqui(salto_fin)
            else:
                actual.parchar_aqui(salto_sino)

        elif tipo is NodoMientras:
            inicio = len(actual.palabras)
            self._expresion(nodo.condicion)
            salto_fin = actual.emitir_salto(OP_SALTO_FALSO, linea)
            self.iteradores.append((inicio, [], len(actual.palabras)))
            self._bloque(nodo.cuerpo.sentencias, ambito_nuevo=True)
            _, saltos_romper, _ = self.iteradores.pop()
            actual.salto_a(inicio, linea)
            actual.parchar_aqui(salto_fin)
            for hueco in saltos_romper:
                actual.parchar_aqui(hueco)

        elif tipo is NodoPara:
            self._para(nodo)

        elif tipo is NodoRetorna:
            if nodo.valor is not None:
                self._expresion(nodo.valor)
            elif self._retorno_esperado is not None:
                actual.emitir(OP_NULO, linea=linea)
            if self._retorno_esperado is not None:
                actual.emitir(OP_VERIFICAR_RET, self._retorno_esperado, linea=linea)
                actual.emitir(OP_RETORNAR, linea=linea)
            elif nodo.valor is not None:
                actual.emitir(OP_RETORNAR, linea=linea)
            else:
                actual.emitir(OP_RETORNAR_NULO, linea=linea)

        elif tipo is NodoRomper:
            if not self.iteradores:
                raise NoSoportadoNativo("'romper' fuera de un bucle", linea)
            hueco = actual.emitir_salto(OP_SALTO, linea)
            self.iteradores[-1][1].append(hueco)

        elif tipo is NodoContinuar:
            if not self.iteradores:
                raise NoSoportadoNativo("'continuar' fuera de un bucle", linea)
            inicio = self.iteradores[-1][0]
            actual.salto_a(inicio, linea)

        elif tipo is NodoDiccionario:
            for clave, valor in nodo.pares:
                self._expresion(clave)
                self._expresion(valor)
            actual.emitir(OP_DICT, len(nodo.pares), linea=linea)

        elif tipo is NodoElegir:
            # el valor se guarda en un slot oculto: se evalúa una sola vez
            self._expresion(nodo.expresion)
            reservado = actual.reservar()
            actual.emitir(OP_SET_LOCAL, reservado, linea=linea)
            actual.emitir(OP_POP, linea=linea)
            saltos_fin: list[int] = []
            for valores, cuerpo in nodo.casos:
                for indice_candidato, candidato in enumerate(valores):
                    actual.emitir(OP_GET_LOCAL, reservado, linea=linea)
                    self._expresion(candidato)
                    actual.emitir(OP_IGUAL, linea=linea)
                    hueco = actual.emitir_salto(OP_SALTO_FALSO, linea)
                    if indice_candidato < len(valores) - 1:
                        # el salto cae al siguiente candidato: no hay nada que parchar
                        continue
                    salto_cuerpo = hueco
                self._bloque(cuerpo.sentencias, ambito_nuevo=True)
                saltos_fin.append(actual.emitir_salto(OP_SALTO, linea))
                # si ningún candidato coincidió, se salta el cuerpo
                actual.parchar_aqui(salto_cuerpo)
            if nodo.sino is not None:
                self._bloque(nodo.sino.sentencias, ambito_nuevo=True)
            for hueco in saltos_fin:
                actual.parchar_aqui(hueco)

        elif tipo is NodoIntentar:
            if nodo.finalmente is not None or nodo.captura is None:
                raise NoSoportadoNativo("'finalmente' aún no está en el motor nativo", linea)
            manejador = actual.emitir(OP_MANEJAR, 0, linea=linea)
            hueco = len(actual.palabras) - 1
            self._bloque(nodo.cuerpo.sentencias, ambito_nuevo=True)
            actual.emitir(OP_FIN_MANEJAR, linea=linea)
            salto_fin = actual.emitir_salto(OP_SALTO, linea)
            actual.parchar(hueco, len(actual.palabras))
            self._abrir()
            if nodo.nombre_error is not None:
                slot = actual.declarar(nodo.nombre_error)
                actual.emitir(OP_ERROR_EN, slot, linea=linea)
                if actual.es_celda[slot]:
                    actual.emitir(OP_CELDA, slot, linea=linea)
            self._bloque(nodo.captura.sentencias)
            self._cerrar()
            actual.parchar_aqui(salto_fin)
            del manejador

        else:
            raise NoSoportadoNativo(f"sentencia no soportada: {tipo.__name__}", linea)

    def _declarar(self, nombre: str, inicializador: Nodo | None, linea: int,
                  tipo: str | None = None) -> None:
        actual = self.actual
        # ¿estamos en el nivel superior del programa? entonces es global
        if len(self.pila) == 1 and len(actual.scopes) == 1:
            if inicializador is not None:
                self._expresion(inicializador)
            else:
                actual.emitir(OP_NULO, linea=linea)
            if tipo is not None:
                actual.emitir(OP_VERIFICAR_TIPO, tipo, nombre, linea=linea)
            self.declarados.add(nombre)
            actual.emitir(OP_DECL_GLOBAL, self._global(nombre), linea=linea)
            actual.emitir(OP_POP, linea=linea)
            return
        slot = actual.declarar(nombre)
        if inicializador is not None:
            self._expresion(inicializador)
        else:
            actual.emitir(OP_NULO, linea=linea)
        if tipo is not None:
            actual.emitir(OP_VERIFICAR_TIPO, tipo, nombre, linea=linea)
        actual.emitir(OP_SET_LOCAL, slot, linea=linea)
        if actual.es_celda[slot]:
            # la variable la captura una closure: el slot pasa a ser una celda
            actual.emitir(OP_CELDA, slot, linea=linea)
        actual.emitir(OP_POP, linea=linea)

    def _declarar_funcion(self, nodo: NodoFuncion) -> None:
        actual = self.actual
        linea = nodo.linea
        indice = self._compilar_funcion(nodo)
        if len(self.pila) == 1 and len(actual.scopes) == 1:
            self.declarados.add(nodo.nombre)
            actual.emitir(OP_CIERRE, indice, linea=linea)
            actual.emitir(OP_DECL_GLOBAL, self._global(nodo.nombre), linea=linea)
            actual.emitir(OP_POP, linea=linea)
            return
        slot = actual.declarar(nodo.nombre)
        actual.emitir(OP_CIERRE, indice, linea=linea)
        actual.emitir(OP_SET_LOCAL, slot, linea=linea)
        if actual.es_celda[slot]:
            actual.emitir(OP_CELDA, slot, linea=linea)
        actual.emitir(OP_POP, linea=linea)

    def _declarar_clase(self, nodo: NodoClase) -> None:
        """clase Nombre [hereda Padre] { ... } (v1.25): cada método se
        compila como una función con 'este' como primer parámetro (el
        motor liga el receptor al llamar, igual que MetodoLigado en
        Python) y CREAR_CLASE junta padre + métodos en un valor clase."""
        actual = self.actual
        linea = nodo.linea
        indices = []
        for metodo in nodo.metodos:
            adaptado = NodoFuncion(
                nombre=metodo.nombre,
                parametros=["este", *metodo.parametros],
                cuerpo=metodo.cuerpo,
                linea=metodo.linea,
                defectos=[None, *(metodo.defectos or [])],
                tipos=[None, *(metodo.tipos or [])],
                tipo_retorno=metodo.tipo_retorno,
            )
            indices.append(self._compilar_funcion(adaptado))
        if nodo.padre is not None:
            self._expresion(NodoVariable(nodo.padre, linea))
        else:
            actual.emitir(OP_NULO, linea=linea)
        for indice in indices:
            actual.emitir(OP_CIERRE, indice, linea=linea)
        actual.emitir(OP_CREAR_CLASE, nodo.nombre, len(indices),
                      *[m.nombre for m in nodo.metodos], linea=linea)
        if len(self.pila) == 1 and len(actual.scopes) == 1:
            self.declarados.add(nodo.nombre)
            actual.emitir(OP_DECL_GLOBAL, self._global(nodo.nombre), linea=linea)
            actual.emitir(OP_POP, linea=linea)
            return
        slot = actual.declarar(nodo.nombre)
        actual.emitir(OP_SET_LOCAL, slot, linea=linea)
        if actual.es_celda[slot]:
            actual.emitir(OP_CELDA, slot, linea=linea)
        actual.emitir(OP_POP, linea=linea)

    def _guardar_desestructurado(self, nombres: list[str], linea: int, declarar: bool) -> None:
        """Guarda los n elementos que DESESTRUCTURAR dejó en la pila.

        Se recorre al revés porque el último elemento es el que está en
        el top. Con `declarar` liga nombres nuevos (como `_declarar`);
        sin él, asigna a nombres que ya existen y la lista original
        queda debajo como valor de la expresión."""
        actual = self.actual
        for nombre in reversed(nombres):
            if declarar:
                if len(self.pila) == 1 and len(actual.scopes) == 1:
                    self.declarados.add(nombre)
                    actual.emitir(OP_DECL_GLOBAL, self._global(nombre), linea=linea)
                    actual.emitir(OP_POP, linea=linea)
                    continue
                slot = actual.declarar(nombre)
                actual.emitir(OP_SET_LOCAL, slot, linea=linea)
                if actual.es_celda[slot]:
                    actual.emitir(OP_CELDA, slot, linea=linea)
                actual.emitir(OP_POP, linea=linea)
            else:
                clase, indice = self._resolver(nombre)
                if clase == "local":
                    actual.emitir(OP_SET_LOCAL, indice, linea=linea)
                elif clase == "celda":
                    actual.emitir(OP_SET_CELDA, indice, linea=linea)
                elif clase == "upval":
                    actual.emitir(OP_SET_UPVAL, indice, linea=linea)
                else:
                    actual.emitir(OP_SET_GLOBAL, indice, linea=linea)
                actual.emitir(OP_POP, linea=linea)

    def _compilar_funcion(self, nodo: NodoFuncion) -> int:
        # los parámetros también pueden acabar en una closure: si una función
        # anidada los usa, el parámetro tiene que vivir en una celda desde el
        # primer instante (si no, la closure capturaría el valor crudo).
        defectos = list(getattr(nodo, "defectos", []) or [])
        defectos += [None] * (len(nodo.parametros) - len(defectos))
        usados: set[str] = set()
        for interno in _caminar(nodo.cuerpo):
            if isinstance(interno, NodoFuncion):
                usados |= _usados_de_funcion(interno)
        for defecto in defectos:
            if defecto is not None:
                for interno in _caminar(defecto):
                    if isinstance(interno, NodoFuncion):
                        usados |= _usados_de_funcion(interno)
        capturadas = _capturadas_por_anidadas(nodo.cuerpo) | (usados & set(nodo.parametros))
        tipos = list(getattr(nodo, "tipos", []) or [])
        tipos += [None] * (len(nodo.parametros) - len(tipos))
        funcion = _Funcion(nodo.nombre or "<anónima>", len(nodo.parametros), capturadas)
        for parametro in nodo.parametros:
            funcion.declarar(parametro)
        self.funciones.append(funcion)
        indice = len(self.funciones) - 1
        self.pila.append(funcion)
        if any(d is not None for d in defectos):
            # Valores por defecto (v1.25): la llamada rellena los huecos
            # con un centinela; el prólogo exige los obligatorios y
            # sustituye cada centinela por su defecto (que puede usar
            # los parámetros anteriores, ya con valor).
            requeridos = sum(1 for d in defectos if d is None)
            funcion.emitir(OP_DEFECTOS, requeridos, linea=nodo.linea)
            for i, defecto in enumerate(defectos):
                if defecto is None:
                    continue
                funcion.emitir(OP_SALTAR_SI_HAY_VALOR, i, 0, linea=nodo.linea)
                hueco = len(funcion.palabras) - 1
                self._expresion(defecto)
                funcion.emitir(OP_SET_LOCAL, i, linea=nodo.linea)
                funcion.emitir(OP_POP, linea=nodo.linea)
                funcion.parchar_aqui(hueco)
        # Tipos opcionales (v1.27): ya con los defectos aplicados, cada
        # parámetro anotado se comprueba antes de encerrar en celdas.
        for i, tipo in enumerate(tipos):
            if tipo is not None:
                funcion.emitir(OP_VERIFICAR_ARG, i, tipo, nodo.parametros[i], linea=nodo.linea)
        # las parámetros capturados necesitan celda desde el arranque
        for slot, es_celda in enumerate(funcion.es_celda[:len(nodo.parametros)]):
            if es_celda:
                # el argumento ya vive en el slot: se convierte en celda sin tocar la pila
                funcion.emitir(OP_CELDA, slot, linea=nodo.linea)
        retorno_anterior = self._retorno_esperado
        self._retorno_esperado = nodo.tipo_retorno
        self._bloque(nodo.cuerpo.sentencias, ambito_nuevo=True)
        self._retorno_esperado = retorno_anterior
        if nodo.tipo_retorno is not None:
            # también el 'devuelve' implícito del final se comprueba
            funcion.emitir(OP_NULO, linea=nodo.linea)
            funcion.emitir(OP_VERIFICAR_RET, nodo.tipo_retorno, linea=nodo.linea)
            funcion.emitir(OP_RETORNAR, linea=nodo.linea)
        else:
            funcion.emitir(OP_RETORNAR_NULO, linea=nodo.linea)
        self.pila.pop()
        return indice

    def _para(self, nodo: NodoPara) -> None:
        actual = self.actual
        linea = nodo.linea
        slot_iter = actual.reservar()
        self._expresion(nodo.iterable)
        actual.emitir(OP_ITER_INIT, slot_iter, linea=linea)
        inicio = len(actual.palabras)
        self.iteradores.append((inicio, [], len(actual.palabras)))
        self._abrir()
        slot_var = actual.declarar(nodo.variable)
        if nodo.variable2 is not None:
            slot_var2 = actual.declarar(nodo.variable2)
            en_celda = actual.es_celda[slot_var] or actual.es_celda[slot_var2]
            if en_celda:
                mascara = (1 if actual.es_celda[slot_var] else 0) | (2 if actual.es_celda[slot_var2] else 0)
                actual.emitir(OP_ITER_NEXT_PAR_CELDA, slot_iter, slot_var, slot_var2, mascara, 0, linea=linea)
            else:
                actual.emitir(OP_ITER_NEXT_PAR, slot_iter, slot_var, slot_var2, 0, linea=linea)
        else:
            op = OP_ITER_NEXT_CELDA if actual.es_celda[slot_var] else OP_ITER_NEXT
            actual.emitir(op, slot_iter, slot_var, 0, linea=linea)
        hueco = len(actual.palabras) - 1
        self._bloque(nodo.cuerpo.sentencias)
        _, saltos_romper, _ = self.iteradores.pop()
        actual.salto_a(inicio, linea)
        actual.parchar_aqui(hueco)
        for hueco_romper in saltos_romper:
            actual.parchar_aqui(hueco_romper)
        self._cerrar()

    # ------------------------------------------------------ expresiones

    def _expresion(self, nodo: Nodo | None) -> None:
        actual = self.actual
        linea = getattr(nodo, "linea", 0)
        tipo = type(nodo)

        if tipo is NodoNumero:
            valor = nodo.valor
            if isinstance(valor, bool):  # imposible, pero explícito
                actual.emitir(OP_VERDADERO if valor else OP_FALSO, linea=linea)
            elif isinstance(valor, int):
                if not -2**63 <= valor < 2**63:
                    # Python tiene enteros de precisión arbitraria; el motor
                    # nativo usa 64 bits. Antes de dar un número distinto, se
                    # rechaza y el CLI sigue con el motor de Python.
                    raise NoSoportadoNativo(
                        "los enteros de más de 64 bits aún no están en el motor nativo "
                        f"(el {valor} de la línea) — el motor de Python los soporta",
                        linea,
                    )
                actual.emitir_i64(valor, linea)
            else:
                actual.emitir_f64(float(valor), linea)

        elif tipo is NodoCadena:
            actual.emitir(OP_CONST_S, nodo.valor, linea=linea)

        elif tipo is NodoBooleano:
            actual.emitir(OP_VERDADERO if nodo.valor else OP_FALSO, linea=linea)

        elif tipo is NodoNulo:
            actual.emitir(OP_NULO, linea=linea)

        elif tipo is NodoVariable:
            clase, indice = self._resolver(nodo.nombre)
            if clase == "local":
                actual.emitir(OP_GET_LOCAL, indice, linea=linea)
            elif clase == "celda":
                actual.emitir(OP_GET_CELDA, indice, linea=linea)
            elif clase == "upval":
                actual.emitir(OP_GET_UPVAL, indice, linea=linea)
            else:
                actual.emitir(OP_GET_GLOBAL, indice, linea=linea)

        elif tipo is NodoAsignacion:
            self._expresion(nodo.valor)
            clase, indice = self._resolver(nodo.nombre)
            if clase == "local":
                actual.emitir(OP_SET_LOCAL, indice, linea=linea)
            elif clase == "celda":
                actual.emitir(OP_SET_CELDA, indice, linea=linea)
            elif clase == "upval":
                actual.emitir(OP_SET_UPVAL, indice, linea=linea)
            else:
                actual.emitir(OP_SET_GLOBAL, indice, linea=linea)

        elif tipo is NodoBinario:
            self._binario(nodo)

        elif tipo is NodoUnario:
            self._expresion(nodo.operando)
            if nodo.operador == "-":
                actual.emitir(OP_NEG, linea=linea)
            elif nodo.operador == "no":
                actual.emitir(OP_NO, linea=linea)
            else:
                raise NoSoportadoNativo(f"operador unario desconocido: {nodo.operador}", linea)

        elif tipo is NodoLlamada:
            if nodo.seguro:
                # [callee]; si es nulo salta al fin (queda el nulo, sin
                # evaluar argumentos); si no, llamada normal.
                actual = self.actual
                self._expresion(nodo.callee)
                a_cont = actual.emitir_salto(OP_SALTO_NO_NULO_MANTENER, linea)
                al_fin = actual.emitir_salto(OP_SALTO, linea)
                actual.parchar_aqui(a_cont)
                for argumento in nodo.argumentos:
                    self._expresion(argumento)
                actual.emitir(OP_LLAMAR, len(nodo.argumentos), linea=linea)
                actual.parchar_aqui(al_fin)
                return
            if isinstance(nodo.callee, NodoIndice) and MÉTODOS_PENDIENTES:
                # Solo se rechaza lo que el motor en C todavía no sabe hacer: si no,
                # sería un error en tiempo de ejecución en vez de una caída limpia.
                indice = nodo.callee.indice
                if isinstance(indice, NodoCadena) and indice.valor in MÉTODOS_PENDIENTES:
                    raise NoSoportadoNativo(
                        f"el método '{indice.valor}()' aún no está en el motor nativo", linea
                    )
            self._expresion(nodo.callee)
            for argumento in nodo.argumentos:
                self._expresion(argumento)
            actual.emitir(OP_LLAMAR, len(nodo.argumentos), linea=linea)

        elif tipo is NodoIndice:
            if nodo.seguro:
                # [objeto]; si es nulo salta al fin (queda el nulo); si no,
                # indice + INDICE como siempre.
                actual = self.actual
                self._expresion(nodo.objeto)
                a_cont = actual.emitir_salto(OP_SALTO_NO_NULO_MANTENER, linea)
                al_fin = actual.emitir_salto(OP_SALTO, linea)
                actual.parchar_aqui(a_cont)
                self._expresion(nodo.indice)
                actual.emitir(OP_INDICE, linea=linea)
                actual.parchar_aqui(al_fin)
                return
            self._expresion(nodo.objeto)
            self._expresion(nodo.indice)
            actual.emitir(OP_INDICE, linea=linea)

        elif tipo is NodoLista:
            for elemento in nodo.elementos:
                self._expresion(elemento)
            actual.emitir(OP_LISTA, len(nodo.elementos), linea=linea)

        elif tipo is NodoRango:
            self._expresion(nodo.izquierda)
            self._expresion(nodo.derecha)
            if nodo.paso is None:
                actual.emitir(OP_RANGO, 0, linea=linea)
            else:
                self._expresion(nodo.paso)
                actual.emitir(OP_RANGO, 1, linea=linea)

        elif tipo is NodoAsignarIndice:
            self._expresion(nodo.objeto)
            self._expresion(nodo.indice)
            self._expresion(nodo.valor)
            actual.emitir(OP_INDICE_ASIG, linea=linea)

        elif tipo is NodoFuncion:
            indice = self._compilar_funcion(nodo)
            actual.emitir(OP_CIERRE, indice, linea=linea)

        elif tipo is NodoAsignacionLista:
            self._expresion(nodo.valor)
            actual.emitir(OP_DUP, linea=linea)
            actual.emitir(OP_DESESTRUCTURAR, len(nodo.nombres), linea=linea)
            self._guardar_desestructurado(nodo.nombres, linea, declarar=False)

        elif tipo is NodoDiccionario:
            for clave, valor in nodo.pares:
                self._expresion(clave)
                self._expresion(valor)
            actual.emitir(OP_DICT, len(nodo.pares), linea=linea)

        elif tipo is NodoInterpolacion:
            # "hola {nombre}!" es azúcar de suma: texto + valor + texto, y el
            # `+` de JP ya convierte con jp_a_texto cuando hay un texto.
            if not nodo.partes:
                actual.emitir(OP_CONST_S, "", linea=linea)
                return
            for indice, parte in enumerate(nodo.partes):
                self._expresion(parte)
                if indice:
                    actual.emitir(OP_SUMA, linea=linea)

        else:
            raise NoSoportadoNativo(f"expresión no soportada: {tipo.__name__}", linea)

    def _binario(self, nodo: NodoBinario) -> None:
        actual = self.actual
        linea = nodo.linea
        operador = nodo.operador

        if operador == "y":
            self._expresion(nodo.izquierda)
            hueco = actual.emitir_salto(OP_SALTO_FALSO_MANTENER, linea)
            actual.emitir(OP_POP, linea=linea)
            self._expresion(nodo.derecha)
            actual.parchar_aqui(hueco)
            return
        if operador == "??":
            # Igual que 'o' pero la condicion es "no es nulo": si lo de la
            # izquierda no es nulo se conserva; si es nulo, se calcula lo otro.
            self._expresion(nodo.izquierda)
            hueco = actual.emitir_salto(OP_SALTO_NO_NULO_MANTENER, linea)
            actual.emitir(OP_POP, linea=linea)
            self._expresion(nodo.derecha)
            actual.parchar_aqui(hueco)
            return
        if operador == "o":
            self._expresion(nodo.izquierda)
            hueco = actual.emitir_salto(OP_SALTO_VERDAD_MANTENER, linea)
            actual.emitir(OP_POP, linea=linea)
            self._expresion(nodo.derecha)
            actual.parchar_aqui(hueco)
            return

        self._expresion(nodo.izquierda)
        self._expresion(nodo.derecha)
        opciones = {
            "+": OP_SUMA, "-": OP_RESTA, "*": OP_MULT, "/": OP_DIV, "%": OP_MOD,
            "**": OP_POT, "==": OP_IGUAL, "!=": OP_DIF, "<": OP_MENOR,
            ">": OP_MAYOR, "<=": OP_MENOR_IG, ">=": OP_MAYOR_IG,
        }
        op = opciones.get(operador)
        if op is None:
            raise NoSoportadoNativo(f"operador desconocido: {operador}", linea)
        actual.emitir(op, linea=linea)

    # -------------------------------------------------------- empaquetar

    def _empaquetar(self) -> bytes:
        # Un nombre global que el programa no declara tiene que ser una nativa:
        # si el motor en C no la trae, se rechaza aquí (y el CLI sigue con el
        # motor de Python) en vez de fallar en tiempo de ejecución.
        for nombre in self.globales_orden:
            if nombre in self.declarados or nombre in NATIVAS_EN_C:
                continue
            raise NoSoportadoNativo(
                f"la función nativa '{nombre}' aún no está en el motor nativo "
                "(el motor de Python sí la tiene)"
            )

        # tabla de cadenas global (nombres de globales + cadenas por función)
        cadenas: dict[str, int] = {}

        def cadena(texto: str) -> int:
            if texto not in cadenas:
                cadenas[texto] = len(cadenas)
            return cadenas[texto]

        for nombre in self.globales_orden:
            cadena(nombre)
        for funcion in self.funciones:
            cadena(funcion.nombre)
            for texto in funcion.const_s:
                cadena(texto)

        orden = sorted(cadenas, key=cadenas.__getitem__)

        salida = bytearray()
        salida += MAGIA
        salida += struct.pack("<IIIII", VERSION_FORMATO, len(self.funciones),
                              len(orden), len(self.globales_orden), 0)
        # cadenas
        for texto in orden:
            datos = texto.encode("utf-8")
            salida += struct.pack("<I", len(datos))
            salida += datos
        # nombres de globales
        for nombre in self.globales_orden:
            salida += struct.pack("<I", cadenas[nombre])
        # funciones
        for funcion in self.funciones:
            salida += struct.pack("<III", cadenas[funcion.nombre], funcion.aridad, funcion.slots)
            salida += bytes(1 if celda else 0 for celda in funcion.es_celda)
            salida += struct.pack("<I", len(funcion.upvalues))
            for es_local, indice in funcion.upvalues:
                salida += struct.pack("<BI", 1 if es_local else 0, indice)
            salida += struct.pack("<I", len(funcion.const_i))
            for valor in funcion.const_i:
                salida += struct.pack("<q", valor)
            salida += struct.pack("<I", len(funcion.const_d))
            for valor in funcion.const_d:
                salida += struct.pack("<d", valor)
            salida += struct.pack("<I", len(funcion.const_s))
            for texto in funcion.const_s:
                salida += struct.pack("<I", cadenas[texto])
            salida += struct.pack("<I", len(funcion.palabras))
            if funcion.palabras:
                salida += struct.pack(f"<{len(funcion.palabras)}I", *funcion.palabras)
            salida += struct.pack("<I", len(funcion.lineas))
            for pc, numero in funcion.lineas:
                salida += struct.pack("<II", pc, numero)
        # el código fuente (para errores con la línea culpable, como el de Python)
        fuente = self.fuente.encode("utf-8")
        salida += struct.pack("<I", len(fuente))
        salida += fuente
        return bytes(salida)


def compilar_a_bytes(programa: NodoPrograma, nombre: str = "<código>", fuente: str = "") -> bytes:
    """Compila un AST de JP al blob .jpb del motor nativo en C."""
    compilador = CompiladorNativo(nombre)
    compilador.fuente = fuente
    return compilador.compilar(programa)


# ------------------------------------------------------------- desensamblado

def desensamblar_blob(blob: bytes) -> str:
    """Desensambla un .jpb (para depurar el compilador y el motor)."""
    pos = 4
    version, n_fun, n_cadenas, n_globales, _ = struct.unpack_from("<IIIII", blob, pos)
    pos += 20
    cadenas: list[str] = []
    for _ in range(n_cadenas):
        (largo,) = struct.unpack_from("<I", blob, pos)
        pos += 4
        cadenas.append(blob[pos:pos + largo].decode("utf-8"))
        pos += largo
    globales: list[str] = []
    for _ in range(n_globales):
        (indice,) = struct.unpack_from("<I", blob, pos)
        pos += 4
        globales.append(cadenas[indice])

    lineas_salida = [f"JPB1 v{version}: {n_fun} función(es), {n_globales} global(es)"]
    for indice_fun in range(n_fun):
        (nombre_idx, aridad, slots) = struct.unpack_from("<III", blob, pos)
        pos += 12
        flags = blob[pos:pos + slots]
        pos += slots
        (n_up, ) = struct.unpack_from("<I", blob, pos)
        pos += 4
        ups = []
        for _ in range(n_up):
            (es_local, idx) = struct.unpack_from("<BI", blob, pos)
            pos += 5
            ups.append(f"{'local' if es_local else 'upval'}:{idx}")
        (n_i,) = struct.unpack_from("<I", blob, pos)
        pos += 4 + 8 * n_i
        (n_d,) = struct.unpack_from("<I", blob, pos)
        pos += 4 + 8 * n_d
        (n_s,) = struct.unpack_from("<I", blob, pos)
        pos += 4 + 4 * n_s
        (largo,) = struct.unpack_from("<I", blob, pos)
        pos += 4
        codigo = blob[pos:pos + largo]
        pos += largo
        (n_lineas,) = struct.unpack_from("<I", blob, pos)
        pos += 4 + 8 * n_lineas
        celda_txt = "".join("C" if f else "-" for f in flags)
        lineas_salida.append(
            f"\nfunción #{indice_fun} '{cadenas[nombre_idx]}' aridad={aridad} "
            f"slots={slots} [{celda_txt}] upvalues=[{', '.join(ups)}]"
        )
        lineas_salida.append("   " + codigo.hex(" "))
    return "\n".join(lineas_salida)
