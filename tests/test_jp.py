"""Tests del lenguaje JP: lexer, parser, intérprete y programas completos.

Ejecutar con:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from jp.errores import ErrorEjecucion, ErrorLexico, ErrorSintaxis
from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear


def ejecutar(codigo: str) -> str:
    """Ejecuta código JP y captura lo que imprime con muestra()."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        interprete = Interprete()
        programa = parsear(tokenizar(codigo))
        interprete.ejecutar(programa)
    return buffer.getvalue()


class TestAritmetica(unittest.TestCase):
    def test_basica(self):
        self.assertEqual(ejecutar('muestra(1 + 2 * 3)'), "7\n")
        self.assertEqual(ejecutar('muestra(10 / 4)'), "2.5\n")
        self.assertEqual(ejecutar('muestra(10 % 3)'), "1\n")
        self.assertEqual(ejecutar('muestra(-5 + 3)'), "-2\n")

    def test_division_entera_vs_decimal(self):
        self.assertEqual(ejecutar('muestra(10 / 2)'), "5\n")     # exacta -> entero
        self.assertEqual(ejecutar('muestra(7 / 2)'), "3.5\n")    # inexacta -> decimal

    def test_precedencia(self):
        self.assertEqual(ejecutar('muestra(2 + 3 * 4 - 1)'), "13\n")
        self.assertEqual(ejecutar('muestra((2 + 3) * 4)'), "20\n")

    def test_decimales(self):
        self.assertEqual(ejecutar('var p = 2.5\nmuestra(p * 2)'), "5\n")


class TestCadenas(unittest.TestCase):
    def test_concatenacion(self):
        self.assertEqual(ejecutar('muestra("hola" + " " + "mundo")'), "hola mundo\n")

    def test_autoconversion(self):
        self.assertEqual(ejecutar('muestra("n = " + 42)'), "n = 42\n")

    def test_repeticion(self):
        self.assertEqual(ejecutar('muestra("ab" * 3)'), "ababab\n")

    def test_escapes(self):
        self.assertEqual(ejecutar('muestra("a\\tb")'), "a\tb\n")


class TestVariables(unittest.TestCase):
    def test_declaracion_y_asignacion(self):
        self.assertEqual(ejecutar('var x = 10\nx = x + 5\nmuestra(x)'), "15\n")

    def test_sin_inicializador(self):
        self.assertEqual(ejecutar('var x\nmuestra(x)'), "nulo\n")


class TestLogica(unittest.TestCase):
    def test_comparaciones(self):
        self.assertEqual(ejecutar('muestra(1 < 2, 2 <= 2, 3 > 4, 4 >= 4)'), "verdadero verdadero falso verdadero\n")

    def test_igualdad(self):
        self.assertEqual(ejecutar('muestra(1 == 1, 1 != 1, "a" == "a")'), "verdadero falso verdadero\n")

    def test_y_o_no(self):
        self.assertEqual(ejecutar('muestra(1 < 2 y 3 > 2)'), "verdadero\n")
        self.assertEqual(ejecutar('muestra(1 > 2 o 3 > 2)'), "verdadero\n")
        self.assertEqual(ejecutar('muestra(no falso)'), "verdadero\n")

    def test_cortocircuito(self):
        # el lado derecho (división por cero) no debe evaluarse
        self.assertEqual(ejecutar('muestra(verdadero o 1 / 0)'), "verdadero\n")
        self.assertEqual(ejecutar('muestra(falso y 1 / 0)'), "falso\n")


