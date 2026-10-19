# Cambios de JP

## 1.6.0 — «Programas que se componen» (2026-10-19)

Todo lo nuevo funciona con la **misma salida en el intérprete de árbol y en la
VM de bytecode** (28 tests nuevos de paridad en `tests/test_v16.py`; suite
total: 280 tests). El motor en C y el JIT rechazan limpiamente lo que aún no
tienen y el CLI sigue con el motor de Python, sin resultados distintos.

- **Módulos**: `importar "utilidades.jp"` o `importar "utilidades.jp" como util`
  (y luego `util.doble(2)`). Cada módulo se ejecuta una sola vez, ve sus
  propios globales al ser llamado desde otro archivo y las importaciones
  circulares dan un error claro. Rutas relativas al archivo que importa.
  Ejemplos: `ejemplos/modulos.jp` + `ejemplos/utilidades.jp`.
- **Valores por defecto**: `funcion f(a, b = 2) { ... }` — también en funciones
  anónimas, y un defecto puede usar los parámetros anteriores (`b = a + 1`).
- **Desestructuración**: `variable [a, b] = [1, 2]` y el intercambio sin
  variable temporal `[a, b] = [b, a]`.
- **`para` con dos nombres**: `para i, valor en lista` (posición desde 0 y
  valor) y `para clave, valor en diccionario`.
- **`lanzar expr`**: crea un error propio atrapable con `atrapa`.
- **`finalmente`**: `intenta { ... } atrapa e { ... } finalmente { ... }` —
  el bloque final corre siempre: sin error, tras el atrapa, y antes de que un
  `devuelve`/`romper`/`continuar` salga del `intenta`. También vale
  `intenta { ... } finalmente { ... }` sin `atrapa`.
- **Recursión unificada**: el tope del lenguaje es 6000 llamadas en los dos
  motores (antes el árbol cortaba mucho antes que la VM).
- **Arreglo del lexer**: `lista[0]=1` (sin espacios) ya no se confunde con un
  signo compuesto; antes `]=` se leía como `>=`.
- **Proyecto**: este CHANGELOG, la `LICENSE` MIT y el ejemplo
  `ejemplos/ia-perceptron.jp` (una IA que aprende la tabla OR desde cero).

## 1.5.0 y anteriores

Ver el historial en el `README.md` y el plan de trabajo en `PLAN.md`
(motor nativo en C, JIT x86-64, modo turbo, `elegir/caso`, `intenta/atrapa`,
rangos con paso, potencia `**` y asignación compuesta).
