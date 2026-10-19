"""Tests de la v1.27: tipos opcionales en el motor en C.

OP_VERIFICAR_TIPO (62) al declarar, OP_VERIFICAR_ARG (63) en el
prólogo de cada función (tras aplicar defectos) y OP_VERIFICAR_RET
(64) en cada 'devuelve' y en el retorno implícito. Mismos mensajes
que la VM de Python.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.compilar_nativo import (  # noqa: E402
    OP_VERIFICAR_ARG,
    OP_VERIFICAR_RET,
    OP_VERIFICAR_TIPO,
    compilar_a_bytes,
)
from jp.errores import ErrorEjecucion  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402
from jp.vm import MaquinaVM  # noqa: E402

MOTOR = RAIZ / "motor-c" / "jpvm"

OK = """
funcion dividir(a: numero, b: numero = 2): numero {
    devuelve a / b
}
muestra(dividir(10), dividir(9, 3))
variable nombre: texto = "Ana"
variable edad: entero = 30
muestra(nombre, edad, tipo(dividir))
funcion libre(x: diccionario): cualquiera {
    devuelve x
}
muestra(libre({"a": 1}))
clase Persona {
    funcion iniciar(nombre: texto) {
        este.nombre = nombre
    }
    funcion saludar(): texto {
        devuelve "hola " + este.nombre
    }
}
muestra(Persona("Luis").saludar())
"""


def correr_c(codigo: str) -> subprocess.CompletedProcess:
    blob = compilar_a_bytes(parsear(tokenizar(codigo)))
    with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
        archivo.write(blob)
        ruta = archivo.name
    return subprocess.run([str(MOTOR), ruta], capture_output=True, timeout=60)


@unittest.skipUnless(MOTOR.exists(), "Motor-c/jpvm sin compilar (make -C motor-c)")
class TestTiposEnC(unittest.TestCase):
    def test_programa_ok_identico(self):
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            MaquinaVM().ejecutar(parsear(tokenizar(OK)), directorio=str(RAIZ))
        resultado = correr_c(OK)
        self.assertEqual(resultado.returncode, 0, resultado.stderr.decode())
        self.assertEqual(resultado.stdout.decode(), buffer.getvalue())

    def test_parametro_malo(self):
        r = correr_c('funcion f(a: numero) { devuelve a }\nmuestra(f("x"))\n')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("es de tipo numero y recibió texto", r.stderr.decode())

    def test_retorno_malo(self):
        r = correr_c('funcion f(): numero { devuelve "x" }\nmuestra(f())\n')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("debe devolver numero y devolvió texto", r.stderr.decode())

    def test_variable_mala(self):
        r = correr_c('variable x: numero = "x"\n')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("'x' es de tipo numero", r.stderr.decode())

    def test_retorno_implicito_malo(self):
        r = correr_c('funcion f(): numero {\n variable z = 1\n}\nmuestra(f())\n')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("devolvió nulo", r.stderr.decode())

    def test_defecto_incorrecto_tambien_se_comprueba(self):
        r = correr_c('funcion f(a: numero = "x") { devuelve a }\nmuestra(f())\n')
        self.assertNotEqual(r.returncode, 0)


class TestSinMotor(unittest.TestCase):
    def test_python_rechaza_igual(self):
        maquina = MaquinaVM()
        with self.assertRaises(ErrorEjecucion):
            maquina.ejecutar(
                parsear(tokenizar('funcion f(): numero { devuelve "x" }\nmuestra(f())\n')),
                directorio=str(RAIZ),
            )

    def test_opcodes(self):
        self.assertEqual((OP_VERIFICAR_TIPO, OP_VERIFICAR_ARG, OP_VERIFICAR_RET), (62, 63, 64))


if __name__ == "__main__":
    unittest.main()