class TestControlFlujo(unittest.TestCase):
    def test_si_sino(self):
        codigo = 'var edad = 20\nsi (edad >= 18) { muestra("adulto") } sino { muestra("menor") }'
        self.assertEqual(ejecutar(codigo), "adulto\n")

    def test_sino_si(self):
        codigo = (
            'var n = 15\n'
            'si (n % 3 == 0 y n % 5 == 0) { muestra("FizzBuzz") }'
            ' sino si (n % 3 == 0) { muestra("Fizz") }'
            ' sino { muestra(n) }'
        )
        self.assertEqual(ejecutar(codigo), "FizzBuzz\n")

    def test_mientras(self):
        codigo = 'var i = 3\nvar t = 0\nmientras (i > 0) { t = t + i\ni = i - 1 }\nmuestra(t)'
        self.assertEqual(ejecutar(codigo), "6\n")

    def test_para_rango(self):
        self.assertEqual(ejecutar('var s = 0\npara (i en rango(1, 5)) { s = s + i }\nmuestra(s)'), "10\n")

    def test_para_lista(self):
        self.assertEqual(ejecutar('para (f en ["a", "b"]) { muestra(f) }'), "a\nb\n")

    def test_para_cadena(self):
        self.assertEqual(ejecutar('para (c en "hola") { muestra(c) }'), "h\no\nl\na\n")

    def test_para_numero(self):
        self.assertEqual(ejecutar('para (i en 3) { muestra(i) }'), "1\n2\n3\n")


class TestFunciones(unittest.TestCase):
    def test_basica(self):
        self.assertEqual(ejecutar('fun sumar(a, b) { retorna a + b }\nmuestra(sumar(2, 3))'), "5\n")

    def test_recursiva(self):
        codigo = 'fun fib(n) { si (n <= 1) { retorna n } retorna fib(n - 1) + fib(n - 2) }\nmuestra(fib(10))'
        self.assertEqual(ejecutar(codigo), "55\n")

    def test_primera_clase(self):
        codigo = (
            'fun duplicar(x) { retorna x * 2 }\n'
            'fun aplicar(f, v) { retorna f(v) }\n'
            'muestra(aplicar(duplicar, 21))'
        )
        self.assertEqual(ejecutar(codigo), "42\n")

    def test_retorno_implicito_nulo(self):
        self.assertEqual(ejecutar('fun nada() { var x = 1 }\nmuestra(nada())'), "nulo\n")

    def test_cierre_lexico(self):
        codigo = (
            'fun exterior() {\n'
            '    var n = 10\n'
            '    fun interior() { retorna n + 1 }\n'
            '    retorna interior()\n'
            '}\n'
            'muestra(exterior())'
        )
        self.assertEqual(ejecutar(codigo), "11\n")


class TestListas(unittest.TestCase):
    def test_indices(self):
        codigo = 'var l = [1, 2, 3]\nmuestra(l[0], l[-1], longitud(l))'
        self.assertEqual(ejecutar(codigo), "1 3 3\n")

    def test_concatenacion(self):
        self.assertEqual(ejecutar('muestra([1, 2] + [3])'), "[1, 2, 3]\n")

    def test_anidadas(self):
        self.assertEqual(ejecutar('muestra([[1, 2], [3]])'), "[[1, 2], [3]]\n")


