"""Paridad entre el motor nativo en C y los motores de Python.

La regla del proyecto: *mismo programa, misma salida*. Estas pruebas compilan
cada programa con `jp.compilar_nativo` y comparan lo que imprime el binario
`motor-c/jpvm` contra lo que imprime la VM de Python.

Se saltan solos si el binario no está compilado (`make -C motor-c`).
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.compilar_nativo import NoSoportadoNativo, compilar_a_bytes  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402
from jp.vm import MaquinaVM  # noqa: E402

MOTOR = RAIZ / "motor-c" / "jpvm"

_PROGRAMAS = {
    "aritmética y formato": """
        imprime(1 + 2, 10 / 4, 10 / 5, 7 % 3, -7 % 3, 2 ** 10, 2 ** -1)
        imprime(1.5 + 1.5, 3.0, 0.1 + 0.2, 1000000000000000000 + 1)
        imprime(verdadero, falso, nulo, "texto")
        imprime(2 == 2.0, 2 == "2", verdadero != falso, no nulo)
        imprime([1, 2] + [3], "ab" * 3, "hola" + 42)
        imprime("a" + verdadero + "b", 0 y 5, 1 o 2, nulo o 7)
    """,
    "bucles y control": """
        funcion suma_hasta(n) {
            variable s = 0
            variable i = 1
            mientras i <= n {
                s = s + i
                i = i + 1
            }
            devuelve s
        }
        imprime(suma_hasta(100))
        variable total = 0
        para i en 1..10 { total += i }
        imprime(total)
        para i en 10..1 paso 3: imprime(i)
        variable k = 0
        mientras verdadero {
            k += 1
            si k == 3: continuar
            si k > 5: romper
            imprime("k", k)
        }
        para letra en "jpl" { imprime(letra) }
        para n en 3 { imprime("n", n) }
    """,
    "funciones, recursión y closures": """
        funcion fib(n) {
            si n <= 1 { devuelve n }
            devuelve fib(n - 1) + fib(n - 2)
        }
        funcion contador() {
            variable n = 0
            variable inc = funcion() { n = n + 1
            devuelve n }
            devuelve inc
        }
        funcion aplicar(f, x) { devuelve f(f(x)) }
        funcion doble(x) { devuelve x * 2 }
        imprime(fib(18))
        variable c = contador()
        imprime(c(), c(), c())
        imprime(aplicar(doble, 5))
        variable acumulador = 0
        funcion sumar_clave(pares) {
            para p en pares { acumulador += p }
            devuelve acumulador
        }
        imprime(sumar_clave([1, 2, 3]), acumulador)
    """,
    "listas, índices y rangos": """
        variable l = [3, 1, 2]
        imprime(l, l[0], l[-1], longitud(l))
        l[0] = 9
        imprime(l, "indice")
        imprime(1..5, 5..1, 1..9 paso 4, rango(1, 5), rango(0, 10, 3))
        imprime(longitud(1..100), sumar(1..100))
        imprime(minimo(3, 1, 2), maximo([3, 1, 2]), invertir(l))
        imprime(agregar(l, 7), l)
        imprime(unir(["a", "b", "c"], "-"), contiene(l, 9), contiene("hola", "ol"))
    """,
    "textos y matemáticas": """
        imprime(mayusculas("jp"), minusculas("JP"), recortar("  hola  "))
        imprime(raiz(16), absoluto(-3.5), piso(2.9), techo(2.1), redondear(3.14159, 3))
        imprime(log(100, 10), exp(0), seno(0), coseno(0), pi())
        imprime(entero("42"), numero("2.5"), texto(42) + "!", tipo(42), tipo("x"), tipo([1]))
        imprime(longitud("hola"), "hola"[0], "hola"[-1])
    """,
}


def _ejecutar_python(fuente: str) -> str:
    from jp.interprete import Interprete

    salida = io.StringIO()
    with redirect_stdout(salida):
        interprete = Interprete()
        interprete.ejecutar(parsear(tokenizar(fuente)))
    return salida.getvalue()


def _ejecutar_python_vm(fuente: str) -> str:
    salida = io.StringIO()
    with redirect_stdout(salida):
        MaquinaVM().ejecutar(parsear(tokenizar(fuente)))
    return salida.getvalue()


@unittest.skipUnless(MOTOR.exists(), "el motor nativo no está compilado (make -C motor-c)")
class TestParidadMotorC(unittest.TestCase):
    def _nativo(self, fuente: str) -> tuple[str, str]:
        blob = compilar_a_bytes(parsear(tokenizar(fuente)), "<test>", fuente)
        with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
            archivo.write(blob)
            ruta = archivo.name
        proceso = subprocess.run([str(MOTOR), ruta], capture_output=True, text=True, timeout=120)
        return proceso.stdout, proceso.stderr

    def test_paridad_con_vm_de_python(self) -> None:
        for nombre, fuente in _PROGRAMAS.items():
            with self.subTest(programa=nombre):
                esperado = _ejecutar_python_vm(fuente)
                obtenido, errores = self._nativo(fuente)
                self.assertEqual(errores, "", f"{nombre}: el motor nativo falló: {errores}")
                self.assertEqual(obtenido, esperado, f"{nombre}: salidas distintas")

    def test_paridad_con_los_dos_motores_de_python(self) -> None:
        for nombre, fuente in _PROGRAMAS.items():
            with self.subTest(programa=nombre):
                self.assertEqual(_ejecutar_python(fuente), _ejecutar_python_vm(fuente))

    def test_lo_no_soportado_se_rechaza_con_mensaje(self) -> None:
        casos = [
            'variable d = {clave: 1}',
            'intenta { variable x = 1 / 0 } atrapa e { imprime(e) }',
            'elegir 1 { caso 1 { imprime("uno") } }',
            'imprime("hola".mayusculas())',
            'imprime(100000000000000000000)',
        ]
        for fuente in casos:
            with self.subTest(fuente=fuente):
                with self.assertRaises(NoSoportadoNativo):
                    compilar_a_bytes(parsear(tokenizar(fuente)), "<test>", fuente)

    def test_binario_independiente(self) -> None:
        if shutil.which("cc") is None:
            self.skipTest("no hay compilador de C")
        fuente = 'imprime("hola desde un binario sin Python", 6 * 7)'
        blob = compilar_a_bytes(parsear(tokenizar(fuente)), "<test>", fuente)
        with tempfile.TemporaryDirectory() as carpeta:
            chunk = Path(carpeta) / "chunk.c"
            chunk.write_text(
                "const unsigned char jp_chunk_embebido[] = {"
                + ",".join(str(b) for b in blob)
                + "};\nconst unsigned long jp_chunk_largo = sizeof(jp_chunk_embebido);\n",
                encoding="utf-8",
            )
            salida = Path(carpeta) / "programa"
            proceso = subprocess.run(
                ["cc", "-O2", "-std=c11", "-w", str(RAIZ / "motor-c" / "jpvm.c"),
                 str(chunk), "-o", str(salida), "-lm"],
                capture_output=True, text=True,
            )
            self.assertEqual(proceso.returncode, 0, proceso.stderr)
            corrida = subprocess.run([str(salida)], capture_output=True, text=True)
            self.assertEqual(corrida.stdout, "hola desde un binario sin Python 42\n")


@unittest.skipUnless(MOTOR.exists(), "el motor nativo no está compilado (make -C motor-c)")
class TestEjemplosReales(unittest.TestCase):
    """Los ejemplos que el motor nativo ya soporta deben coincidir línea a línea."""

    SOPORTADOS = ["hola.jp", "fizzbuzz.jp", "fibonacci.jp", "primos.jp",
                  "tabla-multiplicar.jp", "benchmark.jp", "agenda.jp"]

    def test_ejemplos_soportados(self) -> None:
        for nombre in self.SOPORTADOS:
            ruta = RAIZ / "ejemplos" / nombre
            if not ruta.exists():
                continue
            with self.subTest(ejemplo=nombre):
                fuente = ruta.read_text(encoding="utf-8")
                try:
                    blob = compilar_a_bytes(parsear(tokenizar(fuente)), str(ruta), fuente)
                except NoSoportadoNativo as error:
                    self.skipTest(f"{nombre}: aún no soportado ({error.que})")
                with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
                    archivo.write(blob)
                    ruta_jpb = archivo.name
                esperado = _ejecutar_python_vm(fuente)
                proceso = subprocess.run(
                    [str(MOTOR), ruta_jpb], capture_output=True, text=True, timeout=180,
                )
                self.assertEqual(proceso.stdout, esperado, f"{nombre}: salidas distintas")


if __name__ == "__main__":
    unittest.main()
