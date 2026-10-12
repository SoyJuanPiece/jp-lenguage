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
    "elegir, intenta y diccionarios": """
        funcion clasificar(n) {
            elegir n {
                caso 0: devuelve "cero"
                caso 1, 2: devuelve "pocos"
                sino: devuelve "muchos"
            }
        }
        imprime(clasificar(0), clasificar(2), clasificar(9))

        funcion dividir(a, b) {
            intenta {
                devuelve a / b
            } atrapa error {
                devuelve "error: " + error
            }
        }
        imprime(dividir(10, 2))
        imprime(dividir(10, 0))

        variable persona = {nombre: "Ana", edad: 30}
        imprime(persona, persona.nombre, persona["edad"], longitud(persona))
        persona.edad = 31
        persona["ciudad"] = "Maturín"
        imprime(persona, claves(persona), valores(persona), tiene(persona, "nombre"))
        para clave en persona { imprime(clave, persona[clave]) }
        variable vacio = {}
        imprime(vacio, longitud(vacio), tiene(vacio, "x"))
        intenta {
            imprime(persona["no-existe"])
        } atrapa e {
            imprime("atrapado:", e)
        }
    """,
    "orden superior y métodos": """
        funcion doble(x) { devuelve x * 2 }
        funcion par(x) { devuelve x % 2 == 0 }
        funcion suma(a, b) { devuelve a + b }
        variable numeros = [5, 1, 4, 2, 3]
        imprime(mapear(numeros, doble), filtrar(numeros, par))
        imprime(reducir(numeros, suma), reducir(numeros, suma, 100))
        imprime(ordenar(numeros), ordenar(numeros, funcion(x) { devuelve 0 - x }))
        imprime(ordenar(["b", "c", "a"]), numeros)
        para_cada([1, 2], funcion(x) { imprime("cada", x) })
        imprime(mapear("abc", funcion(x) { devuelve mayusculas(x) }))
        imprime(mapear(3, doble), filtrar([1, 2, 3, 4], par))
        imprime(reducir({a: 1, b: 2}, suma, 0))
        imprime([3, 1, 2].ordenar(), [1, 2, 3].invertir(), [1, 2].longitud())
        imprime("jp".mayusculas(), "  hola  ".recortar(), "a,b,c".separar(","))
        imprime("hola".letra(1), "hola".subtexto(1, 3), "hola".contiene("ol"))
        imprime({x: 1, y: 2}.claves(), {x: 1}.tiene("x"), {x: 1}.valores())
        intenta {
            imprime(mapear([1, 2], 5))
        } atrapa e {
            imprime("no es función:", e)
        }
        intenta {
            funcion revienta(x) { devuelve 1 / x }
            imprime(mapear([1, 0], revienta))
        } atrapa e {
            imprime("mapeo falló:", contiene(e, "división"))
        }
        funcion seguro(x) { intenta { devuelve 1 / x } atrapa e { devuelve "cero" } }
        imprime(mapear([1, 0, 2], seguro))
        intenta {
            imprime(ordenar([1, "a"]))
        } atrapa e {
            imprime("orden raro:", contiene(e, "no puede comparar"))
        }
    """,
    "cierres y parámetros capturados": """
        funcion multiplicador(n) { devuelve funcion(x) { devuelve x * n } }
        variable triple = multiplicador(3)
        imprime(triple(7), multiplicador(10)(4), multiplicador(0 - 2)(5))
        funcion contador() {
            variable total = 0
            devuelve funcion() {
                total = total + 1
                devuelve total
            }
        }
        variable c1 = contador()
        variable c2 = contador()
        imprime(c1(), c1(), c1(), c2())
        funcion escala(factor) { devuelve funcion(uno) { devuelve funcion(dos) { devuelve factor * uno * dos } } }
        imprime(escala(2)(3)(4))
        variable base = 100
        imprime(mapear([1, 2, 3], funcion(x) { devuelve base + x }))
        funcion sumador(a) { devuelve funcion(b) { devuelve a + b } }
        imprime(reducir([sumador(1), sumador(2)], funcion(f, g) { devuelve f(10) + g(10) }))
        funcion con_estado(inicio) {
            devuelve funcion(paso) {
                inicio = inicio + paso
                devuelve inicio
            }
        }
        variable avanza = con_estado(10)
        imprime(avanza(5), avanza(5))
        variable contador_directo = funcion() {
            variable cuenta = 0
            funcion sube() { cuenta = cuenta + 1; devuelve cuenta }
            devuelve sube
        }
        variable s = contador_directo()
        imprime(s(), s(), s())
    """,
    "archivos y JSON": """
        imprime(existe_archivo("ejemplos/hola.jp"), existe_archivo("no-existe.txt"))
        variable texto = leer_archivo("ejemplos/fizzbuzz.jp")
        imprime(longitud(texto) > 0, tamano_archivo("ejemplos/hola.jp") > 0)
        imprime(tamano_archivo("no-existe.txt"))
        variable datos = json_leer('{"ok": true, "n": 3, "lista": [1, 2.5, "x"], "nada": null}')
        imprime(datos.ok, datos["n"], datos.lista, datos.lista[1], datos.nada)
        imprime(json_texto(datos))
        imprime(json_texto([1, "dos", verdadero, nulo]), json_texto({a: 1, b: [2, 3]}))
        imprime(json_leer(json_texto({texto: "áéíóú"})).texto)
        imprime(contiene(lista_archivos("ejemplos"), "hola.jp"))
        intenta {
            json_leer('{roto')
        } atrapa e {
            imprime("json malo:", contiene(e, "válido"))
        }
        intenta {
            leer_archivo("no-existe-de-verdad.txt")
        } atrapa e {
            imprime("archivo malo:", contiene(e, "no existe"))
        }
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
            'imprime(100000000000000000000)',                   # entero > 64 bits
            'imprime(http_get("http://ejemplo"))',              # nativa de red
            'imprime(telegram_leer("token"))',                  # nativa de bots
            'imprime(telegram_responder("t", 1, "hola"))',      # nativa de bots
        ]
        for fuente in casos:
            with self.subTest(fuente=fuente):
                with self.assertRaises(NoSoportadoNativo):
                    compilar_a_bytes(parsear(tokenizar(fuente)), "<test>", fuente)

    def test_las_nativas_del_motor_no_se_desincronizan(self) -> None:
        """NATIVAS_EN_C se lee de jpvm.c: si el motor gana una nativa, se ve aquí."""
        import re

        from jp.compilar_nativo import NATIVAS_EN_C

        fuente = (RAIZ / "motor-c" / "jpvm.c").read_text(encoding="utf-8")
        en_el_motor = set(re.findall(r'instalar_nativa\("([a-z_]+)"', fuente))
        self.assertTrue(en_el_motor, "no se encontró ningún instalar_nativa en jpvm.c")
        self.assertEqual(en_el_motor, set(NATIVAS_EN_C))

    def test_los_ejemplos_se_compilan_o_se_rechazan_con_limpieza(self) -> None:
        """Ningún ejemplo puede romper el compilador nativo de otra forma."""
        for ruta in sorted((RAIZ / "ejemplos").glob("*.jp")):
            with self.subTest(ejemplo=ruta.name):
                fuente = ruta.read_text(encoding="utf-8")
                try:
                    compilar_a_bytes(parsear(tokenizar(fuente)), str(ruta), fuente)
                except NoSoportadoNativo:
                    pass  # caída limpia: el CLI sigue con el motor de Python

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
    """Los ejemplos que el motor nativo ya soporta dan la misma salida exacta.

    Se comparan las tres cosas: stdout, stderr y el código de salida. Un
    ejemplo solo entra en la lista cuando se comprueba que coincide.
    """

    SOPORTADOS = ["hola.jp", "fizzbuzz.jp", "fibonacci.jp", "primos.jp",
                  "tabla-multiplicar.jp", "benchmark.jp", "agenda.jp",
                  "seguro.jp", "calculadora.jp", "api-json.jp", "listas.jp",
                  "estadisticas.jp"]

    def _python(self, ruta: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "jp", str(ruta)],
            capture_output=True, text=True, input="", timeout=300, cwd=str(RAIZ),
        )

    def _nativo(self, ruta: Path) -> subprocess.CompletedProcess:
        fuente = ruta.read_text(encoding="utf-8")
        blob = compilar_a_bytes(parsear(tokenizar(fuente)), str(ruta), fuente)
        with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
            archivo.write(blob)
            ruta_jpb = archivo.name
        return subprocess.run(
            [str(MOTOR), ruta_jpb],
            capture_output=True, text=True, input="", timeout=300, cwd=str(RAIZ),
        )

    def test_ejemplos_soportados(self) -> None:
        for nombre in self.SOPORTADOS:
            ruta = RAIZ / "ejemplos" / nombre
            if not ruta.exists():
                continue
            with self.subTest(ejemplo=nombre):
                fuente = ruta.read_text(encoding="utf-8")
                try:
                    compilar_a_bytes(parsear(tokenizar(fuente)), str(ruta), fuente)
                except NoSoportadoNativo as error:
                    self.skipTest(f"{nombre}: aún no soportado ({error.que})")
                esperado = self._python(ruta)
                obtenido = self._nativo(ruta)
                self.assertEqual(obtenido.stdout, esperado.stdout, f"{nombre}: stdout distinto")
                self.assertEqual(obtenido.stderr, esperado.stderr, f"{nombre}: stderr distinto")
                self.assertEqual(obtenido.returncode, esperado.returncode,
                                 f"{nombre}: código de salida distinto")


if __name__ == "__main__":
    unittest.main()