class TestSintaxisFacil(unittest.TestCase):
    """La versión fácil: sin paréntesis, sin llaves de una línea, palabras en español."""

    def test_si_sin_parentesis(self):
        self.assertEqual(ejecutar('var edad = 20\nsi edad >= 18 { muestra("mayor") }'), "mayor\n")

    def test_llaves_de_una_linea_sin_dos_puntos(self):
        self.assertEqual(ejecutar('var x = 5\nsi x > 0 { muestra("positivo") }'), "positivo\n")

    def test_dos_puntos_una_sentencia(self):
        self.assertEqual(ejecutar('si 1 < 2: muestra("hola")'), "hola\n")
        self.assertEqual(ejecutar('var i = 0\nmientras i < 3: i = i + 1\nmuestra(i)'), "3\n")

    def test_para_sin_parentesis(self):
        self.assertEqual(ejecutar('para i en 1..3 { muestra(i) }'), "1\n2\n3\n")
        self.assertEqual(ejecutar('para f en ["a", "b"]: muestra(f)'), "a\nb\n")

    def test_rango_inclusivo(self):
        # 1..5 es inclusivo (a diferencia de rango() que es exclusivo)
        self.assertEqual(ejecutar('var s = 0\npara i en 1..5 { s = s + i }\nmuestra(s)'), "15\n")
        # y al revés también
        self.assertEqual(ejecutar('para i en 3..1 { muestra(i) }'), "3\n2\n1\n")

    def test_comillas_simples(self):
        self.assertEqual(ejecutar("imprime('hola')"), "hola\n")
        self.assertEqual(ejecutar("imprime('dice que \"sí\"')"), 'dice que "sí"\n')

    def test_alias_de_palabras(self):
        codigo = (
            'variable saludo = "hola"\n'
            'funcion decir(x) { devuelve x }\n'
            'imprime(decir(saludo))'
        )
        self.assertEqual(ejecutar(codigo), "hola\n")

    def test_si_sino_facil(self):
        codigo = (
            'variable edad = 15\n'
            'si edad >= 18: imprime("adulto")\n'
            'sino si edad >= 13: imprime("adolescente")\n'
            'sino: imprime("niño")'
        )
        self.assertEqual(ejecutar(codigo), "adolescente\n")

    def test_funcion_retorna(self):
        codigo = 'funcion doble(n) { devuelve n * 2 }\nimprime(doble(21))'
        self.assertEqual(ejecutar(codigo), "42\n")

    def test_mientras_facil(self):
        codigo = 'variable n = 3\nmientras n > 0: n = n - 1\nimprime(n)'
        self.assertEqual(ejecutar(codigo), "0\n")


class TestAmbitos(unittest.TestCase):
    def test_bloque_crea_ambito(self):
        codigo = 'si (verdadero) { var secreta = 42 }\nmuestra(secreta)'
        with self.assertRaises(ErrorEjecucion):
            ejecutar(codigo)

    def test_variable_global_visible_en_funcion(self):
        codigo = 'var g = 5\nfun f() { retorna g }\nmuestra(f())'
        self.assertEqual(ejecutar(codigo), "5\n")


class TestNativas(unittest.TestCase):
    def test_entero_y_numero(self):
        self.assertEqual(ejecutar('muestra(entero("42"), entero(3.9))'), "42 3\n")
        self.assertEqual(ejecutar('muestra(numero("2.5"))'), "2.5\n")

    def test_texto(self):
        self.assertEqual(ejecutar('muestra(texto(123) + "!")'), "123!\n")

    def test_rango_1_2_3_args(self):
        self.assertEqual(ejecutar('muestra(rango(3))'), "[0, 1, 2]\n")
        self.assertEqual(ejecutar('muestra(rango(1, 4))'), "[1, 2, 3]\n")
        self.assertEqual(ejecutar('muestra(rango(0, 10, 3))'), "[0, 3, 6, 9]\n")

    def test_muestra_varios_valores(self):
        self.assertEqual(ejecutar('muestra(1, "dos", verdadero)'), "1 dos verdadero\n")

    def test_azar(self):
        # 50 tiradas de azar(6) siempre suman entre 50 y 300 (determinista)
        codigo = 'variable s = 0\npara i en 1..50 { s = s + azar(6) }\nimprime(s >= 50 y s <= 300)'
        self.assertEqual(ejecutar(codigo), "verdadero\n")
        self.assertEqual(ejecutar('imprime(azar(1))'), "1\n")

    def test_leer(self):
        import io
        import builtins
        original = builtins.input
        builtins.input = lambda prompt="": (print(prompt, end=""), "42")[1]
        try:
            # input() imprime su prompt: por eso la salida incluye "dime: "
            self.assertEqual(ejecutar('imprime(entero(leer("dime: ")))'), "dime: 42\n")
        finally:
            builtins.input = original


