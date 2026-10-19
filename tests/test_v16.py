"""Tests de la v1.6: lanzar, finalmente, valores por defecto, desestructuración,
'para a, b en', módulos (importar) y el tope de recursión unificado.

Todo se prueba en los DOS motores (VM y árbol) con la misma salida.
Ejecutar con:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jp.compilar_nativo import NoSoportadoNativo, compilar_a_bytes
from jp.errores import ErrorEjecucion
from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM


def ejecutar_en(maquina, codigo: str, directorio=None) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)), directorio=directorio)
    return buffer.getvalue()


def paridad(codigo: str) -> str:
    vm = ejecutar_en(MaquinaVM(), codigo)
    arbol = ejecutar_en(Interprete(), codigo)
    assert vm == arbol, f"VM y árbol difieren:\nVM: {vm!r}\nárbol: {arbol!r}"
    return vm


class TestLanzarYFinalmente(unittest.TestCase):
    def test_lanzar_atrapable(self):
        salida = paridad('intenta { lanzar "boom" } atrapa e { muestra("atrapado:", e) }')
        self.assertEqual(salida, "atrapado: boom\n")

    def test_lanzar_fuera_de_intenta_es_error(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion) as ctx:
                ejecutar_en(maquina, 'lanzar "fallo propio"')
            self.assertIn("fallo propio", str(ctx.exception))

    def test_finalmente_sin_error(self):
        self.assertEqual(
            paridad('intenta { muestra("cuerpo") } finalmente { muestra("final") }'),
            "cuerpo\nfinal\n",
        )

    def test_finalmente_tras_error_y_atrapa(self):
        self.assertEqual(
            paridad('intenta { 1 / 0 } atrapa e { muestra("atrapa") } finalmente { muestra("final") }'),
            "atrapa\nfinal\n",
        )

    def test_finalmente_antes_de_devuelve(self):
        codigo = (
            'funcion f() { intenta { devuelve 7 } finalmente { muestra("limpieza") } }\n'
            'muestra(f())'
        )
        self.assertEqual(paridad(codigo), "limpieza\n7\n")

    def test_finalmente_antes_de_romper(self):
        codigo = (
            'para i en 1..5 { intenta { si i == 2 { romper } muestra(i) } '
            'finalmente { muestra("f", i) } }'
        )
        self.assertEqual(paridad(codigo), "1\nf 1\nf 2\n")

    def test_solo_finalmente_relance(self):
        # sin 'atrapa', el error sigue su camino tras correr el finalmente
        codigo = (
            'intenta { intenta { 1 / 0 } finalmente { muestra("interno") } } '
            'atrapa e { muestra("externo") }'
        )
        self.assertEqual(paridad(codigo), "interno\nexterno\n")


class TestValoresPorDefecto(unittest.TestCase):
    def test_defecto_simple(self):
        self.assertEqual(
            paridad('funcion f(a, b = 2) { devuelve a + b }\nmuestra(f(1), f(1, 10))'),
            "3 11\n",
        )

    def test_defecto_usa_parametro_anterior(self):
        self.assertEqual(
            paridad('funcion f(a, b = a + 1) { devuelve b }\nmuestra(f(5))'), "6\n"
        )

    def test_defecto_en_anonima(self):
        self.assertEqual(
            paridad('variable f = funcion(x, z = 10) { devuelve x + z }\nmuestra(f(1), f(1, 2))'),
            "11 3\n",
        )

    def test_faltan_obligatorios(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina, 'funcion f(a, b = 2) { devuelve a }\nf()')


class TestDesestructuracion(unittest.TestCase):
    def test_declaracion(self):
        self.assertEqual(paridad('variable [a, b] = [1, 2]\nmuestra(a, b)'), "1 2\n")

    def test_intercambio_sin_temporal(self):
        self.assertEqual(
            paridad('variable a = 1\nvariable b = 2\n[a, b] = [b, a]\nmuestra(a, b)'),
            "2 1\n",
        )

    def test_desde_llamada(self):
        codigo = 'funcion par() { devuelve [3, 4] }\nvariable [a, b] = par()\nmuestra(a * b)'
        self.assertEqual(paridad(codigo), "12\n")

    def test_largo_distinto_es_error(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion) as ctx:
                ejecutar_en(maquina, 'variable [a, b] = [1]')
            self.assertIn("esperaba 2", str(ctx.exception))


class TestParaDoble(unittest.TestCase):
    def test_indice_y_valor_en_lista(self):
        self.assertEqual(
            paridad('para i, v en ["a", "b"] { muestra(i, v) }'), "0 a\n1 b\n"
        )

    def test_clave_y_valor_en_diccionario(self):
        self.assertEqual(
            paridad('para k, v en {x: 1, y: 2} { muestra(k, v) }'), "x 1\ny 2\n"
        )

    def test_en_texto_y_rango(self):
        self.assertEqual(paridad('para i, c en "ho" { muestra(i, c) }'), "0 h\n1 o\n")
        self.assertEqual(paridad('para i, n en 10..20 paso 10 { muestra(i, n) }'), "0 10\n1 20\n")


class TestImportar(unittest.TestCase):
    def _carpeta(self, archivos: dict[str, str]) -> Path:
        carpeta = Path(tempfile.mkdtemp())
        for nombre, fuente in archivos.items():
            (carpeta / nombre).write_text(fuente, encoding="utf-8")
        return carpeta

    def test_como_alias_y_sin_alias(self):
        carpeta = self._carpeta({
            "mates.jp": 'variable pi2 = 6\nfuncion doble(n) { devuelve n * 2 }\n'
                        'funcion grande() { devuelve doble(10) + pi2 }\n',
        })
        codigo = 'importar "mates.jp" como m\nmuestra(m.grande(), m.pi2)'
        for maquina in (MaquinaVM(), Interprete()):
            self.assertEqual(ejecutar_en(maquina, codigo, carpeta), "26 6\n")
        codigo2 = 'importar "mates.jp"\nmuestra(doble(3))'
        for maquina in (MaquinaVM(), Interprete()):
            self.assertEqual(ejecutar_en(maquina, codigo2, carpeta), "6\n")

    def test_se_ejecuta_una_sola_vez(self):
        carpeta = self._carpeta({"una.jp": 'muestra("cargado")\nvariable x = 1\n'})
        codigo = 'importar "una.jp"\nimportar "una.jp" como otra\nmuestra("fin")'
        for maquina in (MaquinaVM(), Interprete()):
            self.assertEqual(ejecutar_en(maquina, codigo, carpeta), "cargado\nfin\n")

    def test_modulo_no_encontrado(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion) as ctx:
                ejecutar_en(maquina, 'importar "no-esta.jp"', Path(tempfile.mkdtemp()))
            self.assertIn("no se encontró el módulo", str(ctx.exception))

    def test_importacion_circular(self):
        carpeta = self._carpeta({
            "a.jp": 'importar "b.jp"\n',
            "b.jp": 'importar "a.jp"\n',
        })
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion) as ctx:
                ejecutar_en(maquina, 'importar "a.jp"', carpeta)
            self.assertIn("circular", str(ctx.exception))

    def test_el_motor_c_lo_rechaza_limpio(self):
        # El motor en C aún no tiene módulos: se niega y el CLI usa Python.
        programa = parsear(tokenizar('importar "x.jp"'))
        with self.assertRaises(NoSoportadoNativo):
            compilar_a_bytes(programa, "prueba", 'importar "x.jp"')


class TestRecursionUnificada(unittest.TestCase):
    def test_recursion_profunda_igual_en_ambos(self):
        codigo = 'funcion f(n) { si n == 0 { devuelve 0 } devuelve f(n - 1) }\nmuestra(f(2000))'
        self.assertEqual(paridad(codigo), "0\n")

    def test_recursion_infinita_mismo_error(self):
        codigo = 'funcion f(n) { devuelve f(n + 1) }\nf(0)'
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion) as ctx:
                ejecutar_en(maquina, codigo)
            self.assertIn("desbordamiento de pila", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

class TestFinalmenteEnAtrapa(unittest.TestCase):
    def test_devuelve_en_atrapa_corre_finalmente(self):
        codigo = (
            'funcion f() { intenta { 1 / 0 } atrapa e { devuelve "fallo" } '
            'finalmente { muestra("fin") } }\nmuestra(f())'
        )
        self.assertEqual(paridad(codigo), "fin\nfallo\n")

    def test_error_en_atrapa_corre_finalmente(self):
        codigo = (
            'intenta { intenta { 1 / 0 } atrapa e { 2 / 0 } finalmente { muestra("f") } } '
            'atrapa e2 { muestra("externo") }'
        )
        self.assertEqual(paridad(codigo), "f\nexterno\n")

    def test_defectos_desde_nativa(self):
        # mapear llama a la función desde una nativa: también valen los defectos
        codigo = (
            'funcion f(x, mas = 100) { devuelve x + mas }\n'
            'muestra(mapear([1, 2], f))'
        )
        self.assertEqual(paridad(codigo), "[101, 102]\n")
