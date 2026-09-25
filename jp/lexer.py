"""Lexer de JP: convierte el código fuente (str) en una lista de tokens.

Ejemplo:
    "var x = 10"  ->  [VAR, IDENTIFICADOR(x), IGUAL, NUMERO(10), FIN]

Interpolación: las cadenas con COMILLAS DOBLES pueden incrustar expresiones
entre llaves:  "hola {nombre}, tienes {edad * 2} vidas".  El lexer trocea la
cadena en CADENA_INI / (tokens de la expresión empalmados) / CADENA_MEDIO /
... / CADENA_FIN, y el parser los convierte en NodoInterpolacion. Las
comillas SIMPLES son literales puros (nunca interpolan).
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
    "{": "{",   # escapa una interpolación: "a\{b"
    "}": "}",
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

    # ---------- cadenas e interpolación ----------

    def _cadena(self, delim: str) -> None:
        """Escanea una cadena.

        - COMILLAS SIMPLES: literal puro con los escapes de siempre
          (\\n, \\t, \\\", \\\\). Nunca interpola.
        - COMILLAS DOBLES: un '{' inicia una interpolación
              "hola {nombre}, tienes {edad * 2} vidas"
          Se emite: CADENA_INI(texto) [tokens de la expresión]
                    (CADENA_MEDIO(texto) [tokens])* CADENA_FIN(texto).
          '\\{' y '\\}' insertan llaves literales.
        """
        if delim == "'":
            valor = []
            while True:
                if self._fin():
                    raise ErrorLexico(
                        "cadena sin cerrar (falta ')", self.linea_inicial, self.columna_inicial
                    )
                c = self._avanzar()
                if c == "'":
                    break
                if c == "\\":
                    escape = self._avanzar()
                    if escape not in _ESCAPES:
                        raise ErrorLexico(
                            f"escape no válido: \\{escape}", self.linea, self.columna - 1
                        )
                    valor.append(_ESCAPES[escape])
                else:
                    valor.append(c)
            self._agregar(TToken.CADENA, "".join(valor))
            return

        # --- comillas dobles, con interpolación ---
        trozos: list[str] = []       # textos; trozos[i+1] sigue a la interpolación i
        expresiones: list[str] = []
        actual: list[str] = []
        while True:
            if self._fin():
                raise ErrorLexico(
                    'cadena sin cerrar (falta ")', self.linea_inicial, self.columna_inicial
                )
            c = self._avanzar()
            if c == '"':
                break
            if c == "\\":
                escape = self._avanzar()
                if escape not in _ESCAPES:
                    raise ErrorLexico(
                        f"escape no válido: \\{escape}", self.linea, self.columna - 1
                    )
                actual.append(_ESCAPES[escape])
                continue
            if c == "{":
                trozos.append("".join(actual))
                actual = []
                expresiones.append(self._leer_hasta_llave())
                continue
            actual.append(c)
        trozos.append("".join(actual))

        if not expresiones:
            self._agregar(TToken.CADENA, trozos[0])
            return

        self._agregar(TToken.CADENA_INI, trozos[0])
        for indice, expr in enumerate(expresiones):
            self._empalmar_expresion(expr)
            texto = trozos[indice + 1]
            if indice == len(expresiones) - 1:
                self._agregar(TToken.CADENA_FIN, texto)
            else:
                self._agregar(TToken.CADENA_MEDIO, texto)

    def _leer_hasta_llave(self) -> str:
        """Dentro de una interpolación (el '{' ya fue consumido): consume
        caracteres hasta el '}' que la cierra, contando anidación y respetando
        cadenas anidadas. Devuelve el texto de la expresión."""
        linea_inicial = self.linea
        columna_inicial = self.columna - 1
        trozo: list[str] = []
        llaves = 1
        parentesis = 0
        corchetes = 0
        while True:
            if self._fin():
                raise ErrorLexico(
                    "interpolación sin cerrar (falta '}')", linea_inicial, columna_inicial
                )
            c = self._avanzar()
            if c == '"' or c == "'":
                trozo.append(c)
                if not self._saltar_cadena_simple(c, trozo):
                    raise ErrorLexico(
                        "cadena sin cerrar dentro de una interpolación",
                        self.linea,
                        self.columna,
                    )
                continue
            if c == "\\":
                trozo.append(c)
                if self._fin():
                    raise ErrorLexico(
                        "escape incompleto en interpolación", self.linea, self.columna
                    )
                trozo.append(self._avanzar())
                continue
            if c == "{":
                llaves += 1
            elif c == "}":
                llaves -= 1
                if llaves == 0 and parentesis == 0 and corchetes == 0:
                    return "".join(trozo)
            elif c == "(":
                parentesis += 1
            elif c == ")":
                parentesis -= 1
            elif c == "[":
                corchetes += 1
            elif c == "]":
                corchetes -= 1
            trozo.append(c)

    def _saltar_cadena_simple(self, delim: str, trozo: list[str]) -> bool:
        """Cadena anidada dentro de una interpolación: consume hasta el cierre
        (respetando escapes) y deja el texto crudo en `trozo`."""
        while True:
            if self._fin():
                return False
            c = self._avanzar()
            if c == "\\":
                trozo.append(c)
                if self._fin():
                    return False
                trozo.append(self._avanzar())
                continue
            trozo.append(c)
            if c == delim:
                return True

    def _empalmar_expresion(self, expr: str) -> None:
        """Tokeniza el texto de una interpolación y EMPALMA sus tokens en la
        secuencia actual (sin el FIN_DE_ARCHIVO del sub-lexer). El parser
        después consume esos tokens con _expresion() normal."""
        sub_tokens = tokenizar(expr)
        if len(sub_tokens) <= 1:
            raise ErrorLexico(
                "interpolación vacía {}", self.linea_inicial, self.columna_inicial
            )
        self.tokens.extend(sub_tokens[:-1])

    # ---------- números e identificadores ----------

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
