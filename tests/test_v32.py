"""Tests de la v1.23: tipos opcionales con chequeo al ejecutar."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from jp.compilar_nativo import NoSoportadoNativo, compilar_a_bytes
from jp.errores import ErrorEjecucion, ErrorJP
from jp.formateador import formatear
from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM


def ejecutar_en(maquina, codigo: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)))
    return buffer.getvalue()


def paridad(codigo: str) -> str:
    vm = ejecutar_en(MaquinaVM(), codigo)
    arbol = ejecutar_en(Interprete(), codigo)
    assert vm == arbol, f"VM y arbol difieren:\nVM: {vm!r}\narbol: {arbol!r}"
    return vm


BIEN = """
funcion sumar(a: numero, b: numero): numero { devuelve a + b }
variable edad: numero = sumar(20, 22)
funcion saludar(nombre: texto): texto { devuelve "hola " + nombre }
muestra(edad, saludar("Ana"), tipo(edad))
"""


class TestTipos(unittest.TestCase):
    def test_programa_bien_tipado(self):
        self.assertEqual(paridad(BIEN), "42 hola Ana número\n")

    def test_errores_de_tipo_en_ambos_motores(self):
        casos = [
            'variable x: texto = 5',
            'funcion f(a: numero) { devuelve a }\nf("x")',
            'funcion f(): numero { devuelve "x" }\nf()',
            'funcion f(a: numero = "x") { devuelve a }\nf()',
        ]
        for codigo in casos:
            for maquina in (MaquinaVM, Interprete):
                with self.subTest(codigo=codigo, motor=maquina.__name__):
                    with self.assertRaises(ErrorEjecucion):
                        ejecutar_en(maquina(), codigo)

    def test_tipo_desconocido_es_error_de_sintaxis(self):
        with self.assertRaises(ErrorJP):
            parsear(tokenizar("funcion f(a: cadena) { devuelve a }"))

    def test_sin_anotar_todo_vale(self):
        self.assertEqual(paridad('funcion f(a) { devuelve a }\nmuestra(f("x"), f(3))'), "x 3\n")

    def test_formateador_conserva_los_tipos(self):
        salida = formatear(parsear(tokenizar(
            "funcion f(a: numero): numero { devuelve a }\nvariable x: numero = 3")))
        self.assertIn("a: numero): numero", salida)
        self.assertIn("variable x: numero = 3", salida)

    def test_motor_c_lo_rechaza_limpio(self):
        with self.assertRaises(NoSoportadoNativo):
            compilar_a_bytes(parsear(tokenizar("funcion f(a: numero) { devuelve a }")), "p")


if __name__ == "__main__":
    unittest.main()
