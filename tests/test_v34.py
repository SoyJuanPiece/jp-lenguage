"""Tests de la v1.25: clases y valores por defecto en el motor en C.

El compilador nativo emite CREAR_CLASE (56) más el prólogo
DEFECTOS (57)/SALTAR_SI_HAY_VALOR (58); la VM en C tiene Clase,
Instancia y Método como tipos de objeto propios. Aquí: paridad con la
VM de Python (si hay binario), los errores de construcción y que los
defectos pueden usar parámetros anteriores y capturas.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.compilar_nativo import compilar_a_bytes  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402
from jp.vm import MaquinaVM  # noqa: E402

MOTOR = RAIZ / "motor-c" / "jpvm"

CLASES = """
clase Punto {
    funcion iniciar(a, b = 10) {
        este.a = a
        este.b = b
    }
    funcion norma2() {
        devuelve este.a * este.a + este.b * este.b
    }
    funcion mover(da, db = 1) {
        este.a = este.a + da
        este.b = este.b + db
    }
}
clase Punto3D hereda Punto {
    funcion norma2() {
        devuelve 1000 + este.a
    }
    funcion describir() {
        devuelve "soy 3D con a=" + texto(este.a)
    }
}
variable p = Punto(3)
muestra(p.norma2(), p)
p.mover(1)
muestra(p.a, p.b)
variable q = Punto3D(7, 8)
muestra(q.norma2(), q.describir())
variable ligado = p.mover
ligado(100, 100)
muestra(p.a)
muestra(tipo(p), tipo(Punto))
"""

DEFECTOS = """
funcion f(a, b = a * 10, c = 5) {
    devuelve [a, b, c]
}
muestra(f(1), f(1, 2), f(1, 2, 3))
funcion g(x = "hola") {
    devuelve x
}
muestra(g(), g("adios"))
funcion con_captura() {
    variable base = 40
    funcion suma(x, w = base) {
        devuelve x + w
    }
    devuelve suma(2)
}
muestra(con_captura())
"""


def salida_vm(codigo: str) -> str:
    maquina = MaquinaVM()
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)), directorio=str(RAIZ))
    return buffer.getvalue()


def salida_c(codigo: str) -> subprocess.CompletedProcess:
    blob = compilar_a_bytes(parsear(tokenizar(codigo)))
    with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
        archivo.write(blob)
        ruta = archivo.name
    return subprocess.run([str(MOTOR), ruta], capture_output=True, timeout=60)


@unittest.skipUnless(MOTOR.exists(), "Motor-c/jpvm sin compilar (make -C motor-c)")
class TestMotorCClases(unittest.TestCase):
    def test_clases_identicas(self):
        esperado = salida_vm(CLASES)
        resultado = salida_c(CLASES)
        self.assertEqual(resultado.returncode, 0, resultado.stderr.decode())
        self.assertEqual(resultado.stdout.decode(), esperado)

    def test_defectos_identicos(self):
        esperado = salida_vm(DEFECTOS)
        resultado = salida_c(DEFECTOS)
        self.assertEqual(resultado.returncode, 0, resultado.stderr.decode())
        self.assertEqual(resultado.stdout.decode(), esperado)

    def test_sin_iniciar_con_argumentos_es_error(self):
        resultado = salida_c("clase Vacia {\n}\nvariable v = Vacia(1)\n")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("iniciar", resultado.stderr.decode() + resultado.stdout.decode())

    def test_atributo_faltante_es_error(self):
        codigo = ("clase A {\n funcion iniciar() { este.x = 1 }\n}\n"
                  "variable a = A()\nmuestra(a.otro)\n")
        resultado = salida_c(codigo)
        self.assertNotEqual(resultado.returncode, 0)

    def test_faltan_obligatorios_es_error(self):
        resultado = salida_c("funcion f(a, b = 2) {\n devuelve a + b\n}\nmuestra(f())\n")
        self.assertNotEqual(resultado.returncode, 0)


class TestCompilacionClases(unittest.TestCase):
    def test_opcodes_nuevos_en_el_blob(self):
        from jp.compilar_nativo import OP_CREAR_CLASE, OP_DEFECTOS
        self.assertEqual(OP_CREAR_CLASE, 56)
        self.assertEqual(OP_DEFECTOS, 57)
        blob = compilar_a_bytes(parsear(tokenizar(CLASES)))
        self.assertGreater(len(blob), 100)


if __name__ == "__main__":
    unittest.main()
