"""Tests de la v1.7: clases y objetos (clase/hereda/este), errores con
campos (e.tipo/.mensaje/.linea), el kit de IA (sigmoide, producto_punto)
y 'jp --check'. Todo en los DOS motores con la misma salida.
"""

from __future__ import annotations

import io
import subprocess
import sys
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

RAIZ = Path(__file__).resolve().parent.parent


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


BASE = """
clase Persona {
    funcion iniciar(nombre, edad = 0) { este.nombre = nombre; este.edad = edad }
    funcion saludar() { devuelve "Hola, soy " + este.nombre }
    funcion cumplir() { este.edad = este.edad + 1; devuelve este.edad }
}
"""


class TestClases(unittest.TestCase):
    def test_crear_y_usar(self):
        salida = paridad(BASE + 'variable p = Persona("Ana", 30)\nmuestra(p.saludar(), p.edad)')
        self.assertEqual(salida, "Hola, soy Ana 30\n")

    def test_defecto_en_iniciar_y_mutacion(self):
        salida = paridad(BASE + 'variable p = Persona("Ana")\nmuestra(p.edad, p.cumplir(), p)')
        self.assertEqual(salida, '0 1 Persona{nombre: "Ana", edad: 1}\n')

    def test_herencia(self):
        codigo = BASE + """
clase Empleado hereda Persona {
    funcion iniciar(nombre, sueldo) { este.nombre = nombre; este.edad = 20; este.sueldo = sueldo }
    funcion saludar() { devuelve "Empleado " + este.nombre }
}
variable e = Empleado("Luis", 900)
muestra(e.saludar(), e.edad, e.sueldo, e.cumplir())
"""
        self.assertEqual(paridad(codigo), "Empleado Luis 20 900 21\n")

    def test_iniciar_heredado(self):
        codigo = BASE + """
clase Becario hereda Persona { }
variable b = Becario("Eva", 19)
muestra(b.saludar(), b.edad)
"""
        self.assertEqual(paridad(codigo), "Hola, soy Eva 19\n")

    def test_metodo_como_valor_y_tipo(self):
        codigo = BASE + 'variable p = Persona("Ana")\nvariable m = p.saludar\nmuestra(m(), tipo(p), tipo(Persona))'
        self.assertEqual(paridad(codigo), "Hola, soy Ana objeto clase\n")

    def test_metodos_que_se_llaman(self):
        codigo = """
clase Contador {
    funcion iniciar() { este.n = 0 }
    funcion paso() { este.n = este.n + 1; devuelve este.n }
    funcion dos() { este.paso(); devuelve este.paso() }
}
muestra(Contador().dos())
"""
        self.assertEqual(paridad(codigo), "2\n")

    def test_sin_iniciar_no_acepta_argumentos(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina, 'clase P { funcion f() { devuelve 1 } }\nP(1)')

    def test_campo_inexistente_da_pista(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion) as ctx:
                ejecutar_en(maquina, BASE + 'variable p = Persona("Ana")\nmuestra(p.apellido)')
            self.assertIn("no tiene 'apellido'", str(ctx.exception))

    def test_objetos_en_modulos(self):
        # Una clase definida en un modulo sigue funcionando al importarla:
        # sus metodos ven los globales de SU archivo en ambos motores.
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta)
            (ruta / "figuras.jp").write_text(
                'variable unidad = "cm"\n'
                'clase Rectangulo {\n'
                '    funcion iniciar(a, b) { este.ancho = a; este.alto = b }\n'
                '    funcion area() { devuelve este.ancho * este.alto }\n'
                '    funcion describe() { devuelve texto(este.area()) + unidad }\n'
                '}\n',
                encoding="utf-8",
            )
            codigo = 'importar "figuras.jp" como fig\nvariable r = fig.Rectangulo(3, 4)\nmuestra(r.describe())'
            for maquina in (MaquinaVM(), Interprete()):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    maquina.ejecutar(parsear(tokenizar(codigo)), directorio=ruta)
                self.assertEqual(buffer.getvalue(), "12cm\n")

    def test_el_motor_c_lo_rechaza_limpio(self):
        programa = parsear(tokenizar('clase P { funcion f() { devuelve 1 } }'))
        with self.assertRaises(NoSoportadoNativo):
            compilar_a_bytes(programa, "prueba", 'clase P { funcion f() { devuelve 1 } }')


class TestErroresConCampos(unittest.TestCase):
    def test_tipo_y_mensaje(self):
        codigo = 'intenta { 1 / 0 } atrapa e { muestra(e.tipo, "|", e.mensaje, "|", e) }'
        self.assertEqual(paridad(codigo), "division_por_cero | división por cero | división por cero\n")

    def test_tipo_usuario_e_indice(self):
        self.assertEqual(
            paridad('intenta { lanzar "boom" } atrapa e { muestra(e.tipo) }'), "usuario\n"
        )
        self.assertEqual(
            paridad('intenta { [1][5] } atrapa e { muestra(e.tipo) }'), "indice_fuera_de_rango\n"
        )

    def test_linea_del_error(self):
        codigo = 'variable x = 1\nintenta { muestra(x / 0) } atrapa e { muestra(e.linea > 0) }'
        self.assertEqual(paridad(codigo), "verdadero\n")


class TestKitIA(unittest.TestCase):
    def test_sigmoide(self):
        self.assertEqual(paridad('muestra(sigmoide(0))'), "0.5\n")

    def test_producto_punto(self):
        self.assertEqual(paridad('muestra(producto_punto([1, 2, 3], [4, 5, 6]))'), "32\n")

    def test_producto_punto_largos_distintos(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina, 'producto_punto([1], [1, 2])')


class TestCheckCLI(unittest.TestCase):
    def test_check_ok_y_con_error(self):
        with tempfile.TemporaryDirectory() as carpeta:
            bueno = Path(carpeta) / "bueno.jp"
            bueno.write_text('muestra("no deberia ejecutarse")\n', encoding="utf-8")
            proceso = subprocess.run(
                [sys.executable, "-m", "jp", "--check", str(bueno)],
                capture_output=True, text=True, cwd=str(RAIZ),
            )
            self.assertEqual(proceso.returncode, 0)
            self.assertNotIn("no deberia ejecutarse", proceso.stdout)
            self.assertIn("sintaxis correcta", proceso.stdout)

            roto = Path(carpeta) / "roto.jp"
            roto.write_text("funcion rota( {\n", encoding="utf-8")
            proceso = subprocess.run(
                [sys.executable, "-m", "jp", "--check", str(roto)],
                capture_output=True, text=True, cwd=str(RAIZ),
            )
            self.assertEqual(proceso.returncode, 65)


if __name__ == "__main__":
    unittest.main()

class TestRangoPerezoso(unittest.TestCase):
    def test_suma_grande_sin_crear_lista(self):
        # 2 millones de vueltas: si se creara la lista, funcionaria igual,
        # pero la salida demuestra que el bucle sobre rango es correcto.
        codigo = 'variable s = 0\npara i en 1..2000000 { s = s + 1 }\nmuestra(s)'
        self.assertEqual(paridad(codigo), "2000000\n")

    def test_rango_perezoso_descendente_y_paso(self):
        self.assertEqual(paridad('para i en 5..1 { muestra(i) }'), "5\n4\n3\n2\n1\n")
        self.assertEqual(paridad('para i, n en 10..20 paso 10 { muestra(i, n) }'), "0 10\n1 20\n")
        self.assertEqual(paridad('muestra(1..5)'), "[1, 2, 3, 4, 5]\n")  # como valor si es lista