class TestErrores(unittest.TestCase):
    def test_variable_no_definida(self):
        with self.assertRaises(ErrorEjecucion):
            ejecutar('muestra(no_existo)')

    def test_division_por_cero(self):
        with self.assertRaises(ErrorEjecucion):
            ejecutar('var x = 1 / 0')

    def test_caracter_no_reconocido(self):
        with self.assertRaises(ErrorLexico):
            ejecutar('var x = 1 ? 2')

    def test_cadena_sin_cerrar(self):
        with self.assertRaises(ErrorLexico):
            ejecutar('muestra("ups')

    def test_sintaxis_falta_parentesis(self):
        with self.assertRaises(ErrorSintaxis):
            ejecutar('si (verdadero { muestra(1) }')

    def test_llamar_a_no_funcion(self):
        with self.assertRaises(ErrorEjecucion):
            ejecutar('var x = 5\nx(1)')

    def test_indice_fuera_de_rango(self):
        with self.assertRaises(ErrorEjecucion):
            ejecutar('var l = [1]\nmuestra(l[5])')

    def test_formato_bonito(self):
        error = ErrorSintaxis("prueba", linea=1, columna=3)
        formateado = error.formatear('var x = ;')
        self.assertIn("--> línea 1", formateado)
        self.assertIn("^", formateado)


class TestProgramasCompletos(unittest.TestCase):
    def test_fizzbuzz(self):
        codigo = (
            'para (i en rango(1, 16)) {\n'
            '    si (i % 15 == 0) { muestra("FizzBuzz") }'
            ' sino si (i % 3 == 0) { muestra("Fizz") }'
            ' sino si (i % 5 == 0) { muestra("Buzz") }'
            ' sino { muestra(i) }\n'
            '}\n'
        )
        lineas = ejecutar(codigo).strip().splitlines()
        self.assertEqual(lineas[0], "1")
        self.assertEqual(lineas[2], "Fizz")      # i=3
        self.assertEqual(lineas[4], "Buzz")      # i=5
        self.assertEqual(lineas[14], "FizzBuzz") # i=15
        self.assertEqual(len(lineas), 15)

    def test_fibonacci_15(self):
        codigo = 'fun fib(n) { si (n <= 1) { retorna n } retorna fib(n - 1) + fib(n - 2) }\nmuestra(fib(15))'
        self.assertEqual(ejecutar(codigo), "610\n")

    def test_suma_digitos(self):
        codigo = (
            'var n = 9876\n'
            'var suma = 0\n'
            'mientras (n > 0) { suma = suma + n % 10\nn = entero(n / 10) }\n'
            'muestra(suma)'
        )
        self.assertEqual(ejecutar(codigo), "30\n")


class TestDiccionarios(unittest.TestCase):
    def test_literal_y_acceso(self):
        codigo = 'variable d = {nombre: "JP", version: 3}\nimprime(d.nombre, d["version"])'
        self.assertEqual(ejecutar(codigo), "JP 3\n")

    def test_claves_con_comillas(self):
        self.assertEqual(ejecutar('variable d = {"a b": 7}\nimprime(d["a b"])'), "7\n")

    def test_asignar_clave(self):
        codigo = 'variable d = {}\nd.nueva = 5\nd["otra"] = 2\nimprime(d.nueva, d.otra)'
        self.assertEqual(ejecutar(codigo), "5 2\n")

    def test_clave_inexistente(self):
        with self.assertRaises(ErrorEjecucion) as ctx:
            ejecutar('variable d = {a: 1}\nimprime(d.falta)')
        self.assertIn("no existe la clave", str(ctx.exception))

    def test_claves_y_tiene(self):
        codigo = 'variable d = {x: 1, y: 2}\nimprime(claves(d), tiene(d, "x"), tiene(d, "z"))'
        self.assertEqual(ejecutar(codigo), '["x", "y"] verdadero falso\n')

    def test_iterar_diccionario(self):
        codigo = 'variable d = {a: 1, b: 2}\nvariable suma = ""\npara k en d { suma = suma + k }\nimprime(suma)'
        self.assertEqual(ejecutar(codigo), "ab\n")

    def test_anidados(self):
        codigo = 'variable d = {persona: {nombre: "Ana"}}\nimprime(d.persona.nombre)'
        self.assertEqual(ejecutar(codigo), "Ana\n")

    def test_longitud_dict(self):
        self.assertEqual(ejecutar('imprime(longitud({a: 1, b: 2}))'), "2\n")

    def test_asignar_elemento_lista(self):
        self.assertEqual(ejecutar('variable l = [1, 2]\nl[0] = 9\nimprime(l)'), "[9, 2]\n")


