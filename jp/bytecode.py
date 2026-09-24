"""Bytecode de JP: opcodes, chunk y desensamblador.

La VM (jp.vm) ejecuta listas de instrucciones. Cada instrucción es una tupla
(codigo, operando, linea). Compilar el AST una vez y ejecutar el bytecode en
un bucle compacto es el salto de rendimiento real frente a recorrer el árbol.

Diseño de pila:
    - Todas las expresiones dejan su resultado en la pila.
    - Las sentencias POPean lo que no necesitan.
    - Los locales de una función viven en una lista plana (velocidad).
"""

from __future__ import annotations

from enum import Enum, auto


class Codigo(Enum):
    # Literales y constantes
    CONSTANTE = auto()      # operando=índice de constante -> empuja el valor
    NULO = auto()           # empuja None
    VERDADERO = auto()      # empuja True
    FALSO = auto()          # empuja False

    # Variables
    LEER_GLOBAL = auto()    # operando=nombre -> empuja el valor global
    LEER_LOCAL = auto()     # operando=slot -> empuja el valor local
    ASIGNAR_GLOBAL = auto() # operando=nombre, deja el valor en la pila
    ASIGNAR_LOCAL = auto()  # operando=slot, deja el valor en la pila
    DECLARAR = auto()       # operando=nombre; define en el ámbito actual (envuelve FunCerrada)

    # Estructuras
    LISTA = auto()          # operando=n -> construye lista con n elementos
    DICCIONARIO = auto()    # operando=n -> construye dict con n pares (k,v en pila)
    RANGO = auto()          # inicio y fin en pila -> lista inclusiva (al revés también)
    INDICE = auto()         # objeto[indice] (ambos en pila)
    INDICE_ASIG = auto()    # objeto, indice, valor en pila; deja el valor

    # Operadores
    SUMAR = auto()          # +  (números, cadenas o listas)
    RESTAR = auto()         # -
    MULTIPLICAR = auto()    # *  (incluye cadena * número)
    DIVIDIR = auto()        # /  (entera si es exacta)
    MODULO = auto()         # %
    NEGAR = auto()          # -x
    NO = auto()             # no x
    IGUAL = auto()          # ==
    DIFERENTE = auto()      # !=
    MENOR = auto()          # <
    MAYOR = auto()          # >
    MENOR_IGUAL = auto()    # <=
    MAYOR_IGUAL = auto()    # >=

    # Control de flujo
    SALTAR = auto()         # operando=destino absoluto
    SALTAR_SI_FALSO = auto()  # Popea la condición; salta si no es verdad
    SALTAR_SI_VERDAD = auto() # NO popea; salta si es verdad (para 'o')
    LLAMAR = auto()         # operando=nargs; callee y args en pila
    RETORNAR = auto()       # Popea el valor y sale de la función

    # Iteración (para x en ...) — estado en la pila, seguro en recursión
    ITERAR = auto()           # pop iterable -> empuja un IteradorJP
    ITERAR_SIGUIENTE = auto() # operando=[nombre, fin]; define la var o salta a fin si terminó

    # Ámbitos de bloque (para que 'var' dentro de { } no se escape del bloque)
    AMBITO_PUSH = auto()      # ambito = Ambito(padre=ambito)
    AMBITO_POP = auto()       # ambito = ambito.padre

    # Sentencias
    POP = auto()            # descarta el tope de la pila
    EXPR_SENT = auto()      # popea y guarda el valor como último (REPL, como el árbol)
    IMPRIMIR = auto()       # operando=nargs; imprime con muestra()/imprime()
    ULTIMO_VALOR = auto()   # copia el tope al slot del REPL (sin popear)


