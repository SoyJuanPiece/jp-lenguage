# Cambios de JP

## 1.28.0 — Cobertura de líneas (2026-10-19)

La pieza que faltaba de la caja de herramientas de calidad:

- **`jp --cobertura programa.jp`**: ejecuta con el intérprete de árbol
  (gancho por sentencia, como el depurador) y reporta porcentaje de
  líneas ejecutadas y las que nunca corrieron, agrupadas en rangos:
  «Sin ejecutar: líneas 3-5, 9». Un error a mitad de camino también
  imprime la cobertura parcial y sale con código 65.
- Módulo `jp/cobertura.py` con la lógica (`lineas_ejecutables`,
  `medir`, `InformeCobertura`). La medida es del archivo principal;
  las líneas de módulos importados no se atribuyen. Tests:
  `tests/test_v37.py`.

## 1.27.0 — Tipos opcionales en el motor en C (2026-10-19)

La v1.23, ahora también nativa (`ejemplos/tipos.jp` idéntico):

- **Opcodes 62–64** en `jpvm.c`: `VERIFICAR_TIPO` al declarar una
  variable anotada, `VERIFICAR_ARG` en el prólogo de la función
  (después de aplicar los defectos, antes de encerrar en celdas) y
  `VERIFICAR_RET` en cada `devuelve` y en el retorno implícito.
- Mismas reglas (`cumple_tipo`) y mismos mensajes que Python:
  «el parámetro 'a' de 'sumar' es de tipo numero y recibió texto
  ('veinte')», con el valor entre comillas simples como en la VM.
  `numero` y `número` equivalen; un tipo desconocido no estorba,
  igual que en Python.
- Tests: `tests/test_v36.py`; actualizado el test de la v1.23 que
  exigía el rechazo. Paridad de ejemplos: 25 idénticos, 0 fallos.

## 1.26.0 — Desestructurar en el motor en C (2026-10-19)

Sigue creciendo la cobertura nativa (24 ejemplos idénticos a Python):

- **`para a, b en ...`**: opcodes `ITER_NEXT_PAR` (59) y
  `ITER_NEXT_PAR_CELDA` (60). Sobre listas y textos da (índice desde
  0, valor); sobre diccionarios, (clave, valor): el iterador de C
  recuerda el diccionario de origen. Las dos variables pueden ser
  capturadas por closures (máscara de celdas), verificadas en ASan.
- **`variable [a, b] = ...` y `[a, b] = ...`**: opcode
  `DESESTRUCTURAR` (61) exige una lista del largo exacto (mismos
  mensajes de error que Python) y deja los elementos en la pila.
- El análisis de ámbito del compilador conoce ahora la segunda
  variable del `para` y los nombres desestructurados, para que las
  closures puedan capturarlos. `ejemplos/utilidades.jp` ya corre
  también nativo, y `tests/test_v35.py` cubre la paridad.

## 1.25.0 — Clases en el motor en C (2026-10-19)

El proyecto grande: las clases ya viven en los tres motores.

- **Motor en C**: tipos de objeto nuevos `O_CLASE`, `O_INSTANCIA` y
  `O_METODO` (método ligado), con su marcado en el GC y su
  representación (`Punto{a: 4, b: 5}`, `<clase Punto>`). El opcode
  `CREAR_CLASE` (56) junta clase madre y métodos; `Punto(3, 4)` llama a
  `iniciar` si existe y devuelve el objeto nuevo; los métodos se ligan
  al leerlos (`variable m = p.mover`) y la herencia resuelve subiendo
  por la cadena de madres. `este` es el primer parámetro de cada
  método, como en Python. Ejemplo: `ejemplos/clases.jp`, `funcional.jp`
  e `ia-perceptron.jp` coinciden byte a byte con la VM de Python.
- **Valores por defecto también en nativo**: prólogo `DEFECTOS` (57) +
  `SALTAR_SI_HAY_VALOR` (58). La llamada rellena los parámetros que
  faltan con un centinela interno y el prólogo lo sustituye por el
  defecto, que puede usar parámetros anteriores (`b = a * 10`) y
  variables capturadas del ámbito. El análisis de capturas ahora mira
  también dentro de las expresiones por defecto. Sin tocar el formato
  `.jpb`: una función con defectos se reconoce porque su código
  empieza por `DEFECTOS`.
- Tests: `tests/test_v34.py` (paridad de clases y defectos en C,
  errores de construcción); actualizado el test de la v1.17 que exigía
  el rechazo. Paridad de ejemplos: 22 idénticos, 0 fallos.

## 1.24.1 — Arreglo del motor en C (2026-10-19)