class TestJSONYRed(unittest.TestCase):
    def test_json_leer(self):
        codigo = 'variable d = json_leer(\'{"a": [1, 2], "ok": true}\')\nimprime(d.ok, d.a[1])'
        self.assertEqual(ejecutar(codigo), "verdadero 2\n")

    def test_json_texto(self):
        self.assertEqual(ejecutar('imprime(json_texto({a: 1}))'), '{"a": 1}\n')

    def test_json_ida_y_vuelta(self):
        codigo = 'variable original = {lista: [1, 2]}\nvariable vuelta = json_leer(json_texto(original))\nimprime(vuelta.lista[1])'
        self.assertEqual(ejecutar(codigo), "2\n")

    def test_json_invalido(self):
        with self.assertRaises(ErrorEjecucion):
            ejecutar('imprime(json_leer("esto no es json"))')

    def test_http_get_simulado(self):
        with mock.patch("jp.red._http_get", return_value='{"hola": 42}'):
            self.assertEqual(ejecutar('imprime(json_leer(http_get("https://x.test"))["hola"])'), "42\n")

    def test_http_post_dict_a_json(self):
        with mock.patch("jp.red._http_post", return_value='{"ok": true}') as post:
            self.assertEqual(ejecutar('imprime(http_post("https://x.test", {content: "hola"}))'), '{"ok": true}\n')
            url, cuerpo, tipo = post.call_args[0]
            self.assertEqual(url, "https://x.test")
            self.assertEqual(json.loads(cuerpo), {"content": "hola"})
            self.assertIn("application/json", tipo)

    def test_http_error_conectado(self):
        import urllib.error
        with mock.patch("jp.red._http_get", side_effect=urllib.error.URLError("sin red")):
            with self.assertRaises(ErrorEjecucion):
                ejecutar('imprime(http_get("https://nunca.test"))')

    def test_telegram_leer(self):
        respuesta = json.dumps({"ok": True, "result": [
            {"update_id": 10, "message": {"chat": {"id": 777}, "text": "hola jp"}}
        ]})
        with mock.patch("jp.red._http_get", return_value=respuesta):
            codigo = 'variable msjs = telegram_leer("TOKEN")\npara m en msjs { imprime(m.de, ":", m.texto) }'
            self.assertEqual(ejecutar(codigo), "777 : hola jp\n")

    def test_telegram_responder(self):
        with mock.patch("jp.red._http_post", return_value='{"ok": true}') as post:
            self.assertEqual(
                ejecutar('imprime(telegram_responder("TOKEN", 777, "¡hola!"))'),
                "verdadero\n",
            )
            url, cuerpo, tipo = post.call_args[0]
            self.assertIn("sendMessage", url)
            self.assertEqual(json.loads(cuerpo), {"chat_id": 777, "text": "¡hola!"})

    def test_telegram_token_invalido(self):
        respuesta = json.dumps({"ok": False, "description": "Unauthorized"})
        with mock.patch("jp.red._http_get", return_value=respuesta):
            with self.assertRaises(ErrorEjecucion) as ctx:
                ejecutar('imprime(telegram_leer("MALO"))')
        self.assertIn("Unauthorized", str(ctx.exception))

    def test_esperar(self):
        self.assertEqual(ejecutar('esperar(0)\nimprime("ok")'), "ok\n")


