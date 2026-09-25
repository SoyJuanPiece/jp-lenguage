"""Parser de JP: convierte la lista de tokens en un AST.

Descenso recursivo con niveles de precedencia:
    asignacion < o < y < igualdad < comparacion < termino < factor < unario < llamada < primario
"""

from __future__ import annotations

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
    NodoInterpolacion,
    NodoRomper,
    NodoContinuar,
    NodoRetorna,
    NodoSi,
    NodoUnario,
    NodoVariable,
)
from .errores import ErrorSintaxis
from .tokens import TToken, Token


# Palabras clave que también sirven como claves de diccionario (ej: {y: 1})
# o después de un punto (ej: d.no), igual que en Python o JavaScript.
_CLAVES_VALIDAS = {
    TToken.IDENTIFICADOR,
    TToken.SI,
    TToken.EN,
    TToken.Y,
    TToken.O,
    TToken.NO,
}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ---------- helpers ----------

    def _actual(self) -> Token:
        return self.tokens[self.pos]

    def _avanzar(self) -> Token:
        token = self.tokens[self.pos]
        if token.tipo != TToken.FIN_DE_ARCHIVO:
            self.pos += 1
        return token

    def _coincide(self, *tipos: TToken) -> Token | None:
        if self._actual().tipo in tipos:
            return self._avanzar()
        return None

    def _esperar(self, tipo: TToken, mensaje: str) -> Token:
        if self._actual().tipo == tipo:
            return self._avanzar()
        actual = self._actual()
        raise ErrorSintaxis(f"{mensaje}, pero se encontró {actual.lexema!r}", actual.linea, actual.columna)

    def _error(self, mensaje: str) -> "ErrorSintaxis":
        actual = self._actual()
        return ErrorSintaxis(f"{mensaje}, pero se encontró {actual.lexema!r}", actual.linea, actual.columna)

    # ---------- punto de entrada ----------

    def parsear(self) -> NodoPrograma:
        sentencias: list[Nodo] = []
        while self._actual().tipo != TToken.FIN_DE_ARCHIVO:
            sentencias.append(self._sentencia())
        return NodoPrograma(sentencias=sentencias)


    # ---------- sentencias ----------

    def _sentencia(self) -> Nodo:
        try:
            if self._coincide(TToken.VAR):
                return self._sentencia_var()
            if self._coincide(TToken.FUN):
                return self._sentencia_fun()
            if self._coincide(TToken.RETORNA):
                return self._sentencia_retorna()
            if (token := self._coincide(TToken.ROMPER)):
                return NodoRomper(linea=token.linea)
            if (token := self._coincide(TToken.CONTINUAR)):
                return NodoContinuar(linea=token.linea)
            if self._coincide(TToken.SI):
                return self._sentencia_si()
            if self._coincide(TToken.MIENTRAS):
                return self._sentencia_mientras()
            if self._coincide(TToken.PARA):
                return self._sentencia_para()
            if self._coincide(TToken.LLAVE_IZQ):
                return self._bloque()
            return self._sentencia_expresion()
        finally:
            # punto y coma opcional al final de cada sentencia
            while self._coincide(TToken.PUNTO_Y_COMA):
                pass

    def _sentencia_var(self) -> Nodo:
        token = self._esperar(TToken.IDENTIFICADOR, "se esperaba un nombre de variable")
        inicializador = self._expresion() if self._coincide(TToken.IGUAL) else None
        return NodoDeclaracionVar(nombre=token.lexema, inicializador=inicializador, linea=token.linea)

    def _sentencia_fun(self) -> Nodo:
        token = self._esperar(TToken.IDENTIFICADOR, "se esperaba el nombre de la función")
        self._esperar(TToken.PAREN_IZQ, "se esperaba '(' tras el nombre de la función")
        parametros: list[str] = []
        if self._actual().tipo != TToken.PAREN_DER:
            while True:
                parametro = self._esperar(TToken.IDENTIFICADOR, "se esperaba un nombre de parámetro")
                parametros.append(parametro.lexema)
                if not self._coincide(TToken.COMA):
                    break
        self._esperar(TToken.PAREN_DER, "se esperaba ')' tras los parámetros")
        self._esperar(TToken.LLAVE_IZQ, "se esperaba '{' antes del cuerpo de la función")
        cuerpo = self._bloque()
        return NodoFuncion(nombre=token.lexema, parametros=parametros, cuerpo=cuerpo, linea=token.linea)

    def _sentencia_retorna(self) -> Nodo:
        token = self._actual()
        valor = None
        # Si la línea cambió o viene un cierre, no hay valor de retorno
        if token.tipo not in (TToken.PUNTO_Y_COMA, TToken.LLAVE_DER, TToken.FIN_DE_ARCHIVO):
            valor = self._expresion()
        return NodoRetorna(valor=valor, linea=token.linea)

    def _sentencia_si(self) -> Nodo:
        token = self._actual()
        condicion = self._condicion("si")
        entonces = self._cuerpo_sentencia()
        sino = None
        if self._coincide(TToken.SINO):
            if self._coincide(TToken.SI):
                # 'sino si' → bloque con un solo 'si' anidado
                sino = NodoBloque(sentencias=[self._sentencia_si()])
            else:
                sino = self._cuerpo_sentencia()
        return NodoSi(condicion=condicion, entonces=entonces, sino=sino, linea=token.linea)

    def _condicion(self, palabra: str) -> Nodo:
        """Condición de si/mientras: paréntesis opcionales.

        'si (a > b) {'  y  'si a > b {'  son equivalentes.
        """
        en_parentesis = self._coincide(TToken.PAREN_IZQ)
        condicion = self._expresion()
        if en_parentesis:
            self._esperar(TToken.PAREN_DER, f"se esperaba ')' tras la condición de '{palabra}'")
        return condicion

    def _cuerpo_sentencia(self) -> NodoBloque:
        """Cuerpo de si/mientras/para: '{ varias }' o ': una sola'."""
        if self._coincide(TToken.LLAVE_IZQ):
            return self._bloque()
        if self._coincide(TToken.DOSPUNTOS):
            sentencia = self._sentencia()
            declara = isinstance(sentencia, (NodoDeclaracionVar, NodoFuncion))
            return NodoBloque(sentencias=[sentencia], declara=declara)
        raise self._error("se esperaba '{' (varias sentencias) o ':' (una sola) tras la condición")

    def _sentencia_mientras(self) -> Nodo:
        token = self._actual()
        condicion = self._condicion("mientras")
        cuerpo = self._cuerpo_sentencia()
        return NodoMientras(condicion=condicion, cuerpo=cuerpo, linea=token.linea)

    def _sentencia_para(self) -> Nodo:
        token = self._actual()
        en_parentesis = self._coincide(TToken.PAREN_IZQ)
        variable = self._esperar(TToken.IDENTIFICADOR, "se esperaba la variable: 'para i en ...'")
        self._esperar(TToken.EN, "se esperaba 'en' (ej: 'para i en 1..10')")
        iterable = self._expresion()
        if en_parentesis:
            self._esperar(TToken.PAREN_DER, "se esperaba ')' tras el 'para'")
        cuerpo = self._cuerpo_sentencia()
        return NodoPara(variable=variable.lexema, iterable=iterable, cuerpo=cuerpo, linea=token.linea)

    def _bloque(self) -> NodoBloque:
        sentencias: list[Nodo] = []
        while self._actual().tipo not in (TToken.LLAVE_DER, TToken.FIN_DE_ARCHIVO):
            sentencias.append(self._sentencia())
        self._esperar(TToken.LLAVE_DER, "se esperaba '}' para cerrar el bloque")
        declara = any(isinstance(s, (NodoDeclaracionVar, NodoFuncion)) for s in sentencias)
        return NodoBloque(sentencias=sentencias, declara=declara)

    def _sentencia_expresion(self) -> Nodo:
        token = self._actual()
        expresion = self._expresion()
        return NodoExpresion(expresion=expresion, linea=token.linea)

    # ---------- expresiones ----------

    def _expresion(self) -> Nodo:
        return self._asignacion()

    def _asignacion(self) -> Nodo:
        expr = self._rango()
        if self._coincide(TToken.IGUAL):
            igual = self._actual()
            valor = self._asignacion()
            if isinstance(expr, NodoVariable):
                return NodoAsignacion(nombre=expr.nombre, valor=valor, linea=expr.linea)
            if isinstance(expr, NodoIndice):
                return NodoAsignarIndice(objeto=expr.objeto, indice=expr.indice, valor=valor, linea=expr.linea)
            raise ErrorSintaxis(
                "el objetivo de '=' debe ser una variable, lista[i] o d.clave", igual.linea, igual.columna
            )
        return expr

    def _rango(self) -> Nodo:
        """Rango inclusivo '..': 1..10 = del 1 al 10 (5..1 también funciona)."""
        expr = self._o()
        if (token := self._coincide(TToken.PUNTO_PUNTO)):
            derecha = self._o()
            return NodoRango(izquierda=expr, derecha=derecha, linea=token.linea)
        return expr

    def _o(self) -> Nodo:
        expr = self._y()
        while (token := self._coincide(TToken.O)):
            derecha = self._y()
            expr = NodoBinario(operador="o", izquierda=expr, derecha=derecha, linea=token.linea)
        return expr

    def _y(self) -> Nodo:
        expr = self._igualdad()
        while (token := self._coincide(TToken.Y)):
            derecha = self._igualdad()
            expr = NodoBinario(operador="y", izquierda=expr, derecha=derecha, linea=token.linea)
        return expr

    def _igualdad(self) -> Nodo:
        expr = self._comparacion()
        while (token := self._coincide(TToken.IGUAL_IGUAL, TToken.DIFERENTE)):
            derecha = self._comparacion()
            expr = NodoBinario(operador=token.lexema, izquierda=expr, derecha=derecha, linea=token.linea)
        return expr

    def _comparacion(self) -> Nodo:
        expr = self._termino()
        while (token := self._coincide(TToken.MENOR, TToken.MAYOR, TToken.MENOR_IGUAL, TToken.MAYOR_IGUAL)):
            derecha = self._termino()
            expr = NodoBinario(operador=token.lexema, izquierda=expr, derecha=derecha, linea=token.linea)
        return expr

    def _termino(self) -> Nodo:
        expr = self._factor()
        while (token := self._coincide(TToken.MAS, TToken.MENOS)):
            derecha = self._factor()
            expr = _plegar(token.lexema, expr, derecha, token.linea)
        return expr

    def _factor(self) -> Nodo:
        expr = self._unario()
        while (token := self._coincide(TToken.POR, TToken.ENTRE, TToken.MODULO)):
            derecha = self._unario()
            expr = _plegar(token.lexema, expr, derecha, token.linea)
        return expr

    def _unario(self) -> Nodo:
        if (token := self._coincide(TToken.NO, TToken.MENOS)):
            operando = self._unario()
            if token.tipo == TToken.MENOS and isinstance(operando, NodoNumero):
                return NodoNumero(valor=-operando.valor, linea=token.linea)
            return NodoUnario(operador=token.lexema, operando=operando, linea=token.linea)
        return self._llamada()

    def _llamada(self) -> Nodo:
        expr = self._primario()
        while True:
            if self._coincide(TToken.PAREN_IZQ):
                argumentos: list[Nodo] = []
                if self._actual().tipo != TToken.PAREN_DER:
                    while True:
                        argumentos.append(self._expresion())
                        if not self._coincide(TToken.COMA):
                            break
                parentesis = self._esperar(TToken.PAREN_DER, "se esperaba ')' tras los argumentos")
                expr = NodoLlamada(callee=expr, argumentos=argumentos, linea=parentesis.linea)
            elif self._coincide(TToken.CORCHETE_IZQ):
                indice = self._expresion()
                cierre = self._esperar(TToken.CORCHETE_DER, "se esperaba ']' tras el índice")
                expr = NodoIndice(objeto=expr, indice=indice, linea=cierre.linea)
            elif self._coincide(TToken.PUNTO):
                clave = self._avanzar()
                if clave.tipo not in _CLAVES_VALIDAS:
                    raise ErrorSintaxis(
                        "después de '.' va el nombre de la clave",
                        clave.linea,
                        clave.columna,
                    )
                expr = NodoIndice(
                    objeto=expr,
                    indice=NodoCadena(valor=clave.lexema, linea=clave.linea),
                    linea=clave.linea,
                )
            else:
                break
        return expr

    def _primario(self) -> Nodo:
        token = self._avanzar()
        if token.tipo == TToken.CADENA_INI:
            return self._interpolacion(token)
        if token.tipo == TToken.NUMERO:
            return NodoNumero(valor=token.literal, linea=token.linea)
        if token.tipo == TToken.CADENA:
            return NodoCadena(valor=token.literal, linea=token.linea)
        if token.tipo == TToken.VERDADERO:
            return NodoBooleano(valor=True, linea=token.linea)
        if token.tipo == TToken.FALSO:
            return NodoBooleano(valor=False, linea=token.linea)
        if token.tipo == TToken.NULO:
            return NodoNulo(linea=token.linea)
        if token.tipo == TToken.IDENTIFICADOR:
            return NodoVariable(nombre=token.lexema, linea=token.linea)
        if token.tipo == TToken.CORCHETE_IZQ:
            elementos: list[Nodo] = []
            if self._actual().tipo != TToken.CORCHETE_DER:
                while True:
                    elementos.append(self._expresion())
                    if not self._coincide(TToken.COMA):
                        break
            self._esperar(TToken.CORCHETE_DER, "se esperaba ']' tras la lista")
            return NodoLista(elementos=elementos, linea=token.linea)
        if token.tipo == TToken.LLAVE_IZQ:
            pares: list[tuple[Nodo, Nodo]] = []
            if self._actual().tipo != TToken.LLAVE_DER:
                while True:
                    clave_token = self._actual()
                    if clave_token.tipo in _CLAVES_VALIDAS:
                        self._avanzar()
                        clave = NodoCadena(valor=clave_token.lexema, linea=clave_token.linea)
                    elif clave_token.tipo == TToken.CADENA:
                        self._avanzar()
                        clave = NodoCadena(valor=clave_token.literal, linea=clave_token.linea)
                    else:
                        raise ErrorSintaxis(
                            "las claves de un diccionario son nombres o cadenas, ej: {nombre: \"Ana\"}",
                            clave_token.linea,
                            clave_token.columna,
                        )
                    self._esperar(TToken.DOSPUNTOS, "se esperaba ':' entre la clave y el valor")
                    valor = self._expresion()
                    pares.append((clave, valor))
                    if not self._coincide(TToken.COMA):
                        break
            self._esperar(TToken.LLAVE_DER, "se esperaba '}' para cerrar el diccionario")
            return NodoDiccionario(pares=pares, linea=token.linea)
        if token.tipo == TToken.PAREN_IZQ:
            expr = self._expresion()
            self._esperar(TToken.PAREN_DER, "se esperaba ')' tras la expresión")
            return expr
        encontrado = "fin del archivo" if token.tipo == TToken.FIN_DE_ARCHIVO else repr(token.lexema)
        raise ErrorSintaxis(f"se esperaba una expresión, pero se encontró {encontrado}", token.linea, token.columna)

    def _interpolacion(self, token: Token) -> Nodo:
        """Convierte CADENA_INI [expr] (CADENA_MEDIO [expr])* CADENA_FIN en
        NodoInterpolacion (partes de texto + expresiones alternadas)."""
        partes: list[Nodo] = [NodoCadena(valor=token.literal, linea=token.linea)]
        while True:
            partes.append(self._expresion())
            token_medio = self._avanzar()
            if token_medio.tipo == TToken.CADENA_FIN:
                partes.append(NodoCadena(valor=token_medio.literal, linea=token_medio.linea))
                break
            if token_medio.tipo != TToken.CADENA_MEDIO:
                raise ErrorSintaxis(
                    "interpolación mal formada: falta el '}'",
                    token_medio.linea,
                    token_medio.columna,
                )
            partes.append(NodoCadena(valor=token_medio.literal, linea=token_medio.linea))
        return NodoInterpolacion(partes=partes, linea=token.linea)