_NOMBRES: dict[Codigo, str] = {
    Codigo.CONSTANTE: "CONSTANTE",
    Codigo.NULO: "NULO",
    Codigo.VERDADERO: "VERDADERO",
    Codigo.FALSO: "FALSO",
    Codigo.LEER_GLOBAL: "LEER_GLOBAL",
    Codigo.LEER_LOCAL: "LEER_LOCAL",
    Codigo.ASIGNAR_GLOBAL: "ASIGNAR_GLOBAL",
    Codigo.ASIGNAR_LOCAL: "ASIGNAR_LOCAL",
    Codigo.DECLARAR: "DECLARAR",
    Codigo.ITERAR: "ITERAR",
    Codigo.ITERAR_SIGUIENTE: "ITERAR_SIGUIENTE",
    Codigo.AMBITO_PUSH: "AMBITO_PUSH",
    Codigo.AMBITO_POP: "AMBITO_POP",
    Codigo.LISTA: "LISTA",
    Codigo.DICCIONARIO: "DICCIONARIO",
    Codigo.RANGO: "RANGO",
    Codigo.INDICE: "INDICE",
    Codigo.INDICE_ASIG: "INDICE_ASIG",
    Codigo.SUMAR: "SUMAR",
    Codigo.RESTAR: "RESTAR",
    Codigo.MULTIPLICAR: "MULTIPLICAR",
    Codigo.DIVIDIR: "DIVIDIR",
    Codigo.MODULO: "MODULO",
    Codigo.NEGAR: "NEGAR",
    Codigo.NO: "NO",
    Codigo.IGUAL: "IGUAL",
    Codigo.DIFERENTE: "DIFERENTE",
    Codigo.MENOR: "MENOR",
    Codigo.MAYOR: "MAYOR",
    Codigo.MENOR_IGUAL: "MENOR_IGUAL",
    Codigo.MAYOR_IGUAL: "MAYOR_IGUAL",
    Codigo.SALTAR: "SALTAR",
    Codigo.SALTAR_SI_FALSO: "SALTAR_SI_FALSO",
    Codigo.SALTAR_SI_VERDAD: "SALTAR_SI_VERDAD",
    Codigo.LLAMAR: "LLAMAR",
    Codigo.RETORNAR: "RETORNAR",
    Codigo.POP: "POP",
    Codigo.EXPR_SENT: "EXPR_SENT",
    Codigo.IMPRIMIR: "IMPRIMIR",
    Codigo.ULTIMO_VALOR: "ULTIMO_VALOR",
}


class Chunk:
    """Bytecode + constantes de una unidad de código (programa o función).

    Para el compilador, `codigo` es una lista de tuplas (codigo, operando, linea).
    Cuando la VM ejecuta el chunk por primera vez, aplana las columnas en tres
    listas paralelas (_c, _o, _l) para que el bucle caliente no haga indexing
    de tuplas ni busque atributos por instrucción.
    """

    __slots__ = ("codigo", "constantes", "_c", "_o", "_l", "ops")

    def __init__(self) -> None:
        self.codigo: list[tuple[Codigo, object, int]] = []
        self.constantes: list[object] = []
        self._c: list[Codigo] | None = None
        self._o: list[object] | None = None
        self._l: list[int] | None = None
        self.ops: list | None = None  # closures compiladas (las construye la VM)

    def preparar(self) -> None:
        """Aplana las columnas del bytecode (solo se llama antes de ejecutar)."""
        self._c = [instruccion[0] for instruccion in self.codigo]
        self._o = [instruccion[1] for instruccion in self.codigo]
        self._l = [instruccion[2] for instruccion in self.codigo]

    def emitir(self, codigo: Codigo, operando: object = None, linea: int = 0) -> int:
        self.codigo.append((codigo, operando, linea))
        return len(self.codigo) - 1

    def agregar_constante(self, valor: object) -> int:
        # Reutilizar constantes iguales (números pequeños, nombres repetidos)
        try:
            indice = self.constantes.index(valor)
        except ValueError:
            indice = len(self.constantes)
            self.constantes.append(valor)
        return indice

    def parchar(self, direccion: int) -> None:
        """Escribe el destino de un salto dejado pendiente (por índice de instrucción)."""
        codigo, _, linea = self.codigo[direccion]
        self.codigo[direccion] = (codigo, direccion + 1, linea)


def desensamblar(chunk: Chunk, titulo: str = "chunk") -> str:
    """Devuelve el bytecode en texto (útil para depurar y para los tests)."""
    lineas = [f"== {titulo} =="]
    for i, (codigo, operando, linea) in enumerate(chunk.codigo):
        nombre = _NOMBRES[codigo]
        if codigo is Codigo.CONSTANTE:
            valor = chunk.constantes[operando]
            lineas.append(f"{i:4}  {nombre:<18} {operando:<4} ({valor!r})")
        elif operando is not None:
            lineas.append(f"{i:4}  {nombre:<18} {operando}")
        else:
            lineas.append(f"{i:4}  {nombre}")
        if linea:
            lineas[-1] += f"    ; línea {linea}"
    return "\n".join(lineas)