class TestInterpolacion(unittest.TestCase):
    def test_basica(self):
        self.assertEqual(ejecutar('variable n = "mundo"\nmuestra("hola {n}!")'), "hola mundo!\n")

    def test_expresiones(self):
        self.assertEqual(ejecutar('variable e = 25\nmuestra("{e} + 10 = {e + 10}")'), "25 + 10 = 35\n")
        self.assertEqual(ejecutar('muestra("{2 * 3 + 1}")'), "7\n")

    def test_varias_y_adheridas(self):
        self.assertEqual(ejecutar('muestra("{1}{2}{3}")'), "123\n")
        self.assertEqual(ejecutar('variable a = "x"\nmuestra("{a}-{a}")'), "x-x\n")

    def test_formato_como_muestra(self):
        # los valores se convierten igual que muestra(): verdadero/falso, etc.
        self.assertEqual(ejecutar('muestra("v={verdadero} n={nulo}")'), "v=verdadero n=nulo\n")
        self.assertEqual(ejecutar('muestra("{1 / 2}")'), "0.5\n")

    def test_escape_de_llaves(self):
        self.assertEqual(ejecutar('muestra("escape: \\{no interpola}")'), "escape: {no interpola}\n")

    def test_simples_no_interpolan(self):
        self.assertEqual(ejecutar('variable n = "mundo"\nmuestra(\'hola {n}\')'), "hola {n}\n")

    def test_con_indices_y_llamadas(self):
        self.assertEqual(
            ejecutar('variable d = {nombre: "Ana"}\nmuestra("hola {d.nombre}!")'),
            "hola Ana!\n",
        )
        self.assertEqual(
            ejecutar('funcion doble(x) { devuelve x * 2 }\nmuestra("doble = {doble(21)}")'),
            "doble = 42\n",
        )

    def test_errores(self):
        with self.assertRaises(ErrorLexico):
            ejecutar('muestra("sin cerrar {n")')
        with self.assertRaises(ErrorLexico):
            ejecutar('muestra("vacio {}")')


class TestOptimizaciones(unittest.TestCase):
    def test_plegado_de_constantes(self):
        from jp.arbol import NodoBinario, NodoNumero
        from jp.lexer import tokenizar as tok
        from jp.parser import parsear as par

        programa = par(tok("variable x = 2 + 3 * 4"))
        inicializador = programa.sentencias[0].inicializador
        self.assertNotIsInstance(inicializador, NodoBinario)  # ya plegado
        self.assertIsInstance(inicializador, NodoNumero)
        self.assertEqual(inicializador.valor, 14)

    def test_plegado_cadenas(self):
        from jp.arbol import NodoCadena
        from jp.lexer import tokenizar as tok
        from jp.parser import parsear as par

        programa = par(tok('variable s = "a" + "b"'))
        self.assertIsInstance(programa.sentencias[0].inicializador, NodoCadena)

    def test_plegado_no_oculta_division_por_cero(self):
        # 1/0 NO se pliega en el parseo: debe seguir fallando en ejecución
        with self.assertRaises(ErrorEjecucion):
            ejecutar('imprime(1 / 0)')


class TestRomperContinuar(unittest.TestCase):
    def test_romper_mientras(self):
        self.assertEqual(
            ejecutar('variable i = 0\nmientras verdadero {\n  i = i + 1\n  si i == 3 { romper }\n}\nmuestra(i)'),
            "3\n",
        )

    def test_continuar_mientras(self):
        self.assertEqual(
            ejecutar('variable s = 0\nmientras i := 0 is None:\n  continuar'),
            "",
        ) if False else None
        codigo = ('variable s = 0\nvariable i = 0\nmientras i < 10 {\n'
                  '  i = i + 1\n  si i % 2 == 0 { continuar }\n  s = s + i\n}\nmuestra(s)')
        self.assertEqual(ejecutar(codigo), "25\n")

    def test_romper_para(self):
        self.assertEqual(
            ejecutar('variable x = 0\npara i en 1..10 {\n  si i == 4 { romper }\n  x = x + i\n}\nmuestra(x)'),
            "6\n",
        )

    def test_continuar_para(self):
        self.assertEqual(
            ejecutar('variable s = 0\npara i en 1..10 {\n  si i % 2 == 0 { continuar }\n  s = s + i\n}\nmuestra(s)'),
            "25\n",
        )

    def test_romper_solo_el_interno(self):
        self.assertEqual(
            ejecutar('variable n = 0\npara i en 1..3 {\n  para j en 1..3 {\n    si j == 2 { romper }\n  }\n  n = n + 1\n}\nmuestra(n)'),
            "3\n",
        )

    def test_romper_cierra_ambito_de_si(self):
        self.assertEqual(
            ejecutar('variable i = 0\nmientras verdadero {\n  variable zona = i\n  i = i + 1\n  si zona == 2 { romper }\n}\nmuestra(i)'),
            "3\n",
        )

    def test_romper_fuera_de_bucle(self):
        with self.assertRaises(ErrorEjecucion) as ctx:
            ejecutar('romper')
        self.assertIn("fuera de un bucle", str(ctx.exception))

    def test_continuar_fuera_de_bucle(self):
        with self.assertRaises(ErrorEjecucion) as ctx:
            ejecutar('continuar')
        self.assertIn("fuera de un bucle", str(ctx.exception))

    def test_romper_en_funcion_no_escapa(self):
        with self.assertRaises(ErrorEjecucion) as ctx:
            ejecutar('funcion f() { romper }\nmientras verdadero { f() }')
        self.assertIn("fuera de un bucle", str(ctx.exception))


