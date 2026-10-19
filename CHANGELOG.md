# Cambios de JP

## 1.12.0 — «Gráficos» (2026-10-19)

- **SVG desde JP** (`jp/graficos.py`): primitivas `svg_linea`,
  `svg_rectangulo`, `svg_circulo`, `svg_texto` (con escape XML),
  `svg_lineas`, `svg_camino`, `crear_svg` y `guardar_svg`, idénticas en el
  árbol y en la VM. El SVG se puede guardar o servir por web con
  `tipo: "image/svg+xml"`.
- **Gráficas en JP puro** (`biblioteca/graficas.jp`): `grafica_barras`,
  `grafica_lineas` y `grafica_pastel` (con leyenda y porcentajes) escritas
  con las primitivas. `ejemplos/grafica.jp` genera `grafica-barras.svg` y
  `grafica-pastel.svg` de las ventas por ciudad (incluidos como muestra).

## 1.11.0 — «Web Pro» (2026-10-19)

- **Mini-framework web en JP puro** (`biblioteca/web.jp`): clase
  `Aplicacion` con rutas por método y patrón (`app.get("/saludar/:nombre",
  ...)` — los `:parámetros` llegan en `peticion.parametros`),
  intermediarios (`app.usar(...)`, pueden cortar la petición: claves,
  registro...), respuestas `web.json(datos, estado)`, `web.pagina(html)` y
  `web.redirigir(destino)`, y 404 en JSON por defecto. `app.atender(...)`
  permite probarlo sin abrir red (`ejemplos/web-rutas.jp`); sitio completo
  en `biblioteca/ejemplo-web.jp`.
- **Servidor más capaz**: la petición trae `json` con el cuerpo ya leído si
  venía en JSON, y la respuesta acepta `cabeceras` propias (ej:
  `{cabeceras: {"X-App": "JP"}}`, redirecciones con `Location`...).

## 1.10.0 — «Web» (2026-10-19)

- **Servidor web**: `servir(puerto, manejador[, anfitrion])` — JP ya no solo
  consume APIs: las sirve. La petición llega como diccionario
  `{metodo, ruta, consulta, cuerpo, cabeceras}` y la respuesta puede ser
  texto o `{cuerpo, estado, tipo}` (dict/lista sale como JSON). Las llamadas
  al manejador se serializan (el motor no es multi-hilo). Ejemplo ejecutable
  en `biblioteca/ejemplo-servidor.jp`; test con HTTP real en
  `tests/test_v20.py`.
- **Seguridad básica**: `hash_texto(texto[, algoritmo])` (md5/sha1/sha256/
  sha512), `codificar64`/`decodificar64` e `id_unico()`.

## 1.9.0 — «Datos» (2026-10-19)

Paridad árbol↔VM en todo (8 tests nuevos en `tests/test_v19.py`) y las
primeras nativas de la biblioteca **dentro del motor en C**.

- **CSV estilo pandas**: `leer_csv`, `leer_csv_texto`, `escribir_csv`,
  `convertir_csv` (con conversión de tipos: "42" -> 42, "verdadero" -> booleano)
  y `sublista`. Sobre eso, `biblioteca/tabla.jp` trae la clase `Tabla`:
  `filtrar_con`, `ordenar_por`, `agrupar_por`, `agregar_columna`,
  `promedio_columna`, `cabeza`, `guardar_csv`... Ejemplo con datos reales:
  `ejemplos/datos.jp` + `ejemplos/ventas.csv`.
- **Fechas**: `sumar_dias` y `dias_entre` se suman a las de la v1.8.
- **Motor en C**: `sigmoide`, `producto_punto`, `promedio`, `mediana`,
  `norma`, `distancia` y `softmax` ya están implementadas en `jpvm.c` —
  un programa que solo use eso corre en el binario sin Python, con la
  misma salida (test de paridad incluido).

## 1.8.0 — «La biblioteca» (2026-10-19)

JP pasa de ~69 a **120 funciones nativas** y gana una biblioteca en JP puro.
Todo con paridad árbol↔VM (11 tests nuevos en `tests/test_v18.py`; suite
total: 310). El motor en C rechaza limpiamente las nativas que aún no tiene.

- **51 nativas nuevas** en 5 módulos del motor (el equivalente humilde y en
  español de `statistics`, un mini-NumPy, `datetime`, `os`/`subprocess` y `re`):
  estadística (`promedio`, `mediana`, `moda`, `varianza`, `desviacion`,
  `percentil`, `frecuencias`, `contar`, `resumen`), matrices y vectores
  (`multiplicar_matrices`, `transponer`, `softmax`, `norma`, `distancia`,
  `normalizar`, `matriz_aplicar`...), fechas (`fecha_actual`, `formatear_fecha`,
  `convertir_fecha`, `hoy`...), sistema (`plataforma`, `ejecutar`,
  `leer_entorno`, `unir_ruta`...) y patrones regex (`buscar_patron`,
  `coincide_patron`, `encontrar_patrones`, `reemplazar_patron`, `separar_patron`).
- **`biblioteca/` en JP puro**: `mates.jp`, `texto.jp`, `listas.jp`,
  `colecciones.jp` (clases `Pila`, `Cola`, `Conjunto`) e `ia.jp` — una
  `RedNeuronal` multicapa con backprop que aprende el XOR (ver
  `biblioteca/LEEME.md`). Ejemplo: `ejemplos/biblioteca.jp`.

## 1.7.0 — «Objetos» (2026-10-19)

Todo lo nuevo funciona con la **misma salida en el intérprete de árbol y en la
VM de bytecode** (19 tests nuevos en `tests/test_v17.py`; suite total: 299).
El motor en C y el JIT rechazan limpiamente lo que aún no tienen.

- **Clases y objetos**: `clase Persona { funcion iniciar(nombre) { este.nombre = nombre } ... }`,
  herencia con `clase Empleado hereda Persona`, métodos con valores por
  defecto, métodos como valores (`variable m = p.saludar`) y objetos que
  funcionan también importados desde un módulo. Ejemplo: `ejemplos/clases.jp`.
- **Errores con campos**: dentro de `atrapa`, el error sigue siendo el texto
  de siempre y además trae `e.tipo` (`"division_por_cero"`, `"usuario"`,
  `"indice_fuera_de_rango"`...), `e.mensaje` y `e.linea`.
- **Kit de IA**: `sigmoide(x)` y `producto_punto(a, b)` como nativas rápidas
  (~1,7x frente al bucle equivalente en JP). El perceptrón de ejemplo ahora
  es una clase: `ejemplos/ia-perceptron.jp`.
- **Rangos perezosos en `para`**: `para i en 1..5000000` ya no crea la lista
  entera en memoria (pico de ~4 MB para 3 millones de vueltas).
- **`jp --check archivo.jp`**: comprueba la sintaxis sin ejecutar (editores/CI).

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
