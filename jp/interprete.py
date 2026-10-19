"""Intérprete de JP: recorre el AST y ejecuta el programa.

Diseño:
    - Entornos con ámbito léxico (cada bloque/función crea uno nuevo).
    - Las funciones de JP son valores de primera clase (se pueden pasar por parámetro).
    - Las funciones nativas (muestra, longitud, ...) viven en el entorno global.
"""

from __future__ import annotations

import math
import random
import sys
import time
from pathlib import Path

from .arbol import (
    Nodo,
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
    NodoIntentar,
    NodoIndice,
    NodoInterpolacion,
    NodoLista,
    NodoLanzar,
    NodoLlamada,
    NodoMientras,
    NodoNumero,
    NodoNulo,
    NodoPara,
    NodoPrograma,
    NodoRango,
    NodoRomper,
    NodoContinuar,
    NodoRetorna,
    NodoSi,
    NodoUnario,
    NodoVariable,
)
from .errores import ErrorEjecucion, ErrorJP


# ----------------- Métodos de valor ("texto".mayusculas(), [1, 2].agregar(3), ...) -----------------

# Registro: tipo Python -> {nombre: (funcion, aridad_total)}.
# funcion recibe el receptor como primer argumento; aridad_total es el total de
# argumentos que recibe funcion (receptor + extras) y None significa varargs.
# Lo llena _instalar_nativas, así que los métodos siguen a las nativas del módulo que se instale.
_METODOS_VALOR: dict[type, dict[str, tuple]] = {}


def _metodo_de_valor(objeto: object, nombre: str) -> object | None:
    """Devuelve el método `nombre` ligado a `objeto`, o None si no existe."""
    metodos = _METODOS_VALOR.get(type(objeto))
    if metodos is None:
        return None
    registro = metodos.get(nombre)
    if registro is None:
        return None
    funcion, aridad_total = registro
    aridad = None if aridad_total is None else aridad_total - 1  # sin el receptor
    return FuncionNativa(f"{nombre}()", lambda *args: funcion(objeto, *args), aridad=aridad)


# ----------------- Señales de control de flujo -----------------

class Retornar(Exception):
    """Excepción interna para implementar 'retorna'."""

    def __init__(self, valor: object):
        self.valor = valor


class _Romper(Exception):
    """Señal interna de 'romper' (lleva la línea para el error amigable)."""

    def __init__(self, linea: int = 0):
        self.linea = linea


class _Continuar(Exception):
    """Señal interna de 'continuar'."""

    def __init__(self, linea: int = 0):
        self.linea = linea


# ----------------- Entornos -----------------

class Entorno:
    def __init__(self, padre: "Entorno | None" = None):
        self.variables: dict[str, object] = {}
        self.padre = padre

    def definir(self, nombre: str, valor: object) -> None:
        self.variables[nombre] = valor

    def obtener(self, nombre: str, linea: int = 0) -> object:
        entorno: Entorno | None = self
        while entorno is not None:
            if nombre in entorno.variables:
                return entorno.variables[nombre]
            entorno = entorno.padre
        raise ErrorEjecucion(f"variable no definida: '{nombre}'", linea)

    def asignar(self, nombre: str, valor: object, linea: int = 0) -> None:
        entorno: Entorno | None = self
        while entorno is not None:
            if nombre in entorno.variables:
                entorno.variables[nombre] = valor
                return
            entorno = entorno.padre
        raise ErrorEjecucion(f"variable no definida: '{nombre}' (usa 'var' para declararla)", linea)


# ----------------- Funciones -----------------

class FuncionJP:
    """Una función definida en código JP."""

    def __init__(self, declaracion: NodoFuncion, cierre: Entorno):
        self.declaracion = declaracion
        self.cierre = cierre

    def __repr__(self) -> str:
        return f"<fun {self.declaracion.nombre or '<anónima>'}>"


class FuncionNativa:
    """Una función implementada en Python y expuesta a JP."""

    def __init__(self, nombre: str, funcion, aridad: int | None = None):
        self.nombre = nombre
        self.funcion = funcion
        self.aridad = aridad  # None = varargs

    def __repr__(self) -> str:
        return f"<nativa {self.nombre}>"


class Cierre:
    """Función ya compilada a bytecode (la VM) + ámbito donde fue definida.

    Vive aquí (y no en jp.vm) para que la librería estándar pueda reconocer
    las funciones de los DOS motores con un solo isinstance.
    """

    __slots__ = ("fun", "ambito", "globales")

    def __init__(self, fun, ambito, globales=None) -> None:
        self.fun = fun
        self.ambito = ambito
        # Diccionario de globales del motor/módulo donde se definió la función
        # (la VM lo usa para que las funciones de un módulo importado sigan
        # viendo SUS globales al ser llamadas desde otro archivo).
        self.globales = globales

    def __repr__(self) -> str:
        return f"<fun {getattr(self.fun, 'nombre', '') or '<anónima>'}>"


# ----------------- Clases y objetos (clase / hereda / este) -----------------

class ClaseJP:
    """Una clase definida en JP. Sus métodos son FuncionJP en el árbol y
    Cierre en la VM: esta clase solo guarda el molde (nombre, métodos, madre)."""

    __slots__ = ("nombre", "metodos", "padre")

    def __init__(self, nombre: str, metodos: dict, padre: "ClaseJP | None" = None):
        self.nombre = nombre
        self.metodos = metodos
        self.padre = padre

    def __repr__(self) -> str:
        return f"<clase {self.nombre}>"


class Instancia:
    """Un objeto: su clase + sus campos propios."""

    __slots__ = ("clase", "campos")

    def __init__(self, clase: ClaseJP):
        self.clase = clase
        self.campos: dict[str, object] = {}

    def __repr__(self) -> str:
        return f"<objeto {self.clase.nombre}>"


class MetodoLigado:
    """Un método ya unido a su objeto: p.saludar (sin llamarlo todavía)."""

    __slots__ = ("instancia", "funcion")

    def __init__(self, instancia: Instancia, funcion: object):
        self.instancia = instancia
        self.funcion = funcion

    def __repr__(self) -> str:
        nombre = getattr(self.funcion, "nombre", None) or getattr(
            getattr(self.funcion, "fun", None), "nombre", ""
        )
        return f"<método {nombre}() de {self.instancia.clase.nombre}>"


def buscar_metodo(clase: ClaseJP, nombre: str):
    """Busca un método en la clase y en sus madres (herencia)."""
    actual: ClaseJP | None = clase
    while actual is not None:
        if nombre in actual.metodos:
            return actual.metodos[nombre]
        actual = actual.padre
    return None


class ErrorValor(str):
    """Lo que recibe el nombre de un 'atrapa': un texto (el mensaje, como
    siempre) que además trae .tipo, .mensaje y .linea para poder decidir
    sin comparar textos:  si e.tipo == "division_por_cero { ... }"""

    def __new__(cls, mensaje: str, tipo: str = "ejecucion", linea: int = 0):
        objeto = super().__new__(cls, mensaje)
        objeto.mensaje = mensaje
        objeto.tipo = tipo
        objeto.linea = linea
        return objeto


_TIPOS_POR_MENSAJE = (
    ("división por cero", "division_por_cero"),
    ("módulo por cero", "division_por_cero"),
    ("índice fuera de rango", "indice_fuera_de_rango"),
    ("variable no definida", "variable_no_definida"),
    ("desbordamiento de pila", "desbordamiento_de_pila"),
    ("no se encontró el módulo", "modulo_no_encontrado"),
    ("importación circular", "importacion_circular"),
    ("no existe la clave", "clave_no_encontrada"),
)


def crear_error_valor(error: ErrorEjecucion) -> ErrorValor:
    """Convierte un ErrorEjecucion en el ErrorValor que ve el 'atrapa'."""
    tipo = getattr(error, "tipo", None)
    if not tipo or tipo == "ejecucion":
        for fragmento, codigo in _TIPOS_POR_MENSAJE:
            if fragmento in error.mensaje:
                tipo = codigo
                break
        else:
            tipo = "ejecucion"
    return ErrorValor(error.mensaje, tipo, getattr(error, "linea", 0))


