"""Tests de la v1.30: UTF-8 de verdad en el motor en C, y SVG, CSV,
plataforma y patrones nativos.

La regla de siempre: *mismo programa, misma salida* en los tres motores
(árbol, VM de Python y motor en C).
"""

from __future__ import annotations

import io
import subprocess
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.compilar_nativo import compilar_a_bytes  # noqa: E402
from jp.interprete import Interprete  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402
from jp.vm import MaquinaVM  # noqa: E402

def _motor_c() -> Path:
    """El motor en C, del entorno si está compilado fuera del repo."""
    ruta = os.environ.get("JPVM")
    if ruta:
        return Path(ruta)
    sufijo = ".exe" if os.name == "nt" else ""
    return RAIZ / "motor-c" / f"jpvm{sufijo}"


MOTOR = _motor_c()
if not MOTOR.is_file():
    raise unittest.SkipTest("motor en C sin compilar (make -C motor-c)")



def _en(maquina, fuente: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(fuente)))
    return buffer.getvalue()


def _nativo(fuente: str) -> tuple[str, str]:
    blob = compilar_a_bytes(parsear(tokenizar(fuente)), "<test>", fuente)
    with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
        archivo.write(blob)
        ruta = archivo.name
    proceso = subprocess.run([str(MOTOR), ruta], capture_output=True, text=True, timeout=120)
    return proceso.stdout, proceso.stderr


class ParidadTriple(unittest.TestCase):
    """Compara árbol, VM y —si está compilado— el motor en C."""

    def paridad(self, fuente: str) -> str:
        arbol = _en(Interprete(), fuente)
        vm = _en(MaquinaVM(), fuente)
        self.assertEqual(arbol, vm, "el árbol y la VM difieren")
        if MOTOR.exists():
            nativo, errores = _nativo(fuente)
            self.assertEqual(errores, "", f"el motor nativo falló: {errores}")
            self.assertEqual(nativo, vm, "el motor en C difiere de la VM")
        return vm


class TestTextoUnicode(ParidadTriple):
    """"Maturín" tiene 7 letras, no 8: el motor en C cuenta caracteres."""

    def test_longitud_y_corte(self) -> None:
        salida = self.paridad(
            'variable s = "Maturín"\n'
            'muestra(longitud(s), longitud("ñandú"), longitud("día"))\n'
            'muestra(letra(s, 6), letra(s, -1), s[6], s[5])\n'
            'muestra(subtexto(s, 0, 5), subtexto(s, 5, 7), subtexto(s, -2))\n'
            'muestra(invertir(s), invertir("ñandú"))'
        )
        self.assertEqual(
            salida,
            "7 5 3\nn n n í\nMatur ín ín\nnírutaM údnañ\n",
        )

    def test_mayusculas_del_espanol(self) -> None:
        salida = self.paridad(
            'muestra(mayusculas("maturín"), minusculas("MATURÍN"))\n'
            'muestra(mayusculas("ñandú"), minusculas("ÑANDÚ"))\n'
            'muestra(mayusculas("áéíóúü"), minusculas("ÁÉÍÓÚÜ"))'
        )
        self.assertEqual(
            salida,
            "MATURÍN maturín\nÑANDÚ ñandú\nÁÉÍÓÚÜ áéíóúü\n",
        )

    def test_posiciones_y_recorrido(self) -> None:
        salida = self.paridad(
            'variable s = "Maturín"\n'
            'muestra(buscar(s, "í"), indice_de(s, "n"), buscar("ñandú", "d"))\n'
            'variable letras = []\n'
            'para c en "ñuó" { letras = agregar(letras, c) }\n'
            'muestra(letras, separar("á,é,í", ","))'
        )
        self.assertEqual(salida, '5 6 3\n["ñ", "u", "ó"] ["á", "é", "í"]\n')