- **Segfault en `ejemplos/red-profunda.jp` corregido**: el GC del motor
  en C barría los objetos `Nativa` del registro (`nativas_por_nombre`)
  porque al cargar el programa el contador de globales se reinicia y
  dejaban de estar marcados como raíces; cualquier método de valor
  posterior leía memoria liberada. Ahora el registro de nativas y los
  nombres de las globales se marcan en cada recolección. Detectado con
  AddressSanitizer; la paridad Python↔C vuelve a 0 fallos.

## 1.24.0 — «Revisor» (2026-10-19)

- **`jp --revisar archivo.jp`**: análisis estático sin ejecutar —
  recorre el AST con pila de ámbitos y avisa de variables usadas sin
  declarar, asignaciones sin `variable` previa y declaraciones que
  nunca se usan (las de `_nombre` no acusan: son "a propósito"). Sale
  con 1 si hay avisos y 0 si está limpio, listo para CI. Es una
  aproximación amable: tras un `importar` sin alias no acusa lo que no
  puede conocer (`jp/revisor.py`, `tests/test_v33.py`).

## 1.23.0 — «Tipos» (2026-10-19)

- **Tipos opcionales con chequeo al ejecutar**, en el árbol y en la VM:
  `funcion sumar(a: numero, b: numero): numero { ... }`,
  `variable edad: numero = 42`. Tipos: `numero`, `entero`, `texto`,
  `booleano`, `lista`, `diccionario`, `funcion`, `nulo`, `cualquiera`
  (también `número`). Se comprueban los parámetros (también cuando
  entra el valor por defecto), el valor devuelto y la declaración; el
  error dice qué se esperaba y qué llegó («el parámetro 'a' de 'sumar'
  es de tipo numero y recibió texto»). Sin anotar, todo vale como
  siempre: es gradual, no un idioma nuevo. El formateador los conserva;
  el motor en C los rechaza limpiamente por ahora.

## 1.22.0 — «En paralelo» (2026-10-19)

- **Concurrencia real por procesos** (`jp/procesos.py`):
  `iniciar_proceso(comando)` lanza un proceso hijo (otro programa, otro
  `.jp`...) que corre en paralelo de verdad, `proceso_en_curso(id)`,
  `esperar_proceso(id[, limite])` → `{codigo, salida, errores,
  terminado}` (con límite mata al que se cuelga) y `terminar_proceso`.
  La demostración se mide sola: 3 procesos que duermen 1 s terminan en
  ~1 s, no en 3 (`ejemplos/procesos.jp`).

## 1.21.0 — «Paquetes» (2026-10-19)

- **Gestor de paquetes** (`jp/paquetes.py`): un paquete es una carpeta
  con `paquete.json` (`nombre`, `version`, `principal`). Comandos:
  `jp --instalar github:usuario/repo[/subcarpeta][@rama]` (descarga el
  zip de GitHub, sin necesitar git), `jp --instalar ./carpeta` (local),
  `jp --instalar` (las `dependencias` del `paquete.json` del proyecto),
  `jp --instalar --aqui` (a `./paquetes` en vez de `~/.jp/paquetes`),
  `jp --paquetes` (listar) y `jp --quitar-paquete nombre`.
- **`importar "@paquete"`** en el árbol y en la VM: se busca en
  `paquetes/` junto al archivo, `paquetes/` del trabajo, `$JP_PAQUETES`
  y `~/.jp/paquetes`. Sin instalar: error que dice cómo instalarlo.
- **Primer paquete del ecosistema**: `paquetes/saludos` vive en este
  repo y se instala de verdad con
  `jp --instalar github:SoyJuanPiece/jp-lenguage/paquetes/saludos`.
  Cualquiera con un repo de GitHub ya puede publicar el suyo.

## 1.20.0 — «Proyecto» (2026-10-19)

- **`jp --proyecto nombre`**: crea un proyecto JP listo para correr —
  `principal.jp` (fibonacci de bienvenida), `pruebas/` con su primera
  prueba y una copia viajera de `pruebas.jp`, y un `LEEME.md` con ideas.
  Si la carpeta ya existe, no toca nada (exit 66).
- Ajuste: `jp --probar` sin archivos ahora descubre solo
  `*_prueba.jp` (antes ejecutaba también cualquier `.jp` de `pruebas/`,
  incluida la propia biblioteca de afirmaciones).

## 1.19.0 — «Web completa» (2026-10-19)

- **Archivos estáticos**: la respuesta `{archivo: "ruta"}` sirve los bytes
  con su tipo (HTML, CSS, SVG, imágenes...), y el framework gana
  `app.estatico("/static", "publica")` con patrones comodín
  (`/static/*` → `peticion.parametros.resto`). `biblioteca/ejemplo-web.jp`
  ya sirve su portada y su CSS así (`biblioteca/publica/`).