# ----------------- Utilidades de tipos -----------------

def jp_a_texto(valor: object) -> str:
    """Convierte un valor de JP a su representación textual (como print)."""
    if valor is None:
        return "nulo"
    if valor is True:
        return "verdadero"
    if valor is False:
        return "falso"
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    if isinstance(valor, str):
        return valor
    if isinstance(valor, list):
        return "[" + ", ".join(_inspeccionar(v) for v in valor) + "]"
    if isinstance(valor, dict):
        return "{" + ", ".join(f"{_inspeccionar(k)}: {_inspeccionar(v)}" for k, v in valor.items()) + "}"
    if isinstance(valor, Instancia):
        if not valor.campos:
            return f"{valor.clase.nombre}{{}}"
        campos = ", ".join(f"{k}: {_inspeccionar(v)}" for k, v in valor.campos.items())
        return f"{valor.clase.nombre}{{{campos}}}"
    return str(valor)


def _inspeccionar(valor: object) -> str:
    """Representación para dentro de listas (las cadenas van entre comillas)."""
    if isinstance(valor, str):
        return f'"{valor}"'
    return jp_a_texto(valor)


def es_verdad(valor: object) -> bool:
    """Verdad de JP: falso = nulo, false y 0... pero 0 SÍ es verdadero (como Ruby).

    Decidimos: solo 'nulo' y 'falso' son falsos. Cero es verdadero.
    """
    if valor is None:
        return False
    if valor is False:
        return False
    return True


def iguales(a: object, b: object) -> bool:
    """Igualdad de JP: los booleanos solo son iguales a sí mismos.

    1 == verdadero es falso (como en Python), pero 1 == 1.0 es verdadero.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    return a == b


def evaluar_paso(valor: object, linea: int) -> int:
    """El paso de 'a..b paso c' debe ser un número mayor que 0 (magnitud)."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorEjecucion(f"el paso de '..' espera un número, recibió {jp_a_texto(valor)!r}", linea)
    paso = int(valor)
    if paso <= 0:
        raise ErrorEjecucion("el paso de '..' debe ser mayor que 0 (la dirección la deciden los extremos)", linea)
    return paso


_MAX_LLAMADAS = 6000  # tope del lenguaje, igual que _MAX_FRAMES de la VM


# ----------------- Intérprete -----------------

