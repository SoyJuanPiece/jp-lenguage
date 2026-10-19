"""Tests de la v1.8: la libreria estandar (51 nativas nuevas en 5 modulos
del motor: estadistica, matrices, fechas, sistema y patrones) y la
biblioteca en JP puro de biblioteca/ (mates, texto, listas, colecciones, ia).

Todo en los DOS motores con la misma salida.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jp.errores import ErrorEjecucion
from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM

RAIZ = Path(__file__).resolve().parent.parent


def ejecutar_en(maquina, codigo: str, directorio=None) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)), directorio=directorio)
    return buffer.getvalue()


def paridad(codigo: str) -> str:
    vm = ejecutar_en(MaquinaVM(), codigo)
    arbol = ejecutar_en(Interprete(), codigo)
    assert vm == arbol, f"VM y arbol difieren:\nVM: {vm!r}\narbol: {arbol!r}"
    return vm


class TestEstadistica(unittest.TestCase):
    def test_basicas(self):
        salida = paridad(
            'muestra(promedio([1, 2, 3, 4]), mediana([3, 1, 2]), mediana([1, 2, 3, 4]), moda([1, 2, 2, 3]))\n'
            'muestra(percentil([1, 2, 3, 4], 50), resumen([2, 4, 4, 6]).promedio)\n'
            'muestra(frecuencias(["a", "b", "a"]).a, contar([1, 2, 2], 2), contar("banana", "a"))'
        )
        self.assertEqual(salida, "2.5 2 2.5 2\n2.5 4\n2 2 3\n")

    def test_errores(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina, 'promedio([])')
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina, 'promedio([1, "x"])')


class TestMatrices(unittest.TestCase):
    def test_operaciones(self):
        salida = paridad(
            'muestra(transponer([[1, 2], [3, 4]]), multiplicar_matrices([[1, 2]], [[3], [4]]))\n'
            'muestra(forma([[1, 2, 3]]), identidad(2), matriz_vector([[1, 0], [0, 2]], [3, 4]))\n'
            'muestra(sumar_vectores([1, 2], [10, 20]), norma([3, 4]), distancia([0, 0], [3, 4]))\n'
            'muestra(softmax([1, 1]), crear_matriz(2, 2, 7), matriz_aplicar([[1]], funcion(x) { devuelve x * 3 }))'
        )
        self.assertEqual(
            salida,
            "[[1, 3], [2, 4]] [[11]]\n"
            "[1, 3] [[1, 0], [0, 1]] [3, 8]\n"
            "[11, 22] 5 5\n"
            "[0.5, 0.5] [[7, 7], [7, 7]] [[3]]\n",
        )

    def test_formas_incompatibles(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina, 'multiplicar_matrices([[1, 2]], [[1, 2]])')
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina, 'normalizar([0, 0])')


class TestFechasSistemaPatrones(unittest.TestCase):
    def test_fechas(self):
        salida = paridad(
            'variable f = fecha_actual()\n'
            'muestra(f.ano >= 2026, formatear_fecha(convertir_fecha("2026-10-19"), "%Y"), longitud(hoy()))'
        )
        self.assertEqual(salida, "verdadero 2026 10\n")

    def test_sistema(self):
        salida = paridad(
            'muestra(unir_ruta("a", "b.txt") == unir_ruta("a", "b.txt"), nombre_base("/x/y.jp"), extension_de("f.png"))\n'
            f'variable r = ejecutar("{sys.executable} --version")\n'
            'muestra(r.codigo, contiene(r.salida + r.error, "Python"))'
        )
        self.assertEqual(salida, "verdadero y.jp .png\n0 verdadero\n")

    def test_patrones(self):
        salida = paridad(
            'muestra(buscar_patron("[0-9]+", "abc123").texto, coincide_patron("[a-z]+@[a-z]+[.]com", "a@b.com"))\n'
            'muestra(encontrar_patrones("[0-9]+", "a1 b22"), reemplazar_patron("[0-9]", "a1b2", "#"), separar_patron("[,;]", "a,b;c"))\n'
            'muestra(buscar_patron("zzz", "abc"))'
        )
        self.assertEqual(salida, '123 verdadero\n["1", "22"] a#b# ["a", "b", "c"]\nnulo\n')

    def test_patron_invalido(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina, 'buscar_patron("[", "x")')


class TestBibliotecaJP(unittest.TestCase):
    """Los modulos de biblioteca/*.jp, importados como cualquier modulo."""

    def test_mates_texto_listas(self):
        codigo = (
            'importar "biblioteca/mates.jp" como mates\n'
            'importar "biblioteca/texto.jp" como txt\n'
            'importar "biblioteca/listas.jp" como lis\n'
            'muestra(mates.factorial(5), mates.mcd(12, 18), mates.fibonacci(10), mates.primos_hasta(10))\n'
            'muestra(txt.titulo("hola mundo"), txt.cesar("abc", 1), txt.es_anagrama("roma", "amor"), txt.es_palindromo("Anita lava la tina"))\n'
            'muestra(lis.aplanar([[1, 2], [3]]), lis.unicos([1, 1, 2]), lis.buscar_binario([1, 3, 5], 5))'
        )
        salida_vm = ejecutar_en(MaquinaVM(), codigo, RAIZ)
        salida_arbol = ejecutar_en(Interprete(), codigo, RAIZ)
        self.assertEqual(salida_vm, salida_arbol)
        self.assertEqual(
            salida_vm,
            "120 6 55 [2, 3, 5, 7]\n"
            "Hola Mundo bcd verdadero verdadero\n"
            "[1, 2, 3] [1, 2] 2\n",
        )

    def test_colecciones(self):
        codigo = (
            'importar "biblioteca/colecciones.jp" como col\n'
            'variable p = col.Pila()\np.empujar(1)\np.empujar(2)\n'
            'variable c = col.Conjunto()\nc.agregar(1)\nc.agregar(1)\nc.agregar(2)\n'
            'muestra(p.sacar(), p.cima(), c.tamano(), c.contiene(2))'
        )
        for maquina in (MaquinaVM(), Interprete()):
            self.assertEqual(ejecutar_en(maquina, codigo, RAIZ), "2 1 2 verdadero\n")

    def test_red_neuronal_aprende_xor(self):
        # La red de biblioteca/ia.jp (en JP puro) aprende el XOR en ambos
        # motores: error que baja y predicciones en el lado correcto de 0.5.
        codigo = (
            'importar "biblioteca/ia.jp" como ia\n'
            'variable datos = [[0, 0], [0, 1], [1, 0], [1, 1]]\n'
            'variable metas = [[0], [1], [1], [0]]\n'
            'variable red = ia.RedNeuronal(2, 4, 1)\n'
            'variable antes = red.error_total(datos, metas)\n'
            'red.entrenar(datos, metas, 3000)\n'
            'variable ok = red.predecir([0, 0])[0] < 0.3 y red.predecir([0, 1])[0] > 0.7 '
            'y red.predecir([1, 0])[0] > 0.7 y red.predecir([1, 1])[0] < 0.3\n'
            'muestra(red.error_total(datos, metas) < antes, ok)'
        )
        for maquina in (MaquinaVM(), Interprete()):
            self.assertEqual(ejecutar_en(maquina, codigo, RAIZ), "verdadero verdadero\n")


if __name__ == "__main__":
    unittest.main()
