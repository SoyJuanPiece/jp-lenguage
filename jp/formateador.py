"""Formateador de codigo JP: jp --formatear archivo.jp.

Vuelve a imprimir el AST con un estilo unico (sangria de 4 espacios, un
espacio tras las comas, bloques siempre en varias lineas). Sirve para
dejar cualquier archivo legible y para que los equipos no discutan por
el estilo. Ojo: los comentarios se pierden (el parser no los conserva).
"""

from __future__ import annotations

import re

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
    NodoIndice,
    NodoIntentar,
    NodoInterpolacion,
    NodoLanzar,
    NodoLista,
    NodoLlamada,
    NodoMientras,
    NodoNulo,
    NodoNumero,
    NodoPara,
    NodoPrograma,
    NodoRango,
    NodoRetorna,
    NodoRomper,
    NodoContinuar,
    NodoSi,
    NodoUnario,
    NodoVariable,
)

_IDENT = re.compile(r"^[A-Za-z_ñ][A-Za-z0-9_ñ]*$")
_RESERVADAS = {
    "variable", "funcion", "devuelve", "si", "sino", "mientras", "para",
    "en", "elegir", "caso", "intenta", "atrapa", "finalmente", "lanzar",
    "romper", "continuar", "importar", "como", "clase", "hereda",
    "verdadero", "falso", "nulo", "y", "o", "no", "paso", "este",
}

# Precedencia (mayor = liga mas fuerte), la misma del parser.
_PREC = {
    "asignacion": 1, "rango": 2, "??": 3, "o": 4, "y": 5,
    "==": 6, "!=": 6, "<": 7, ">": 7, "<=": 7, ">=": 7,
    "+": 8, "-": 8, "*": 9, "/": 9, "%": 9,
    "unario": 10, "**": 11, "sufijo": 12, "primario": 13,
}
_ASOC_DERECHA = {"??", "**"}


def _cadena(valor: str) -> str:
    escapada = (
        valor.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )
    return f'"{escapada}"'


def _numero(valor: float | int) -> str:
    if isinstance(valor, float) and valor == int(valor) and abs(valor) < 1e16:
        return str(int(valor))
    return repr(valor)


