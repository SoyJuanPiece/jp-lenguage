"""Tests del JIT nativo (jp.nativo): funciones JP compiladas a x86-64.

Los tests se saltan solos si la plataforma no permite mmap RWX.
Ejecutar con:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from jp.lexer import tokenizar
from jp.parser import parsear

try:
    import ctypes

    from jp.nativo import FalloCompilacion, compilar_lote

    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.restype = ctypes.c_void_p
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
    _prueba = libc.mmap(None, 4096, 7, 0x22, -1, 0)
    _HAY_JIT = _prueba not in (-1, None)
    if _HAY_JIT:
        libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        libc.munmap(_prueba, 4096)
except Exception:  # pragma: no cover
    _HAY_JIT = False


@unittest.skipUnless(_HAY_JIT, "esta plataforma no permite mmap RWX")
class TestNativo(unittest.TestCase):
    def _compilar(self, fuente: str):
        grupo = compilar_lote(parsear(tokenizar(fuente)))
        self.assertTrue(grupo.funciones, "nada calificó para el JIT")
        self.addCleanup(grupo.liberar)
        return {nombre: fn.funcion for nombre, fn in grupo.funciones.items()}

    def test_fib_recursivo(self):
        fns = self._compilar(
            "funcion fib(n) {\n  si n <= 1 { devuelve n }\n  devuelve fib(n - 1) + fib(n - 2)\n}\n"
        )
        fib = fns["fib"]

        def fib_py(n):
            return n if n <= 1 else fib_py(n - 1) + fib_py(n - 2)

        for n in (0, 1, 2, 5, 10, 20, 25):
            self.assertEqual(fib(n), fib_py(n), f"fib({n}) difiere")

    def test_aritmetica_y_modulo(self):
        fns = self._compilar(
            "funcion cuadrado(x) { devuelve x * x }\n"
            "funcion suma(a, b, c) { devuelve a + b + c }\n"
            "funcion modulo(n) { devuelve n % 3 }\n"
            "funcion resta(x) { devuelve x - 5 }\n"
        )
        self.assertEqual(fns["cuadrado"](7), 49)
        self.assertEqual(fns["cuadrado"](-3), 9)
        self.assertEqual(fns["suma"](1, 2, 3), 6)
        self.assertEqual(fns["modulo"](10), 1)
        self.assertEqual(fns["modulo"](8), 2)
        self.assertEqual(fns["modulo"](9), 0)
        self.assertEqual(fns["resta"](2), -3)

    def test_bucle_mientras(self):
        fns = self._compilar(
            "funcion suma_hasta(n) {\n  variable s = 0\n  variable i = 1\n"
            "  mientras i <= n { s = s + i; i = i + 1 }\n  devuelve s\n}\n"
        )
        self.assertEqual(fns["suma_hasta"](10), 55)
        self.assertEqual(fns["suma_hasta"](100), 5050)
        self.assertEqual(fns["suma_hasta"](0), 0)

    def test_para_y_si(self):
        fns = self._compilar(
            "funcion cuenta(n) {\n  variable t = 0\n  para i en 1..n { t = t + i }\n  devuelve t\n}\n"
            "funcion maximo(a, b) { si a > b { devuelve a }; devuelve b }\n"
        )
        self.assertEqual(fns["cuenta"](10), 55)
        self.assertEqual(fns["cuenta"](5), 15)
        self.assertEqual(fns["maximo"](3, 7), 7)
        self.assertEqual(fns["maximo"](9, 2), 9)

    def test_no_califica_fallback_vm(self):
        from jp.interprete import Interprete
        from jp.nativo import instalar

        # cadenas: no califica para enteros -> nada se instala
        programa = parsear(tokenizar('funcion saluda(n) { devuelve "hola" }\n'))
        grupo = compilar_lote(programa)
        self.assertEqual(grupo.funciones, {})

        # instalar() sobre un programa con strings devuelve 0 y no rompe
        interprete = Interprete()
        programa2 = parsear(tokenizar('funcion f(x) { devuelve x + 1 }\nmuestra(f(41))\n'))
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            instaladas = instalar(programa2, interprete)
            interprete.ejecutar(programa2)
        self.assertEqual(instaladas, 1)
        self.assertIn("42", buffer.getvalue())

    def test_tipos_rechazados_con_mensaje(self):
        fns = self._compilar("funcion doble(x) { devuelve x * 2 }\n")
        with self.assertRaises(Exception) as ctx:
            fns["doble"](1.5)
        self.assertIn("entero", str(ctx.exception))
        with self.assertRaises(Exception):
            fns["doble"](1, 2)  # aridad


if __name__ == "__main__":
    unittest.main()
