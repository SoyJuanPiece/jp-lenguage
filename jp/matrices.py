"""Matrices y vectores para JP: el mini-NumPy de la casa.

Una matriz es una lista de listas de números: [[1, 2], [3, 4]].
Operaciones con formas comprobadas y errores en español. Lo usan la IA y
cualquier cuenta con tablas de números.
"""

from __future__ import annotations

import math

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa, jp_a_texto


def _num(v: object, nombre: str):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ErrorEjecucion(f"{nombre} espera números, recibió {jp_a_texto(v)!r}")
    return v


def _vector(valor: object, nombre: str) -> list:
    if not isinstance(valor, list) or not valor:
        raise ErrorEjecucion(f"{nombre} espera una lista de números no vacía")
    return [_num(v, nombre) for v in valor]


def _matriz(valor: object, nombre: str) -> tuple[list, int, int]:
    if not isinstance(valor, list) or not valor or not all(isinstance(f, list) for f in valor):
        raise ErrorEjecucion(f"{nombre} espera una matriz (lista de listas de números)")
    columnas = len(valor[0])
    if columnas == 0:
        raise ErrorEjecucion(f"{nombre} espera una matriz con al menos una columna")
    filas = []
    for fila in valor:
        if len(fila) != columnas:
            raise ErrorEjecucion(f"{nombre}: todas las filas deben tener el mismo largo")
        filas.append([_num(v, nombre) for v in fila])
    return filas, len(filas), columnas


