"""Tipos de token y clase Token para el lenguaje JP."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TToken(Enum):
    # Signos de un carácter
    PAREN_IZQ = auto()
    PAREN_DER = auto()
    LLAVE_IZQ = auto()
    LLAVE_DER = auto()
    CORCHETE_IZQ = auto()
    CORCHETE_DER = auto()
    COMA = auto()
    PUNTO_Y_COMA = auto()
    DOSPUNTOS = auto()      # :
    MAS = auto()          # +
    MENOS = auto()        # -
    POR = auto()          # *
    ENTRE = auto()        # /
    MODULO = auto()       # %
    PUNTO = auto()        # .  (acceso a claves: d.clave)
    IGUAL = auto()        # =
    MENOR = auto()        # <
    MAYOR = auto()        # >

    # Signos de dos caracteres
    IGUAL_IGUAL = auto()      # ==
    DIFERENTE = auto()        # !=
    MENOR_IGUAL = auto()      # <=
    MAYOR_IGUAL = auto()      # >=
    PUNTO_PUNTO = auto()      # ..

    # Literales
    NUMERO = auto()
    CADENA = auto()
    IDENTIFICADOR = auto()

    # Palabras clave
    VAR = auto()          # var
    FUN = auto()          # fun
    RETORNA = auto()      # retorna
    SI = auto()           # si
    SINO = auto()         # sino
    MIENTRAS = auto()     # mientras
    PARA = auto()         # para
    EN = auto()           # en
    VERDADERO = auto()    # verdadero
    FALSO = auto()        # falso
    NULO = auto()         # nulo
    Y = auto()            # y
    O = auto()            # o
    NO = auto()           # no

    # Especiales
    FIN_DE_ARCHIVO = auto()


@dataclass(frozen=True)
class Token:
    tipo: TToken
    lexema: str
    literal: object
    linea: int
    columna: int


PALABRAS_CLAVE: dict[str, TToken] = {
    "var": TToken.VAR,
    "variable": TToken.VAR,          # alias fácil
    "fun": TToken.FUN,
    "funcion": TToken.FUN,           # alias fácil
    "función": TToken.FUN,           # alias fácil con tilde
    "retorna": TToken.RETORNA,
    "devuelve": TToken.RETORNA,      # alias fácil
    "si": TToken.SI,
    "sino": TToken.SINO,
    "mientras": TToken.MIENTRAS,
    "para": TToken.PARA,
    "en": TToken.EN,
    "verdadero": TToken.VERDADERO,
    "falso": TToken.FALSO,
    "nulo": TToken.NULO,
    "y": TToken.Y,
    "o": TToken.O,
    "no": TToken.NO,
}

NOMBRES_TOKEN: dict[TToken, str] = {
    TToken.PAREN_IZQ: "(",
    TToken.PAREN_DER: ")",
    TToken.LLAVE_IZQ: "{",
    TToken.LLAVE_DER: "}",
    TToken.CORCHETE_IZQ: "[",
    TToken.CORCHETE_DER: "]",
    TToken.COMA: ",",
    TToken.PUNTO_Y_COMA: ";",
    TToken.DOSPUNTOS: ":",
    TToken.PUNTO: ".",
    TToken.PUNTO_PUNTO: "..",
    TToken.MAS: "+",
    TToken.MENOS: "-",
    TToken.POR: "*",
    TToken.ENTRE: "/",
    TToken.MODULO: "%",
    TToken.IGUAL: "=",
    TToken.MENOR: "<",
    TToken.MAYOR: ">",
    TToken.IGUAL_IGUAL: "==",
    TToken.DIFERENTE: "!=",
    TToken.MENOR_IGUAL: "<=",
    TToken.MAYOR_IGUAL: ">=",
    TToken.NUMERO: "número",
    TToken.CADENA: "cadena",
    TToken.IDENTIFICADOR: "identificador",
    TToken.VAR: "'var'",
    TToken.FUN: "'fun'",
    TToken.RETORNA: "'retorna'",
    TToken.SI: "'si'",
    TToken.SINO: "'sino'",
    TToken.MIENTRAS: "'mientras'",
    TToken.PARA: "'para'",
    TToken.EN: "'en'",
    TToken.VERDADERO: "'verdadero'",
    TToken.FALSO: "'falso'",
    TToken.NULO: "'nulo'",
    TToken.Y: "'y'",
    TToken.O: "'o'",
    TToken.NO: "'no'",
    TToken.FIN_DE_ARCHIVO: "fin del archivo",
}