- **Cliente HTTP serio**: `pedir(url[, metodo, datos, cabeceras])` →
  `{estado, cuerpo, json, cabeceras}`. No lanza por un 404 (el estado
  viene en el diccionario), lee el JSON solo y manda dicts como JSON.
  Con servidor y cliente en el mismo lenguaje, JP se habla a sí mismo.
- `app.escuchar(puerto[, anfitrion])` admite `"0.0.0.0"`.

## 1.18.0 — «Formateador» (2026-10-19)

- **`jp --formatear archivo.jp`** (y `--en-sitio` para reescribirlo):
  reimprime el programa con el estilo de la casa — sangría de 4, bloques
  siempre en varias líneas, `} sino {` pegado, `caso` en línea cuando
  cabe — respetando la precedencia al poner paréntesis y escapando las
  llaves de las cadenas para no romper interpolaciones. El formateador
  es idempotente sobre los 45 archivos `.jp` del repo (test incluido).
  Ojo: pierde los comentarios, porque el parser no los conserva.

## 1.17.0 — «Depurador» (2026-10-19)

- **`jp --depurar programa.jp`**: depurador paso a paso sobre el
  intérprete de árbol. Pausa antes de cada sentencia (también dentro de
  funciones y bucles) con comandos en español: `s` siguiente, `c`
  continuar, `v <var>` ver una variable, `e <expr>` evaluar una expresión
  en el entorno vivo, `l` listar variables, `p <línea>` punto de
  interrupción y `q` salir. Sin terminal (EOF) continúa hasta el final
  sin bloquearse. El motor gana el gancho `Interprete.gancho_paso`.

## 1.16.0 — «Nativo seguro» (2026-10-19)

- **`??` y `?.` llegan al motor en C**: opcode nuevo
  `SALTO_NO_NULO_MANTENER` (55) en `jp/compilar_nativo.py` y en
  `motor-c/jpvm.c` (mira el tope sin popear, salta si no es `T_NULO`), con
  emisión para el operador y para índices/llamadas seguras. Lo que la
  v1.14 dejó rechazado limpiamente ya corre nativo, con salida idéntica
  verificada contra la VM (`tests/test_v24.py`).

## 1.15.0 — «Pruébalo» (2026-10-19)

- **Pruebas para programas JP** (`biblioteca/pruebas.jp`): `afirmar`,
  `afirmar_igual`, `afirmar_casi` (con tolerancia) y `afirmar_error`
  escritas en JP puro, con `resumen()` que cuenta y lanza si algo falló.
- **`jp --probar [archivos...]`**: corre cada archivo de prueba y resume
  «N/M archivos de prueba pasan», saliendo con 0 o 1 como cualquier
  corredor. Sin archivos descubre `pruebas/**/*.jp` y `./*_prueba.jp`.
  El repo estrena las suyas: `pruebas/mates_prueba.jp` (7 afirmaciones
  sobre `mates.jp` y `texto.jp`).

## 1.14.0 — «Sin nulos» (2026-10-19)

- **`a ?? b` (por defecto si es nulo)**: devuelve `a` salvo que sea
  `nulo`, y solo entonces calcula `b` (cortocircuito de verdad: la derecha
  ni se evalúa si no hace falta). Ojo: `falso ?? x` es `falso` y `0 ?? x`
  es `0` — solo manda el nulo. Asocia a la derecha (`a ?? b ?? c`).
- **`a?.b` / `a?.b()` / `a?.[i]` (acceso seguro)**: si `a` es `nulo`, toda
  la cadena da `nulo` sin evaluar el resto (ni índices ni argumentos). Sin
  el `?`, tocar un nulo sigue fallando como siempre, y asignar a un acceso
  seguro (`a?.b = 1`) es error de sintaxis con explicación.
- En el árbol y en la VM con paridad total (opcode nuevo
  `SALTAR_SI_NO_NULO`); el motor en C lo rechaza limpiamente y el CLI cae
  al motor de Python, como con el resto de novedades.

## 1.13.0 — «Persistencia» (2026-10-19)

- **Bases de datos SQLite** (`jp/basedatos.py`): `abrir_bd(ruta)` (o
  `":memory:"`), `bd_ejecutar` (devuelve filas afectadas, confirma solo),
  `bd_consultar` → lista de diccionarios lista para una `Tabla`, y
  `bd_cerrar`. Parámetros con `?` aparte del SQL (nada de comillas
  rompiendo consultas), errores de SQL como `ErrorEjecucion` en español.
  Con web + Tabla, JP ya hace aplicaciones completas con datos que se
  quedan guardados (`ejemplos/base-datos.jp`).

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
