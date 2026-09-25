"""Máquina virtual de JP: ejecuta bytecode (jp.bytecode) sobre una pila.

Técnica: *threaded code* por cierres. La primera vez que se ejecuta un chunk,
cada instrucción se compila a una función de Python con sus operandos ya
prefijados; cada función devuelve la SIGUIENTE función a ejecutar (o None al
acabar). Así el bucle principal es `op = op()` y el coste por instrucción es
uniforme y mínimo (sin cadenas de if/elif ni indexado de tuplas).

Semántica idéntica al intérprete de árbol (jp.interprete):
    - Ámbitos léxicos con cadenas de Ambito; los closures capturan el ámbito
      de definición (Cierre), igual que FuncionJP captura su Entorno.
    - Las funciones JP se llaman de forma iterativa (frames), sin recursión
      de Python ni excepciones Retornar.
    - Las nativas y el módulo de red se reutilizan tal cual.
"""

from __future__ import annotations

from .arbol import NodoPrograma
from .bytecode import Chunk, Codigo
from .compilador import FunCerrada, compilar
from .errores import ErrorEjecucion
from .interprete import (
    Entorno,
    FuncionNativa,
    _instalar_nativas,
    es_verdad,
    jp_a_texto,
)

_MAX_FRAMES = 6000  # tope de llamadas JP anidadas (equivalente al RecursionError del árbol)

_FALTA = object()  # centinela para dict.get (nunca es un valor JP válido)


class Ambito:
    """Ámbito léxico ligero: variables locales de funciones y bloques."""

    __slots__ = ("vars", "padre")

    def __init__(self, padre: "Ambito | None" = None):
        self.vars: dict[str, object] = {}
        self.padre = padre


class Cierre:
    """Función compilada + ámbito donde fue definida (closures reales)."""

    __slots__ = ("fun", "ambito")

    def __init__(self, fun: FunCerrada, ambito: Ambito | None):
        self.fun = fun
        self.ambito = ambito

    def __repr__(self) -> str:
        return f"<fun {self.fun.nombre}>"


class IteradorJP:
    """Estado de un 'para ... en' que vive en la pila de la VM."""

    __slots__ = ("it",)

    def __init__(self, it):
        self.it = it

    def __repr__(self) -> str:
        return "<iterador>"


