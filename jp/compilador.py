"""Compilador de JP: convierte el AST en bytecode.

Recorre el árbol una única vez y emite instrucciones (jp.bytecode). Ideas
principales:

    - INVARIANTE "netas-0": cada sentencia deja la pila en el mismo nivel en
      que la encontró (el valor para el REPL lo guarda EXPR_SENT). Esto hace
      que romper/continuar solo tengan que cerrar ámbitos, no apilar POPs.
    - Ámbitos como dicts en una pila (misma semántica léxica que el árbol);
      la cadena "SENTINELA" marca hasta dónde puede saltar un romper/continuar
      (los cuerpos de si abren posibles ámbitos que el salto aún no cruza).
    - muestra()/imprime() con constantes se compilan a IMPRIMIR directo.
    - Las funciones aíslan la pila de bucles: un 'romper' jamás salta a un
      bucle del llamador (otro chunk).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .arbol import (
    Nodo,
    NodoAsignacion,
    NodoAsignarIndice,
    NodoBinario,
    NodoBloque,
    NodoBooleano,
    NodoCadena,
    NodoContinuar,
    NodoDeclaracionVar,
    NodoDiccionario,
    NodoExpresion,
    NodoFuncion,
    NodoIndice,
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
    NodoSi,
    NodoUnario,
    NodoVariable,
)
from .bytecode import Chunk, Codigo
from .errores import ErrorEjecucion

_SENTINELA = "SENTINELA"  # marca el límite de salto de romper/continuar


@dataclass
class FunCerrada:
    """Función ya compilada: bytecode listo para que la VM lo ejecute."""

    nombre: str
    chunk: Chunk
    aridad: int
    parametros: list[str] = field(default_factory=list)


class Compilador:
    def __init__(self) -> None:
        self.global_chunk = Chunk()
        # Pila de ámbitos de COMPILACIÓN (dicts) con "SENTINELA" como frontera
        # de romper/continuar. En tiempo de ejecución la VM mantiene su propia
        # cadena de Ambito con la misma forma.
        self.ambitos: list[dict[str, bool] | str] = []
        # Bucles activos: {"vuelta", "fin", "c_pops", "r_pops"}. Los POPs
        # son los extras que 'para' deja en la pila alrededor del cuerpo
        # ([iter, valor]): 'continuar' popea el valor (conserva el iterador)
        # y 'romper' popea ambos; en 'mientras' son 0.
        self.bucles: list[dict[str, int]] = []

    # ---------------- API ----------------

    def compilar(self, programa: NodoPrograma) -> Chunk:
        self.ambitos = []
        self.bucles = []
        self._cuerpo(programa.sentencias, self.global_chunk, es_fun=False)
        return self.global_chunk

    # ---------------- helpers ----------------

    @property
    def en_fun(self) -> bool:
        return bool(self.ambitos)

    def _emitir(self, chunk: Chunk, codigo: Codigo, operando: object = None, linea: int = 0) -> int:
        return chunk.emitir(codigo, operando, linea)

    def _es_local(self, nombre: str) -> bool:
        for ambito in reversed(self.ambitos):
            if ambito is _SENTINELA:
                break  # frontera: lo que sigue pertenece a otro camino de ejecución
            if isinstance(ambito, dict) and nombre in ambito:
                return True
        return False

    # ---------- centinela de romper/continuar ----------

    def _marcar(self) -> None:
        """Abre una frontera de salto (inicio de una rama de si, p. ej.)."""
        if self.bucles:
            self.ambitos.append(_SENTINELA)

    def _desmarcar(self) -> None:
        if self.ambitos and self.ambitos[-1] is _SENTINELA:
            self.ambitos.pop()

    # ---------------- cuerpos ----------------

    def _cuerpo(self, sentencias: list[Nodo], chunk: Chunk, es_fun: bool) -> None:
        """Compila un cuerpo. Las sentencias son netas-0; solo las funciones
        necesitan cierre: garantizar que acaban en RETORNAR."""
        for sentencia in sentencias:
            self._sentencia(sentencia, chunk)

        if es_fun:
            if not chunk.codigo or chunk.codigo[-1][0] is not Codigo.RETORNAR:
                self._emitir(chunk, Codigo.NULO, linea=0)
                self._emitir(chunk, Codigo.RETORNAR, linea=0)

    # ---------------- sentencias ----------------

    def _sentencia(self, nodo: Nodo, chunk: Chunk) -> None:
        tipo = type(nodo)

        if tipo is NodoDeclaracionVar:
            if nodo.inicializador is not None:
                self._expresion(nodo.inicializador, chunk)
            else:
                self._emitir(chunk, Codigo.NULO, linea=nodo.linea)
            if self.ambitos and self.ambitos[-1] is not _SENTINELA:
                self.ambitos[-1][nodo.nombre] = True
            self._emitir(chunk, Codigo.DECLARAR, nodo.nombre, nodo.linea)
            return

        if tipo is NodoExpresion:
            self._expresion(nodo.expresion, chunk)
            # Como el árbol: el valor se guarda en ultimo_valor y se descarta.
            self._emitir(chunk, Codigo.EXPR_SENT, linea=nodo.linea)
            return

        if tipo is NodoBloque:
            # Bloque { } suelto como sentencia: si declara variables, abre
            # ámbito propio (igual que el Entorno nuevo de _ej_bloque).
            con_ambito = nodo.declara
            if con_ambito:
                self._emitir(chunk, Codigo.AMBITO_PUSH, linea=getattr(nodo, "linea", 0))
                self.ambitos.append({})
            for sentencia in nodo.sentencias:
                self._sentencia(sentencia, chunk)
            if con_ambito:
                self.ambitos.pop()
                self._emitir(chunk, Codigo.AMBITO_POP, linea=getattr(nodo, "linea", 0))
            return

        if tipo is NodoSi:
            self._expresion(nodo.condicion, chunk)
            si_falso = self._emitir(chunk, Codigo.SALTAR_SI_FALSO, 0, nodo.linea)
            # La frontera evita que un romper dentro de la rama cierre ámbitos
            # de la OTRA rama (que no llegó a abrirse).
            self._marcar()
            self._sentencia(nodo.entonces, chunk)
            self._desmarcar()
            self._emitir(chunk, Codigo.NULO, linea=nodo.linea)   # valor del 'entonces'
            al_final = self._emitir(chunk, Codigo.SALTAR, 0, nodo.linea)
            # El falso salta AQUÍ: al inicio del 'sino' (o del NULO)
            chunk.codigo[si_falso] = (Codigo.SALTAR_SI_FALSO, len(chunk.codigo), nodo.linea)
            self._marcar()
            if nodo.sino is not None:
                self._sentencia(nodo.sino, chunk)
            self._desmarcar()
            self._emitir(chunk, Codigo.NULO, linea=nodo.linea)   # valor del 'sino' (AMBAS ramas empujan 1)
            fin = len(chunk.codigo)
            chunk.codigo[al_final] = (Codigo.SALTAR, fin, nodo.linea)  # salta AL FINAL
            self._emitir(chunk, Codigo.POP, linea=nodo.linea)    # deja exactamente 1 valor
            return

        if tipo is NodoMientras:
            self._bucle(nodo.condicion, nodo.cuerpo, chunk)
            return

        if tipo is NodoPara:
            self._para(nodo, chunk)
            return

        if tipo is NodoFuncion:
            fun_cerrada = self._compilar_funcion(nodo)
            indice = chunk.agregar_constante(fun_cerrada)
            self._emitir(chunk, Codigo.CONSTANTE, indice, nodo.linea)
            if self.ambitos and self.ambitos[-1] is not _SENTINELA:
                self.ambitos[-1][nodo.nombre] = True
            self._emitir(chunk, Codigo.DECLARAR, nodo.nombre, nodo.linea)
            return

        if tipo is NodoRetorna:
            if nodo.valor is not None:
                self._expresion(nodo.valor, chunk)
            else:
                self._emitir(chunk, Codigo.NULO, linea=nodo.linea)
            self._emitir(chunk, Codigo.RETORNAR, linea=nodo.linea)
            return

        if tipo is NodoRomper:
            self._saltar_bucle(chunk, nodo.linea, "fin", "romper")
            return

        if tipo is NodoContinuar:
            self._saltar_bucle(chunk, nodo.linea, "vuelta", "continuar")
            return

        raise ErrorEjecucion(f"sentencia desconocida para el compilador: {tipo.__name__}", getattr(nodo, "linea", 0))

    # ---------------- bucles ----------------

    def _bucle(self, condicion: Nodo, cuerpo: NodoBloque, chunk: Chunk) -> None:
        linea = getattr(condicion, "linea", 0)
        inicio = len(chunk.codigo)
        self._expresion(condicion, chunk)
        salir = self._emitir(chunk, Codigo.SALTAR_SI_FALSO, 0, linea)
        # Si el cuerpo declara variables, cada iteración recibe un ámbito
        # fresco (igual que el Entorno nuevo por vuelta del intérprete árbol).
        base = len(self.ambitos)  # los scopes previos NO se cierran con romper
        con_ambito = cuerpo.declara
        if con_ambito:
            self._emitir(chunk, Codigo.AMBITO_PUSH, linea=linea)
            self.ambitos.append({})
        marco = {"vuelta": inicio, "base": base, "c_pops": 0, "r_pops": 0, "pendientes": []}
        self.bucles.append(marco)
        self._sentencia(cuerpo, chunk)
        self.bucles.pop()
        if con_ambito:
            self.ambitos.pop()
            self._emitir(chunk, Codigo.AMBITO_POP, linea=linea)
        self._emitir(chunk, Codigo.SALTAR, inicio, linea)
        fin = len(chunk.codigo)  # salida del bucle: tras el SALTAR, NO el cuerpo
        chunk.codigo[salir] = (Codigo.SALTAR_SI_FALSO, fin, linea)
        self._parchar_pendientes(chunk, marco, fin, linea)
        self._emitir(chunk, Codigo.NULO, linea=linea)
        self._emitir(chunk, Codigo.POP, linea=linea)

    def _para(self, nodo: NodoPara, chunk: Chunk) -> None:
        """para x en it { cuerpo }  (el estado del bucle vive en la pila).

        pila: [iter] -> ITERAR_SIGUIENTE -> [iter, valor] -> cuerpo ->
        [iter, valor, cuerpo] -> POP POP -> [iter] -> repetir.
        Cada vuelta abre un ámbito fresco (AMBITO_PUSH) con la variable del
        bucle y las declaraciones del cuerpo: los closures capturan SU vuelta,
        igual que el Entorno nuevo del intérprete árbol, y 'para' anidados con
        el mismo nombre no se pisan. romper/continuar cierran ese ámbito antes
        de saltar (los salta _cerrar_hasta_sentinela).
        """
        linea = nodo.linea
        base = len(self.ambitos)
        self._expresion(nodo.iterable, chunk)   # se evalúa en el ámbito exterior
        self._emitir(chunk, Codigo.ITERAR, linea=linea)           # pila: iter
        self.ambitos.append({nodo.variable: True})  # el cuerpo ve la var como local
        vuelta = len(chunk.codigo)  # tras ITERAR se cae AQUÍ (sin salto de entrada)
        self._emitir(chunk, Codigo.AMBITO_PUSH, linea=linea)      # ámbito de la vuelta
        ix_iter = self._emitir(chunk, Codigo.ITERAR_SIGUIENTE, (nodo.variable, 0), linea)
        marco = {"vuelta": vuelta, "base": base, "c_pops": 1, "r_pops": 1, "pendientes": []}
        self.bucles.append(marco)
        self._sentencia(nodo.cuerpo, chunk)                       # el cuerpo deja 0 neto
        self.bucles.pop()
        self._emitir(chunk, Codigo.POP, linea=linea)              # descarta 'valor' -> pila: iter
        self._emitir(chunk, Codigo.AMBITO_POP, linea=linea)
        self._emitir(chunk, Codigo.SALTAR, vuelta, linea)
        fin = len(chunk.codigo)  # aquí se salta al agotarse el iterable
        chunk.codigo[ix_iter] = (Codigo.ITERAR_SIGUIENTE, (nodo.variable, fin), linea)
        self._parchar_pendientes(chunk, marco, fin, linea)
        self._emitir(chunk, Codigo.POP, linea=linea)              # quita el centinela
        self._emitir(chunk, Codigo.NULO, linea=linea)             # valor de la sentencia
        self._emitir(chunk, Codigo.POP, linea=linea)              # ... y lo descarta (netas 0)
        self.ambitos.pop()

    # ---------------- romper / continuar ----------------

    def _parchar_pendientes(self, chunk: Chunk, marco: dict, fin: int, linea: int) -> None:
        """Resuelve los saltos de romper/continuar ya que 'fin' es conocido."""
        for ix, destino in marco["pendientes"]:
            destino_idx = fin if destino == "fin" else marco["vuelta"]
            chunk.codigo[ix] = (Codigo.SALTAR, destino_idx, linea)

    def _saltar_bucle(self, chunk: Chunk, linea: int, destino: str, palabra: str) -> None:
        """Solo afecta al bucle MÁS INTERNO. Cierra los ámbitos abiertos hasta
        la frontera más cercana, popea los extras del 'para' y deja el salto
        PENDIENTE (el destino 'fin' se conoce al cerrar el bucle)."""
        if not self.bucles:
            raise ErrorEjecucion(f"'{palabra}' fuera de un bucle", linea)
        marco = self.bucles[-1]
        # Cerrar SOLO los ámbitos abiertos desde la base de este bucle (los suyos
        # y los de bloques/si anidados en el camino actual); los bucles externos
        # conservan los suyos porque siguen vivos.
        base = marco["base"]
        for _ in range(sum(1 for a in self.ambitos[base:] if isinstance(a, dict))):
            self._emitir(chunk, Codigo.AMBITO_POP, linea=linea)
        # Extras del 'para' en pila: continuar popea el valor (el iterador
        # queda para ITERAR_SIGUIENTE); romper popea solo el valor porque el
        # POP del destino 'fin' ya se lleva el iterador (centinela).
        for _ in range(marco["c_pops" if destino == "vuelta" else "r_pops"]):
            self._emitir(chunk, Codigo.POP, linea=linea)
        ix = self._emitir(chunk, Codigo.SALTAR, 0, linea)
        marco["pendientes"].append((ix, destino))

    # ---------------- expresiones ----------------

    def _expresion(self, nodo: Nodo, chunk: Chunk) -> None:
        tipo = type(nodo)

        if tipo is NodoNumero or tipo is NodoCadena:
            indice = chunk.agregar_constante(nodo.valor)
            self._emitir(chunk, Codigo.CONSTANTE, indice, nodo.linea)
            return
        if tipo is NodoBooleano:
            self._emitir(chunk, Codigo.VERDADERO if nodo.valor else Codigo.FALSO, linea=nodo.linea)
            return
        if tipo is NodoNulo:
            self._emitir(chunk, Codigo.NULO, linea=nodo.linea)
            return

        if tipo is NodoVariable:
            nombre = nodo.nombre
            if self._es_local(nombre):
                self._emitir(chunk, Codigo.LEER_LOCAL, nombre, nodo.linea)
            else:
                self._emitir(chunk, Codigo.LEER_GLOBAL, nombre, nodo.linea)
            return

        if tipo is NodoAsignacion:
            nombre = nodo.nombre
            self._expresion(nodo.valor, chunk)
            if self._es_local(nombre):
                self._emitir(chunk, Codigo.ASIGNAR_LOCAL, nombre, nodo.linea)
            else:
                self._emitir(chunk, Codigo.ASIGNAR_GLOBAL, nombre, nodo.linea)
            return

        if tipo is NodoAsignarIndice:
            self._expresion(nodo.objeto, chunk)
            self._expresion(nodo.indice, chunk)
            self._expresion(nodo.valor, chunk)
            self._emitir(chunk, Codigo.INDICE_ASIG, linea=nodo.linea)
            return

        if tipo is NodoBinario:
            self._binario(nodo, chunk)
            return

        if tipo is NodoUnario:
            self._expresion(nodo.operando, chunk)
            if nodo.operador == "-":
                self._emitir(chunk, Codigo.NEGAR, linea=nodo.linea)
            else:
                self._emitir(chunk, Codigo.NO, linea=nodo.linea)
            return

        if tipo is NodoLista:
            for elemento in nodo.elementos:
                self._expresion(elemento, chunk)
            self._emitir(chunk, Codigo.LISTA, len(nodo.elementos), nodo.linea)
            return

        if tipo is NodoDiccionario:
            for clave, valor in nodo.pares:
                self._expresion(clave, chunk)
                self._expresion(valor, chunk)
            self._emitir(chunk, Codigo.DICCIONARIO, len(nodo.pares), nodo.linea)
            return

        if tipo is NodoRango:
            self._expresion(nodo.izquierda, chunk)
            self._expresion(nodo.derecha, chunk)
            self._emitir(chunk, Codigo.RANGO, linea=nodo.linea)
            return

        if tipo is NodoIndice:
            self._expresion(nodo.objeto, chunk)
            self._expresion(nodo.indice, chunk)
            self._emitir(chunk, Codigo.INDICE, linea=nodo.linea)
            return

        if tipo is NodoLlamada:
            self._llamada(nodo, chunk)
            return

        raise ErrorEjecucion(f"expresión desconocida para el compilador: {tipo.__name__}", getattr(nodo, "linea", 0))

    def _binario(self, nodo: NodoBinario, chunk: Chunk) -> None:
        operador = nodo.operador

        # 'y' / 'o' con cortocircuito: devuelven el OPERANDO original
        # (nulo/falso devuelven tal cual, como el intérprete de árbol).
        # SALTAR_SI_VERDAD solo MIRA el tope (no popea), así la pila queda
        # sincronizada en ambos caminos.
        if operador == "y":
            self._expresion(nodo.izquierda, chunk)
            a_der = self._emitir(chunk, Codigo.SALTAR_SI_VERDAD, 0, nodo.linea)  # ¿izq verdad?
            al_fin = self._emitir(chunk, Codigo.SALTAR, 0, nodo.linea)           # no: conserva izq
            destino = len(chunk.codigo)
            self._emitir(chunk, Codigo.POP, linea=nodo.linea)                    # descarta izq
            self._expresion(nodo.derecha, chunk)
            fin = len(chunk.codigo)
            chunk.codigo[a_der] = (Codigo.SALTAR_SI_VERDAD, destino, nodo.linea)
            chunk.codigo[al_fin] = (Codigo.SALTAR, fin, nodo.linea)
            return
        if operador == "o":
            self._expresion(nodo.izquierda, chunk)
            al_fin = self._emitir(chunk, Codigo.SALTAR_SI_VERDAD, 0, nodo.linea)  # izq verdad: consérvalo
            a_der = self._emitir(chunk, Codigo.SALTAR, 0, nodo.linea)             # izq falso: evalúa der
            destino = len(chunk.codigo)
            self._emitir(chunk, Codigo.POP, linea=nodo.linea)                     # descarta izq falso
            self._expresion(nodo.derecha, chunk)
            fin = len(chunk.codigo)
            chunk.codigo[al_fin] = (Codigo.SALTAR_SI_VERDAD, fin, nodo.linea)
            chunk.codigo[a_der] = (Codigo.SALTAR, destino, nodo.linea)
            return

        opcode = _OP_BINARIOS.get(operador)
        if opcode is None:
            raise ErrorEjecucion(f"operador desconocido para el compilador: {operador}", nodo.linea)
        self._expresion(nodo.izquierda, chunk)
        self._expresion(nodo.derecha, chunk)
        self._emitir(chunk, opcode, linea=nodo.linea)

    def _llamada(self, nodo: NodoLlamada, chunk: Chunk) -> None:
        callee = nodo.callee
        argumentos = nodo.argumentos

        # muestra()/imprime() con solo constantes -> IMPRIMIR directo (sin llamadas)
        if (
            isinstance(callee, NodoVariable)
            and callee.nombre in ("muestra", "imprime")
            and all(isinstance(a, (NodoCadena, NodoNumero)) for a in argumentos)
        ):
            for a in argumentos:
                self._expresion(a, chunk)
            self._emitir(chunk, Codigo.IMPRIMIR, len(argumentos), nodo.linea)
            self._emitir(chunk, Codigo.NULO, linea=nodo.linea)
            return

        self._expresion(callee, chunk)
        for a in argumentos:
            self._expresion(a, chunk)
        self._emitir(chunk, Codigo.LLAMAR, len(argumentos), nodo.linea)

    # ---------------- funciones ----------------

    def _compilar_funcion(self, nodo: NodoFuncion) -> FunCerrada:
        chunk = Chunk()
        # Un nuevo ámbito por llamada: las funciones recursivas ven solo sus
        # parámetros y sus propias locales, nunca las de la llamada anterior.
        self.ambitos.append({parametro: True for parametro in nodo.parametros})
        # Aislamiento: dentro de la función no existen los bucles del llamador
        # (un 'romper' no puede saltar a otro chunk).
        bucles_externos = self.bucles
        self.bucles = []
        self._cuerpo(nodo.cuerpo.sentencias, chunk, es_fun=True)
        self.bucles = bucles_externos
        self.ambitos.pop()
        return FunCerrada(nodo.nombre, chunk, len(nodo.parametros), list(nodo.parametros))


_OP_BINARIOS: dict[str, Codigo] = {
    "+": Codigo.SUMAR,
    "-": Codigo.RESTAR,
    "*": Codigo.MULTIPLICAR,
    "/": Codigo.DIVIDIR,
    "%": Codigo.MODULO,
    "==": Codigo.IGUAL,
    "!=": Codigo.DIFERENTE,
    "<": Codigo.MENOR,
    ">": Codigo.MAYOR,
    "<=": Codigo.MENOR_IGUAL,
    ">=": Codigo.MAYOR_IGUAL,
}


def compilar(programa: NodoPrograma) -> Chunk:
    """Compila un programa completo y devuelve su chunk principal."""
    return Compilador().compilar(programa)