class Interprete:
    def __init__(self):
        self.global_env = Entorno()
        _instalar_nativas(self.global_env, self._llamar_valor)
        from .red import instalar as _instalar_red
        _instalar_red(self.global_env)
        from .archivos import instalar as _instalar_archivos
        _instalar_archivos(self.global_env)
        # La libreria estandar (como la de Python, en espanol): estadistica,
        # matrices/IA, fechas, sistema y patrones. La VM instala las mismas.
        from .estadistica import instalar as _instalar_estadistica
        _instalar_estadistica(self.global_env, self._llamar_valor)
        from .matrices import instalar as _instalar_matrices
        _instalar_matrices(self.global_env, self._llamar_valor)
        from .fechas import instalar as _instalar_fechas
        _instalar_fechas(self.global_env, self._llamar_valor)
        from .sistema import instalar as _instalar_sistema
        _instalar_sistema(self.global_env, self._llamar_valor)
        from .patrones import instalar as _instalar_patrones
        _instalar_patrones(self.global_env, self._llamar_valor)
        from .tablas import instalar as _instalar_tablas
        _instalar_tablas(self.global_env, self._llamar_valor)
        from .servidor import instalar as _instalar_servidor
        _instalar_servidor(self.global_env, self._llamar_valor)
        from .seguridad import instalar as _instalar_seguridad
        _instalar_seguridad(self.global_env, self._llamar_valor)
        self.ultimo_valor: object = None  # valor de la última sentencia de expresión (para el REPL)
        self._profundidad = 0  # llamadas JP activas (tope _MAX_LLAMADAS, como la VM)
        # Módulos importados: ruta resuelta -> nombres exportados; y pila de
        # rutas en curso para detectar importaciones circulares.
        self._modulos_cache: dict[str, dict] = {}
        self._importando: set[str] = set()
        self.directorio_base: Path = Path.cwd()
        # Nombres globales instalados por el JIT (jp.nativo): la declaración
        # JP no los pisa para que la versión nativa siga viva.
        self.resguardadas: set[str] = set()
        # Despachos por tipo: un dict.get(type(nodo)) es más rápido que una
        # cadena larga de isinstance en el camino caliente del intérprete.
        self._ejecutores = {
            NodoPrograma: self._ej_programa,
            NodoDeclaracionVar: self._ej_declaracion,
            NodoExpresion: self._ej_expresion,
            NodoBloque: self._ej_bloque,
            NodoSi: self._ej_si,
            NodoElegir: self._ej_elegir,
            NodoIntentar: self._ej_intentar,
            NodoMientras: self._ej_mientras,
            NodoPara: self._ejecutar_para,
            NodoFuncion: self._ej_funcion,
            NodoClase: self._ej_clase,
            NodoLanzar: self._ej_lanzar,
            NodoImportar: self._ej_importar,
            NodoDeclaracionLista: self._ej_declaracion_lista,
            NodoRetorna: self._ej_retorna,
            NodoRomper: self._ej_romper,
            NodoContinuar: self._ej_continuar,
        }
        self._evaluadores = {
            NodoNumero: self._ev_literal,
            NodoCadena: self._ev_literal,
            NodoBooleano: self._ev_literal,
            NodoNulo: self._ev_nulo,
            NodoVariable: self._ev_variable,
            NodoAsignacion: self._ev_asig,
            NodoAsignarIndice: self._ev_asig_indice,
            NodoBinario: self._ev_binario,
            NodoUnario: self._ev_unario,
            NodoLista: self._ev_lista,
            NodoRango: self._ev_rango,
            NodoIndice: self._ev_indice,
            NodoDiccionario: self._ev_diccionario,
            NodoInterpolacion: self._ev_interpolacion,
            NodoLlamada: self._ev_llamada,
            NodoAsignacionLista: self._ev_asignacion_lista,
            NodoFuncion: self._ev_funcion,  # función anónima usada como valor
        }

    # ---------- API pública ----------

    def ejecutar(self, programa: NodoPrograma, directorio: object = None) -> None:
        # El tope del LENGUAJE es _MAX_LLAMADAS llamadas JP (igual que la VM);
        # el de Python debe quedar por encima para no cortar antes de tiempo
        # (cada llamada JP gasta varios marcos de Python en el árbol).
        if sys.getrecursionlimit() < 150000:
            sys.setrecursionlimit(150000)
        if directorio is not None:
            self.directorio_base = Path(str(directorio))
        self.ultimo_valor = None
        try:
            self._ejecutar_bloque(programa.sentencias, self.global_env)
        except Retornar as retorno:
            # 'retorna' en el nivel superior termina el programa en paz
            # (antes se escapaba la excepción interna y tumbaba el REPL).
            self.ultimo_valor = retorno.valor
        except _Romper as senal:
            raise ErrorEjecucion("'romper' fuera de un bucle", senal.linea) from None
        except _Continuar as senal:
            raise ErrorEjecucion("'continuar' fuera de un bucle", senal.linea) from None

    # ---------- sentencias ----------

    def _ejecutar_bloque(self, sentencias: list[Nodo], entorno: Entorno) -> None:
        for sentencia in sentencias:
            self._ejecutar(sentencia, entorno)

    def _ejecutar(self, nodo: Nodo, entorno: Entorno) -> None:
        handler = self._ejecutores.get(type(nodo))
        if handler is None:
            raise ErrorEjecucion(f"nodo desconocido: {type(nodo).__name__}", getattr(nodo, "linea", 0))
        handler(nodo, entorno)

    def _ej_programa(self, nodo, entorno) -> None:
        self._ejecutar_bloque(nodo.sentencias, entorno)

    def _ej_declaracion(self, nodo: NodoDeclaracionVar, entorno: Entorno) -> None:
        valor = None
        if nodo.inicializador is not None:
            valor = self._evaluar(nodo.inicializador, entorno)
        entorno.definir(nodo.nombre, valor)

    def _desestructurar(self, valor: object, nombres: list[str], linea: int) -> list:
        if not isinstance(valor, list):
            raise ErrorEjecucion(
                f"la desestructuración '[a, b] = ...' espera una lista, no {jp_a_texto(valor)!r}", linea
            )
        if len(valor) != len(nombres):
            raise ErrorEjecucion(
                f"la desestructuración esperaba {len(nombres)} valor(es) y recibió {len(valor)}", linea
            )
        return list(valor)

    def _ej_declaracion_lista(self, nodo: NodoDeclaracionLista, entorno: Entorno) -> None:
        valores = self._desestructurar(
            self._evaluar(nodo.inicializador, entorno), nodo.nombres, nodo.linea
        )
        for nombre, valor in zip(nodo.nombres, valores):
            entorno.definir(nombre, valor)

    def _ev_asignacion_lista(self, nodo: NodoAsignacionLista, entorno: Entorno):
        valores = self._desestructurar(self._evaluar(nodo.valor, entorno), nodo.nombres, nodo.linea)
        resultado = list(valores)
        for nombre, valor in zip(nodo.nombres, valores):
            entorno.asignar(nombre, valor, nodo.linea)
        return resultado

    def _ej_lanzar(self, nodo: NodoLanzar, entorno: Entorno) -> None:
        valor = self._evaluar(nodo.expresion, entorno)
        raise ErrorEjecucion(jp_a_texto(valor), nodo.linea, tipo="usuario")

    def _ej_clase(self, nodo: NodoClase, entorno: Entorno) -> None:
        padre = None
        if nodo.padre is not None:
            valor_padre = entorno.obtener(nodo.padre, nodo.linea)
            if not isinstance(valor_padre, ClaseJP):
                raise ErrorEjecucion(
                    f"'{nodo.padre}' no es una clase: no se puede heredar de {jp_a_texto(valor_padre)!r}",
                    nodo.linea,
                )
            padre = valor_padre
        metodos = {
            metodo.nombre: FuncionJP(metodo, entorno) for metodo in nodo.metodos
        }
        entorno.definir(nodo.nombre, ClaseJP(nodo.nombre, metodos, padre))

    def _ej_importar(self, nodo: NodoImportar, entorno: Entorno) -> None:
        """importar "x.jp" [como n]: ejecuta el módulo una sola vez y trae sus nombres."""
        ruta = (self.directorio_base / nodo.ruta).resolve()
        if not ruta.is_file():
            raise ErrorEjecucion(
                f"no se encontró el módulo '{nodo.ruta}' (buscado en {ruta})", nodo.linea
            )
        clave = str(ruta)
        if clave in self._modulos_cache:
            exportaciones = self._modulos_cache[clave]
        elif clave in self._importando:
            raise ErrorEjecucion(
                f"importación circular detectada: '{nodo.ruta}' ya se está importando", nodo.linea
            )
        else:
            self._importando.add(clave)
            try:
                from .lexer import tokenizar
                from .parser import parsear

                fuente = ruta.read_text(encoding="utf-8")
                sub = Interprete()
                sub._modulos_cache = self._modulos_cache   # una sola ejecución en total
                sub._importando = self._importando
                antes = dict(sub.global_env.variables)
                sub.ejecutar(parsear(tokenizar(fuente)), directorio=ruta.parent)
                exportaciones = {
                    nombre: valor
                    for nombre, valor in sub.global_env.variables.items()
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
                    f"error en el módulo '{nodo.ruta}'{donde}: {detalle}", nodo.linea
                ) from None
            finally:
                self._importando.discard(clave)
        if nodo.alias is not None:
            entorno.definir(nodo.alias, exportaciones)
        else:
            for nombre, valor in exportaciones.items():
                entorno.definir(nombre, valor)

    def _ej_expresion(self, nodo: NodoExpresion, entorno: Entorno) -> None:
        self.ultimo_valor = self._evaluar(nodo.expresion, entorno)

    def _ej_bloque(self, nodo: NodoBloque, entorno: Entorno) -> None:
        # Optimización: si el bloque no declara nada, no hace falta crear un
        # ámbito nuevo (los bucles lo agradecen: 1 allocación menos por vuelta).
        if nodo.declara:
            self._ejecutar_bloque(nodo.sentencias, Entorno(padre=entorno))
        else:
            for sentencia in nodo.sentencias:
                self._ejecutar(sentencia, entorno)

    def _ej_si(self, nodo: NodoSi, entorno: Entorno) -> None:
        if es_verdad(self._evaluar(nodo.condicion, entorno)):
            self._ejecutar(nodo.entonces, entorno)
        elif nodo.sino is not None:
            self._ejecutar(nodo.sino, entorno)

    def _ej_elegir(self, nodo: NodoElegir, entorno: Entorno) -> None:
        """Sin caída entre casos: gana el primero que coincide (o el 'sino')."""
        valor = self._evaluar(nodo.expresion, entorno)
        for valores, cuerpo in nodo.casos:
            for candidato in valores:
                if self._igual(valor, self._evaluar(candidato, entorno)):
                    self._ejecutar(cuerpo, entorno)
                    return
        if nodo.sino is not None:
            self._ejecutar(nodo.sino, entorno)

    def _ej_intentar(self, nodo: NodoIntentar, entorno: Entorno) -> None:
        """intenta { ... } atrapa error { ... }: captura errores de ejecución.

        'romper', 'continuar' y 'retorna' NO son errores: siguen su camino.
        El nombre del error solo vive dentro del bloque 'atrapa'.
        """
        try:
            try:
                self._ejecutar(nodo.cuerpo, entorno)
            except ErrorEjecucion as error:
                if nodo.captura is None:
                    raise
                entorno_error = Entorno(padre=entorno)
                if nodo.nombre_error is not None:
                    entorno_error.definir(nodo.nombre_error, crear_error_valor(error))
                self._ejecutar(nodo.captura, entorno_error)
        finally:
            # 'finalmente' corre siempre: sin error, tras el 'atrapa' y antes
            # de que un devuelve/romper/continuar salga del bloque.
            if nodo.finalmente is not None:
                self._ejecutar(nodo.finalmente, entorno)

    def _ej_mientras(self, nodo: NodoMientras, entorno: Entorno) -> None:
        while es_verdad(self._evaluar(nodo.condicion, entorno)):
            try:
                self._ejecutar(nodo.cuerpo, entorno)
            except _Romper:
                break
            except _Continuar:
                continue

    def _ej_funcion(self, nodo: NodoFuncion, entorno: Entorno) -> None:
        if entorno is self.global_env and nodo.nombre in self.resguardadas:
            return  # el JIT ya puso una versión nativa con este nombre
        entorno.definir(nodo.nombre, FuncionJP(nodo, entorno))

    def _ej_retorna(self, nodo: NodoRetorna, entorno: Entorno) -> None:
        valor = None
        if nodo.valor is not None:
            valor = self._evaluar(nodo.valor, entorno)
        raise Retornar(valor)

    def _ej_romper(self, nodo, entorno) -> None:
        raise _Romper(nodo.linea)

    def _ej_continuar(self, nodo, entorno) -> None:
        raise _Continuar(nodo.linea)

    def _ejecutar_para(self, nodo: NodoPara, entorno: Entorno) -> None:
        if type(nodo.iterable) is NodoRango:
            # Perezoso: 'para i en 1..1000000' no crea la lista entera.
            elementos = self._rango_perezoso(nodo.iterable, entorno)
            iterable = elementos
        else:
            iterable = self._evaluar(nodo.iterable, entorno)
        if isinstance(iterable, (list, range)):
            elementos = iterable
        elif isinstance(iterable, dict):
            elementos = list(iterable.keys())
        elif isinstance(iterable, str):
            elementos = list(iterable)
        elif isinstance(iterable, (int, float)):
            # para i en 5 { ... }  ->  1..5
            elementos = list(range(1, int(iterable) + 1))
        else:
            raise ErrorEjecucion(
                f"'para ... en' espera una lista, cadena, diccionario o número, no {jp_a_texto(iterable)!r}", nodo.linea
            )
        if nodo.variable2 is not None:
            # para i, valor en lista -> (posición desde 0, valor)
            # para clave, valor en dict -> (clave, valor)
            if isinstance(iterable, dict):
                pares = iterable.items()
            else:
                pares = enumerate(elementos)
            for primero, segundo in pares:
                cuerpo_env = Entorno(padre=entorno)
                cuerpo_env.definir(nodo.variable, primero)
                cuerpo_env.definir(nodo.variable2, segundo)
                try:
                    self._ejecutar_bloque(nodo.cuerpo.sentencias, cuerpo_env)
                except _Romper:
                    break
                except _Continuar:
                    continue
            return
        for elemento in elementos:
            cuerpo_env = Entorno(padre=entorno)
            cuerpo_env.definir(nodo.variable, elemento)
            try:
                self._ejecutar_bloque(nodo.cuerpo.sentencias, cuerpo_env)
            except _Romper:
                break
            except _Continuar:
                continue

    # ---------- expresiones ----------

    def _evaluar(self, nodo: Nodo, entorno: Entorno) -> object:
        handler = self._evaluadores.get(type(nodo))
        if handler is None:
            raise ErrorEjecucion(f"expresión desconocida: {type(nodo).__name__}", getattr(nodo, "linea", 0))
        return handler(nodo, entorno)

    def _ev_literal(self, nodo, entorno):
        return nodo.valor

    def _ev_nulo(self, nodo, entorno):
        return None

    def _ev_variable(self, nodo: NodoVariable, entorno: Entorno):
        return entorno.obtener(nodo.nombre, nodo.linea)

    def _ev_asig(self, nodo: NodoAsignacion, entorno: Entorno):
        valor = self._evaluar(nodo.valor, entorno)
        entorno.asignar(nodo.nombre, valor, nodo.linea)
        return valor

    def _ev_asig_indice(self, nodo: NodoAsignarIndice, entorno: Entorno):
        objeto = self._evaluar(nodo.objeto, entorno)
        indice = self._evaluar(nodo.indice, entorno)
        valor = self._evaluar(nodo.valor, entorno)
        if isinstance(objeto, Instancia):
            if not isinstance(indice, str):
                raise ErrorEjecucion("los campos de un objeto se acceden con .nombre", nodo.linea)
            objeto.campos[indice] = valor
            return valor
        if isinstance(objeto, dict):
            if not isinstance(indice, str):
                raise ErrorEjecucion("la clave de un diccionario debe ser texto", nodo.linea)
            objeto[indice] = valor
            return valor
        if isinstance(objeto, list):
            if isinstance(indice, bool) or not isinstance(indice, (int, float)):
                raise ErrorEjecucion("el índice de una lista debe ser un número", nodo.linea)
            i = int(indice)
            if i < 0:
                i += len(objeto)
            if i < 0 or i >= len(objeto):
                raise ErrorEjecucion(
                    f"índice fuera de rango: {i} (lista de {len(objeto)} elementos)", nodo.linea
                )
            objeto[i] = valor
            return valor
        raise ErrorEjecucion(f"no se puede asignar dentro de {jp_a_texto(objeto)!r}", nodo.linea)

    def _ev_binario(self, nodo: NodoBinario, entorno: Entorno):
        return self._binario(nodo, entorno)

    def _ev_unario(self, nodo: NodoUnario, entorno: Entorno):
        return self._unario(nodo, entorno)

    def _ev_lista(self, nodo: NodoLista, entorno: Entorno):
        return [self._evaluar(e, entorno) for e in nodo.elementos]

    def _ev_rango(self, nodo: NodoRango, entorno: Entorno):
        return self._rango(nodo, entorno)

    def _ev_indice(self, nodo: NodoIndice, entorno: Entorno):
        return self._indice(nodo, entorno)

    def _ev_diccionario(self, nodo: NodoDiccionario, entorno: Entorno):
        return {self._evaluar(k, entorno): self._evaluar(v, entorno) for k, v in nodo.pares}

    def _ev_interpolacion(self, nodo: NodoInterpolacion, entorno: Entorno):
        # "texto {expr} medio": las partes de texto van tal cual; las
        # expresiones se convierten a texto como hace muestra() (jp_a_texto).
        piezas: list[str] = []
        for indice, parte in enumerate(nodo.partes):
            if indice % 2 == 0:
                piezas.append(parte.valor)
            else:
                piezas.append(jp_a_texto(self._evaluar(parte, entorno)))
        return "".join(piezas)

    def _ev_llamada(self, nodo: NodoLlamada, entorno: Entorno):
        return self._llamada(nodo, entorno)

    def _ev_funcion(self, nodo: NodoFuncion, entorno: Entorno):
        """Función anónima como valor: captura el entorno donde se define."""
        return FuncionJP(nodo, entorno)

    def _rango(self, nodo: NodoRango, entorno: Entorno) -> list[int]:
        """1..5 -> [1,2,3,4,5] inclusive; 5..1 -> [5,4,3,2,1] (al revés también).

        Con paso: 1..9 paso 4 -> [1,5,9]; 9..1 paso 4 -> [9,5,1]. El paso es
        una magnitud (mayor que 0) y la dirección la marcan los extremos.
        """
        inicio = self._evaluar(nodo.izquierda, entorno)
        fin = self._evaluar(nodo.derecha, entorno)
        for valor in (inicio, fin):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ErrorEjecucion(
                    f"el rango '..' espera números, recibió {jp_a_texto(valor)!r}", nodo.linea
                )
        i, f = int(inicio), int(fin)
        if nodo.paso is None:
            paso = 1 if i <= f else -1
        else:
            paso = evaluar_paso(self._evaluar(nodo.paso, entorno), nodo.linea)
            if i > f:
                paso = -paso
        return list(range(i, f + (1 if paso > 0 else -1), paso))

    def _rango_perezoso(self, nodo: NodoRango, entorno: Entorno) -> range:
        """El mismo rango que _rango, pero sin crear la lista (para 'para')."""
        inicio = self._evaluar(nodo.izquierda, entorno)
        fin = self._evaluar(nodo.derecha, entorno)
        for valor in (inicio, fin):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ErrorEjecucion(
                    f"el rango '..' espera números, recibió {jp_a_texto(valor)!r}", nodo.linea
                )
        i, f = int(inicio), int(fin)
        if nodo.paso is None:
            paso = 1 if i <= f else -1
        else:
            paso = evaluar_paso(self._evaluar(nodo.paso, entorno), nodo.linea)
            if i > f:
                paso = -paso
        return range(i, f + (1 if paso > 0 else -1), paso)

    def _binario(self, nodo: NodoBinario, entorno: Entorno) -> object:
        operador = nodo.operador
        # 'y' / 'o' con cortocircuito
        if operador == "y":
            izquierda = self._evaluar(nodo.izquierda, entorno)
            if not es_verdad(izquierda):
                return izquierda
            return self._evaluar(nodo.derecha, entorno)
        if operador == "o":
            izquierda = self._evaluar(nodo.izquierda, entorno)
            if es_verdad(izquierda):
                return izquierda
            return self._evaluar(nodo.derecha, entorno)

        izquierda = self._evaluar(nodo.izquierda, entorno)
        derecha = self._evaluar(nodo.derecha, entorno)

        if operador == "==":
            return self._igual(izquierda, derecha)
        if operador == "!=":
            return not self._igual(izquierda, derecha)

        if operador in ("<", ">", "<=", ">="):
            self._verificar_numeros(izquierda, derecha, operador, nodo.linea)
            if operador == "<":
                return izquierda < derecha
            if operador == ">":
                return izquierda > derecha
            if operador == "<=":
                return izquierda <= derecha
            return izquierda >= derecha

        if operador == "+":
            # concatenación si alguno es cadena
            if isinstance(izquierda, str) or isinstance(derecha, str):
                return jp_a_texto(izquierda) + jp_a_texto(derecha)
            if isinstance(izquierda, list) and isinstance(derecha, list):
                return izquierda + derecha
            self._verificar_numeros(izquierda, derecha, "+", nodo.linea)
            return izquierda + derecha

        if operador == "*":
            # "ab" * 3 = "ababab"
            if isinstance(izquierda, str) and isinstance(derecha, (int, float)) and not isinstance(derecha, bool):
                return izquierda * int(derecha)
            self._verificar_numeros(izquierda, derecha, operador, nodo.linea)
            return izquierda * derecha

        if operador == "**":
            self._verificar_numeros(izquierda, derecha, "**", nodo.linea)
            try:
                resultado = izquierda ** derecha
            except (OverflowError, ZeroDivisionError):
                raise ErrorEjecucion("potencia no válida (¿0 elevado a algo negativo?)", nodo.linea)
            if isinstance(resultado, complex):
                raise ErrorEjecucion("la potencia no dio un número real", nodo.linea)
            return resultado

        if operador in ("-", "/", "%"):
            self._verificar_numeros(izquierda, derecha, operador, nodo.linea)
            if operador == "-":
                return izquierda - derecha
            if operador == "/":
                if derecha == 0:
                    raise ErrorEjecucion("división por cero", nodo.linea)
                resultado = izquierda / derecha
                # si ambos eran enteros y la división es exacta, mantener entero
                if isinstance(izquierda, int) and isinstance(derecha, int) and izquierda % derecha == 0:
                    return izquierda // derecha
                return resultado
            if operador == "%":
                if derecha == 0:
                    raise ErrorEjecucion("módulo por cero", nodo.linea)
                return izquierda % derecha

        raise ErrorEjecucion(f"operador desconocido: {operador}", nodo.linea)

    def _unario(self, nodo: NodoUnario, entorno: Entorno) -> object:
        valor = self._evaluar(nodo.operando, entorno)
        if nodo.operador == "-":
            if not isinstance(valor, (int, float)) or isinstance(valor, bool):
                raise ErrorEjecucion(f"el operando de '-' debe ser número, no {jp_a_texto(valor)!r}", nodo.linea)
            return -valor
        if nodo.operador == "no":
            return not es_verdad(valor)
        raise ErrorEjecucion(f"operador unario desconocido: {nodo.operador}", nodo.linea)

    def _indice(self, nodo: NodoIndice, entorno: Entorno) -> object:
        objeto = self._evaluar(nodo.objeto, entorno)
        indice = self._evaluar(nodo.indice, entorno)
        return self._indexar(objeto, indice, nodo.linea)

    @staticmethod
    def _indexar(objeto: object, indice: object, linea: int) -> object:
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
                raise ErrorEjecucion(f"índice fuera de rango: {i} (lista de {len(objeto)} elementos)", linea)
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
                raise ErrorEjecucion(f"índice fuera de rango: {i} (cadena de {len(objeto)} caracteres)", linea)
            return objeto[i]
        raise ErrorEjecucion(f"este valor no se puede indexar: {jp_a_texto(objeto)!r}", linea)

    def _llamada(self, nodo: NodoLlamada, entorno: Entorno) -> object:
        callee = self._evaluar(nodo.callee, entorno)
        argumentos = [self._evaluar(arg, entorno) for arg in nodo.argumentos]
        return self._llamar_valor(callee, argumentos, nodo.linea)

    def _llamar_valor(self, callee: object, argumentos: list[object], linea: int = 0) -> object:
        """Llama a un valor-función (JP o nativa). La usan también las nativas
        de orden superior (mapear, filtrar, reducir, ordenar con clave...)."""
        if isinstance(callee, ClaseJP):
            return self._instanciar(callee, argumentos, linea)
        if isinstance(callee, MetodoLigado):
            funcion = callee.funcion
            if not isinstance(funcion, FuncionJP):  # en el arbol siempre lo es
                raise ErrorEjecucion("metodo no valido", linea)
            return self._llamar_funcion(funcion, argumentos, linea, este=callee.instancia)
        if isinstance(callee, FuncionNativa):
            if callee.aridad is not None and len(argumentos) != callee.aridad:
                raise ErrorEjecucion(
                    f"{callee.nombre}() espera {callee.aridad} argumento(s), recibió {len(argumentos)}", linea
                )
            try:
                return callee.funcion(*argumentos)
            except ErrorEjecucion:
                raise
            except TypeError as exc:
                raise ErrorEjecucion(f"argumentos no válidos para {callee.nombre}(): {exc}", linea)

        if isinstance(callee, FuncionJP):
            return self._llamar_funcion(callee, argumentos, linea)

        raise ErrorEjecucion(f"este valor no es una función: {jp_a_texto(callee)!r}", linea)

    def _instanciar(self, clase: ClaseJP, argumentos: list[object], linea: int):
        """Clase(args): crea el objeto y llama a su 'iniciar' (si lo tiene)."""
        instancia = Instancia(clase)
        iniciar = buscar_metodo(clase, "iniciar")
        if iniciar is not None:
            self._llamar_funcion(iniciar, argumentos, linea, este=instancia)
        elif argumentos:
            raise ErrorEjecucion(
                f"la clase '{clase.nombre}' no tiene un metodo 'iniciar' y no acepta argumentos",
                linea,
            )
        return instancia

    def _llamar_funcion(self, funcion: FuncionJP, argumentos: list[object], linea: int, este: object = None) -> object:
        declaracion = funcion.declaracion
        defectos = declaracion.defectos or [None] * len(declaracion.parametros)
        obligatorios = sum(1 for d in defectos if d is None)
        if not obligatorios <= len(argumentos) <= len(declaracion.parametros):
            espera = (
                f"{obligatorios} a {len(declaracion.parametros)}"
                if obligatorios != len(declaracion.parametros)
                else f"{len(declaracion.parametros)}"
            )
            raise ErrorEjecucion(
                f"la función '{declaracion.nombre or '<anónima>'}' espera "
                f"{espera} argumento(s), recibió {len(argumentos)}",
                linea,
            )
        if self._profundidad >= _MAX_LLAMADAS:
            raise ErrorEjecucion("desbordamiento de pila (¿recursión infinita?)", linea)
        entorno_local = Entorno(padre=funcion.cierre)
        if este is not None:
            entorno_local.definir("este", este)
        for indice, nombre in enumerate(declaracion.parametros):
            if indice < len(argumentos):
                entorno_local.definir(nombre, argumentos[indice])
            else:
                # El defecto se evalúa en el ámbito local: puede usar los
                # parámetros anteriores (funcion f(a, b = a + 1) { ... }).
                entorno_local.definir(nombre, self._evaluar(defectos[indice], entorno_local))
        self._profundidad += 1
        try:
            self._ejecutar_bloque(declaracion.cuerpo.sentencias, entorno_local)
        except Retornar as retorno:
            return retorno.valor
        except _Romper as senal:
            # Un 'romper' no puede cruzar el límite de la función.
            raise ErrorEjecucion("'romper' fuera de un bucle", senal.linea) from None
        except _Continuar as senal:
            raise ErrorEjecucion("'continuar' fuera de un bucle", senal.linea) from None
        finally:
            self._profundidad -= 1
        return None

    # ---------- helpers ----------

    @staticmethod
    def _igual(a: object, b: object) -> bool:
        if isinstance(a, bool) or isinstance(b, bool):
            return a is b
        return a == b

    @staticmethod
    def _verificar_numeros(a: object, b: object, operador: str, linea: int) -> None:
        for valor in (a, b):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ErrorEjecucion(
                    f"el operador '{operador}' espera números, recibió {jp_a_texto(valor)!r}", linea
                )