def _igual(a: object, b: object) -> bool:
    """Igualdad de JP (misma regla que Interprete._igual)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    return a == b


class MaquinaVM:
    """Ejecuta chunks de bytecode. Misma semántica observable que Interprete."""

    def __init__(self) -> None:
        # Reutiliza las nativas del intérprete (incluida la red) tal cual.
        entorno_global = Entorno()
        _instalar_nativas(entorno_global)
        from .red import instalar as _instalar_red

        _instalar_red(entorno_global)
        from .archivos import instalar as _instalar_archivos

        _instalar_archivos(entorno_global)
        self.globals: dict[str, object] = entorno_global.variables
        self.pila: list[object] = []
        self.frames: list[list] = []  # [cierre_de_reanudación, ámbito_previo]
        self.ambito: Ambito | None = None
        self.ultimo_valor: object = None
        # Nombres globales instalados por el JIT (jp.nativo): DECLARAR no los
        # pisa para que la versión nativa siga viva durante la ejecución.
        self.resguardadas: set[str] = set()

    # ---------------- API pública ----------------

    def ejecutar(self, programa: NodoPrograma) -> None:
        self.ultimo_valor = None
        self.pila.clear()
        self.frames.clear()
        self.ambito = None
        chunk = compilar(programa)
        ops = self._compilar_ops(chunk)
        if not ops:
            return
        op = ops[0]
        while op is not None:
            op = op()

    # ---------------- compilación a cierres ----------------

    def _compilar_ops(self, chunk: Chunk) -> list:
        """Convierte el bytecode del chunk en una lista de cierres ejecutables."""
        if chunk.ops is not None:
            return chunk.ops
        if chunk._c is None:
            chunk.preparar()
        ops: list = []
        for i, (codigo, operando, linea) in enumerate(zip(chunk._c, chunk._o, chunk._l)):
            ops.append(self._op_de(chunk, ops, i, codigo, operando, linea))
        ops.append(lambda: None)  # centinela: acabar el chunk = terminar (los saltos 'fin' apuntan aquí)
        chunk.ops = ops
        return ops

    def _op_de(self, chunk: Chunk, lista: list, i: int, codigo: Codigo, operando: object, linea: int):
        """Devuelve la función que ejecuta una instrucción.

        Convención: cada op hace su trabajo y devuelve la siguiente función
        de la lista (o None si el chunk termina). `lista` es la lista de ops
        del propio chunk; los saltos devuelven lista[destino].
        """
        pila = self.pila
        frames = self.frames
        sig = i + 1

        # ---------- constantes y variables ----------

        if codigo is Codigo.CONSTANTE:
            constante = chunk.constantes[operando]
            if type(constante) is FunCerrada:
                def op():
                    pila.append(Cierre(constante, self.ambito))
                    return lista[sig]
            else:
                def op():
                    pila.append(constante)
                    return lista[sig]
            return op

        if codigo is Codigo.LEER_GLOBAL:
            def op():
                # .get con centinela: 1 acceso al dict en vez de 2 (in + [])
                ambito = self.ambito
                if ambito is None:
                    valor = self.globals.get(operando, _FALTA)
                    if valor is _FALTA:
                        raise ErrorEjecucion(f"variable no definida: '{operando}'", linea)
                    pila.append(valor)
                    return lista[sig]
                nombre = operando
                a = ambito
                while a is not None:
                    valor = a.vars.get(nombre, _FALTA)
                    if valor is not _FALTA:
                        pila.append(valor)
                        return lista[sig]
                    a = a.padre
                valor = self.globals.get(nombre, _FALTA)
                if valor is _FALTA:
                    raise ErrorEjecucion(f"variable no definida: '{nombre}'", linea)
                pila.append(valor)
                return lista[sig]
            return op

        if codigo is Codigo.LEER_LOCAL:
            def op():
                nombre = operando
                a = self.ambito
                while a is not None:
                    valor = a.vars.get(nombre, _FALTA)
                    if valor is not _FALTA:
                        pila.append(valor)
                        return lista[sig]
                    a = a.padre
                raise ErrorEjecucion(f"variable no definida: '{nombre}'", linea)
            return op

        if codigo is Codigo.ASIGNAR_GLOBAL:
            def op():
                valor = pila.pop()
                ambito = self.ambito
                if ambito is None:
                    if operando not in self.globals:
                        raise ErrorEjecucion(
                            f"variable no definida: '{operando}' (usa 'var' para declararla)", linea
                        )
                    self.globals[operando] = valor
                    pila.append(valor)
                    return lista[sig]
                nombre = operando
                a = ambito
                while a is not None:
                    if nombre in a.vars:
                        a.vars[nombre] = valor
                        pila.append(valor)
                        return lista[sig]
                    a = a.padre
                if nombre in self.globals:
                    self.globals[nombre] = valor
                    pila.append(valor)
                    return lista[sig]
                raise ErrorEjecucion(
                    f"variable no definida: '{nombre}' (usa 'var' para declararla)", linea
                )
            return op

        if codigo is Codigo.ASIGNAR_LOCAL:
            def op():
                valor = pila.pop()
                nombre = operando
                a = self.ambito
                while a is not None:
                    if nombre in a.vars:
                        a.vars[nombre] = valor
                        pila.append(valor)
                        return lista[sig]
                    a = a.padre
                raise ErrorEjecucion(
                    f"variable no definida: '{nombre}' (usa 'var' para declararla)", linea
                )
            return op

        if codigo is Codigo.DECLARAR:
            # Define y NO deja valor: las sentencias son netas de pila 0
            # (igual que en el árbol, donde definir no produce valor).
            def op():
                nombre = operando
                valor = pila.pop()
                if self.ambito is None:
                    if nombre not in self.resguardadas:  # el JIT la reemplazó
                        self.globals[nombre] = valor
                else:
                    self.ambito.vars[nombre] = valor
                return lista[sig]
            return op

        # ---------- aritmética y comparaciones ----------

        if codigo is Codigo.SUMAR:
            def op():
                b = pila.pop()
                a = pila.pop()
                if isinstance(a, str) or isinstance(b, str):
                    pila.append(jp_a_texto(a) + jp_a_texto(b))
                elif isinstance(a, list) and isinstance(b, list):
                    pila.append(a + b)
                elif isinstance(a, bool) or not isinstance(a, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '+' espera números, recibió {jp_a_texto(a)!r}", linea
                    )
                elif isinstance(b, bool) or not isinstance(b, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '+' espera números, recibió {jp_a_texto(b)!r}", linea
                    )
                else:
                    pila.append(a + b)
                return lista[sig]
            return op

        if codigo is Codigo.RESTAR:
            def op():
                b = pila.pop()
                a = pila.pop()
                if isinstance(a, bool) or not isinstance(a, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '-' espera números, recibió {jp_a_texto(a)!r}", linea
                    )
                if isinstance(b, bool) or not isinstance(b, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '-' espera números, recibió {jp_a_texto(b)!r}", linea
                    )
                pila.append(a - b)
                return lista[sig]
            return op

        if codigo is Codigo.MULTIPLICAR:
            def op():
                b = pila.pop()
                a = pila.pop()
                if isinstance(a, str) and isinstance(b, (int, float)) and not isinstance(b, bool):
                    pila.append(a * int(b))  # "ab" * 3
                elif isinstance(a, bool) or not isinstance(a, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '*' espera números, recibió {jp_a_texto(a)!r}", linea
                    )
                elif isinstance(b, bool) or not isinstance(b, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '*' espera números, recibió {jp_a_texto(b)!r}", linea
                    )
                else:
                    pila.append(a * b)
                return lista[sig]
            return op

        if codigo is Codigo.DIVIDIR:
            def op():
                b = pila.pop()
                a = pila.pop()
                if isinstance(a, bool) or not isinstance(a, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '/' espera números, recibió {jp_a_texto(a)!r}", linea
                    )
                if isinstance(b, bool) or not isinstance(b, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '/' espera números, recibió {jp_a_texto(b)!r}", linea
                    )
                if b == 0:
                    raise ErrorEjecucion("división por cero", linea)
                if isinstance(a, int) and isinstance(b, int) and a % b == 0:
                    pila.append(a // b)  # división exacta entre enteros -> entero
                else:
                    pila.append(a / b)
                return lista[sig]
            return op

        if codigo is Codigo.MODULO:
            def op():
                b = pila.pop()
                a = pila.pop()
                if isinstance(a, bool) or not isinstance(a, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '%' espera números, recibió {jp_a_texto(a)!r}", linea
                    )
                if isinstance(b, bool) or not isinstance(b, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '%' espera números, recibió {jp_a_texto(b)!r}", linea
                    )
                if b == 0:
                    raise ErrorEjecucion("módulo por cero", linea)
                pila.append(a % b)
                return lista[sig]
            return op

        if codigo is Codigo.IGUAL:
            def op():
                b = pila.pop()
                a = pila.pop()
                pila.append(_igual(a, b))
                return lista[sig]
            return op

        if codigo is Codigo.DIFERENTE:
            def op():
                b = pila.pop()
                a = pila.pop()
                pila.append(not _igual(a, b))
                return lista[sig]
            return op

        if codigo is Codigo.MENOR:
            def op():
                b = pila.pop()
                a = pila.pop()
                if isinstance(a, bool) or not isinstance(a, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '<' espera números, recibió {jp_a_texto(a)!r}", linea
                    )
                if isinstance(b, bool) or not isinstance(b, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '<' espera números, recibió {jp_a_texto(b)!r}", linea
                    )
                pila.append(a < b)
                return lista[sig]
            return op

        if codigo is Codigo.MAYOR:
            def op():
                b = pila.pop()
                a = pila.pop()
                if isinstance(a, bool) or not isinstance(a, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '>' espera números, recibió {jp_a_texto(a)!r}", linea
                    )
                if isinstance(b, bool) or not isinstance(b, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '>' espera números, recibió {jp_a_texto(b)!r}", linea
                    )
                pila.append(a > b)
                return lista[sig]
            return op

        if codigo is Codigo.MENOR_IGUAL:
            def op():
                b = pila.pop()
                a = pila.pop()
                if isinstance(a, bool) or not isinstance(a, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '<=' espera números, recibió {jp_a_texto(a)!r}", linea
                    )
                if isinstance(b, bool) or not isinstance(b, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '<=' espera números, recibió {jp_a_texto(b)!r}", linea
                    )
                pila.append(a <= b)
                return lista[sig]
            return op

        if codigo is Codigo.MAYOR_IGUAL:
            def op():
                b = pila.pop()
                a = pila.pop()
                if isinstance(a, bool) or not isinstance(a, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '>=' espera números, recibió {jp_a_texto(a)!r}", linea
                    )
                if isinstance(b, bool) or not isinstance(b, (int, float)):
                    raise ErrorEjecucion(
                        f"el operador '>=' espera números, recibió {jp_a_texto(b)!r}", linea
                    )
                pila.append(a >= b)
                return lista[sig]
            return op

        if codigo is Codigo.NEGAR:
            def op():
                v = pila.pop()
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ErrorEjecucion(
                        f"el operando de '-' debe ser número, no {jp_a_texto(v)!r}", linea
                    )
                pila.append(-v)
                return lista[sig]
            return op

        if codigo is Codigo.NO:
            def op():
                v = pila.pop()
                pila.append(v is None or v is False)  # es_verdad inlineado
                return lista[sig]
            return op

        # ---------- saltos ----------

        if codigo is Codigo.SALTAR:
            destino = operando
            return lambda: lista[destino]

        if codigo is Codigo.SALTAR_SI_FALSO:
            destino = operando

            def op():
                # es_verdad inlineado (camino caliente): falso = nulo o falso
                v = pila.pop()
                if v is not None and v is not False:
                    return lista[sig]
                return lista[destino]
            return op

        if codigo is Codigo.SALTAR_SI_VERDAD:
            destino = operando

            def op():
                v = pila[-1]
                if v is not None and v is not False:
                    return lista[destino]
                return lista[sig]
            return op

        # ---------- estructuras ----------

        if codigo is Codigo.LISTA:
            n = operando

            def op():
                if n:
                    elementos = pila[-n:]
                    del pila[-n:]
                    pila.append(elementos)
                else:
                    pila.append([])
                return lista[sig]
            return op

        if codigo is Codigo.DICCIONARIO:
            n = operando

            def op():
                if n:
                    datos = pila[-2 * n:]
                    del pila[-2 * n:]
                    pila.append({datos[j]: datos[j + 1] for j in range(0, 2 * n, 2)})
                else:
                    pila.append({})
                return lista[sig]
            return op

        if codigo is Codigo.INTERPOLAR:
            n = operando   # partes de NodoInterpolacion: texto, valor, texto...

            def op():
                piezas = pila[-n:]
                del pila[-n:]
                trozos: list[str] = []
                for indice, pieza in enumerate(piezas):
                    if indice % 2 == 0:
                        trozos.append(pieza)          # NodoCadena ya es str
                    else:
                        trozos.append(jp_a_texto(pieza))
                pila.append("".join(trozos))
                return lista[sig]
            return op

        if codigo is Codigo.RANGO:
            def op():
                fin = pila.pop()
                inicio = pila.pop()
                for v in (inicio, fin):
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        raise ErrorEjecucion(
                            f"el rango '..' espera números, recibió {jp_a_texto(v)!r}", linea
                        )
                ini, finn = int(inicio), int(fin)
                paso = 1 if ini <= finn else -1
                pila.append(list(range(ini, finn + paso, paso)))
                return lista[sig]
            return op

        if codigo is Codigo.INDICE:
            def op():
                indice = pila.pop()
                objeto = pila.pop()
                pila.append(self._indice(objeto, indice, linea))
                return lista[sig]
            return op

        if codigo is Codigo.INDICE_ASIG:
            def op():
                valor = pila.pop()
                indice = pila.pop()
                objeto = pila.pop()
                self._asignar_indice(objeto, indice, valor, linea)
                pila.append(valor)
                return lista[sig]
            return op

        # ---------- iteración (para ... en) ----------

        if codigo is Codigo.ITERAR:
            def op():
                v = pila.pop()
                if isinstance(v, (list, dict, str)):
                    pila.append(IteradorJP(iter(v)))
                elif isinstance(v, (int, float)):  # 'para i en 5' -> 1..5 (como el árbol)
                    pila.append(IteradorJP(iter(range(1, int(v) + 1))))
                else:
                    raise ErrorEjecucion(
                        f"'para ... en' espera una lista, cadena, diccionario o número, no {jp_a_texto(v)!r}",
                        linea,
                    )
                return lista[sig]
            return op

        if codigo is Codigo.ITERAR_SIGUIENTE:
            nombre, fin = operando

            def op():
                it = pila.pop()
                try:
                    valor = next(it.it)
                except StopIteration:
                    pila.append(it)  # el centinela lo quita el POP posterior
                    return lista[fin]
                if self.ambito is None:  # defensivo: el 'para' siempre abre ámbito
                    self.globals[nombre] = valor
                else:
                    self.ambito.vars[nombre] = valor
                pila.append(it)
                pila.append(valor)
                return lista[sig]
            return op

        # ---------- ámbitos ----------

        if codigo is Codigo.AMBITO_PUSH:
            def op():
                self.ambito = Ambito(self.ambito)
                return lista[sig]
            return op

        if codigo is Codigo.AMBITO_POP:
            def op():
                if self.ambito is not None:
                    self.ambito = self.ambito.padre
                return lista[sig]
            return op

        # ---------- llamadas y retorno ----------

        if codigo is Codigo.LLAMAR:
            n = operando
            reanudar = sig  # índice al que vuelve la llamada

            def op():
                callee = pila[-n - 1]
                argumentos = pila[-n:] if n else []
                del pila[-n - 1:]
                tipo = type(callee)
                if tipo is Cierre:
                    fun = callee.fun
                    if n != fun.aridad:
                        raise ErrorEjecucion(
                            f"la función '{fun.nombre}' espera {fun.aridad} argumento(s), recibió {n}",
                            linea,
                        )
                    if len(frames) >= _MAX_FRAMES:
                        raise ErrorEjecucion("desbordamiento de pila (¿recursión infinita?)", linea)
                    ops_fun = fun.chunk.ops
                    if ops_fun is None:
                        ops_fun = self._compilar_ops(fun.chunk)
                    frames.append([lista[reanudar], self.ambito])
                    self.ambito = Ambito(callee.ambito)  # padre = ámbito de definición
                    locales = self.ambito.vars
                    for nombre_arg, valor in zip(fun.parametros, argumentos):
                        locales[nombre_arg] = valor
                    return ops_fun[0]
                if tipo is FuncionNativa:
                    if callee.aridad is not None and n != callee.aridad:
                        raise ErrorEjecucion(
                            f"{callee.nombre}() espera {callee.aridad} argumento(s), recibió {n}",
                            linea,
                        )
                    try:
                        pila.append(callee.funcion(*argumentos))
                    except ErrorEjecucion:
                        raise
                    except TypeError as exc:
                        raise ErrorEjecucion(
                            f"argumentos no válidos para {callee.nombre}(): {exc}", linea
                        )
                    return lista[sig]
                raise ErrorEjecucion(f"este valor no es una función: {jp_a_texto(callee)!r}", linea)
            return op

        if codigo is Codigo.RETORNAR:
            def op():
                valor = pila.pop()
                if not frames:
                    # 'retorna' en el nivel superior: termina el programa
                    # (misma conducta que el intérprete de árbol).
                    self.ultimo_valor = valor
                    return None
                frame = frames.pop()
                self.ambito = frame[1]
                pila.append(valor)
                return frame[0]
            return op

        # ---------- sentencias ----------

        if codigo is Codigo.POP:
            def op():
                pila.pop()
                return lista[sig]
            return op

        if codigo is Codigo.EXPR_SENT:
            # Sentencia de expresión: el árbol guarda el valor en ultimo_valor
            # y lo descarta (paridad de REPL).
            def op():
                self.ultimo_valor = pila.pop()
                return lista[sig]
            return op

        if codigo is Codigo.ULTIMO_VALOR:
            def op():
                self.ultimo_valor = pila[-1]
                return lista[sig]
            return op

        if codigo is Codigo.IMPRIMIR:
            n = operando

            def op():
                if n:
                    valores = pila[-n:]
                    del pila[-n:]
                    print(" ".join(jp_a_texto(v) for v in valores))
                else:
                    print("")
                return lista[sig]
            return op

        if codigo is Codigo.NULO:
            return lambda: (pila.append(None), lista[sig])[1]

        if codigo is Codigo.VERDADERO:
            return lambda: (pila.append(True), lista[sig])[1]

        if codigo is Codigo.FALSO:
            return lambda: (pila.append(False), lista[sig])[1]

        raise ErrorEjecucion(f"instrucción desconocida: {codigo}", linea)  # pragma: no cover

    # ---------------- helpers de índices (misma semántica que el árbol) ----------------

    @staticmethod
    def _indice(objeto: object, indice: object, linea: int) -> object:
        if isinstance(objeto, dict):
            if not isinstance(indice, str):
                raise ErrorEjecucion("la clave de un diccionario debe ser texto", linea)
            if indice not in objeto:
                claves = ", ".join(str(k) for k in objeto) or "ninguna"
                raise ErrorEjecucion(
                    f"no existe la clave '{indice}' (claves disponibles: {claves})", linea
                )
            return objeto[indice]
        if isinstance(objeto, list):
            if not isinstance(indice, (int, float)) or isinstance(indice, bool):
                raise ErrorEjecucion("el índice de una lista debe ser un número", linea)
            i = int(indice)
            if i < 0:
                i += len(objeto)
            if i < 0 or i >= len(objeto):
                raise ErrorEjecucion(
                    f"índice fuera de rango: {i} (lista de {len(objeto)} elementos)", linea
                )
            return objeto[i]
        if isinstance(objeto, str):
            if not isinstance(indice, (int, float)) or isinstance(indice, bool):
                raise ErrorEjecucion("el índice de una cadena debe ser un número", linea)
            i = int(indice)
            if i < 0:
                i += len(objeto)
            if i < 0 or i >= len(objeto):
                raise ErrorEjecucion(
                    f"índice fuera de rango: {i} (cadena de {len(objeto)} caracteres)", linea
                )
            return objeto[i]
        raise ErrorEjecucion(f"este valor no se puede indexar: {jp_a_texto(objeto)!r}", linea)

    @staticmethod
    def _asignar_indice(objeto: object, indice: object, valor: object, linea: int) -> None:
        if isinstance(objeto, dict):
            if not isinstance(indice, str):
                raise ErrorEjecucion("la clave de un diccionario debe ser texto", linea)
            objeto[indice] = valor
            return
        if isinstance(objeto, list):
            if isinstance(indice, bool) or not isinstance(indice, (int, float)):
                raise ErrorEjecucion("el índice de una lista debe ser un número", linea)
            i = int(indice)
            if i < 0:
                i += len(objeto)
            if i < 0 or i >= len(objeto):
                raise ErrorEjecucion(
                    f"índice fuera de rango: {i} (lista de {len(objeto)} elementos)", linea
                )
            objeto[i] = valor
            return
        raise ErrorEjecucion(f"no se puede asignar dentro de {jp_a_texto(objeto)!r}", linea)