class TestGraficosSVG(ParidadTriple):
    def test_primitivas(self) -> None:
        salida = self.paridad(
            'muestra(svg_circulo(10, 20, 5))\n'
            'muestra(svg_rectangulo(0, 0, 10, 4, "red"))\n'
            'muestra(svg_linea(0, 0, 10, 10))\n'
            'muestra(svg_texto(5, 7, "a<b", 12, "blue"))\n'
            'muestra(svg_lineas([[0, 0], [1, 2.5]]))\n'
            'muestra(svg_camino("M0 0 L1 1", "none"))'
        )
        self.assertEqual(
            salida,
            '<circle cx="10" cy="20" r="5" fill="tomato"/>\n'
            '<rect x="0" y="0" width="10" height="4" fill="red"/>\n'
            '<line x1="0" y1="0" x2="10" y2="10" stroke="black" stroke-width="2"/>\n'
            '<text x="5" y="7" font-size="12" fill="blue" font-family="sans-serif">a&lt;b</text>\n'
            '<polyline points="0,0 1,2.5" fill="none" stroke="steelblue" stroke-width="2"/>\n'
            '<path d="M0 0 L1 1" fill="none"/>\n',
        )

    def test_crear_y_guardar(self) -> None:
        salida = self.paridad(
            'variable dibujo = crear_svg(20, 10, [svg_circulo(5, 5, 2)], "")\n'
            'muestra(dibujo)\n'
            'muestra(longitud(crear_svg(20, 10, [], "#fff")) > 0)'
        )
        self.assertIn('viewBox="0 0 20 10"', salida)
        self.assertIn("</svg>", salida)


class TestTablasCSV(ParidadTriple):
    def test_leer_y_escribir(self) -> None:
        salida = self.paridad(
            'variable filas = leer_csv_texto("ciudad,total\\nMaturín,120\\nCaracas,320\\n")\n'
            'muestra(longitud(filas), filas[0].ciudad, filas[0].total + filas[1].total)\n'
            'muestra(convertir_csv(filas))\n'
            'muestra(convertir_csv([{a: 1, b: verdadero}, {a: nulo, b: "x,y"}]))'
        )
        lineas = salida.splitlines()
        self.assertEqual(lineas[0], "2 Maturín 440")
        self.assertIn("ciudad,total", salida)
        self.assertIn("Maturín,120", salida)
        self.assertIn('"x,y"', salida)      # la coma de dentro va entre comillas
        self.assertIn("1,verdadero", salida)

    def test_conversion_de_valores(self) -> None:
        salida = self.paridad(
            'variable f = leer_csv_texto("n,d,b,v\\n42,3.5,verdadero,\\n")[0]\n'
            'muestra(tipo(f.n), tipo(f.d), tipo(f.b), tipo(f.v))\n'
            'muestra(f.n + 1, f.d * 2, f.b, f.v)'
        )
        self.assertEqual(salida, "número número booleano nulo\n43 7 verdadero nulo\n")


class TestSistema(ParidadTriple):
    def test_plataforma(self) -> None:
        salida = self.paridad('muestra(longitud(plataforma()) > 0)')
        self.assertEqual(salida, "verdadero\n")


class TestPatronesNativos(ParidadTriple):
    def test_los_cinco(self) -> None:
        salida = self.paridad(
            'muestra(buscar_patron("[0-9]+", "abc123").texto)\n'
            'muestra(coincide_patron("[a-z]+@[a-z]+[.]com", "a@b.com"), coincide_patron("[a-z]+", "A"))\n'
            'muestra(encontrar_patrones("[0-9]+", "a1 b22"), reemplazar_patron("[0-9]", "a1b2", "#"))\n'
            'muestra(separar_patron("[,;]", "a,b;c"), buscar_patron("zzz", "abc"))'
        )
        self.assertEqual(
            salida,
            "123\n"
            "verdadero falso\n"
            '["1", "22"] a#b#\n'
            '["a", "b", "c"] nulo\n',
        )

    def test_grupos_anclajes_y_alternativas(self) -> None:
        salida = self.paridad(
            'muestra(buscar_patron("(a+)(b*)", "xaaabby").grupos)\n'
            'muestra(buscar_patron("[0-9]+", "ab12cd").inicio, buscar_patron("[0-9]+", "ab12cd").fin)\n'
            'muestra(coincide_patron("^hola$", "hola"), coincide_patron("gato|perro", "perro"))\n'
            'muestra(coincide_patron("colou?r", "color"), encontrar_patrones("(ab)+", "ababX ab"))\n'
            'muestra(encontrar_patrones("[^0-9]+", "a1bb22ccc"), reemplazar_patron("^x", "xyx", "Z"))'
        )
        self.assertEqual(
            salida,
            '["aaa", "bb"]\n'
            "2 4\n"
            "verdadero verdadero\n"
            'verdadero ["abab", "ab"]\n'
            '["a", "bb", "ccc"] Zyx\n',
        )

    def test_patron_invalido_avisa(self) -> None:
        from jp.errores import ErrorEjecucion

        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion):
                _en(maquina, 'buscar_patron("[", "x")')
        if MOTOR.exists():
            _, errores = _nativo('buscar_patron("[", "x")')
            self.assertIn("patrón no válido", errores)


if __name__ == "__main__":
    unittest.main()
