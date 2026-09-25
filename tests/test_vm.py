"""Tests de la VM de bytecode: paridad con el intérprete de árbol.

Cada programa se ejecuta dos veces (VM e intérprete de árbol) y las salidas
deben ser idénticas. Ejecutar con:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM


def ejecutar_en(maquina, codigo: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)))
    return buffer.getvalue()


def paridad(codigo: str) -> tuple[str, str]:
    """Ejecuta el mismo código en la VM y en el árbol; devuelve ambas salidas."""
    return ejecutar_en(MaquinaVM(), codigo), ejecutar_en(Interprete(), codigo)


class TestParidadVM(unittest.TestCase):
    def _par(self, codigo: str):
        vm, arbol = paridad(codigo)
        self.assertEqual(vm, arbol, "la VM y el intérprete de árbol difieren")
        return vm

    # ---------- aritmética y operadores ----------

    def test_aritmetica(self):
        self._par('muestra(1 + 2 * 3)\nmuestra(10 / 4)\nmuestra(10 % 3)\nmuestra(-5 + 3)')
        self._par('muestra(10 / 2)\nmuestra(7 / 2)')  # división exacta vs decimal

    def test_operadores_raros(self):
        self._par('muestra("ab" * 3)\nmuestra([1] + [2, 3])\nmuestra("a" + 1 + verdadero)')

    def test_igualdad_y_comparaciones(self):
        self._par('muestra(1 == 1.0, 1 == verdadero, "a" != "b", nulo == nulo)\n'
                  'muestra(2 < 3, 3 <= 3, 4 > 5, 5 >= 5)')

    def test_division_por_cero_igual(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, 'muestra(1 / 0)')
            self.assertIn("división por cero", str(ctx.exception))

    # ---------- verdad, si/mientras/para ----------

    def test_verdad(self):
        self._par('si 0 { muestra("cero es verdad") }\n'
                  'si nulo { muestra("no") } sino { muestra("nulo es falso") }\n'
                  'muestra(no 0, no nulo, no falso)')

    def test_mientras(self):
        self._par('variable i = 0\nvariable s = 0\nmientras i < 5 {\n  s = s + i\n  i = i + 1\n}\nmuestra(s)')

    def test_para_rango_lista_dict_numero_cadena(self):
        self._par('para i en 1..5 { muestra(i) }\npara i en 3..1 { muestra(i) }')
        self._par('para x en ["a", "b"] { muestra(x) }')
        self._par('para k en {x: 1, y: 2} { muestra(k) }')
        self._par('para i en 3 { muestra(i) }\npara c en "ho" { muestra(c) }')

    def test_para_variable_solo_en_el_bucle(self):
        codigo = ('variable j = "global"\n'
                  'para j en 1..2 { muestra(j) }\n'
                  'muestra(j)\n')
        vm, arbol = paridad(codigo)
        self.assertEqual(vm, arbol)
        self.assertIn("global", vm)  # j vuelve a ser la global tras el bucle

    def test_para_anidado_mismo_nombre(self):
        self._par('para i en 1..2 {\n  para i en 1..2 { muestra(i) }\n  muestra("fuera", i)\n}')

    def test_cuerpo_de_una_linea(self):
        self._par('si verdadero: muestra("sí")\nvariable x = 0\nmientras x < 3: x = x + 1\nmuestra(x)')

    def test_para_de_una_linea(self):
        self._par('para i en 1..3: muestra(i)')

    # ---------- funciones, closures y recursión ----------

    def test_funciones_basicas(self):
        self._par('funcion suma(a, b) { devuelve a + b }\nmuestra(suma(2, 3))\nmuestra(suma("a", "b"))')

    def test_retorno_implicito(self):
        self._par('funcion cinco() { 5 }\nmuestra(cinco())')
        self._par('funcion nada() { variable x = 1 }\nmuestra(nada())')

    def test_recursion(self):
        self._par('funcion fib(n) {\n  si n <= 1 { devuelve n }\n  devuelve fib(n - 1) + fib(n - 2)\n}\n'
                  'muestra(fib(10))')

    def test_closures(self):
        self._par('funcion contador() {\n  variable n = 0\n'
                  'funcion paso() { n = n + 1; devuelve n }\n'
                  'devuelve paso\n}\n'
                  'variable p = contador()\nmuestra(p(), p(), p())')

    def test_closures_con_recursion_mutua(self):
        self._par('funcion par(n) { si n == 0 { devuelve verdadero }; devuelve impar(n - 1) }\n'
                  'funcion impar(n) { si n == 0 { devuelve falso }; devuelve par(n - 1) }\n'
                  'muestra(par(10), impar(10))')

    def test_recursion_anidada_variables_locales(self):
        # Cada llamada debe tener su PROPIA copia de las locales (sin colisiones)
        self._par('funcion suma(n) {\n  variable total = 0\n  para i en 1..n { total = total + i }\n'
                  'si n > 1 { total = total + suma(n - 1) }\ndevuelve total\n}\n'
                  'muestra(suma(4))')

    def test_primera_clase(self):
        # Las funciones son valores de primera clase (por nombre, como en el árbol)
        self._par('funcion doble(n) { devuelve n * 2 }\n'
                  'funcion aplicar(f, x) { devuelve f(x) }\n'
                  'muestra(aplicar(doble, 5))')

    def test_argumentos_incorrectos_igual(self):
        codigo = 'funcion f(a) { devuelve a }\nf(1, 2)'
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, codigo)
            self.assertIn("espera 1 argumento", str(ctx.exception))

    def test_no_funcion_igual(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, 'variable x = 5\nx()')
            self.assertIn("no es una función", str(ctx.exception))

    # ---------- variables y ámbitos ----------

    def test_global_vs_local(self):
        # ojo: 'y' es palabra clave (and), así que la local se llama 'z'
        self._par('variable x = 1\nfuncion f() { x = 2; variable z = 3; devuelve z }\n'
                  'muestra(f(), x)\n'
                  'funcion g() { variable x = 99; devuelve x }\nmuestra(g(), x)')

    def test_asignacion_a_no_declarada(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, 'x = 5')
            self.assertIn("usa 'var' para declararla", str(ctx.exception))

    def test_variable_no_definida(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, 'muestra(nadie)')
            self.assertIn("variable no definida", str(ctx.exception))

    # ---------- listas, diccionarios, rangos ----------

    def test_indices_y_negativos(self):
        self._par('variable l = [10, 20, 30]\nmuestra(l[0], l[-1], l[-3])')
        self._par('muestra("hola"[0], "hola"[-1])')

    def test_indice_fuera_de_rango_igual(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, 'variable l = [1]\nmuestra(l[5])')
            self.assertIn("fuera de rango", str(ctx.exception))

    def test_clave_inexistente_igual(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, 'variable d = {a: 1}\nmuestra(d.falta)')
            self.assertIn("no existe la clave", str(ctx.exception))

    def test_diccionarios(self):
        self._par('variable d = {x: 1, y: 2}\nd.z = 9\nd["x"] = 5\nmuestra(d.x, d["y"], d.z, longitud(d))')

    def test_asignar_indice(self):
        self._par('variable l = [1, 2, 3]\nl[1] = 99\nl[-1] = 7\nmuestra(l)\n'
                  'variable d = {a: 1}\nd["b"] = 2\nmuestra(d)')

    def test_rangos_al_reves(self):
        self._par('muestra(5..1)\nmuestra(1..5)')

    def test_cortocircuito_devuelve_operando(self):
        self._par('muestra(nulo o "x")\nmuestra("y" o "z")\nmuestra(nulo y 5)\nmuestra(3 y 7)')

    # ---------- REPL / último valor ----------

    def test_ultimo_valor(self):
        vm = MaquinaVM()
        ejecutar_en(vm, '1 + 2')
        self.assertEqual(vm.ultimo_valor, 3)
        vm2 = Interprete()
        ejecutar_en(vm2, '1 + 2')
        self.assertEqual(vm2.ultimo_valor, 3)

    def test_retorna_nivel_superior(self):
        vm, arbol = paridad('retorna 42')
        self.assertEqual(vm, arbol)

    # ---------- romper / continuar (paridad VM vs árbol) ----------

    def test_romper_continuar_mientras(self):
        self._par('variable i = 0\nmientras verdadero {\n  i = i + 1\n  si i == 3 { romper }\n}\nmuestra(i)')
        self._par('variable s = 0\nvariable i = 0\nmientras i < 10 {\n  i = i + 1\n  si i % 2 == 0 { continuar }\n  s = s + i\n}\nmuestra(s)')

    def test_romper_continuar_para(self):
        self._par('variable x = 0\npara i en 1..10 {\n  si i == 4 { romper }\n  x = x + i\n}\nmuestra(x)')
        self._par('variable s = 0\npara i en 1..10 {\n  si i % 2 == 0 { continuar }\n  s = s + i\n}\nmuestra(s)')

    def test_romper_anidados_y_ambitos(self):
        self._par('variable n = 0\npara i en 1..3 {\n  para j en 1..3 {\n    si j == 2 { romper }\n  }\n  n = n + 1\n}\nmuestra(n)')
        self._par('variable i = 0\nmientras verdadero {\n  variable zona = i\n  i = i + 1\n  si zona == 2 { romper }\n}\nmuestra(i)')

    def test_menu_con_romper(self):
        self._par('variable opcion = 0\nmientras verdadero {\n  opcion = opcion + 1\n'
                  '  si opcion == 2 { continuar }\n  si opcion == 4 { romper }\n'
                  '  muestra("paso", opcion)\n}\nmuestra("fin")')

    def test_interpolacion(self):
        self._par('variable n = "mundo"\nmuestra("hola {n} dos veces")')
        self._par('variable e = 5\nmuestra("{e} * {e} = {e * e}")')
        self._par('muestra("suma: {[1, 2] + [3]}")')

    def test_romper_fuera_de_bucle_igual(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, 'romper')
            self.assertIn("fuera de un bucle", str(ctx.exception))

    def test_romper_en_funcion_igual(self):
        codigo = 'funcion f() { romper }\nmientras verdadero { f() }'
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, codigo)
            self.assertIn("fuera de un bucle", str(ctx.exception))


class TestMetodosValorVM(unittest.TestCase):
    """Paridad VM <-> árbol para los métodos de valor."""

    def _par(self, codigo: str):
        vm, arbol = paridad(codigo)
        self.assertEqual(vm, arbol, "la VM y el intérprete de árbol difieren")
        return vm

    def test_metodos_texto(self):
        self._par('muestra("hola".mayusculas())\nmuestra("A B".minusculas())\nmuestra(" x ".recortar())')
        self._par('muestra("a,b".separar(","))\nmuestra("banana".reemplazar("na", "NA"))')
        self._par('muestra("banana".subtexto(1, 3))\nmuestra("banana".letra(-1))')
        self._par('muestra("hola".contiene("ol"))')

    def test_metodos_listas(self):
        self._par('variable l = [1, 2]\nl.agregar(3)\nmuestra(l)\nmuestra(l.longitud())')
        self._par('muestra([1, 2].contiene(3))')

    def test_metodos_diccionarios(self):
        self._par('variable d = {a: 1, b: 2}\nmuestra(d.claves())\nmuestra(d.tiene("a"))')
        self._par('variable d = {claves: 1}\nmuestra(d.claves)')

    def test_errores_metodos_iguales(self):
        for maquina in (MaquinaVM(), Interprete()):
            with self.assertRaises(Exception) as ctx:
                ejecutar_en(maquina, '"hola".falta()')
            self.assertIn("no existe el método 'falta' para texto", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
