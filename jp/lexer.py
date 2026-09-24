"""Lexer de JP: convierte el código fuente (str) en una lista de tokens.

Ejemplo:
    "var x = 10"  ->  [VAR, IDENTIFICADOR(x), IGUAL, NUMERO(10), FIN]
"""

from __future__ import annotations

from .errores import ErrorLexico
from .tokens import PALABRAS_CLAVE, TToken, Token

# Signos de un solo carácter
_SIGNOS_SIMPLES: dict[str, TToken] = {
    "(": TToken.PAREN_IZQ,
    ")": TToken.PAREN_DER,
    "{": TToken.LLAVE_IZQ,
    "}": TToken.LLAVE_DER,
    "[": TToken.CORCHETE_IZQ,
    "]": TToken.CORCHETE_DER,
    ",": TToken.COMA,
    ";": TToken.PUNTO_Y_COMA,
    ":": TToken.DOSPUNTOS,
    "+": TToken.MAS,
    "-": TToken.MENOS,
    "*": TToken.POR,
    "/": TToken.ENTRE,
    "%": TToken.MODULO,
    "=": TToken.IGUAL,
    "<": TToken.MENOR,
    ">": TToken.MAYOR,
}

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


class Lexer:
    def __init__(self, fuente: str):
        self.fuente = fuente
        self.inicio = 0        # inicio del lexema actual
        self.actual = 0        # posición del carácter actual
        self.linea = 1
        self.columna = 1
        self.tokens: list[Token] = []

    # ---------- helpers de lectura ----------

    def _fin(self) -> bool:
        return self.actual >= len(self.fuente)

    def _avanzar(self) -> str:
        c = self.fuente[self.actual]
        self.actual += 1
        if c == "\n":
            self.linea += 1
            self.columna = 1
        else:
            self.columna += 1
        return c

    def _mirar(self, desplazamiento: int = 0) -> str:
        i = self.actual + desplazamiento
        if i >= len(self.fuente):
            return "\0"
        return self.fuente[i]

    def _coincide(self, esperado: str) -> bool:
        if self._fin() or self.fuente[self.actual] != esperado:
            return False
        self._avanzar()
        return True

    def _agregar(self, tipo: TToken, literal: object = None) -> None:
        lexema = self.fuente[self.inicio:self.actual]
        self.tokens.append(
            Token(tipo, lexema, literal, self.linea_inicial, self.columna_inicial)
        )

    # ---------- escaneo ----------

    def tokenizar(self) -> list[Token]:
        while not self._fin():
            self.linea_inicial = self.linea
            self.columna_inicial = self.columna
            self.inicio = self.actual
            self._escanear_token()
        self.linea_inicial = self.linea
        self.columna_inicial = self.columna
        self.tokens.append(
            Token(TToken.FIN_DE_ARCHIVO, "", None, self.linea, self.columna)
        )
        return self.tokens

    def _escanear_token(self) -> None:
        c = self._avanzar()

        # Comentarios: # hasta fin de línea
        if c == "#":
            while not self._fin() and self._mirar() != "\n":
                self._avanzar()
            return

        # Espacios en blanco
        if c in " \t\r\n":
            return

        # Signos
        if c in _SIGNOS_SIMPLES:
            tipo = _SIGNOS_SIMPLES[c]
            if c == "=" and self._coincide("="):
                self._agregar(TToken.IGUAL_IGUAL)
            elif c == "!" and self._coincide("="):
                self._agregar(TToken.DIFERENTE)
            elif c == "<" and self._coincide("="):
                self._agregar(TToken.MENOR_IGUAL)
            elif c == ">" and self._coincide("="):
                self._agregar(TToken.MAYOR_IGUAL)
            else:
                self._agregar(tipo)
            return

        if c == "!":
            if self._coincide("="):
                self._agregar(TToken.DIFERENTE)
            else:
                raise ErrorLexico("carácter inesperado '!'. ¿Quisiste decir '!=' ?", self.linea, self.columna - 1)
            return

        # Cadenas (comillas dobles o simples)
        if c in ('"', "'"):
            self._cadena(c)
            return

        # Puntos: rango '..' o acceso a claves 'd.clave'
        if c == ".":
            if self._mirar() == ".":
                self._avanzar()
                self._agregar(TToken.PUNTO_PUNTO)
                return
            if self._mirar().isalpha() or self._mirar() == "_":
                self._agregar(TToken.PUNTO)
                return
            raise ErrorLexico(
                "el '.' inesperado (los rangos van 1..10 y las claves van d.clave)",
                self.linea,
                self.columna - 1,
            )

        # Números
        if c.isdigit():
            self._numero()
            return

        # Identificadores y palabras clave
        if c.isalpha() or c == "_":
            self._identificador()
            return

        raise ErrorLexico(f"carácter no reconocido: {c!r}", self.linea, self.columna - 1)

    def _cadena(self, delim: str) -> None:
        valor = []
        while True:
            if self._fin():
                raise ErrorLexico(f"cadena sin cerrar (falta '{delim}')", self.linea_inicial, self.columna_inicial)
            c = self._avanzar()
            if c == delim:
                break
            if c == "\\":
                escape = self._avanzar()
                if escape not in _ESCAPES:
                    raise ErrorLexico(f"escape no válido: \\{escape}", self.linea, self.columna - 1)
                valor.append(_ESCAPES[escape])
            else:
                valor.append(c)
        self._agregar(TToken.CADENA, "".join(valor))

    def _numero(self) -> None:
        while self._mirar().isdigit():
            self._avanzar()
        # Parte decimal
        if self._mirar() == "." and self._mirar(1).isdigit():
            self._avanzar()  # consumir '.'
            while self._mirar().isdigit():
                self._avanzar()
            self._agregar(TToken.NUMERO, float(self.fuente[self.inicio:self.actual]))
        else:
            self._agregar(TToken.NUMERO, int(self.fuente[self.inicio:self.actual]))

    def _identificador(self) -> None:
        while self._mirar().isalnum() or self._mirar() == "_":
            self._avanzar()
        texto = self.fuente[self.inicio:self.actual]
        tipo = PALABRAS_CLAVE.get(texto, TToken.IDENTIFICADOR)
        literal = True if tipo == TToken.VERDADERO else (
            False if tipo == TToken.FALSO else (
                None if tipo == TToken.NULO else texto if tipo == TToken.IDENTIFICADOR else None
            )
        )
        self._agregar(tipo, literal)


def tokenizar(fuente: str) -> list[Token]:
    """Función de conveniencia: fuente -> lista de tokens."""
    return Lexer(fuente).tokenizar()
