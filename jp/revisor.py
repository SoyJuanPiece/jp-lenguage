"""Revisor estatico de JP: jp --revisar archivo.jp.

Sin ejecutar nada, recorre el AST con una pila de ambitos y avisa de:

- variables usadas sin declarar ('x' no esta declarada),
- asignaciones sin 'variable' previa,
- variables y parametros declarados que nunca se usan.

Es una aproximacion amable, no un compilador: si un modulo se importa
sin alias no puede saber sus nombres y entonces no acusa lo no
declarado en ese ambito. Los nombres que empiezan por '_' no se acusan
de no usados (es la marca de "lo dejo a proposito").
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from .arbol import (
    Nodo,
    NodoAsignacion,
    NodoAsignacionLista,
    NodoBloque,
    NodoClase,
    NodoDeclaracionLista,
    NodoDeclaracionVar,
    NodoElegir,
    NodoExpresion,
    NodoFuncion,
    NodoImportar,
    NodoIntentar,
    NodoPara,
    NodoPrograma,
    NodoVariable,
)


class Revisor:
    def __init__(self, conocidas: set[str] | None = None) -> None:
        self.avisos: list[str] = []
        # Pila de ambitos: nombre -> [linea, usada]
        self.ambitos: list[dict[str, list]] = []
        self.abierto = 0  # >0 tras un 'importar' sin alias: no acusar
        if conocidas is None:
            from .interprete import Interprete
            conocidas = set(Interprete().global_env.variables)
        self.conocidas = conocidas | {"este"}

    # ---------- ambitos ----------

    def _entrar(self) -> None:
        self.ambitos.append({})

    def _salir(self) -> None:
        ambito = self.ambitos.pop()
        for nombre, (linea, usada) in ambito.items():
            if not usada and not nombre.startswith("_"):
                self.avisos.append(f"línea {linea}: '{nombre}' se declara y nunca se usa")

    def _declarar(self, nombre: str, linea: int) -> None:
        self.ambitos[-1][nombre] = [linea, False]

    def _usar(self, nombre: str, linea: int) -> None:
        for ambito in reversed(self.ambitos):
            if nombre in ambito:
                ambito[nombre][1] = True
                return
        if self.abierto or nombre in self.conocidas:
            return
        self.avisos.append(f"línea {linea}: '{nombre}' no está declarada")

    # ---------- recorrido ----------

    def revisar(self, programa: NodoPrograma) -> list[str]:
        self._entrar()
        for sentencia in programa.sentencias:
            self._sentencia(sentencia)
        ambito = self.ambitos.pop()
        for nombre, (linea, usada) in ambito.items():
            if not usada and not nombre.startswith("_"):
                self.avisos.append(f"línea {linea}: '{nombre}' se declara y nunca se usa")
        return self.avisos

    def _hijos(self, nodo: Nodo):
        for campo in fields(nodo):
            valor = getattr(nodo, campo.name)
            if isinstance(valor, Nodo):
                yield valor
            elif isinstance(valor, (list, tuple)):
                for elemento in valor:
                    if isinstance(elemento, Nodo):
                        yield elemento
                    elif isinstance(elemento, (list, tuple)):
                        for sub in elemento:
                            if isinstance(sub, Nodo):
                                yield sub

    def _expresion(self, nodo: Nodo) -> None:
        tipo = type(nodo)
        if tipo is NodoVariable:
            self._usar(nodo.nombre, nodo.linea)
            return
        if tipo is NodoFuncion:
            self._funcion(nodo, declarar_nombre=False)
            return
        if tipo is NodoAsignacion:
            self._expresion(nodo.valor)
            encontrada = any(nodo.nombre in a for a in self.ambitos) or nodo.nombre in self.conocidas
            if not encontrada and not self.abierto:
                self.avisos.append(
                    f"línea {nodo.linea}: asignas a '{nodo.nombre}' sin declararla antes con 'variable'"
                )
                self._declarar(nodo.nombre, nodo.linea)
                self.ambitos[-1][nodo.nombre][1] = True  # ya avisamos: no repetir
            else:
                self._usar(nodo.nombre, nodo.linea)
            return
        if tipo is NodoAsignacionLista:
            self._expresion(nodo.valor)
            for nombre in nodo.nombres:
                self._usar(nombre, nodo.linea)
            return
        for hijo in self._hijos(nodo):
            self._expresion(hijo)

    def _bloque(self, bloque: NodoBloque | None) -> None:
        if bloque is None:
            return
        self._entrar()
        for sentencia in bloque.sentencias:
            self._sentencia(sentencia)
        self._salir()

    def _funcion(self, nodo: NodoFuncion, declarar_nombre: bool) -> None:
        if declarar_nombre and nodo.nombre:
            self._declarar(nodo.nombre, nodo.linea)
        self._entrar()
        for parametro in nodo.parametros:
            self._declarar(parametro, nodo.linea)
        for defecto in nodo.defectos:
            if defecto is not None:
                self._expresion(defecto)
        for sentencia in nodo.cuerpo.sentencias:
            self._sentencia(sentencia)
        self._salir()

    def _sentencia(self, nodo: Nodo) -> None:
        tipo = type(nodo)
        if tipo is NodoDeclaracionVar:
            if nodo.inicializador is not None:
                self._expresion(nodo.inicializador)
            self._declarar(nodo.nombre, nodo.linea)
        elif tipo is NodoDeclaracionLista:
            self._expresion(nodo.inicializador)
            for nombre in nodo.nombres:
                self._declarar(nombre, nodo.linea)
        elif tipo is NodoExpresion:
            self._expresion(nodo.expresion)
        elif tipo is NodoFuncion:
            self._funcion(nodo, declarar_nombre=True)
        elif tipo is NodoClase:
            self._declarar(nodo.nombre, nodo.linea)
            for metodo in nodo.metodos:
                self._entrar()
                self._declarar("este", metodo.linea)
                for parametro in metodo.parametros:
                    self._declarar(parametro, metodo.linea)
                for defecto in metodo.defectos:
                    if defecto is not None:
                        self._expresion(defecto)
                for sentencia in metodo.cuerpo.sentencias:
                    self._sentencia(sentencia)
                self._salir()
        elif tipo is NodoPara:
            self._expresion(nodo.iterable)
            self._entrar()
            self._declarar(nodo.variable, nodo.linea)
            if nodo.variable2:
                self._declarar(nodo.variable2, nodo.linea)
            for sentencia in nodo.cuerpo.sentencias:
                self._sentencia(sentencia)
            self._salir()
        elif tipo is NodoImportar:
            if nodo.alias:
                self._declarar(nodo.alias, nodo.linea)
            else:
                self.abierto += 1
        elif tipo is NodoBloque:
            self._bloque(nodo)
        elif tipo is NodoIntentar:
            self._bloque(nodo.cuerpo)
            if nodo.captura is not None:
                self._entrar()
                if nodo.nombre_error:
                    self._declarar(nodo.nombre_error, nodo.linea)
                for sentencia in nodo.captura.sentencias:
                    self._sentencia(sentencia)
                self._salir()
            self._bloque(nodo.finalmente)
        elif tipo is NodoElegir:
            self._expresion(nodo.expresion)
            for valores, cuerpo in nodo.casos:
                for valor in valores:
                    self._expresion(valor)
                self._bloque(cuerpo)
            self._bloque(nodo.sino)
        else:
            for hijo in self._hijos(nodo):
                if isinstance(hijo, NodoBloque):
                    self._bloque(hijo)
                else:
                    self._expresion(hijo)


def revisar(programa: NodoPrograma) -> list[str]:
    return Revisor().revisar(programa)