class Formateador:
    def __init__(self) -> None:
        self.lineas: list[str] = []

    def formatear(self, programa: NodoPrograma) -> str:
        self._sentencias(programa.sentencias, 0, superior=True)
        return "\n".join(self.lineas).rstrip() + "\n"

    # ---------------- sentencias ----------------

    def _linea(self, nivel: int, texto: str) -> None:
        self.lineas.append("    " * nivel + texto)

    def _sentencias(self, sentencias: list[Nodo], nivel: int, superior: bool = False) -> None:
        for i, sentencia in enumerate(sentencias):
            if superior and i > 0 and isinstance(sentencia, (NodoFuncion, NodoClase)):
                self.lineas.append("")
            self._sentencia(sentencia, nivel)

    def _bloque(self, bloque: NodoBloque | None, nivel: int, apertura: str, pegar: bool = False) -> None:
        """Escribe 'apertura {' + cuerpo + '}'. Con pegar, la apertura va en
        la misma linea que el '}' anterior: '} sino {', '} atrapa e {'..."""
        if bloque is not None and len(bloque.sentencias) == 1 and type(bloque.sentencias[0]) is NodoBloque:
            bloque = bloque.sentencias[0]  # '{ { ... } }' sobra un nivel
        vacio = bloque is None or not bloque.sentencias
        if pegar:
            self._quitar_cierre()
            self.lineas[-1] += f" {apertura} " + ("{}" if vacio else "{")
            if vacio:
                return
        elif vacio:
            self._linea(nivel, apertura + " {}")
            return
        else:
            self._linea(nivel, apertura + " {")
        self._sentencias(bloque.sentencias, nivel + 1)
        self._linea(nivel, "}")

    def _sentencia(self, nodo: Nodo, nivel: int) -> None:
        tipo = type(nodo)
        if tipo is NodoDeclaracionVar:
            texto = f"variable {nodo.nombre}"
            if nodo.tipo is not None:
                texto += f": {nodo.tipo}"
            if nodo.inicializador is not None:
                texto += " = " + self._expr(nodo.inicializador, nivel)
            self._linea(nivel, texto)
        elif tipo is NodoDeclaracionLista:
            nombres = ", ".join(nodo.nombres)
            self._linea(nivel, f"variable [{nombres}] = " + self._expr(nodo.inicializador, nivel))
        elif tipo is NodoAsignacionLista:
            nombres = ", ".join(nodo.nombres)
            self._linea(nivel, f"[{nombres}] = " + self._expr(nodo.valor, nivel))
        elif tipo is NodoExpresion:
            self._linea(nivel, self._expr(nodo.expresion, nivel))
        elif tipo is NodoSi:
            self._si(nodo, nivel)
        elif tipo is NodoMientras:
            self._bloque(nodo.cuerpo, nivel, f"mientras {self._expr(nodo.condicion, nivel)}")
        elif tipo is NodoPara:
            variables = nodo.variable if nodo.variable2 is None else f"{nodo.variable}, {nodo.variable2}"
            self._bloque(nodo.cuerpo, nivel, f"para {variables} en {self._expr(nodo.iterable, nivel)}")
        elif tipo is NodoElegir:
            self._elegir(nodo, nivel)
        elif tipo is NodoIntentar:
            self._bloque(nodo.cuerpo, nivel, "intenta")
            if nodo.captura is not None:
                nombre = f" {nodo.nombre_error}" if nodo.nombre_error else ""
                self._bloque(nodo.captura, nivel, f"atrapa{nombre}", pegar=True)
            if nodo.finalmente is not None:
                self._bloque(nodo.finalmente, nivel, "finalmente", pegar=True)
        elif tipo is NodoFuncion:
            self._funcion(nodo, nivel)
        elif tipo is NodoClase:
            cabecera = f"clase {nodo.nombre}"
            if nodo.padre:
                cabecera += f" hereda {nodo.padre}"
            if not nodo.metodos:
                self._linea(nivel, cabecera + " {}")
                return
            self._linea(nivel, cabecera + " {")
            for i, metodo in enumerate(nodo.metodos):
                if i > 0:
                    self.lineas.append("")
                self._funcion(metodo, nivel + 1)
            self._linea(nivel, "}")
        elif tipo is NodoRetorna:
            texto = "devuelve"
            if nodo.valor is not None:
                texto += " " + self._expr(nodo.valor, nivel)
            self._linea(nivel, texto)
        elif tipo is NodoRomper:
            self._linea(nivel, "romper")
        elif tipo is NodoContinuar:
            self._linea(nivel, "continuar")
        elif tipo is NodoLanzar:
            self._linea(nivel, "lanzar " + self._expr(nodo.expresion, nivel))
        elif tipo is NodoImportar:
            texto = f"importar {_cadena(nodo.ruta)}"
            if nodo.alias:
                texto += f" como {nodo.alias}"
            self._linea(nivel, texto)
        elif tipo is NodoBloque:
            self._bloque(nodo, nivel, "")
        else:
            raise ValueError(f"el formateador no conoce la sentencia {tipo.__name__}")

    def _quitar_cierre(self) -> None:
        """Une el '}' anterior con lo que sigue ('} atrapa e {')."""
        if self.lineas and self.lineas[-1].strip() == "}":
            cierre = self.lineas.pop()
            self.lineas.append(cierre.rstrip())

    def _si(self, nodo: NodoSi, nivel: int) -> None:
        apertura = f"si {self._expr(nodo.condicion, nivel)}"
        sino = nodo.sino
        if sino is not None and len(sino.sentencias) == 1 and type(sino.sentencias[0]) is NodoSi:
            # Cadena 'sino si': se escribe el primero y se sigue en la misma linea.
            self._bloque(nodo.entonces, nivel, apertura)
            resto = sino.sentencias[0]
            while True:
                self._quitar_cierre()
                self.lineas[-1] += f" sino si {self._expr(resto.condicion, nivel)} {{"
                self._sentencias(resto.entonces.sentencias, nivel + 1)
                siguiente = resto.sino
                if siguiente is not None and len(siguiente.sentencias) == 1 and type(siguiente.sentencias[0]) is NodoSi:
                    self._linea(nivel, "}")
                    resto = siguiente.sentencias[0]
                    continue
                if siguiente is not None:
                    self._linea(nivel, "} sino {")
                    self._sentencias(siguiente.sentencias, nivel + 1)
                self._linea(nivel, "}")
                return
        self._bloque(nodo.entonces, nivel, apertura)
        if sino is not None:
            self._bloque(sino, nivel, "sino", pegar=True)

    def _en_linea(self, nodo: Nodo, nivel: int) -> str | None:
        """La sentencia en una sola linea, o None si necesita varias."""
        guardadas = self.lineas
        self.lineas = []
        try:
            self._sentencia(nodo, nivel)
            if len(self.lineas) == 1:
                return self.lineas[0].strip()
            return None
        finally:
            self.lineas = guardadas

    def _caso(self, cabecera: str, cuerpo: NodoBloque, nivel: int) -> None:
        # 'caso v: sentencia' en la misma linea si es una sola y cabe;
        # si no, bloque con llaves (las dos formas las acepta el parser).
        while len(cuerpo.sentencias) == 1 and type(cuerpo.sentencias[0]) is NodoBloque:
            cuerpo = cuerpo.sentencias[0]
        if len(cuerpo.sentencias) == 1:
            en_linea = self._en_linea(cuerpo.sentencias[0], nivel + 1)
            if en_linea is not None:
                self._linea(nivel, f"{cabecera} {en_linea}")
                return
        if not cuerpo.sentencias:
            self._linea(nivel, cabecera + " {}")
            return
        self._linea(nivel, cabecera + " {")
        self._sentencias(cuerpo.sentencias, nivel + 1)
        self._linea(nivel, "}")

    def _elegir(self, nodo: NodoElegir, nivel: int) -> None:
        self._linea(nivel, f"elegir {self._expr(nodo.expresion, nivel)} {{")
        for valores, cuerpo in nodo.casos:
            casos = ", ".join(self._expr(v, nivel) for v in valores)
            self._caso(f"caso {casos}:", cuerpo, nivel + 1)
        if nodo.sino is not None:
            self._caso("sino:", nodo.sino, nivel + 1)
        self._linea(nivel, "}")

    def _parametros_texto(self, nodo: NodoFuncion, nivel: int) -> str:
        parametros = []
        for i, parametro in enumerate(nodo.parametros):
            texto = parametro
            if i < len(nodo.tipos) and nodo.tipos[i] is not None:
                texto += f": {nodo.tipos[i]}"
            if i < len(nodo.defectos) and nodo.defectos[i] is not None:
                texto += f" = {self._expr(nodo.defectos[i], nivel)}"
            parametros.append(texto)
        retorno = f": {nodo.tipo_retorno}" if nodo.tipo_retorno is not None else ""
        return f"({', '.join(parametros)}){retorno}"

    def _funcion(self, nodo: NodoFuncion, nivel: int) -> None:
        nombre = f" {nodo.nombre}" if nodo.nombre else ""
        self._bloque(nodo.cuerpo, nivel, f"funcion{nombre}{self._parametros_texto(nodo, nivel)}")

    # ---------------- expresiones ----------------

    def _expr(self, nodo: Nodo, nivel: int, minima: int = 0) -> str:
        texto, prec = self._render(nodo, nivel)
        if prec < minima:
            return f"({texto})"
        return texto

    def _render(self, nodo: Nodo, nivel: int) -> tuple[str, int]:
        tipo = type(nodo)
        if tipo is NodoNumero:
            return _numero(nodo.valor), _PREC["primario"]
        if tipo is NodoCadena:
            return _cadena(nodo.valor), _PREC["primario"]
        if tipo is NodoBooleano:
            return ("verdadero" if nodo.valor else "falso"), _PREC["primario"]
        if tipo is NodoNulo:
            return "nulo", _PREC["primario"]
        if tipo is NodoVariable:
            return nodo.nombre, _PREC["primario"]
        if tipo is NodoLista:
            elementos = ", ".join(self._expr(e, nivel) for e in nodo.elementos)
            return f"[{elementos}]", _PREC["primario"]
        if tipo is NodoDiccionario:
            if not nodo.pares:
                return "{}", _PREC["primario"]
            pares = []
            for clave, valor in nodo.pares:
                if type(clave) is NodoCadena and _IDENT.match(clave.valor) and clave.valor not in _RESERVADAS:
                    nombre = clave.valor
                else:
                    nombre = self._expr(clave, nivel)
                pares.append(f"{nombre}: {self._expr(valor, nivel)}")
            return "{" + ", ".join(pares) + "}", _PREC["primario"]
        if tipo is NodoInterpolacion:
            return self._interpolacion(nodo, nivel), _PREC["primario"]
        if tipo is NodoRango:
            izquierda = self._expr(nodo.izquierda, nivel, _PREC["??"] + 1)
            derecha = self._expr(nodo.derecha, nivel, _PREC["??"] + 1)
            texto = f"{izquierda}..{derecha}"
            if nodo.paso is not None:
                texto += " paso " + self._expr(nodo.paso, nivel, _PREC["??"] + 1)
            return texto, _PREC["rango"]
        if tipo is NodoBinario:
            return self._binario(nodo, nivel)
        if tipo is NodoUnario:
            operando = self._expr(nodo.operando, nivel, _PREC["unario"])
            if nodo.operador == "no":
                return f"no {operando}", _PREC["unario"]
            return f"-{operando}", _PREC["unario"]
        if tipo is NodoAsignacion:
            valor = self._expr(nodo.valor, nivel, _PREC["asignacion"])
            return f"{nodo.nombre} = {valor}", _PREC["asignacion"]
        if tipo is NodoAsignacionLista:
            nombres = ", ".join(nodo.nombres)
            valor = self._expr(nodo.valor, nivel, _PREC["asignacion"])
            return f"[{nombres}] = {valor}", _PREC["asignacion"]
        if tipo is NodoAsignarIndice:
            objeto = self._expr(nodo.objeto, nivel, _PREC["sufijo"])
            valor = self._expr(nodo.valor, nivel, _PREC["asignacion"])
            if type(nodo.indice) is NodoCadena and _IDENT.match(nodo.indice.valor) and nodo.indice.valor not in _RESERVADAS:
                return f"{objeto}.{nodo.indice.valor} = {valor}", _PREC["asignacion"]
            indice = self._expr(nodo.indice, nivel)
            return f"{objeto}[{indice}] = {valor}", _PREC["asignacion"]
        if tipo is NodoIndice:
            objeto = self._expr(nodo.objeto, nivel, _PREC["sufijo"])
            if type(nodo.indice) is NodoCadena and _IDENT.match(nodo.indice.valor) and nodo.indice.valor not in _RESERVADAS:
                punto = "?." if nodo.seguro else "."
                return f"{objeto}{punto}{nodo.indice.valor}", _PREC["sufijo"]
            corchete = "?.[" if nodo.seguro else "["
            return f"{objeto}{corchete}{self._expr(nodo.indice, nivel)}]", _PREC["sufijo"]
        if tipo is NodoLlamada:
            callee = self._expr(nodo.callee, nivel, _PREC["sufijo"])
            argumentos = ", ".join(self._expr(a, nivel) for a in nodo.argumentos)
            callee_seguro = type(nodo.callee) is NodoIndice and nodo.callee.seguro
            apertura = "?.(" if nodo.seguro and not callee_seguro else "("
            return f"{callee}{apertura}{argumentos})", _PREC["sufijo"]
        if tipo is NodoFuncion:
            # Funcion anonima como valor: se imprime con su cuerpo en lineas.
            cabecera = f"funcion{self._parametros_texto(nodo, nivel)}"
            if not nodo.cuerpo.sentencias:
                return cabecera + " {}", _PREC["primario"]
            guardadas = self.lineas
            self.lineas = []
            self._sentencias(nodo.cuerpo.sentencias, nivel + 1)
            cuerpo = self.lineas
            self.lineas = guardadas
            return cabecera + " {\n" + "\n".join(cuerpo) + "\n" + "    " * nivel + "}", _PREC["primario"]
        raise ValueError(f"el formateador no conoce la expresion {tipo.__name__}")

    def _binario(self, nodo: NodoBinario, nivel: int) -> tuple[str, int]:
        operador = nodo.operador
        prec = _PREC[operador]
        if operador in _ASOC_DERECHA:
            izquierda = self._expr(nodo.izquierda, nivel, prec + 1)
            derecha = self._expr(nodo.derecha, nivel, prec)
        else:
            izquierda = self._expr(nodo.izquierda, nivel, prec)
            derecha = self._expr(nodo.derecha, nivel, prec + 1)
        return f"{izquierda} {operador} {derecha}", prec

    def _interpolacion(self, nodo: NodoInterpolacion, nivel: int) -> str:
        partes = nodo.partes
        if any(type(p) is NodoCadena and ("{" in p.valor or "}" in p.valor) for p in partes):
            # Una llave literal dentro del texto no se puede re-escribir en
            # una interpolacion: se pasa a suma de cadenas equivalente.
            trozos = []
            for parte in partes:
                if type(parte) is NodoCadena:
                    if parte.valor:
                        trozos.append(_cadena(parte.valor))
                else:
                    trozos.append(self._expr(parte, nivel, _PREC["*"]))
            return " + ".join(trozos) if trozos else '""'
        texto = ""
        for parte in partes:
            if type(parte) is NodoCadena:
                texto += (
                    parte.valor.replace("\\", "\\\\")
                    .replace('"', '\\"')
                    .replace("\n", "\\n")
                    .replace("\t", "\\t")
                    .replace("\r", "\\r")
                )
            else:
                texto += "{" + self._expr(parte, nivel) + "}"
        return f'"{texto}"'


def formatear(programa: NodoPrograma) -> str:
    return Formateador().formatear(programa)
