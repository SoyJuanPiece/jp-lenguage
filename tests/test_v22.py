"""Tests de la v1.12: graficos SVG (jp/graficos.py) y biblioteca/graficas.jp."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM

RAIZ = Path(__file__).resolve().parent.parent


def ejecutar_en(maquina, codigo: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)), directorio=str(RAIZ))
    return buffer.getvalue()


def paridad(codigo: str) -> str:
    vm = ejecutar_en(MaquinaVM(), codigo)
    arbol = ejecutar_en(Interprete(), codigo)
    assert vm == arbol, f"VM y arbol difieren:\nVM: {vm!r}\narbol: {arbol!r}"
    return vm


class TestPrimitivasSvg(unittest.TestCase):
    def test_primitivas_exactas(self):
        self.assertEqual(
            paridad('muestra(svg_circulo(50, 50, 10, "red"), svg_texto(0, 10, "a<b"))'),
            '<circle cx="50" cy="50" r="10" fill="red"/> '
            '<text x="0" y="10" font-size="14" fill="black" font-family="sans-serif">a&lt;b</text>\n',
        )

    def test_crear_svg_y_guardar(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = str(Path(carpeta) / "dibujo.svg").replace("\\", "/")
            codigo = (
                f'muestra(guardar_svg("{ruta}", crear_svg(10, 10, [svg_linea(0, 0, 9, 9)])))\n'
                f'muestra(leer_archivo("{ruta}").empezar_con("<svg"))'
            )
            self.assertEqual(paridad(codigo), "verdadero\nverdadero\n")


class TestGraficasJP(unittest.TestCase):
    def test_barras_y_pastel(self):
        codigo = (
            'importar "biblioteca/graficas.jp" como g\n'
            'variable b = g.grafica_barras([10, 30], ["A", "B"], "Ventas")\n'
            'variable p = g.grafica_pastel([1, 3], ["A", "B"])\n'
            'muestra(longitud(separar(b, "<rect")) - 1, longitud(separar(p, "<path")) - 1)\n'
            'muestra(p.contiene("75%"), b.contiene("Ventas"))\n'
        )
        # 1 rect de fondo + 2 barras; 2 porciones de pastel.
        self.assertEqual(paridad(codigo), "3 2\nverdadero verdadero\n")


if __name__ == "__main__":
    unittest.main()