# ----------------- Funciones nativas (librería estándar) -----------------

def _instalar_nativas(entorno: Entorno, invocar=None) -> None:
    """Instala la librería estándar en el entorno global.

    `invocar` es la forma que tiene el motor activo de llamar a un valor-función
    (el árbol y la VM tienen la suya); lo usan las nativas de orden superior
    (mapear, filtrar, reducir, para_cada, ordenar con clave).
    """

    def _num(valor: object, nombre: str) -> float | int:
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise ErrorEjecucion(f"{nombre}() espera un número, no {jp_a_texto(valor)!r}")
        return valor

    def _secuencia(valor: object, nombre: str) -> list:
        """Lo mismo que acepta 'para ... en': lista, texto, diccionario o número."""
        if isinstance(valor, list):
            return list(valor)
        if isinstance(valor, str):
            return list(valor)
        if isinstance(valor, dict):
            return list(valor.keys())
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            return list(range(1, int(valor) + 1))
        raise ErrorEjecucion(
            f"{nombre}() espera lista, texto, diccionario o número, no {jp_a_texto(valor)!r}"
        )

    def _llamar_fun(f: object, argumentos: list, nombre: str) -> object:
        if invocar is None:  # los dos motores reales siempre pasan su invocador
            raise ErrorEjecucion(f"{nombre}() necesita un motor que sepa llamar funciones")
        return invocar(f, argumentos, 0)

    def muestra(*valores: object) -> None:
        print(" ".join(jp_a_texto(v) for v in valores) if valores else "")

    def longitud(valor: object) -> int:
        if isinstance(valor, (str, list, dict)):
            return len(valor)
        raise ErrorEjecucion(f"longitud() espera cadena, lista o diccionario, no {jp_a_texto(valor)!r}")

    def entero(valor: object) -> int:
        if isinstance(valor, bool):
            raise ErrorEjecucion("entero() no acepta booleanos")
        if isinstance(valor, (int, float)):
            return int(valor)
        if isinstance(valor, str):
            try:
                return int(float(valor))
            except ValueError:
                raise ErrorEjecucion(f"entero() no puede convertir la cadena {valor!r}")
        raise ErrorEjecucion(f"entero() espera número o cadena, no {jp_a_texto(valor)!r}")

    def texto(valor: object) -> str:
        return jp_a_texto(valor)

    def leer(*args: object) -> str:
        if len(args) > 1:
            raise ErrorEjecucion("leer() espera 0 o 1 argumento")
        mensaje = jp_a_texto(args[0]) if args else ""
        try:
            return input(mensaje)
        except EOFError:
            raise ErrorEjecucion("leer() no recibió entrada (fin de archivo)")

    def azar(n: object) -> int:
        """Número al azar entre 1 y n (inclusivo)."""
        if isinstance(n, bool) or not isinstance(n, (int, float)):
            raise ErrorEjecucion("azar() espera un número, como azar(100)")
        if int(n) < 1:
            raise ErrorEjecucion("azar() espera 1 o más")
        return random.randint(1, int(n))

    def numero(valor: object) -> float:
        if isinstance(valor, bool):
            raise ErrorEjecucion("numero() no acepta booleanos")
        if isinstance(valor, (int, float)):
            return float(valor)
        if isinstance(valor, str):
            try:
                return float(valor)
            except ValueError:
                raise ErrorEjecucion(f"numero() no puede convertir la cadena {valor!r}")
        raise ErrorEjecucion(f"numero() espera número o cadena, no {jp_a_texto(valor)!r}")

    def rango(*args: object) -> list[int]:
        for a in args:
            if isinstance(a, bool) or not isinstance(a, (int, float)):
                raise ErrorEjecucion("rango() espera números")
        valores = [int(a) for a in args]
        if len(valores) == 1:
            return list(range(valores[0]))
        if len(valores) == 2:
            return list(range(valores[0], valores[1]))
        if len(valores) == 3:
            return list(range(valores[0], valores[1], valores[2]))
        raise ErrorEjecucion("rango() espera 1, 2 o 3 argumentos")

    # ---------- matemáticas ----------

    def absoluto(x: object):
        return abs(_num(x, "absoluto"))

    def raiz(x: object) -> float:
        valor = _num(x, "raiz")
        if valor < 0:
            raise ErrorEjecucion(f"raiz() de un número negativo ({jp_a_texto(valor)})")
        return math.sqrt(valor)

    def potencia(a: object, b: object):
        return _num(a, "potencia") ** _num(b, "potencia")

    def piso(x: object) -> int:
        return math.floor(_num(x, "piso"))

    def techo(x: object) -> int:
        return math.ceil(_num(x, "techo"))

    def redondear(x: object, decimales: object = 0):
        """Redondeo de escuela: 2.5 -> 3, -2.5 -> -3, 3.14159 con 2 -> 3.14."""
        valor = _num(x, "redondear")
        n = int(_num(decimales, "redondear"))
        factor = 10 ** n
        escalado = valor * factor
        entero = math.floor(escalado + 0.5) if escalado >= 0 else math.ceil(escalado - 0.5)
        resultado = entero / factor
        if n <= 0:
            return int(resultado)
        return resultado

    def log(x: object, base: object = None) -> float:
        valor = _num(x, "log")
        if valor <= 0:
            raise ErrorEjecucion("log() espera un número mayor que 0")
        if base is None:
            return math.log(valor)
        b = _num(base, "log")
        if b <= 0 or b == 1:
            raise ErrorEjecucion("la base de log() debe ser mayor que 0 y distinta de 1")
        return math.log(valor, b)

    def _lista_de_numeros(args: tuple, nombre: str) -> list:
        if len(args) == 1 and isinstance(args[0], list):
            args = tuple(args[0])
        if not args:
            raise ErrorEjecucion(f"{nombre}() necesita al menos un número")
        return [_num(v, nombre) for v in args]

    def minimo(*args: object):
        return min(_lista_de_numeros(args, "minimo"))

    def maximo(*args: object):
        return max(_lista_de_numeros(args, "maximo"))

    def sumar(secuencia: object):
        total: float | int = 0
        for valor in _secuencia(secuencia, "sumar"):
            total += _num(valor, "sumar")
        return total

    def pi() -> float:
        return math.pi

    def aleatorio() -> float:
        """Número decimal al azar entre 0 y 1 (azar(n) sigue siendo para 1..n)."""
        return random.random()

    # ---------- funciones de orden superior ----------

    def mapear(secuencia: object, f: object) -> list:
        """[f(x) para cada x]: mapear([1, 2], funcion(x) { devuelve x * 2 })."""
        return [_llamar_fun(f, [x], "mapear") for x in _secuencia(secuencia, "mapear")]

    def filtrar(secuencia: object, f: object) -> list:
        return [
            x
            for x in _secuencia(secuencia, "filtrar")
            if es_verdad(_llamar_fun(f, [x], "filtrar"))
        ]

    def para_cada(secuencia: object, f: object) -> None:
        for x in _secuencia(secuencia, "para_cada"):
            _llamar_fun(f, [x], "para_cada")

    def reducir(secuencia: object, f: object, *inicial: object):
        """reducir(lista, f) o reducir(lista, f, inicial): acumula de izquierda a derecha."""
        if len(inicial) > 1:
            raise ErrorEjecucion("reducir() espera 2 o 3 argumentos")
        elementos = _secuencia(secuencia, "reducir")
        if inicial:
            acumulado = inicial[0]
        elif elementos:
            acumulado = elementos[0]
            elementos = elementos[1:]
        else:
            raise ErrorEjecucion("reducir() de una lista vacía necesita un valor inicial")
        for x in elementos:
            acumulado = _llamar_fun(f, [acumulado, x], "reducir")
        return acumulado

    def ordenar(secuencia: object, *clave: object) -> list:
        """Copia ordenada; con una función clave: ordenar(lista, funcion(x) { ... })."""
        if len(clave) > 1:
            raise ErrorEjecucion("ordenar() espera 1 o 2 argumentos")
        elementos = _secuencia(secuencia, "ordenar")
        try:
            if clave:
                f = clave[0]
                return sorted(elementos, key=lambda x: _llamar_fun(f, [x], "ordenar"))
            return sorted(elementos)
        except TypeError as exc:
            raise ErrorEjecucion(f"ordenar() no puede comparar esos valores: {exc}")

    # ---------- texto ----------

    def _cadena(v: object, nombre: str) -> str:
        if not isinstance(v, str):
            raise ErrorEjecucion(f"{nombre}() espera texto, no {jp_a_texto(v)!r}")
        return v

    def mayusculas(v: object) -> str:
        return _cadena(v, "mayusculas").upper()

    def minusculas(v: object) -> str:
        return _cadena(v, "minusculas").lower()

    def recortar(v: object) -> str:
        return _cadena(v, "recortar").strip()

    def separar(texto: object, separador: object = None) -> list:
        t = _cadena(texto, "separar")
        if separador is None:
            return t.split()
        return t.split(_cadena(separador, "separar"))

    def unir(partes: object, separador: object = "") -> str:
        if not isinstance(partes, list):
            raise ErrorEjecucion(f"unir() espera una lista, no {jp_a_texto(partes)!r}")
        sep = _cadena(separador, "unir")
        return sep.join(jp_a_texto(p) for p in partes)

    def contiene(contenedor: object, pieza: object) -> bool:
        if isinstance(contenedor, str):
            return isinstance(pieza, str) and pieza in contenedor
        if isinstance(contenedor, list):
            return pieza in contenedor
        if isinstance(contenedor, dict):
            return isinstance(pieza, str) and pieza in contenedor
        raise ErrorEjecucion(
            f"contiene() espera texto, lista o diccionario, no {jp_a_texto(contenedor)!r}"
        )

    def reemplazar(texto: object, viejo: object, nuevo: object) -> str:
        return _cadena(texto, "reemplazar").replace(
            _cadena(viejo, "reemplazar"), _cadena(nuevo, "reemplazar")
        )

    def subtexto(texto: object, inicio: object, fin: object = None) -> str:
        t = _cadena(texto, "subtexto")
        if isinstance(inicio, bool) or not isinstance(inicio, (int, float)):
            raise ErrorEjecucion("subtexto() espera números para inicio y fin")
        i = int(inicio)
        f = len(t) if fin is None else int(fin)  # type: ignore[call-overload]
        return t[i:f] if i >= 0 and f >= 0 else t[i:f]  # soporta negativos como listas

    def letra(texto: object, posicion: object) -> str:
        t = _cadena(texto, "letra")
        if isinstance(posicion, bool) or not isinstance(posicion, (int, float)):
            raise ErrorEjecucion("letra() espera una posición numérica")
        i = int(posicion)
        if i < 0:
            i += len(t)
        if i < 0 or i >= len(t):
            raise ErrorEjecucion(
                f"índice fuera de rango: {i} (cadena de {len(t)} caracteres)"
            )
        return t[i]

    def sigmoide(x: object) -> float:
        """1 / (1 + e^-x): la activacion clasica de las redes neuronales."""
        valor = _num(x, "sigmoide")
        if valor >= 0:
            return 1.0 / (1.0 + math.exp(-valor))
        e = math.exp(valor)
        return e / (1.0 + e)

    def producto_punto(a: object, b: object):
        """Suma de a[i]*b[i] de dos listas del mismo largo (nucleo de toda IA)."""
        if not isinstance(a, list) or not isinstance(b, list):
            raise ErrorEjecucion("producto_punto() espera dos listas de numeros")
        if len(a) != len(b):
            raise ErrorEjecucion(
                f"producto_punto() espera listas del mismo largo ({len(a)} y {len(b)})"
            )
        total: float | int = 0
        for x, y in zip(a, b):
            total += _num(x, "producto_punto") * _num(y, "producto_punto")
        return total

    def exp(x: object) -> float:
        """e^x (para sigmoides y matemática de redes neuronales)."""
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ErrorEjecucion("exp() espera un número")
        return math.exp(x)

    def seno(x: object) -> float:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ErrorEjecucion("seno() espera un número")
        return math.sin(x)

    def coseno(x: object) -> float:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ErrorEjecucion("coseno() espera un número")
        return math.cos(x)

    def reloj() -> float:
        """Segundos (monotónicos) para medir tiempos: reloj() - reloj()."""
        return time.monotonic()

    def agregar(lista: object, valor: object) -> list:
        """Agrega un elemento al final de la lista (y la devuelve)."""
        if not isinstance(lista, list):
            raise ErrorEjecucion(f"agregar() espera una lista, no {jp_a_texto(lista)!r}")
        lista.append(valor)
        return lista

    def claves_dic(d: object) -> list:
        if not isinstance(d, dict):
            raise ErrorEjecucion(f"claves() espera un diccionario, no {jp_a_texto(d)!r}")
        return list(d.keys())

    def tiene_dic(d: object, clave: object) -> bool:
        if not isinstance(d, dict):
            raise ErrorEjecucion(f"tiene() espera un diccionario, no {jp_a_texto(d)!r}")
        return clave in d

    def valores(d: object) -> list:
        if not isinstance(d, dict):
            raise ErrorEjecucion(f"valores() espera un diccionario, no {jp_a_texto(d)!r}")
        return list(d.values())

    def elementos(d: object) -> list:
        """Pares [clave, valor] para recorrer un diccionario con 'para'."""
        if not isinstance(d, dict):
            raise ErrorEjecucion(f"elementos() espera un diccionario, no {jp_a_texto(d)!r}")
        return [[clave, valor] for clave, valor in d.items()]

    def empezar_con(texto: object, prefijo: object) -> bool:
        return _cadena(texto, "empezar_con").startswith(_cadena(prefijo, "empezar_con"))

    def terminar_con(texto: object, sufijo: object) -> bool:
        return _cadena(texto, "terminar_con").endswith(_cadena(sufijo, "terminar_con"))

    def buscar(texto: object, aguja: object) -> int:
        """Posición de un pedazo de texto, o -1 si no está."""
        return _cadena(texto, "buscar").find(_cadena(aguja, "buscar"))

    def repetir(valor: object, veces: object):
        """repetir(\"ab\", 3) -> \"ababab\" (también con listas)."""
        n = int(_num(veces, "repetir"))
        if isinstance(valor, str):
            return valor * n
        if isinstance(valor, list):
            return valor * n
        raise ErrorEjecucion(f"repetir() espera texto o lista, no {jp_a_texto(valor)!r}")

    def invertir(valor: object):
        """Copia al revés (no modifica el original)."""
        if isinstance(valor, list):
            return list(reversed(valor))
        if isinstance(valor, str):
            return valor[::-1]
        raise ErrorEjecucion(f"invertir() espera lista o texto, no {jp_a_texto(valor)!r}")

    def indice_de(secuencia: object, valor: object) -> int:
        """Posición de un valor en una lista o texto, o -1 si no está."""
        for i, candidato in enumerate(_secuencia(secuencia, "indice_de")):
            if iguales(candidato, valor):
                return i
        return -1

    def _indice_lista(lista: list, indice: object, nombre: str) -> int:
        if isinstance(indice, bool) or not isinstance(indice, (int, float)):
            raise ErrorEjecucion(f"{nombre}() espera un índice numérico")
        i = int(indice)
        if i < 0:
            i += len(lista)
        if i < 0 or i >= len(lista):
            raise ErrorEjecucion(f"índice fuera de rango: {i} (lista de {len(lista)} elementos)")
        return i

    def insertar(lista: object, indice: object, valor: object) -> list:
        """Inserta en la posición indicada (el resto se corre) y devuelve la lista."""
        if not isinstance(lista, list):
            raise ErrorEjecucion(f"insertar() espera una lista, no {jp_a_texto(lista)!r}")
        if isinstance(indice, bool) or not isinstance(indice, (int, float)):
            raise ErrorEjecucion("insertar() espera un índice numérico")
        lista.insert(int(indice), valor)
        return lista

    def quitar(lista: object, *indice: object):
        """Quita por posición (la última si no se indica) y devuelve el elemento."""
        if not isinstance(lista, list):
            raise ErrorEjecucion(f"quitar() espera una lista, no {jp_a_texto(lista)!r}")
        if len(indice) > 1:
            raise ErrorEjecucion("quitar() espera 1 o 2 argumentos")
        if not lista:
            raise ErrorEjecucion("quitar() de una lista vacía")
        i = -1 if not indice else _indice_lista(lista, indice[0], "quitar")
        return lista.pop(i)

    def eliminar(lista: object, valor: object) -> bool:
        """Quita la primera aparición de un valor; devuelve si lo encontró."""
        if not isinstance(lista, list):
            raise ErrorEjecucion(f"eliminar() espera una lista, no {jp_a_texto(lista)!r}")
        for i, candidato in enumerate(lista):
            if iguales(candidato, valor):
                del lista[i]
                return True
        return False

    def tipo(valor: object) -> str:
        """Nombre del tipo de un valor, en español."""
        if valor is None:
            return "nulo"
        if isinstance(valor, bool):
            return "booleano"
        if isinstance(valor, (int, float)):
            return "número"
        if isinstance(valor, str):
            return "texto"
        if isinstance(valor, list):
            return "lista"
        if isinstance(valor, dict):
            return "diccionario"
        if isinstance(valor, Instancia):
            return "objeto"
        if isinstance(valor, ClaseJP):
            return "clase"
        if isinstance(valor, (FuncionJP, FuncionNativa, Cierre, MetodoLigado)):
            return "función"
        return "valor"

    # Métodos de valor: reutilizan las nativas poniendo el receptor como primer argumento.
    # En diccionarios la clave manda y el método es fallback; en texto/listas el método manda.
    _METODOS_VALOR[str] = {
        "mayusculas": (mayusculas, 1),
        "minusculas": (minusculas, 1),
        "recortar": (recortar, 1),
        "separar": (separar, None),
        "reemplazar": (reemplazar, 3),
        "subtexto": (subtexto, None),
        "letra": (letra, 2),
        "contiene": (contiene, 2),
        "longitud": (longitud, 1),
        "empezar_con": (empezar_con, 2),
        "terminar_con": (terminar_con, 2),
        "buscar": (buscar, 2),
        "repetir": (repetir, 2),
        "invertir": (invertir, 1),
        "indice_de": (indice_de, 2),
    }
    _METODOS_VALOR[list] = {
        "agregar": (agregar, 2),
        "longitud": (longitud, 1),
        "contiene": (contiene, 2),
        "mapear": (mapear, 2),
        "filtrar": (filtrar, 2),
        "reducir": (reducir, None),
        "para_cada": (para_cada, 2),
        "ordenar": (ordenar, None),
        "invertir": (invertir, 1),
        "sumar": (sumar, 1),
        "indice_de": (indice_de, 2),
        "insertar": (insertar, 3),
        "quitar": (quitar, None),
        "eliminar": (eliminar, 2),
        "unir": (unir, None),
    }
    _METODOS_VALOR[dict] = {
        "claves": (claves_dic, 1),
        "tiene": (tiene_dic, 2),
        "valores": (valores, 1),
        "elementos": (elementos, 1),
    }

    nativas = {
        "muestra": FuncionNativa("muestra", muestra),
        "imprime": FuncionNativa("imprime", muestra),  # alias en español
        "longitud": FuncionNativa("longitud", longitud, aridad=1),
        "entero": FuncionNativa("entero", entero, aridad=1),
        "numero": FuncionNativa("numero", numero, aridad=1),
        "texto": FuncionNativa("texto", texto, aridad=1),
        "rango": FuncionNativa("rango", rango),
        "leer": FuncionNativa("leer", leer),
        "azar": FuncionNativa("azar", azar, aridad=1),
        # texto
        "mayusculas": FuncionNativa("mayusculas", mayusculas, aridad=1),
        "minusculas": FuncionNativa("minusculas", minusculas, aridad=1),
        "recortar": FuncionNativa("recortar", recortar, aridad=1),
        "separar": FuncionNativa("separar", separar),
        "unir": FuncionNativa("unir", unir),
        "contiene": FuncionNativa("contiene", contiene, aridad=2),
        "reemplazar": FuncionNativa("reemplazar", reemplazar, aridad=3),
        "subtexto": FuncionNativa("subtexto", subtexto),
        "letra": FuncionNativa("letra", letra, aridad=2),
        "agregar": FuncionNativa("agregar", agregar, aridad=2),
        "reloj": FuncionNativa("reloj", reloj, aridad=0),
        "exp": FuncionNativa("exp", exp, aridad=1),
        "sigmoide": FuncionNativa("sigmoide", sigmoide, aridad=1),
        "producto_punto": FuncionNativa("producto_punto", producto_punto, aridad=2),
        "seno": FuncionNativa("seno", seno, aridad=1),
        "coseno": FuncionNativa("coseno", coseno, aridad=1),
        # matemáticas
        "absoluto": FuncionNativa("absoluto", absoluto, aridad=1),
        "raiz": FuncionNativa("raiz", raiz, aridad=1),
        "potencia": FuncionNativa("potencia", potencia, aridad=2),
        "piso": FuncionNativa("piso", piso, aridad=1),
        "techo": FuncionNativa("techo", techo, aridad=1),
        "redondear": FuncionNativa("redondear", redondear),
        "log": FuncionNativa("log", log),
        "minimo": FuncionNativa("minimo", minimo),
        "maximo": FuncionNativa("maximo", maximo),
        "sumar": FuncionNativa("sumar", sumar, aridad=1),
        "pi": FuncionNativa("pi", pi, aridad=0),
        "aleatorio": FuncionNativa("aleatorio", aleatorio, aridad=0),
        # orden superior
        "mapear": FuncionNativa("mapear", mapear, aridad=2),
        "filtrar": FuncionNativa("filtrar", filtrar, aridad=2),
        "reducir": FuncionNativa("reducir", reducir),
        "para_cada": FuncionNativa("para_cada", para_cada, aridad=2),
        "ordenar": FuncionNativa("ordenar", ordenar),
        # texto y listas
        "empezar_con": FuncionNativa("empezar_con", empezar_con, aridad=2),
        "terminar_con": FuncionNativa("terminar_con", terminar_con, aridad=2),
        "buscar": FuncionNativa("buscar", buscar, aridad=2),
        "repetir": FuncionNativa("repetir", repetir, aridad=2),
        "invertir": FuncionNativa("invertir", invertir, aridad=1),
        "indice_de": FuncionNativa("indice_de", indice_de, aridad=2),
        "insertar": FuncionNativa("insertar", insertar, aridad=3),
        "quitar": FuncionNativa("quitar", quitar),
        "eliminar": FuncionNativa("eliminar", eliminar, aridad=2),
        "valores": FuncionNativa("valores", valores, aridad=1),
        "elementos": FuncionNativa("elementos", elementos, aridad=1),
        "tipo": FuncionNativa("tipo", tipo, aridad=1),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