def parsear(tokens: list[Token]) -> NodoPrograma:
    """Función de conveniencia: tokens -> AST."""
    return Parser(tokens).parsear()


def _plegar(operador: str, izq: Nodo, der: Nodo, linea: int) -> Nodo:
    """Plegado de constantes (optimización): 2 + 3 se calcula ya en el parseo."""
    if isinstance(izq, NodoNumero) and isinstance(der, NodoNumero):
        a, b = izq.valor, der.valor
        if operador == "+":
            return NodoNumero(valor=a + b, linea=linea)
        if operador == "-":
            return NodoNumero(valor=a - b, linea=linea)
        if operador == "*":
            return NodoNumero(valor=a * b, linea=linea)
        if operador == "/" and b != 0:
            if isinstance(a, int) and isinstance(b, int) and a % b == 0:
                return NodoNumero(valor=a // b, linea=linea)
            return NodoNumero(valor=a / b, linea=linea)
        if operador == "%" and b != 0:
            return NodoNumero(valor=a % b, linea=linea)
    if operador == "+" and isinstance(izq, NodoCadena) and isinstance(der, NodoCadena):
        return NodoCadena(valor=izq.valor + der.valor, linea=linea)
    return NodoBinario(operador=operador, izquierda=izq, derecha=der, linea=linea)
