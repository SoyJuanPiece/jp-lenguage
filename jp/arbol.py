"""Nodos del árbol de sintaxis (AST) de JP.

Cada nodo guarda la línea donde apareció para poder dar errores precisos.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class Nodo:
    linea: int = 0


# ----------------- Expresiones (producen un valor) -----------------

@dataclass
class NodoNumero(Nodo):
    valor: float | int
    linea: int = 0


@dataclass
class NodoCadena(Nodo):
    valor: str
    linea: int = 0


@dataclass
class NodoBooleano(Nodo):
    valor: bool
    linea: int = 0


@dataclass
class NodoNulo(Nodo):
    linea: int = 0


@dataclass
class NodoVariable(Nodo):
    nombre: str
    linea: int = 0


@dataclass
class NodoBinario(Nodo):
    operador: str
    izquierda: Nodo
    derecha: Nodo
    linea: int = 0


@dataclass
class NodoUnario(Nodo):
    operador: str
    operando: Nodo
    linea: int = 0


@dataclass
class NodoLlamada(Nodo):
    callee: Nodo
    argumentos: list[Nodo] = field(default_factory=list)
    linea: int = 0


@dataclass
class NodoIndice(Nodo):
    objeto: Nodo
    indice: Nodo
    linea: int = 0


@dataclass
class NodoLista(Nodo):
    elementos: list[Nodo] = field(default_factory=list)
    linea: int = 0


@dataclass
class NodoRango(Nodo):
    """Rango inclusivo: 1..10 -> del 1 al 10 (incluso al revés: 10..1).

    Con paso opcional: 1..10 paso 2 -> 1, 3, 5, 7, 9. El paso es una
    magnitud (mayor que 0); la dirección la deciden los extremos.
    """
    izquierda: Nodo
    derecha: Nodo
    paso: Nodo | None = None
    linea: int = 0


@dataclass
class NodoAsignacion(Nodo):
    """Asignación como expresión: también funciona dentro de condiciones."""
    nombre: str
    valor: Nodo
    linea: int = 0


@dataclass
class NodoAsignarIndice(Nodo):
    """lista[i] = valor  ·  diccionario["clave"] = valor"""
    objeto: Nodo
    indice: Nodo
    valor: Nodo
    linea: int = 0


@dataclass
class NodoDiccionario(Nodo):
    """Diccionario literal: {clave: valor, ...} (claves siempre texto)."""
    pares: list[tuple[Nodo, Nodo]] = field(default_factory=list)
    linea: int = 0


@dataclass
class NodoInterpolacion(Nodo):
    """"texto {expr} medio {expr} fin" -> partes alternadas texto/expr.

    Las partes de texto son NodoCadena; las expresiones cualquier Nodo.
    Se convierte en una suma que usa jp_a_texto para cada expr.
    """
    partes: list[Nodo] = field(default_factory=list)
    linea: int = 0


# ----------------- Sentencias (efectos) -----------------

@dataclass
class NodoPrograma(Nodo):
    sentencias: list[Nodo] = field(default_factory=list)


@dataclass
class NodoDeclaracionVar(Nodo):
    nombre: str
    inicializador: Nodo | None
    linea: int = 0


@dataclass
class NodoExpresion(Nodo):
    """Una sentencia que solo evalúa una expresión y descarta el valor."""
    expresion: Nodo
    linea: int = 0


@dataclass
class NodoBloque(Nodo):
    sentencias: list[Nodo] = field(default_factory=list)
    declara: bool = False  # ¿declara variables/fun? (permite optimizar el ámbito)


@dataclass
class NodoSi(Nodo):
    condicion: Nodo
    entonces: NodoBloque
    sino: NodoBloque | None = None
    linea: int = 0


@dataclass
class NodoMientras(Nodo):
    condicion: Nodo
    cuerpo: NodoBloque
    linea: int = 0


@dataclass
class NodoPara(Nodo):
    variable: str
    iterable: Nodo
    cuerpo: NodoBloque
    linea: int = 0


@dataclass
class NodoElegir(Nodo):
    """elegir expr { caso v1[, v2]: ... sino: ... } (sin caída entre casos)."""
    expresion: Nodo
    casos: list[tuple[list[Nodo], NodoBloque]] = field(default_factory=list)
    sino: NodoBloque | None = None
    linea: int = 0


@dataclass
class NodoIntentar(Nodo):
    """intenta { ... } atrapa error { ... }

    `nombre_error` es el nombre con el que el bloque `atrapa` ve el mensaje
    del error (None si se escribió un `atrapa` anónimo).
    """
    cuerpo: NodoBloque
    nombre_error: str | None
    captura: NodoBloque
    linea: int = 0


@dataclass
class NodoFuncion(Nodo):
    nombre: str  # "" si es una función anónima usada como valor
    parametros: list[str]
    cuerpo: NodoBloque
    linea: int = 0


@dataclass
class NodoRetorna(Nodo):
    valor: Nodo | None
    linea: int = 0


@dataclass
class NodoRomper(Nodo):
    linea: int = 0


@dataclass
class NodoContinuar(Nodo):
    linea: int = 0