class TestTexto(unittest.TestCase):
    def test_basicas(self):
        self.assertEqual(ejecutar('muestra(mayusculas("hola"))'), "HOLA\n")
        self.assertEqual(ejecutar('muestra(minusculas("HOLA"))'), "hola\n")
        self.assertEqual(ejecutar('muestra(recortar("  hola  "))'), "hola\n")

    def test_separar_unir(self):
        self.assertEqual(ejecutar('muestra(separar("a,b,c", ","))'), '["a", "b", "c"]\n')
        self.assertEqual(ejecutar('muestra(unir(["x", "y"], "-"))'), "x-y\n")
        self.assertEqual(ejecutar('muestra(longitud(separar("uno dos tres")))'), "3\n")

    def test_contiene_reemplazar(self):
        self.assertEqual(ejecutar('muestra(contiene("hola", "ol"))'), "verdadero\n")
        self.assertEqual(ejecutar('muestra(contiene([1, 2], 2))'), "verdadero\n")
        self.assertEqual(ejecutar('muestra(reemplazar("gato", "g", "p"))'), "pato\n")

    def test_subtexto_y_letra(self):
        self.assertEqual(ejecutar('muestra(subtexto("JP lenguaje", 0, 2))'), "JP\n")
        self.assertEqual(ejecutar('muestra(letra("hola", 1))'), "o\n")
        self.assertEqual(ejecutar('muestra(letra("hola", -1))'), "a\n")

    def test_errores_de_tipo(self):
        with self.assertRaises(ErrorEjecucion):
            ejecutar('muestra(mayusculas(5))')
        with self.assertRaises(ErrorEjecucion):
            ejecutar('muestra(letra("hola", 99))')

    def test_reloj_monotonico(self):
        # reloj() da segundos crecientes (con margen generoso por el GIL)
        salida = ejecutar('variable a = reloj()\nmuestra(reloj() >= a)')
        self.assertEqual(salida, "verdadero\n")

    def test_agregar(self):
        self.assertEqual(ejecutar('variable l = []\nagregar(l, 1)\nagregar(l, 2)\nmuestra(l)'), "[1, 2]\n")
        self.assertEqual(ejecutar('muestra(longitud(agregar(agregar([], "a"), "b")))'), "2\n")
        with self.assertRaises(ErrorEjecucion):
            ejecutar('agregar("no soy lista", 1)')


