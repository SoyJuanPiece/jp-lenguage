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

from pathlib import Path

from .arbol import NodoPrograma
from .bytecode import Chunk, Codigo
from .compilador import FunCerrada, compilar
from .errores import ErrorEjecucion, ErrorJP
from .interprete import (
    Cierre,
    ClaseJP,
    Entorno,
    ErrorValor,
    FuncionNativa,
    Instancia,
    MetodoLigado,
    _instalar_nativas,
    buscar_metodo,
    crear_error_valor,
    _metodo_de_valor,
    es_verdad,
    evaluar_paso,
    iguales,
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


class IteradorJP:
    """Estado de un 'para ... en' que vive en la pila de la VM."""

    __slots__ = ("it",)

    def __init__(self, it):
        self.it = it

    def __repr__(self) -> str:
        return "<iterador>"


def _igual(a: object, b: object) -> bool:
    """Igualdad de JP (misma regla que el intérprete de árbol)."""
    return iguales(a, b)


class MaquinaVM:
    """Ejecuta chunks de bytecode. Misma semántica observable que Interprete."""

    def __init__(self) -> None:
        # Reutiliza las nativas del intérprete (incluida la red) tal cual.
        # Se le pasa _llamar_valor para que las nativas de orden superior
        # (mapear, filtrar, reducir...) puedan llamar a funciones JP.
        entorno_global = Entorno()
        _instalar_nativas(entorno_global, self._llamar_valor)
        from .red import instalar as _instalar_red

        _instalar_red(entorno_global)
        from .archivos import instalar as _instalar_archivos

        _instalar_archivos(entorno_global)
        from .estadistica import instalar as _instalar_estadistica
        _instalar_estadistica(entorno_global, self._llamar_valor)
        from .matrices import instalar as _instalar_matrices
        _instalar_matrices(entorno_global, self._llamar_valor)
        from .fechas import instalar as _instalar_fechas
        _instalar_fechas(entorno_global, self._llamar_valor)
        from .sistema import instalar as _instalar_sistema
        _instalar_sistema(entorno_global, self._llamar_valor)
        from .patrones import instalar as _instalar_patrones
        _instalar_patrones(entorno_global, self._llamar_valor)
        self.globals: dict[str, object] = entorno_global.variables
        self.pila: list[object] = []
        # [cierre_de_reanudación, ámbito_previo, alto_de_pila_al_llamar]
        self.frames: list[list] = []
        self.ambito: Ambito | None = None
        self.ultimo_valor: object = None
        # Manejadores de 'intenta': (ops del chunk, destino, largo_pila,
        # largo_frames, ámbito) por cada TRY activo.
        self.manejadores: list[tuple] = []
        self.error_actual: object = ""
        # Nombres globales instalados por el JIT (jp.nativo): DECLARAR no los
        # pisa para que la versión nativa siga viva durante la ejecución.
        self.resguardadas: set[str] = set()
        # Módulos importados (paridad con el árbol): una ejecución por ruta.
        self._modulos_cache: dict[str, dict] = {}
        self._importando: set[str] = set()
        self.directorio_base: Path = Path.cwd()

    # ---------------- API pública ----------------

    def ejecutar(self, programa: NodoPrograma, directorio: object = None) -> None:
        if directorio is not None:
            self.directorio_base = Path(str(directorio))
        self.ultimo_valor = None
        self.pila.clear()
        self.frames.clear()
        self.ambito = None
        self.manejadores.clear()
        self.error_actual = ""
        chunk = compilar(programa)
        ops = self._compilar_ops(chunk)
        if not ops:
            return
        pila = self.pila
        op = ops[0]
        while op is not None:
            try:
                op = op()
            except ErrorEjecucion as error:
                # 'intenta { } atrapa error { }': el error más cercano manda.
                # Se restaura pila, frames y ámbito, y se salta al 'atrapa'.
                if not self.manejadores:
                    raise
                ops_manejador, destino, largo_pila, largo_frames, ambito, globales = self.manejadores.pop()
                del pila[largo_pila:]
                del self.frames[largo_frames:]
                self.ambito = ambito
                self.globals = globales
                self.error_actual = crear_error_valor(error)
                op = ops_manejador[destino]

    def _correr_ops(self, ops) -> None:
        """Corre un chunk hasta el final (el valor queda en la pila).

        Lo usan las llamadas hechas desde nativas (mapear, filtrar...) y los
        valores por defecto: los 'intenta' internos se atrapan aquí; los de
        fuera, no (el error sube tal cual).
        """
        pila = self.pila
        base = len(self.manejadores)
        op = ops[0]
        while op is not None:
            try:
                op = op()
            except ErrorEjecucion as error:
                if len(self.manejadores) <= base:
                    raise
                ops_manejador, destino, largo_pila, largo_frames, ambito, globales = self.manejadores.pop()
                del pila[largo_pila:]
                del self.frames[largo_frames:]
                self.ambito = ambito
                self.globals = globales
                self.error_actual = crear_error_valor(error)
                op = ops_manejador[destino]

    def _evaluar_defecto(self, chunk_defecto, ambito_local, globales, linea: int):
        """Ejecuta el mini-chunk de un valor por defecto en el ámbito local."""
        ops_defecto = self._compilar_ops(chunk_defecto)
        pila = self.pila
        ambito_previo, globales_previos = self.ambito, self.globals
        alto_pila, n_frames = len(pila), len(self.frames)
        self.frames.append([None, ambito_previo, alto_pila, globales_previos])
        if globales is not None:
            self.globals = globales
        self.ambito = ambito_local
        try:
            self._correr_ops(ops_defecto)
        except BaseException:
            del self.frames[n_frames:]
            del pila[alto_pila:]
            self.ambito, self.globals = ambito_previo, globales_previos
            raise
        return pila.pop()

    def _ambito_de_llamada(self, callee, argumentos: list, linea: int, este: object = None):
        """Crea el ámbito local: 'este' (si es método) + argumentos + defectos."""
        fun = callee.fun
        if not fun.aridad_minima <= len(argumentos) <= fun.aridad:
            espera = (
                f"{fun.aridad_minima} a {fun.aridad}"
                if fun.aridad_minima != fun.aridad
                else f"{fun.aridad}"
            )
            raise ErrorEjecucion(
                f"la función '{fun.nombre or '<anónima>'}' espera {espera} "
                f"argumento(s), recibió {len(argumentos)}",
                linea,
            )
        ambito = Ambito(callee.ambito)
        if este is not None:
            ambito.vars["este"] = este
        for indice, nombre in enumerate(fun.parametros):
            if indice < len(argumentos):
                ambito.vars[nombre] = argumentos[indice]
            else:
                ambito.vars[nombre] = self._evaluar_defecto(
                    fun.defectos[indice], ambito, callee.globales, linea
                )
        return ambito

    def _llamar_valor(self, callee: object, argumentos: list, linea: int = 0) -> object:
        """Llama a un valor-función desde una nativa de orden superior.

        Ejecuta un bucle anidado con un marco SIN continuación: el 'retorna'
        de la función devuelve None y el bucle se detiene con el valor en la
        pila. Los errores suben al bucle principal, que sabe de 'intenta'.
        """
        pila = self.pila
        if isinstance(callee, ClaseJP):
            return self._instanciar(callee, argumentos, linea)
        if isinstance(callee, MetodoLigado):
            funcion = callee.funcion
            if type(funcion) is not Cierre:
                raise ErrorEjecucion("metodo no valido", linea)
            if len(self.frames) >= _MAX_FRAMES:
                raise ErrorEjecucion("desbordamiento de pila (¿recursión infinita?)", linea)
            ops_fun = funcion.fun.chunk.ops
            if ops_fun is None:
                ops_fun = self._compilar_ops(funcion.fun.chunk)
            ambito_local = self._ambito_de_llamada(
                funcion, argumentos, linea, este=callee.instancia
            )
            self.frames.append([None, self.ambito, len(pila), self.globals])
            if funcion.globales is not None:
                self.globals = funcion.globales
            self.ambito = ambito_local
            self._correr_ops(ops_fun)
            return pila.pop()
        tipo = type(callee)
        if tipo is FuncionNativa:
            if callee.aridad is not None and len(argumentos) != callee.aridad:
                raise ErrorEjecucion(
                    f"{callee.nombre}() espera {callee.aridad} argumento(s), recibió {len(argumentos)}",
                    linea,
                )
            return callee.funcion(*argumentos)
        if tipo is not Cierre:
            raise ErrorEjecucion(f"este valor no es una función: {jp_a_texto(callee)!r}", linea)
        fun = callee.fun
        if len(self.frames) >= _MAX_FRAMES:
            raise ErrorEjecucion("desbordamiento de pila (¿recursión infinita?)", linea)
        ops_fun = fun.chunk.ops
        if ops_fun is None:
            ops_fun = self._compilar_ops(fun.chunk)
        ambito_local = self._ambito_de_llamada(callee, argumentos, linea)
        self.frames.append([None, self.ambito, len(pila), self.globals])
        if callee.globales is not None:
            self.globals = callee.globales
        self.ambito = ambito_local
        # Los 'intenta' de dentro se atrapan en _correr_ops; los de fuera, no.
        self._correr_ops(ops_fun)
        return pila.pop()

    def _instanciar(self, clase: ClaseJP, argumentos: list, linea: int):
        """Clase(args): crea el objeto y llama a su 'iniciar' (si lo tiene)."""
        instancia = Instancia(clase)
        iniciar = buscar_metodo(clase, "iniciar")
        if iniciar is not None:
            self._llamar_valor(MetodoLigado(instancia, iniciar), argumentos, linea)
        elif argumentos:
            raise ErrorEjecucion(
                f"la clase '{clase.nombre}' no tiene un metodo 'iniciar' y no acepta argumentos",
                linea,
            )
        return instancia

    # ---------------- módulos (importar) ----------------

    def _importar(self, ruta_texto: str, alias: str | None, linea: int) -> None:
        """importar "x.jp" [como n]: paridad con el intérprete de árbol."""
        ruta = (self.directorio_base / ruta_texto).resolve()
        if not ruta.is_file():
            raise ErrorEjecucion(
                f"no se encontró el módulo '{ruta_texto}' (buscado en {ruta})", linea
            )
        clave = str(ruta)
        if clave in self._modulos_cache:
            exportaciones = self._modulos_cache[clave]
        elif clave in self._importando:
            raise ErrorEjecucion(
                f"importación circular detectada: '{ruta_texto}' ya se está importando", linea
            )
        else:
            self._importando.add(clave)
            try:
                from .lexer import tokenizar
                from .parser import parsear

                fuente = ruta.read_text(encoding="utf-8")
                sub = MaquinaVM()
                sub._modulos_cache = self._modulos_cache
                sub._importando = self._importando
                antes = dict(sub.globals)
                sub.ejecutar(parsear(tokenizar(fuente)), directorio=ruta.parent)
                exportaciones = {
                    nombre: valor
                    for nombre, valor in sub.globals.items()
                    if nombre not in antes or antes[nombre] is not valor
                }
                self._modulos_cache[clave] = exportaciones
            except ErrorEjecucion:
                raise
            except (OSError, ErrorJP) as error:
                detalle = getattr(error, "mensaje", str(error))
                linea_mod = getattr(error, "linea", 0)
                donde = f" (línea {linea_mod} del módulo)" if linea_mod else ""
                raise ErrorEjecucion(
                    f"error en el módulo '{ruta_texto}'{donde}: {detalle}", linea
                ) from None
            finally:
                self._importando.discard(clave)
        if alias is not None:
            self._definir(alias, exportaciones)
        else:
            for nombre, valor in exportaciones.items():
                self._definir(nombre, valor)

    def _definir(self, nombre: str, valor: object) -> None:
        if self.ambito is None:
            if nombre not in self.resguardadas:
                self.globals[nombre] = valor
        else:
            self.ambito.vars[nombre] = valor

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
                    pila.append(Cierre(constante, self.ambito, self.globals))
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

        if codigo is Codigo.POTENCIA:
            def op():
                b = pila.pop()
                a = pila.pop()
                for v in (a, b):
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        raise ErrorEjecucion(
                            f"el operador '**' espera números, recibió {jp_a_texto(v)!r}", linea
                        )
                try:
                    resultado = a ** b
                except (OverflowError, ZeroDivisionError):
                    raise ErrorEjecucion("potencia no válida (¿0 elevado a algo negativo?)", linea)
                if isinstance(resultado, complex):
                    raise ErrorEjecucion("la potencia no dio un número real", linea)
                pila.append(resultado)
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
            con_paso = bool(operando)

            def op():
                if con_paso:
                    paso = pila.pop()
                    fin = pila.pop()
                    inicio = pila.pop()
                else:
                    paso = None
                    fin = pila.pop()
                    inicio = pila.pop()
                pila.append(list(self._hacer_rango(inicio, fin, paso, con_paso, linea)))
                return lista[sig]
            return op

        if codigo is Codigo.DUP:
            def op():
                pila.append(pila[-1])
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
            en_pares = bool(operando)  # 'para a, b en ...': (índice/clave, valor)

            def op():
                v = pila.pop()
                if en_pares:
                    if isinstance(v, dict):
                        pila.append(IteradorJP(iter(v.items())))
                    elif isinstance(v, (list, str)):
                        pila.append(IteradorJP(iter(enumerate(v))))
                    elif isinstance(v, (int, float)):
                        pila.append(IteradorJP(iter(enumerate(range(1, int(v) + 1)))))
                    else:
                        raise ErrorEjecucion(
                            f"'para ... en' espera una lista, cadena, diccionario o número, no {jp_a_texto(v)!r}",
                            linea,
                        )
                elif isinstance(v, (list, dict, str)):
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

        if codigo is Codigo.ITERAR_RANGO:
            con_paso_r = bool(operando & 1)
            en_pares_r = bool(operando & 2)

            def op():
                if con_paso_r:
                    paso = pila.pop()
                    fin = pila.pop()
                    inicio = pila.pop()
                else:
                    paso = None
                    fin = pila.pop()
                    inicio = pila.pop()
                rango = self._hacer_rango(inicio, fin, paso, con_paso_r, linea)
                if en_pares_r:
                    pila.append(IteradorJP(iter(enumerate(rango))))
                else:
                    pila.append(IteradorJP(iter(rango)))
                return lista[sig]
            return op

        if codigo is Codigo.ITERAR_SIGUIENTE:
            if len(operando) == 3:
                nombre, nombre2, fin = operando
            else:
                nombre, fin = operando
                nombre2 = None

            def op():
                it = pila.pop()
                try:
                    valor = next(it.it)
                except StopIteration:
                    pila.append(it)  # el centinela lo quita el POP posterior
                    return lista[fin]
                if nombre2 is None:
                    valores = ((nombre, valor),)
                else:
                    valores = ((nombre, valor[0]), (nombre2, valor[1]))
                for nombre_v, valor_v in valores:
                    if self.ambito is None:  # defensivo: el 'para' siempre abre ámbito
                        self.globals[nombre_v] = valor_v
                    else:
                        self.ambito.vars[nombre_v] = valor_v
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

        # ---------- intenta / atrapa ----------

        if codigo is Codigo.TRY:
            destino = operando

            def op():
                self.manejadores.append(
                    (lista, destino, len(pila), len(frames), self.ambito, self.globals)
                )
                return lista[sig]
            return op

        if codigo is Codigo.ENDTRY:
            def op():
                if self.manejadores:
                    self.manejadores.pop()
                return lista[sig]
            return op

        if codigo is Codigo.ERROR_ACTUAL:
            def op():
                pila.append(self.error_actual)
                return lista[sig]
            return op

        if codigo is Codigo.LANZAR:
            def op():
                raise ErrorEjecucion(jp_a_texto(pila.pop()), linea, tipo="usuario")
            return op

        if codigo is Codigo.RELANZAR:
            def op():
                actual = self.error_actual
                raise ErrorEjecucion(
                    str(actual), linea, tipo=getattr(actual, "tipo", "ejecucion")
                )
            return op

        if codigo is Codigo.IMPORTAR:
            ruta_importar, alias_importar = operando

            def op():
                self._importar(ruta_importar, alias_importar, linea)
                return lista[sig]
            return op

        if codigo is Codigo.CREAR_CLASE:
            nombre_clase, nombres_metodos = operando
            n_metodos = len(nombres_metodos)

            def op():
                if n_metodos:
                    valores = pila[-n_metodos - 1:]
                    del pila[-n_metodos - 1:]
                else:
                    valores = [pila.pop()]
                padre = valores[0]
                if padre is not None and not isinstance(padre, ClaseJP):
                    raise ErrorEjecucion(
                        f"la clase '{nombre_clase}' hereda de algo que no es una clase: "
                        f"{jp_a_texto(padre)!r}",
                        linea,
                    )
                metodos = dict(zip(nombres_metodos, valores[1:]))
                pila.append(ClaseJP(nombre_clase, metodos, padre))
                return lista[sig]
            return op

        if codigo is Codigo.DESESTRUCTURAR:
            nombres_des = operando

            def op():
                valores = self._valores_lista(pila.pop(), nombres_des, linea)
                for nombre_v, valor_v in zip(nombres_des, valores):
                    self._definir(nombre_v, valor_v)
                return lista[sig]
            return op

        if codigo is Codigo.DESESTRUCTURAR_ASIG:
            nombres_asig = operando

            def op():
                # La lista queda en la pila: es el valor de la expresión.
                valores = self._valores_lista(pila[-1], nombres_asig, linea)
                for nombre_v, valor_v in zip(nombres_asig, valores):
                    self._asignar_nombre(nombre_v, valor_v, linea)
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
                if tipo is ClaseJP or tipo is MetodoLigado:
                    pila.append(self._llamar_valor(callee, argumentos, linea))
                    return lista[sig]
                if tipo is Cierre:
                    fun = callee.fun
                    if len(frames) >= _MAX_FRAMES:
                        raise ErrorEjecucion("desbordamiento de pila (¿recursión infinita?)", linea)
                    ops_fun = fun.chunk.ops
                    if ops_fun is None:
                        ops_fun = self._compilar_ops(fun.chunk)
                    ambito_local = self._ambito_de_llamada(callee, argumentos, linea)
                    frames.append([lista[reanudar], self.ambito, len(pila), self.globals])
                    if callee.globales is not None:
                        self.globals = callee.globales
                    self.ambito = ambito_local  # padre = ámbito de definición
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
                    pila.clear()
                    return None
                frame = frames.pop()
                self.ambito = frame[1]
                if len(frame) > 3:
                    self.globals = frame[3]
                # Volver al alto de pila del llamador: descarta lo que hayan
                # dejado atrás bucles ('para' deja su iterador) o ámbitos.
                del pila[frame[2]:]
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

    @staticmethod
    def _hacer_rango(inicio, fin, paso, con_paso: bool, linea: int) -> range:
        """El range (perezoso) de 'a..b [paso c]' con la semantica de JP."""
        for v in (inicio, fin):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ErrorEjecucion(
                    f"el rango '..' espera números, recibió {jp_a_texto(v)!r}", linea
                )
        ini, finn = int(inicio), int(fin)
        if not con_paso:
            incremento = 1 if ini <= finn else -1
        else:
            incremento = evaluar_paso(paso, linea)
            if ini > finn:
                incremento = -incremento
        return range(ini, finn + (1 if incremento > 0 else -1), incremento)

    # ---------------- helpers de nombres y desestructuración ----------------

    @staticmethod
    def _valores_lista(valor: object, nombres, linea: int) -> list:
        """Valida la lista de una desestructuración (mismos errores que el árbol)."""
        if not isinstance(valor, list):
            raise ErrorEjecucion(
                f"la desestructuración '[a, b] = ...' espera una lista, no {jp_a_texto(valor)!r}", linea
            )
        if len(valor) != len(nombres):
            raise ErrorEjecucion(
                f"la desestructuración esperaba {len(nombres)} valor(es) y recibió {len(valor)}", linea
            )
        return list(valor)

    def _asignar_nombre(self, nombre: str, valor: object, linea: int) -> None:
        ambito = self.ambito
        while ambito is not None:
            if nombre in ambito.vars:
                ambito.vars[nombre] = valor
                return
            ambito = ambito.padre
        if nombre in self.globals:
            self.globals[nombre] = valor
            return
        raise ErrorEjecucion(
            f"variable no definida: '{nombre}' (usa 'var' para declararla)", linea
        )

    # ---------------- helpers de índices (misma semántica que el árbol) ----------------

    @staticmethod
    def _indice(objeto: object, indice: object, linea: int) -> object:
        if isinstance(objeto, ErrorValor) and isinstance(indice, str):
            if indice == "mensaje":
                return objeto.mensaje
            if indice == "tipo":
                return objeto.tipo
            if indice == "linea":
                return objeto.linea
        if isinstance(objeto, Instancia):
            if not isinstance(indice, str):
                raise ErrorEjecucion("los campos de un objeto se acceden con .nombre", linea)
            if indice in objeto.campos:
                return objeto.campos[indice]
            metodo = buscar_metodo(objeto.clase, indice)
            if metodo is not None:
                return MetodoLigado(objeto, metodo)
            campos = ", ".join(objeto.campos) or "ninguno"
            raise ErrorEjecucion(
                f"el objeto {objeto.clase.nombre} no tiene '{indice}' (campos: {campos})", linea
            )
        if isinstance(objeto, dict):
            if not isinstance(indice, str):
                raise ErrorEjecucion("la clave de un diccionario debe ser texto", linea)
            if indice in objeto:
                return objeto[indice]
            metodo = _metodo_de_valor(objeto, indice)
            if metodo is not None:
                return metodo
            claves = ", ".join(str(k) for k in objeto) or "ninguna"
            raise ErrorEjecucion(
                f"no existe la clave '{indice}' (claves disponibles: {claves})", linea
            )
        if isinstance(objeto, list):
            if not isinstance(indice, (int, float)) or isinstance(indice, bool):
                metodo = _metodo_de_valor(objeto, str(indice))
                if metodo is not None:
                    return metodo
                if isinstance(indice, str):
                    raise ErrorEjecucion(f"no existe el método '{indice}' para lista", linea)
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
                metodo = _metodo_de_valor(objeto, str(indice))
                if metodo is not None:
                    return metodo
                if isinstance(indice, str):
                    raise ErrorEjecucion(f"no existe el método '{indice}' para texto", linea)
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
        if isinstance(objeto, Instancia):
            if not isinstance(indice, str):
                raise ErrorEjecucion("los campos de un objeto se acceden con .nombre", linea)
            objeto.campos[indice] = valor
            return
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