def instalar(entorno: Entorno, invocar=None) -> None:
    def forma(m: object) -> list:
        _, f, c = _matriz(m, "forma()")
        return [f, c]

    def crear_matriz(*args: object) -> list:
        if len(args) not in (2, 3):
            raise ErrorEjecucion("crear_matriz() espera (filas, columnas) o (filas, columnas, relleno)")
        filas, columnas = int(_num(args[0], "crear_matriz()")), int(_num(args[1], "crear_matriz()"))
        if filas <= 0 or columnas <= 0:
            raise ErrorEjecucion("crear_matriz() espera filas y columnas mayores que 0")
        relleno = _num(args[2], "crear_matriz()") if len(args) == 3 else 0
        return [[relleno for _ in range(columnas)] for _ in range(filas)]

    def identidad(n: object) -> list:
        n = int(_num(n, "identidad()"))
        if n <= 0:
            raise ErrorEjecucion("identidad() espera un número mayor que 0")
        return [[1 if i == j else 0 for j in range(n)] for i in range(n)]

    def transponer(m: object) -> list:
        filas, f, c = _matriz(m, "transponer()")
        return [[filas[i][j] for i in range(f)] for j in range(c)]

    def _misma_forma(a: object, b: object, nombre: str):
        ma, fa, ca = _matriz(a, nombre)
        mb, fb, cb = _matriz(b, nombre)
        if (fa, ca) != (fb, cb):
            raise ErrorEjecucion(f"{nombre}: las formas no coinciden ({fa}x{ca} y {fb}x{cb})")
        return ma, mb, fa, ca

    def sumar_matrices(a: object, b: object) -> list:
        ma, mb, f, c = _misma_forma(a, b, "sumar_matrices()")
        return [[ma[i][j] + mb[i][j] for j in range(c)] for i in range(f)]

    def restar_matrices(a: object, b: object) -> list:
        ma, mb, f, c = _misma_forma(a, b, "restar_matrices()")
        return [[ma[i][j] - mb[i][j] for j in range(c)] for i in range(f)]

    def multiplicar_matrices(a: object, b: object) -> list:
        ma, fa, ca = _matriz(a, "multiplicar_matrices()")
        mb, fb, cb = _matriz(b, "multiplicar_matrices()")
        if ca != fb:
            raise ErrorEjecucion(
                f"multiplicar_matrices(): no se puede {fa}x{ca} por {fb}x{cb} "
                "(las columnas de la primera deben ser las filas de la segunda)"
            )
        columnas_b = list(zip(*mb))
        return [[sum(x * y for x, y in zip(fila, col)) for col in columnas_b] for fila in ma]

    def escalar_matriz(m: object, k: object) -> list:
        filas, f, c = _matriz(m, "escalar_matriz()")
        factor = _num(k, "escalar_matriz()")
        return [[filas[i][j] * factor for j in range(c)] for i in range(f)]

    def matriz_vector(m: object, v: object) -> list:
        filas, f, c = _matriz(m, "matriz_vector()")
        vector = _vector(v, "matriz_vector()")
        if c != len(vector):
            raise ErrorEjecucion(f"matriz_vector(): la matriz es de {c} columnas y el vector de {len(vector)}")
        return [sum(x * y for x, y in zip(fila, vector)) for fila in filas]

    def _par_vectores(a: object, b: object, nombre: str):
        va, vb = _vector(a, nombre), _vector(b, nombre)
        if len(va) != len(vb):
            raise ErrorEjecucion(f"{nombre}: los vectores deben tener el mismo largo ({len(va)} y {len(vb)})")
        return va, vb

    def sumar_vectores(a: object, b: object) -> list:
        va, vb = _par_vectores(a, b, "sumar_vectores()")
        return [x + y for x, y in zip(va, vb)]

    def restar_vectores(a: object, b: object) -> list:
        va, vb = _par_vectores(a, b, "restar_vectores()")
        return [x - y for x, y in zip(va, vb)]

    def multiplicar_vectores(a: object, b: object) -> list:
        va, vb = _par_vectores(a, b, "multiplicar_vectores()")
        return [x * y for x, y in zip(va, vb)]

    def norma(v: object):
        vector = _vector(v, "norma()")
        return math.sqrt(sum(x * x for x in vector))

    def distancia(a: object, b: object):
        va, vb = _par_vectores(a, b, "distancia()")
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(va, vb)))

    def normalizar(v: object) -> list:
        vector = _vector(v, "normalizar()")
        n = math.sqrt(sum(x * x for x in vector))
        if n == 0:
            raise ErrorEjecucion("normalizar(): no se puede normalizar el vector cero")
        return [x / n for x in vector]

    def softmax(lista: object) -> list:
        valores = _vector(lista, "softmax()")
        mayor = max(valores)
        exps = [math.exp(v - mayor) for v in valores]
        total = sum(exps)
        return [e / total for e in exps]

    def matriz_aplicar(m: object, f: object) -> list:
        if invocar is None:
            raise ErrorEjecucion("matriz_aplicar() necesita un motor que sepa llamar funciones")
        filas, _, _ = _matriz(m, "matriz_aplicar()")
        return [[invocar(f, [v], 0) for v in fila] for fila in filas]

    nativas = {
        "forma": FuncionNativa("forma", forma, aridad=1),
        "crear_matriz": FuncionNativa("crear_matriz", crear_matriz),
        "identidad": FuncionNativa("identidad", identidad, aridad=1),
        "transponer": FuncionNativa("transponer", transponer, aridad=1),
        "sumar_matrices": FuncionNativa("sumar_matrices", sumar_matrices, aridad=2),
        "restar_matrices": FuncionNativa("restar_matrices", restar_matrices, aridad=2),
        "multiplicar_matrices": FuncionNativa("multiplicar_matrices", multiplicar_matrices, aridad=2),
        "escalar_matriz": FuncionNativa("escalar_matriz", escalar_matriz, aridad=2),
        "matriz_vector": FuncionNativa("matriz_vector", matriz_vector, aridad=2),
        "sumar_vectores": FuncionNativa("sumar_vectores", sumar_vectores, aridad=2),
        "restar_vectores": FuncionNativa("restar_vectores", restar_vectores, aridad=2),
        "multiplicar_vectores": FuncionNativa("multiplicar_vectores", multiplicar_vectores, aridad=2),
        "norma": FuncionNativa("norma", norma, aridad=1),
        "distancia": FuncionNativa("distancia", distancia, aridad=2),
        "normalizar": FuncionNativa("normalizar", normalizar, aridad=1),
        "softmax": FuncionNativa("softmax", softmax, aridad=1),
        "matriz_aplicar": FuncionNativa("matriz_aplicar", matriz_aplicar, aridad=2),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
