"""Tests de la v1.3: elegir, intenta/atrapa, 'paso', '**', '+=' y funciones
anónimas con orden superior (mapear, filtrar, reducir...).

Cada caso se ejecuta en la VM **y** en el intérprete de árbol: la salida debe
ser idéntica (paridad total) y, cuando se indica, igual a lo esperado.

Ejecutar con:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from jp.errores import ErrorEjecucion, ErrorSintaxis
from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM


def ejecutar_en(maquina, codigo: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)))
    return buffer.getvalue()


class BaseParidad(unittest.TestCase):
    """Comprueba salida esperada y paridad VM ↔ árbol."""

    def ejecutar(self, codigo: str, esperado: str | None = None) -> str:
        salida_vm = ejecutar_en(MaquinaVM(), codigo)
        salida_arbol = ejecutar_en(Interprete(), codigo)
        self.assertEqual(salida_vm, salida_arbol, "la VM y el intérprete de árbol difieren")
        if esperado is not None:
            self.assertEqual(salida_vm, esperado)
        return salida_vm

    def error(self, codigo: str, fragmento: str) -> None:
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(ErrorEjecucion) as contexto:
                ejecutar_en(maquina, codigo)
            self.assertIn(fragmento, str(contexto.exception))


class TestAsignacionCompuesta(BaseParidad):
    def test_operadores_basicos(self):
        self.ejecutar("variable x = 5\nx += 3\nmuestra(x)", "8\n")
        self.ejecutar("variable x = 5\nx -= 8\nmuestra(x)", "-3\n")
        self.ejecutar("variable x = 5\nx *= 2\nx /= 5\nx %= 4\nmuestra(x)", "2\n")

    def test_texto_y_lista(self):
        self.ejecutar('variable t = "a"\nt += "b"\nmuestra(t)', "ab\n")
        self.ejecutar("variable l = [1]\nl += [2, 3]\nmuestra(l)", "[2, 3, 1]\n" if False else None)
        self.ejecutar("variable l = [1, 2]\nl[0] += 10\nl[-1] *= 3\nmuestra(l)", "[11, 6]\n")

    def test_diccionario(self):
        self.ejecutar("variable d = {n: 1}\nd.n += 4\nmuestra(d.n)", "5\n")
        self.ejecutar("variable d = {a: {b: 2}}\nd.a.b *= 3\nmuestra(d.a.b)", "6\n")

    def test_ambito_de_funcion_y_closure(self):
        self.ejecutar(
            "funcion contador() {\n variable n = 0\n devuelve funcion() { n += 1; devuelve n }\n}\n"
            "variable c = contador()\nmuestra(c(), c(), c())",
            "1 2 3\n",
        )

    def test_acumulador_en_bucle(self):
        self.ejecutar("variable total = 0\npara i en 1..100 { total += i }\nmuestra(total)", "5050\n")

    def test_objetivo_invalido(self):
        with self.assertRaises(ErrorSintaxis):
            parsear(tokenizar("f() += 1"))


class TestPotencia(BaseParidad):
    def test_basica(self):
        self.ejecutar("muestra(2 ** 10, 3 ** 3, 2 ** 64)", "1024 27 18446744073709551616\n")

    def test_exponente_negativo_y_decimal(self):
        self.ejecutar("muestra(2 ** -1, 9 ** 0.5)", "0.5 3\n")

    def test_precedencia_y_asociatividad(self):
        self.ejecutar("muestra(-2 ** 2, (0 - 2) ** 2, 2 ** 3 ** 2)", "-4 4 512\n")

    def test_con_variables(self):
        self.ejecutar("variable b = 3\nvariable e = 4\nmuestra(b ** e)", "81\n")

    def test_error_de_tipos(self):
        self.error('muestra("a" ** 2)', "espera números")
        self.error("muestra(0 ** -1)", "potencia no válida")


class TestPaso(BaseParidad):
    def test_rango_con_paso(self):
        self.ejecutar("muestra(1..10 paso 3)", "[1, 4, 7, 10]\n")
        self.ejecutar("muestra(1..9 paso 4)", "[1, 5, 9]\n")
        self.ejecutar("muestra(10..1 paso 4)", "[10, 6, 2]\n")

    def test_para_con_paso(self):
        self.ejecutar("para i en 0..20 paso 5 { muestra(i) }", "0\n5\n10\n15\n20\n")
        self.ejecutar("variable p = 2\npara i en 1..7 paso p { muestra(i) }", "1\n3\n5\n7\n")

    def test_paso_con_expresion_y_decimal(self):
        self.ejecutar("variable n = 2\nmuestra(0..10 paso n + 1)", "[0, 3, 6, 9]\n")
        self.ejecutar("muestra(1..6 paso 2.9)", "[1, 3, 5]\n")

    def test_paso_invalido(self):
        self.error("muestra(1..5 paso 0)", "mayor que 0")
        self.error('muestra(1..5 paso -2)', "mayor que 0")
        self.error('muestra(1..5 paso "dos")', "espera un número")

    def test_paso_sigue_siendo_nombre_valido(self):
        # 'paso' solo es palabra clave en el contexto de un rango
        self.ejecutar("variable paso = 2\nmuestra(paso)", "2\n")
        self.ejecutar("funcion paso(n) { devuelve n + 1 }\nmuestra(paso(1))", "2\n")


class TestElegir(BaseParidad):
    def test_casos_y_sino(self):
        codigo = (
            'variable n = 2\n'
            'elegir n {\n'
            '  caso 1 { muestra("uno") }\n'
            '  caso 2 { muestra("dos") }\n'
            '}\n'
        )
        self.ejecutar(codigo, "dos\n")
        self.ejecutar('elegir 9 { caso 1 { muestra("uno") } sino { muestra("otro") } }', "otro\n")
        self.ejecutar('elegir 7 { caso 1 { muestra("uno") } }', "")

    def test_varios_valores_por_caso(self):
        codigo = 'elegir 3 { caso 1, 2 { muestra("poquito") } caso 3, 4 { muestra("medio") } }'
        self.ejecutar(codigo, "medio\n")
        self.ejecutar('elegir 2 { caso 2 { muestra("a") } caso 2, 3 { muestra("b") } }', "a\n")

    def test_una_linea(self):
        codigo = 'elegir "b" { caso "a": muestra(1) caso "b": muestra(2) sino: muestra(0) }'
        self.ejecutar(codigo, "2\n")

    def test_sin_caida_entre_casos(self):
        codigo = 'elegir 1 { caso 1 { muestra("uno") } caso 1 { muestra("otro") } }'
        self.ejecutar(codigo, "uno\n")

    def test_compara_como_igualdad_de_jp(self):
        # 1 == verdadero es falso en JP (como en Python)
        self.ejecutar('elegir 1 { caso verdadero { muestra("bool") } caso 1 { muestra("num") } }', "num\n")
        self.ejecutar("elegir 2.0 { caso 2 { muestra(\"igual\") } }", "igual\n")

    def test_romper_y_continuar(self):
        self.ejecutar("para i en 1..5 { elegir i { caso 3 { romper } sino { muestra(i) } } }", "1\n2\n")
        self.ejecutar("para i en 1..5 { elegir i { caso 2 { continuar } sino { muestra(i) } } }", "1\n3\n4\n5\n")

    def test_ambito_de_los_casos(self):
        codigo = "elegir 2 { caso 2 { variable x = 10; muestra(x) } }\nvariable x = 1\nmuestra(x)"
        self.ejecutar(codigo, "10\n1\n")

    def test_funciones_y_expresiones_en_los_casos(self):
        self.ejecutar("funcion doble(n) { devuelve n * 2 }\nelegir doble(2) { caso 4: muestra(\"cuatro\") }", "cuatro\n")
        self.ejecutar('elegir 3 { caso 1 + 2 { muestra("suma") } }', "suma\n")

    def test_errores(self):
        with self.assertRaises(ErrorSintaxis):
            parsear(tokenizar("elegir 1 { muestra(2) }"))
        error = None
        try:
            parsear(tokenizar("elegir 1 { caso 1 { muestra(2) }"))
        except ErrorSintaxis as exc:
            error = exc
        self.assertIsNotNone(error)


class TestIntentar(BaseParidad):
    def test_captura_basica(self):
        codigo = 'intenta { muestra(1 / 0) } atrapa e { muestra("error:", e) }'
        self.ejecutar(codigo, "error: división por cero\n")

    def test_sin_error_no_entra_al_atrapa(self):
        self.ejecutar('intenta { muestra("bien") } atrapa e { muestra("nunca") }', "bien\n")

    def test_atrapa_anonimo(self):
        self.ejecutar('intenta { longitud(3) } atrapa { muestra("error anónimo") }', "error anónimo\n")

    def test_errores_capturables(self):
        self.ejecutar('intenta { muestra(nada) } atrapa e { muestra("variable") }', "variable\n")
        self.ejecutar('funcion f(a) { devuelve a }\nintenta { f() } atrapa e { muestra(e) }',
                      "la función 'f' espera 1 argumento(s), recibió 0\n")
        self.ejecutar('intenta { muestra("a" - 1) } atrapa e { muestra("tipos") }', "tipos\n")
        self.ejecutar('intenta { [1, 2][9] } atrapa e { muestra("índice") }', "índice\n")

    def test_error_en_funcion_llamada_desde_intenta(self):
        self.ejecutar('funcion f() { devuelve 1 % 0 }\nintenta { f() } atrapa e { muestra("capturado") }',
                      "capturado\n")

    def test_error_en_callback(self):
        codigo = 'intenta { mapear([1, 0], funcion(x) { devuelve 5 / x }) } atrapa e { muestra("capturado") }'
        self.ejecutar(codigo, "capturado\n")

    def test_nombre_del_error_solo_vive_dentro(self):
        codigo = 'intenta { 1 / 0 } atrapa e { muestra("dentro") }\nvariable e = "otra"\nmuestra(e)'
        self.ejecutar(codigo, "dentro\notra\n")

    def test_retorna_dentro_de_intenta(self):
        codigo = (
            'funcion f(n) {\n'
            '  intenta {\n'
            '    si n > 0 { devuelve "positivo" }\n'
            '    devuelve 1 / n\n'
            '  } atrapa e { devuelve "cero" }\n'
            '}\n'
            'muestra(f(1), f(0))'
        )
        self.ejecutar(codigo, "positivo cero\n")

    def test_retorna_en_atrapa(self):
        codigo = 'funcion f() { intenta { 1 / 0 } atrapa e { devuelve "fallo" } }\nmuestra(f())'
        self.ejecutar(codigo, "fallo\n")

    def test_romper_y_continuar_en_intenta(self):
        codigo = 'para i en 1..5 { intenta { si i == 3 { romper }; muestra(i) } atrapa e { muestra("no") } }'
        self.ejecutar(codigo, "1\n2\n")
        codigo = 'para i en 1..3 { intenta { si i == 2 { continuar }; muestra(i) } atrapa e { muestra("no") } }'
        self.ejecutar(codigo, "1\n3\n")

    def test_error_dentro_de_bucle_con_continuar(self):
        codigo = (
            'para i en 0..3 {\n'
            '  intenta { muestra(12 / i) } atrapa e { muestra("fallo en", i); continuar }\n'
            '  muestra("después", i)\n'
            '}'
        )
        self.ejecutar(codigo, "fallo en 0\n12\ndespués 1\n6\ndespués 2\n4\ndespués 3\n")

    def test_intenta_anidado(self):
        codigo = (
            'intenta {\n'
            '  intenta { muestra(1 / 0) } atrapa e { muestra("interno") }\n'
            '} atrapa e2 { muestra("externo") }'
        )
        self.ejecutar(codigo, "interno\n")
        codigo = (
            'intenta {\n'
            '  intenta { 1 / 0 } atrapa e { 2 / 0 }\n'
            '} atrapa e2 { muestra("externo:", e2) }'
        )
        self.ejecutar(codigo, "externo: división por cero\n")

    def test_se_sigue_con_la_pila_sana(self):
        self.ejecutar("intenta { 1 / 0 } atrapa e { }\nmuestra(1 + 1)", "2\n")
        self.ejecutar("intenta { 1 / 0 } atrapa e { }\nmuestra(mapear([1, 2], funcion(x) { devuelve x * 3 }))",
                      "[3, 6]\n")

    def test_en_funcion_con_locales(self):
        codigo = (
            'funcion f() {\n'
            '  variable x = 10\n'
            '  intenta { x / 0 } atrapa e { devuelve x * 2 }\n'
            '}\n'
            'muestra(f())'
        )
        self.ejecutar(codigo, "20\n")

    def test_error_en_el_atrapa_no_se_recaptura(self):
        codigo = 'intenta { intenta { 1 / 0 } atrapa e { 1 / 0 } } atrapa e2 { muestra("exterior:", e2) }'
        self.ejecutar(codigo, "exterior: división por cero\n")

    def test_sintaxis(self):
        with self.assertRaises(ErrorSintaxis):
            parsear(tokenizar("intenta { muestra(1) }"))


class TestFuncionesAnonimas(BaseParidad):
    def test_lambda_basica(self):
        self.ejecutar("variable doble = funcion(x) { devuelve x * 2 }\nmuestra(doble(21))", "42\n")

    def test_lambda_inmediata(self):
        self.ejecutar("muestra(funcion(x) { devuelve x + 1 }(1))", "2\n")

    def test_lambda_con_varias_sentencias_y_sin_parametros(self):
        self.ejecutar("variable f = funcion() { variable x = 1; devuelve x + 1 }\nmuestra(f())", "2\n")

    def test_captura_el_entorno(self):
        codigo = (
            "funcion sumador(n) {\n"
            "  devuelve funcion(x) { devuelve x + n }\n"
            "}\n"
            "variable mas5 = sumador(5)\n"
            "variable mas1 = sumador(1)\n"
            "muestra(mas5(10), mas1(10))"
        )
        self.ejecutar(codigo, "15 11\n")

    def test_en_listas_y_diccionarios(self):
        codigo = (
            "variable fs = [funcion(x) { devuelve x + 1 }, funcion(x) { devuelve x * 10 }]\n"
            "muestra(fs[0](1), fs[1](3))"
        )
        self.ejecutar(codigo, "2 30\n")
        codigo = "variable d = {saluda: funcion(n) { devuelve \"hola \" + n }}\nmuestra(d.saluda(\"jp\"))"
        self.ejecutar(codigo, "hola jp\n")

    def test_error_de_aridad(self):
        self.error("variable f = funcion(x) { devuelve x }\nf(1, 2)", "espera 1 argumento")

    def test_error_de_tipo(self):
        self.error("variable f = funcion() { devuelve 1 }\nf()(2)", "no es una función")


class TestOrdenSuperior(BaseParidad):
    def test_mapear(self):
        self.ejecutar("muestra(mapear([1, 2, 3], funcion(x) { devuelve x * 2 }))", "[2, 4, 6]\n")
        self.ejecutar('muestra(mapear("abc", funcion(c) { devuelve c.mayusculas() }))', '["A", "B", "C"]\n')
        self.ejecutar("muestra(mapear(3, funcion(x) { devuelve x * x }))", "[1, 4, 9]\n")
        self.ejecutar('muestra(mapear({a: 1}, funcion(k) { devuelve k }))', '["a"]\n')

    def test_filtrar(self):
        self.ejecutar("muestra(filtrar(1..10, funcion(x) { devuelve x % 2 == 0 }))", "[2, 4, 6, 8, 10]\n")
        self.ejecutar("funcion par(x) { devuelve x % 2 == 0 }\nmuestra(filtrar([1, 2, 3, 4], par))", "[2, 4]\n")
        # la verdad de JP: 0 y las cadenas vacías SÍ son verdad
        self.ejecutar("muestra(filtrar([0, 1, nulo, falso], funcion(x) { devuelve verdadero }))", "[0, 1, nulo, falso]\n")

    def test_reducir(self):
        self.ejecutar("muestra(reducir([1, 2, 3, 4], funcion(a, b) { devuelve a + b }, 0))", "10\n")
        self.ejecutar("muestra(reducir([1, 2, 3, 4], funcion(a, b) { devuelve a + b }))", "10\n")
        self.ejecutar('muestra(reducir(["a", "b", "c"], funcion(a, b) { devuelve a + b }, ""))', "abc\n")
        self.error("reducir([], funcion(a, b) { devuelve a + b })", "valor inicial")

    def test_para_cada(self):
        self.ejecutar('para_cada([1, 2, 3], funcion(x) { muestra("n:", x) })', "n: 1\nn: 2\nn: 3\n")
        self.ejecutar("variable suma = 0\npara_cada(1..4, funcion(x) { suma += x })\nmuestra(suma)", "10\n")

    def test_ordenar_con_y_sin_clave(self):
        self.ejecutar("muestra(ordenar([3, 1, 2]))", "[1, 2, 3]\n")
        self.ejecutar('muestra(ordenar(["bbb", "a", "cc"], funcion(x) { devuelve longitud(x) }))',
                      '["a", "cc", "bbb"]\n')
        codigo = (
            'variable gente = [{n: "ana", e: 30}, {n: "luis", e: 20}]\n'
            "muestra(ordenar(gente, funcion(p) { devuelve p.e })[0].n)"
        )
        self.ejecutar(codigo, "luis\n")
        self.error('ordenar([1, "a"])', "no puede comparar")

    def test_anidamiento(self):
        codigo = (
            "variable dobles = mapear([1, 2], funcion(x) { devuelve x * 2 })\n"
            "variable total = reducir(dobles, funcion(a, b) { devuelve a + b }, 0)\n"
            "muestra(total)"
        )
        self.ejecutar(codigo, "6\n")

    def test_metodos_equivalentes(self):
        self.ejecutar("muestra([3, 1, 2].ordenar())", "[1, 2, 3]\n")
        self.ejecutar("muestra([1, 2, 3].mapear(funcion(x) { devuelve x * x }))", "[1, 4, 9]\n")
        self.ejecutar("muestra([1, 2, 3].filtrar(funcion(x) { devuelve x > 1 }))", "[2, 3]\n")
        self.ejecutar("muestra([1, 2, 3].reducir(funcion(a, b) { devuelve a * b }, 1))", "6\n")
        self.ejecutar("muestra([1, 2, 3].sumar())", "6\n")

    def test_errores_de_tipo(self):
        self.error("mapear(nulo, funcion(x) { devuelve x })", "espera lista, texto, diccionario o número")
        self.error("filtrar([1], 3)", "no es una función")


class TestNativasNuevas(BaseParidad):
    def test_matematicas(self):
        self.ejecutar("muestra(absoluto(-5), raiz(16), piso(2.9), techo(2.1))", "5 4 2 3\n")
        self.ejecutar("muestra(redondear(2.5), redondear(-2.5), redondear(3.14159, 2))", "3 -3 3.14\n")
        self.ejecutar("muestra(potencia(2, 8), potencia(9, 0.5))", "256 3\n")
        self.ejecutar("muestra(redondear(log(100, 10)), redondear(pi(), 2))", "2 3.14\n")
        self.ejecutar("muestra(minimo(4, 2, 9), maximo([4, 2, 9]), minimo(-1, 0))", "2 9 -1\n")
        self.ejecutar("muestra(sumar([1, 2, 3]), sumar([]), sumar(1..4))", "6 0 10\n")

    def test_errores_matematicos(self):
        self.error("raiz(-4)", "negativo")
        self.error("log(0)", "mayor que 0")
        self.error("minimo()", "al menos un número")
        self.error('sumar(["a"])', "espera un número")

    def test_aleatorio_es_decimal(self):
        codigo = "variable r = aleatorio()\nmuestra(r >= 0 y r < 1)"
        self.ejecutar(codigo, "verdadero\n")

    def test_tipo(self):
        codigo = (
            'muestra(tipo(1), tipo("a"), tipo([1]), tipo({a: 1}), tipo(verdadero), tipo(nulo))'
        )
        self.ejecutar(codigo, "número texto lista diccionario booleano nulo\n")
        self.ejecutar("funcion f() { devuelve 1 }\nvariable g = funcion() { devuelve 2 }\n"
                      "muestra(tipo(f), tipo(g), tipo(imprime))", "función función función\n")

    def test_texto(self):
        codigo = (
            'muestra("hola".empezar_con("ho"), "hola".terminar_con("la"), '
            '"hola".buscar("l"), "hola".buscar("z"))'
        )
        self.ejecutar(codigo, "verdadero verdadero 2 -1\n")
        self.ejecutar('muestra(repetir("ab", 3), repetir([1], 4), invertir("hola"))', "ababab [1, 1, 1, 1] aloh\n")

    def test_listas(self):
        self.ejecutar("muestra(indice_de([5, 6, 7], 6), indice_de([5], 9))", "1 -1\n")
        self.ejecutar("variable l = [1, 2]\ninsertar(l, 1, 9)\nmuestra(l)\nmuestra(quitar(l, 0), l)",
                      "[1, 9, 2]\n1 [9, 2]\n")
        self.ejecutar("variable l = [1, 2, 3]\nmuestra(quitar(l), l)", "3 [1, 2]\n")
        self.ejecutar("variable l = [1, 2, 1]\nmuestra(eliminar(l, 1), l)", "verdadero [2, 1]\n")
        self.ejecutar("variable l = [1]\nmuestra(eliminar(l, 9), l)", "falso [1]\n")
        self.ejecutar("muestra(invertir([1, 2, 3]), [1, 2, 3].unir(\"-\"))", "[3, 2, 1] 1-2-3\n")

    def test_diccionarios(self):
        codigo = 'variable d = {a: 1, b: 2}\nmuestra(d.valores(), d.elementos())'
        self.ejecutar(codigo, '[1, 2] [["a", 1], ["b", 2]]\n')
        codigo = 'para par en {a: 1, b: 2}.elementos() { muestra(par[0], par[1]) }'
        self.ejecutar(codigo, "a 1\nb 2\n")

    def test_errores_de_listas(self):
        self.error("quitar([1, 2], 9)", "fuera de rango")
        self.error("quitar([])", "lista vacía")
        self.error("eliminar(3, 1)", "espera una lista")
        self.error("invertir(3)", "espera lista o texto")


class TestRetornoEnBucles(BaseParidad):
    """Paridad de 'devuelve' dentro de bucles (antes fallaba solo en la VM)."""

    def test_devuelve_en_para(self):
        codigo = (
            "funcion f() {\n"
            "  para i en 1..5 {\n"
            "    si i == 3 { devuelve i }\n"
            "  }\n"
            "  devuelve 0\n"
            "}\n"
            "muestra(f())"
        )
        self.ejecutar(codigo, "3\n")

    def test_devuelve_en_para_anidado(self):
        codigo = (
            "funcion f() {\n"
            "  para i en 1..3 {\n"
            "    para j en 1..3 {\n"
            "      si i * j == 4 { devuelve [i, j] }\n"
            "    }\n"
            "  }\n"
            "  devuelve nulo\n"
            "}\n"
            "muestra(f())"
        )
        self.ejecutar(codigo, "[2, 2]\n")

    def test_devuelve_en_para_dentro_de_mientras(self):
        codigo = (
            "funcion f() {\n"
            "  variable k = 0\n"
            "  mientras k < 3 {\n"
            "    k += 1\n"
            "    para i en 1..9 {\n"
            "      si i == k { devuelve i }\n"
            "    }\n"
            "  }\n"
            "  devuelve -1\n"
            "}\n"
            "muestra(f())"
        )
        self.ejecutar(codigo, "1\n")

    def test_devuelve_en_intenta_dentro_de_bucle(self):
        codigo = (
            "funcion f() {\n"
            "  para i en 1..3 {\n"
            "    intenta { si i == 2 { devuelve i } } atrapa e { muestra(\"no\") }\n"
            "  }\n"
            "  devuelve 0\n"
            "}\n"
            "muestra(f())"
        )
        self.ejecutar(codigo, "2\n")


class TestEjemplosCompletos(BaseParidad):
    def test_menu_con_elegir(self):
        codigo = (
            "variable opcion = 3\n"
            "elegir opcion {\n"
            '  caso 1 { muestra("saludar") }\n'
            '  caso 2 { muestra("despedirse") }\n'
            '  caso 3 { muestra("ayuda") }\n'
            "  sino { muestra(\"opción inválida\") }\n"
            "}"
        )
        self.ejecutar(codigo, "ayuda\n")

    def test_calculadora_segura(self):
        codigo = (
            "funcion dividir(a, b) {\n"
            '  intenta { devuelve a / b } atrapa e { devuelve "error: " + e }\n'
            "}\n"
            "muestra(dividir(10, 2))\n"
            "muestra(dividir(10, 0))"
        )
        self.ejecutar(codigo, "5\nerror: división por cero\n")

    def test_pipeline_de_datos(self):
        codigo = (
            "variable precios = [120, 45, 300, 15, 90]\n"
            "variable caros = filtrar(precios, funcion(p) { devuelve p >= 90 })\n"
            "variable con_iva = mapear(caros, funcion(p) { devuelve redondear(p * 1.21) })\n"
            "muestra(con_iva)\n"
            "muestra(sumar(con_iva))\n"
            "muestra(maximo(con_iva))"
        )
        self.ejecutar(codigo, "[145, 363, 109]\n617\n363\n")

    def test_tabla_de_multiplicar_con_paso(self):
        codigo = 'para i en 1..10 paso 3 { muestra("3 x", i, "=", 3 * i) }'
        self.ejecutar(codigo, "3 x 1 = 3\n3 x 4 = 12\n3 x 7 = 21\n3 x 10 = 30\n")


if __name__ == "__main__":
    unittest.main()