class TestArchivos(unittest.TestCase):
    RUTA = "/tmp/jp_test_archivos.txt"

    def tearDown(self):
        import os

        if os.path.exists(self.RUTA):
            os.remove(self.RUTA)

    def test_ciclo_completo(self):
        codigo = (
            f'escribir_archivo("{self.RUTA}", "linea 1\\n")\n'
            f'agregar_archivo("{self.RUTA}", "linea 2\\n")\n'
            f'muestra(leer_archivo("{self.RUTA}"))\n'
            f'muestra(existe_archivo("{self.RUTA}"))\n'
        )
        self.assertEqual(ejecutar(codigo), "linea 1\nlinea 2\n\nverdadero\n")

    def test_leer_inexistente(self):
        with self.assertRaises(ErrorEjecucion) as ctx:
            ejecutar('leer_archivo("/tmp/jp_no_existe_seguro_xyz.txt")')
        self.assertIn("no existe el archivo", str(ctx.exception))

    def test_tamano_y_existe(self):
        codigo = (
            f'escribir_archivo("{self.RUTA}", "12345")\n'
            f'muestra(tamano_archivo("{self.RUTA}"))\n'
            f'muestra(existe_archivo("{self.RUTA}"), existe_archivo("/tmp/jp_nada_xyz"))\n'
        )
        self.assertEqual(ejecutar(codigo), "5\nverdadero falso\n")


class TestMetodosValor(unittest.TestCase):
    """Métodos sobre valores: "texto".mayusculas(), [1, 2].agregar(3), d.claves()."""

    def test_texto(self):
        self.assertEqual(ejecutar('muestra("hola".mayusculas())'), "HOLA\n")
        self.assertEqual(ejecutar('muestra("ADIOS".minusculas())'), "adios\n")
        self.assertEqual(ejecutar('muestra("  hola  ".recortar())'), "hola\n")
        self.assertEqual(ejecutar('muestra("a,b,c".separar(","))'), '["a", "b", "c"]\n')
        self.assertEqual(ejecutar('muestra("a b c".separar())'), '["a", "b", "c"]\n')
        self.assertEqual(ejecutar('muestra("banana".reemplazar("na", "NA"))'), "baNANA\n")
        self.assertEqual(ejecutar('muestra("banana".subtexto(1, 3))'), "an\n")
        self.assertEqual(ejecutar('muestra("banana".subtexto(2))'), "nana\n")
        self.assertEqual(ejecutar('muestra("banana".letra(0))'), "b\n")
        self.assertEqual(ejecutar('muestra("banana".letra(-1))'), "a\n")
        self.assertEqual(ejecutar('muestra("hola".contiene("ol"))'), "verdadero\n")
        self.assertEqual(ejecutar('muestra("hola".contiene("z"))'), "falso\n")

    def test_texto_en_variables(self):
        self.assertEqual(ejecutar('variable t = "hola"\nmuestra(t.mayusculas())'), "HOLA\n")

    def test_listas(self):
        self.assertEqual(ejecutar('variable l = [1, 2]\nl.agregar(3)\nmuestra(l)'), "[1, 2, 3]\n")
        self.assertEqual(ejecutar('muestra([1, 2, 3].longitud())'), "3\n")
        self.assertEqual(ejecutar('muestra([1, 2].contiene(2))'), "verdadero\n")
        self.assertEqual(ejecutar('muestra("cadena".longitud())'), "6\n")

    def test_diccionarios(self):
        self.assertEqual(ejecutar('variable d = {a: 1, b: 2}\nmuestra(d.claves())'), '["a", "b"]\n')
        self.assertEqual(ejecutar('muestra({a: 1}.tiene("a"))'), "verdadero\n")
        self.assertEqual(ejecutar('muestra({a: 1}.tiene("b"))'), "falso\n")

    def test_clave_gana_sobre_metodo(self):
        self.assertEqual(ejecutar('variable d = {claves: 99}\nmuestra(d.claves)'), "99\n")

    def test_metodos_sobre_expresiones(self):
        self.assertEqual(ejecutar('muestra(("h" + "ola").mayusculas())'), "HOLA\n")
        self.assertEqual(ejecutar('muestra("hola mundo".separar()[0])'), "hola\n")

    def test_metodo_inexistente(self):
        with self.assertRaises(ErrorEjecucion) as ctx:
            ejecutar('"hola".falta()')
        self.assertIn("no existe el método 'falta' para texto", str(ctx.exception))
        with self.assertRaises(ErrorEjecucion):
            ejecutar('[1].falta()')
        with self.assertRaises(ErrorEjecucion):
            ejecutar('"hola".falta')


if __name__ == "__main__":
    unittest.main()
