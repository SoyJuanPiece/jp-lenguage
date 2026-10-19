"""Tests de la v1.22: procesos en paralelo (jp/procesos.py)."""

from __future__ import annotations

import io
import sys
import time
import unittest
from contextlib import redirect_stdout

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


class TestProcesos(unittest.TestCase):
    def test_salida_y_codigo(self):
        codigo = (
            f'variable p = iniciar_proceso(["{sys.executable}", "-c", "print(40 + 2)"])\n'
            "variable r = esperar_proceso(p)\n"
            "muestra(r.codigo, recortar(r.salida), r.terminado)\n"
        )
        self.assertEqual(paridad(codigo), "0 42 verdadero\n")

    def test_paralelo_de_verdad(self):
        codigo = (
            "variable procesos = []\n"
            "para i en 1..3 {\n"
            f'    procesos.agregar(iniciar_proceso(["{sys.executable}", "-c", "import time; time.sleep(0.6)"]))\n'
            "}\n"
            "para p en procesos { esperar_proceso(p) }\n"
            'muestra("listo")\n'
        )
        inicio = time.monotonic()
        self.assertEqual(paridad(codigo), "listo\n")
        # En serie serian ~1.8s solo de sueno (x2 motores, pero cada motor
        # lanza los 3 a la vez): cada tanda debe ir muy por debajo.
        self.assertLess(time.monotonic() - inicio, 2.8)

    def test_limite_mata_al_proceso(self):
        codigo = (
            f'variable p = iniciar_proceso(["{sys.executable}", "-c", "import time; time.sleep(30)"])\n'
            "variable r = esperar_proceso(p, 0.2)\n"
            "muestra(r.terminado, r.codigo == nulo)\n"
        )
        self.assertEqual(paridad(codigo), "falso verdadero\n")


if __name__ == "__main__":
    unittest.main()
