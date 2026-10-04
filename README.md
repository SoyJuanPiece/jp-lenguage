# JP — un pequeño lenguaje de programación en español 🇪🇸

**JP** es un lenguaje de programación hecho desde cero, con palabras clave en
español y una sintaxis pensada para ser **lo más fácil posible**:

- ✍️ Sin paréntesis obligatorios: `si edad >= 18 { ... }`
- 📝 Una sola línea sin llaves: `si 1 < 2: imprime("sí")`
- 🇪🇸 Palabras en español con alias: `variable`, `funcion`, `devuelve`, `imprime`
- 🔢 Rangos inclusivos intuitivos: `para i en 1..5` (con paso: `1..10 paso 3`)
- 💬 Comillas simples o dobles: `'hola'` y `"hola"`
- 📦 Diccionarios: `variable d = {clave: valor}` y acceso `d.clave`
- 🌐 Internet incluido: `http_get`, `json_leer`, bots de Telegram en 10 líneas
- 🧠 Funciones como valores: `mapear(lista, funcion(x) { devuelve x * 2 })`
- 🎯 Decisiones claras: `elegir n { caso 1 { ... } sino { ... } }`
- 🛡️ Errores que no tumban el programa: `intenta { ... } atrapa error { ... }`
- ⚡ Azúcar cómodo: `x += 1`, `2 ** 10`, `promedio *= 2`

```
                                  ┌─ [--nativo: JIT a x86-64 para funciones numéricas]
código → Lexer → Parser → AST → [Compilador] → bytecode → [VM] → resultado
                            └─ [--turbo: evalúa todo y cachea]
                            └─ (--interprete: AST → ejecución)
```

Desde la v0.4 el programa se **compila a bytecode** y se ejecuta en una máquina
virtual (threaded code por cierres). Con `--nativo`, las funciones numéricas
se compilan además a **código de máquina x86-64** y la CPU las ejecuta
directamente (con recursión nativa y convención SysV). El intérprete de árbol
original sigue disponible con `python -m jp --interprete archivo.jp`.

## Uso

```bash
cd jp-lang

# Ejecutar un archivo
python -m jp ejemplos/hola.jp

# Ejecutar código directo
python -m jp -c 'muestra("hola" + " " + "mundo")'

# REPL interactivo
python -m jp

# Modo turbo: programas puros corren en microsegundos (cache total)
python -m jp --turbo ejemplos/benchmark-grande.jp
```

O instálalo como comando global:

```bash
pip install -e .
jp ejemplos/hola.jp
```

## El lenguaje

Los ejemplos clásicos con paréntesis y llaves siguen funcionando (compatibilidad
hacia atrás), pero la forma fácil es la recomendada. Véase `ejemplos/facil.jp`.

### Variables

```jp
variable x = 10          # 'var' también vale
variable nombre = "Ana"
variable lista = [1, 2, 3]
x = x + 1
```

### Condiciones — sin paréntesis y con `:` para una línea

```jp
variable edad = 20
si edad >= 18 {
    imprime("adulto")
} sino si edad >= 13: imprime("adolescente")   # una sola línea, sin llaves
sino: imprime("niño")
```

### Bucles — rangos inclusivos `1..10`, con `romper` y `continuar`

```jp
para i en 1..5 { imprime(i) }     # 1,2,3,4,5 (¡inclusivo!)
para i en 5..1: imprime(i)        # 5,4,3,2,1 (¡al revés también!)
para f en ["a", "b"]: imprime(f)  # listas
variable cuenta = 0
mientras cuenta > 0: cuenta = cuenta - 1

mientras verdadero {                # menús y juegos
    variable opcion = leer("> ")
    si opcion == "salir": romper
    si opcion == "": continuar
    imprime("dijiste:", opcion)
}
```

### Funciones

```jp
funcion doble(n) {       # 'fun' también vale
    devuelve n * 2        # 'retorna' también vale
}
imprime(doble(21))       # => 42
```

Una función también es un valor que se escribe en el momento (anónima):

```jp
variable triple = funcion(x) { devuelve x * 3 }
variable fs = [funcion(x) { devuelve x + 1 }, triple]
imprime(fs[1](5))        # => 15
```

### Elegir (switch) — sin caída entre casos

```jp
variable opcion = 2
elegir opcion {
    caso 1 { imprime("uno") }
    caso 2, 3 { imprime("dos o tres") }    # varios valores por caso
    caso 4: imprime("cuatro")              # y también de una línea
    sino { imprime("otro") }               # opcional
}
```

Se ejecuta **un solo** bloque: el primero que coincide (no hay `romper` que
recordar) y, si ninguno coincide, el `sino`. Compara con la igualdad de JP
(`1 == verdadero` es falso) y los valores se evalúan en orden, de arriba abajo.

### Intentar / atrapar — los errores se pueden manejar

```jp
intenta {
    variable x = 10 / 0
} atrapa error {
    imprime("algo salió mal:", error)   # "algo salió mal: división por cero"
}
imprime("y el programa sigue 🎉")

funcion dividir(a, b) {
    intenta { devuelve a / b } atrapa e { devuelve "no se puede" }
}
```

Atrapa los errores de ejecución (división por cero, índices fuera de rango,
archivos, variables sin definir, tipos equivocados...). El nombre del error
solo existe dentro del bloque `atrapa`, y se puede omitir:

```jp
intenta { variable datos = leer_archivo("no-existe.txt") } atrapa { imprime("ups") }
```

`romper`, `continuar` y `devuelve` **no** son errores: siguen su camino normal.

### Rangos con paso

```jp
para i en 0..20 paso 5 { imprime(i) }   # 0, 5, 10, 15, 20
imprime(10..1 paso 4)                   # => [10, 6, 2]
imprime(1..9 paso 4)                    # => [1, 5, 9]
```

El paso es una magnitud (mayor que 0); la dirección la deciden los extremos,
así que `10..1 paso 4` baja sin sorpresas. `paso` solo es palabra clave dentro
de un rango: `variable paso = 2` sigue siendo un nombre válido.

### Potencia y asignación compuesta

```jp
2 ** 10          # => 1024
2 ** -1          # => 0.5
-2 ** 2          # => -4   (la potencia liga más que el menos unario)
2 ** 3 ** 2      # => 512  (asocia a la derecha)

variable vidas = 3
vidas -= 1       # vidas = vidas - 1
vidas *= 2       # vidas = vidas * 2
variable total = 0
para n en 1..10 { total += n }          # acumuladores cómodos
precios["pan"] += 0.5                   # también con listas[i] y d.clave
```

### Orden superior — funciones que reciben funciones

```jp
mapear([1, 2, 3], funcion(x) { devuelve x * 2 })          # => [2, 4, 6]
filtrar(1..10, funcion(x) { devuelve x % 2 == 0 })        # => [2, 4, 6, 8, 10]
reducir([1, 2, 3, 4], funcion(a, b) { devuelve a + b }, 0) # => 10
para_cada(["a", "b"], funcion(x) { imprime(x) })
ordenar(["bbb", "a"], funcion(x) { devuelve x.longitud() }) # => ["a", "bbb"]
```

Aceptan lo mismo que un `para ... en` (listas, texto, diccionarios y números)
y también existen como métodos: `[3, 1].ordenar()`, `"abc".mapear(f)`...
Se pueden encadenar para escribir tuberías de datos legibles:

```jp
variable caros = filtrar(gastos, funcion(g) { devuelve g.costo > 5 })
imprime(mapear(caros, funcion(g) { devuelve g.nombre }))
```

### Números y cadenas

```jp
"hola" + " " + "mundo"   # => "hola mundo"
'hola' + 42               # comillas simples o dobles
"ab" * 3                  # => "ababab"
[1, 2] + [3]              # => [1, 2, 3]
lista[0]                  # indexar
lista[-1]                 # índice negativo = desde el final
```

### Interpolación — las dobles incrustan expresiones

```jp
variable nombre = "mundo"
variable edad = 25
"hola {nombre}!"                      # => "hola mundo!"
"en 10 años tendrás {edad + 10}"      # => "en 10 años tendrás 35"
"{2 * 3 + 1}"                         # => "7" (cualquier expresión)
"escape: \{esto no interpola}"        # => "escape: {esto no interpola}"
'crudo: {nombre}'                     # => "crudo: {nombre}" (simples = literales)
```

### Métodos de valor — las funciones viven en el propio valor

```jp
"hola".mayusculas()              # => "HOLA"
"  jp  ".recortar()              # => "jp"
"a,b,c".separar(",")             # => ["a", "b", "c"]
"banana".reemplazar("na", "NA")  # => "baNANA"
"banana".subtexto(1, 3)          # => "an"
"banana".letra(0)                # => "b"
"hola".contiene("ol")            # => verdadero
"hola mundo".longitud()          # => 10

variable lista = [1, 2]
lista.agregar(3)                 # => [1, 2, 3]
lista.contiene(2)                # => verdadero

variable d = {nombre: "jp", edad: 1}
d.claves()                       # => ["nombre", "edad"]
d.tiene("edad")                  # => verdadero
```

De la v1.3 hay bastantes más: `lista.ordenar()`, `lista.mapear(f)`,
`lista.sumar()`, `texto.empezar_con("ho")`, `d.valores()`, `d.elementos()`...
Los métodos viven en texto, listas y diccionarios; las matemáticas son
funciones normales (`raiz(x)`, `absoluto(x)`, `redondear(x, 2)`).

Son las mismas funciones de la librería estándar: `t.mayusculas()` es
`mayusculas(t)`. En diccionarios la clave gana sobre el método: con
`d = {claves: 99}`, `d.claves` sigue devolviendo 99.

## Librería estándar

| Función | Descripción |
|---------|-------------|
| `imprime(...)` / `muestra(...)` | Imprime valores separados por espacio |
| `longitud(x)` | Longitud de cadena o lista |
| `entero(x)` | Convierte a entero |
| `numero(x)` | Convierte a decimal |
| `texto(x)` | Convierte a texto |
| `rango(a[, b[, c]])` | Lista exclusiva: `rango(1, 5)` = 1,2,3,4 |
| `leer([mensaje])` | Lee una línea de entrada del usuario |
| `azar(n)` | Número al azar entre 1 y n (¡para juegos!) |
| `tiene(c, k)` | ¿Existe la clave/elemento en dict, lista o texto? |
| `claves(d)` | Lista de claves de un diccionario |
| `esperar(s)` | Pausa en segundos (bots) |
| `http_get(url)` | Petición HTTP GET, devuelve el texto |
| `http_post(url, cuerpo)` | HTTP POST (dict/lista → JSON automático) |
| `json_leer(t)` / `json_texto(v)` | Leer/generar JSON |
| `telegram_leer(token)` | Mensajes nuevos de Telegram |
| `telegram_responder(token, de, texto)` | Responder en Telegram |
| **Texto** | |
| `mayusculas(t)` / `minusculas(t)` | Mayúsculas / minúsculas |
| `recortar(t)` | Quita espacios de los extremos |
| `separar(t[, sep])` | Divide en lista: `separar("a,b", ",")` → `["a", "b"]` |
| `unir(lista[, sep])` | Une una lista en texto |
| `contiene(donde, que)` | ¿Está? (texto, lista o dict) |
| `reemplazar(t, a, b)` | Reemplaza en texto |
| `subtexto(t, ini[, fin])` | Pedazo de texto (soporta negativos) |
| `letra(t, i)` | Letra en posición `i` (soporta negativos) |
| `agregar(lista, v)` | Agrega al final de una lista |
| `reloj()` | Segundos (monotónicos) para cronometrar: `reloj() - reloj()` |
| **Matemáticas** | |
| `absoluto(x)` | Valor absoluto |
| `raiz(x)` | Raíz cuadrada |
| `potencia(a, b)` | `a` elevado a `b` (como `a ** b`) |
| `piso(x)` / `techo(x)` | Redondea hacia abajo / hacia arriba |
| `redondear(x[, dec])` | Redondeo de escuela: `redondear(2.5)` = 3 |
| `log(x[, base])` | Logaritmo (natural por defecto) |
| `minimo(...)` / `maximo(...)` | Menor/mayor de números o de una lista |
| `sumar(lista)` | Suma todos los números de una lista |
| `pi()` | 3.14159... |
| `aleatorio()` | Decimal al azar entre 0 y 1 |
| **Funciones y datos** | |
| `tipo(x)` | "número", "texto", "lista", "diccionario", "booleano", "nulo", "función" |
| `mapear(sec, f)` | Aplica `f` a cada elemento: devuelve lista nueva |
| `filtrar(sec, f)` | Deja los elementos donde `f` es verdad |
| `reducir(sec, f[, inicio])` | Acumula de izquierda a derecha en un solo valor |
| `para_cada(sec, f)` | Llama a `f` por cada elemento (por sus efectos) |
| `ordenar(sec[, clave])` | Copia ordenada (con función clave opcional) |
| `invertir(lista_o_texto)` | Copia al revés (no modifica el original) |
| `indice_de(sec, v)` / `buscar(t, sub)` | Posición de un valor, o -1 si no está |
| `insertar(lista, i, v)` | Inserta en la posición `i` (devuelve la lista) |
| `quitar(lista[, i])` | Quita por posición (la última si no se indica) y devuelve el elemento |
| `eliminar(lista, v)` | Quita la primera aparición de un valor (¿estaba?) |
| `empezar_con(t, pre)` / `terminar_con(t, suf)` | ¿Empieza/termina así? |
| `repetir(t, n)` | `"ab"` * 3 = `"ababab"` (también listas) |
| `unir(lista[, sep])` | Une una lista en texto |
| `elementos(d)` / `valores(d)` | Pares `[clave, valor]` / lista de valores de un diccionario |
| **Archivos** | |
| `leer_archivo(ruta)` | Lee un archivo de texto |
| `escribir_archivo(ruta, t)` | Crea/sobreescribe (UTF-8) |
| `agregar_archivo(ruta, t)` | Añade al final |
| `existe_archivo(ruta)` | ¿Existe? |
| `tamano_archivo(ruta)` | Tamaño en bytes |
| `lista_archivos(carpeta)` | Lista de nombres |

## Conectada a internet (v0.3)

Cualquier API REST queda al alcance: HTTP + JSON + diccionarios trabajan juntos.
Solo la librería estándar de Python (cero dependencias).

```jp
# Leer JSON de una API
variable datos = json_leer(http_get("https://api.ejemplo.com/datos"))
imprime(datos["nombre"])

# Enviar a Discord con un webhook (1 línea)
http_post("https://discord.com/api/webhooks/TU_WEBHOOK", {content: "¡Hola desde JP!"})

# Bot de Telegram completo: ejemplos/bot-telegram.jp
#   (o prueba la lógica sin internet con ejemplos/api-json.jp)
```

## Errores amigables

```
Error de sintaxis: se esperaba ')' tras los argumentos, pero se encontró '2'
    --> línea 3, columna 22
    3 | muestra(1 2)
      |                     ^
```

## Estructura del proyecto

```
jp-lang/
├── jp/
│   ├── __init__.py      # versión y docstring
│   ├── __main__.py      # python -m jp
│   ├── tokens.py        # tipos de token y palabras clave
│   ├── errores.py       # errores con línea y puntero
│   ├── lexer.py         # fuente -> tokens
│   ├── arbol.py         # nodos del AST
│   ├── parser.py        # tokens -> AST (con plegado de constantes)
│   ├── bytecode.py      # opcodes + chunk
│   ├── compilador.py    # AST -> bytecode
│   ├── vm.py            # máquina virtual (threaded code)
│   ├── nativo.py        # JIT: mini-ensamblador x86-64 + mmap RWX (SSE2 incl.)
│   ├── turbo.py         # evaluación total + cache .jpc
│   ├── interprete.py    # AST -> ejecución (modo --interprete)
│   ├── red.py           # HTTP, JSON, bots (urllib estándar)
│   └── cli.py           # CLI + REPL
├── tests/
│   ├── test_jp.py       # lenguaje completo (81 tests)
│   ├── test_vm.py       # paridad VM vs árbol (32 tests)
│   └── test_v13.py      # elegir, intenta, paso, **, += y orden superior (72)
├── ejemplos/            # programas de muestra .jp
│   ├── funcional.jp     # funciones anónimas y orden superior
│   ├── seguro.jp        # intenta/atrapa en acción
│   └── calculadora.jp   # elegir + intenta + leer (interactiva)
└── pyproject.toml       # para instalar el comando jp
```

## Los cuatro motores

JP trae cuatro formas de ejecutar el mismo código, con la misma semántica
(la paridad está garantizada por tests):

| Motor | Bandera | Cómo ejecuta tu código | Fuerte | Límite |
|---|---|---|---|---|
| Árbol | `--interprete` | Recorre el AST sentencia a sentencia | Es el "código fuente" del lenguaje; la referencia de verdad | El más lento |
| **VM** | *(por defecto)* | Bytecode + threaded code (cierres compilados) | Todo el lenguaje, siempre correcto | Vive dentro de Python |
| **JIT** | `--nativo` | Compila funciones numéricas a **x86-64 real** | 19–73x más rápido que Python en cálculo | Solo enteros/decimales; ≤3 parámetros; lo demás va a la VM |
| **Turbo** | `--turbo` | Evalúa todo en compilación y cachea la salida | Microsegundos en corridas repetidas | Solo programas puros (sin `leer`, `azar`, red, archivos, `reloj`) |

### Números medidos (misma máquina, Linux x86-64, Python 3.12)

| Programa | Árbol | VM | JIT | Turbo | Python |
|---|---|---|---|---|---|
| `benchmark.jp` (while 1M + fib(22)) | 11,3 s | **6,7 s** | parcial: fib nativo, bucle en VM (no medido) | 1ª ≈ VM → luego µs | 0,29 s |
| `benchmark-grande.jp` (while 5M + fib(25)) | — | ≈35 s (1ª) | — | 1ª ≈35 s → **0,0086 ms** después | 1,32 s |
| `benchmark-nativo.jp` (5M + fib(25) + armónica 2M) | — | 39,9 s | **0,104 s** | no aplica (usa `reloj()`) | 2,16 s |
| Micro in-process: suma 10M / fib(32) / armónica 10M | — | — | 44,7 / 36,2 / 63,9 ms | — | 3.274 / 694 / 2.908 ms |

Lecturas honestas: el JIT **le gana a Python en raw loop numérico** (19–73x);
el turbo le gana en *runtime* a todo (el trabajo se hace una sola vez);
y en cadenas/colecciones Python sigue adelante (30 años de C optimizado).

```bash
python -m jp archivo.jp                      # VM (recomendado para todo)
python -m jp --interprete archivo.jp         # árbol (referencia)
python -m jp --nativo archivo.jp             # JIT para cálculo numérico
python -m jp --turbo archivo.jp              # cache total para programas puros
```

## Próximos pasos posibles

- Websockets (bots de Discord en vivo)
- Módulos: `importar "utilidades.jp"` y biblioteca compartida
- Clases y objetos, o algo más sencillo: `objeto` + métodos
- Bootstrapping: reescribir el intérprete... ¡en el propio JP!

## Estado

v1.3.0 — **más expresivo y a prueba de errores**. Nuevo:

- 🎯 `elegir` / `caso` / `sino`: decisiones de varios caminos, sin caída
  entre casos y con varios valores por caso (`caso 2, 3 { ... }`).
- 🛡️ `intenta { ... } atrapa error { ... }`: los errores de ejecución se
  capturan (con nombre o anónimos) y el programa sigue. `romper`, `continuar`
  y `devuelve` atraviesan el `intenta` sin confundirse con errores.
- 🧠 Funciones anónimas (`funcion(x) { ... }`) como valores, con closures,
  y orden superior: `mapear`, `filtrar`, `reducir`, `para_cada` y `ordenar`
  con clave (también como métodos).
- 🔢 `paso` en los rangos: `para i en 0..20 paso 5`, `10..1 paso 4`.
- ⚡ `**` (potencia) y `+= -= *= /= %=` (asignación compuesta) con variables,
  `lista[i]` y `d.clave`.
- 🧮 Librería estándar ampliada: matemáticas (`raiz`, `absoluto`, `redondear`,
  `piso`, `techo`, `log`, `minimo`, `maximo`, `sumar`, `pi`, `aleatorio`),
  texto (`empezar_con`, `terminar_con`, `buscar`, `repetir`), listas
  (`ordenar`, `invertir`, `indice_de`, `insertar`, `quitar`, `eliminar`) y
  `tipo(x)`, `valores(d)`, `elementos(d)`.
- 🐛 Un bug de paridad de la VM: `devuelve` dentro de un `para` corrompía la
  pila (el árbol funcionaba). La VM ahora restaura el alto de pila al volver
  de una función. Detectado y cubierto con tests.

Todo implementado en **los dos motores** (árbol y VM) con paridad total,
más tests y ejemplos nuevos (`ejemplos/funcional.jp`, `ejemplos/seguro.jp`,
`ejemplos/calculadora.jp`). 245 tests.

v1.2.0 — **métodos de valor**: `"texto".mayusculas()`, `lista.agregar(x)`,
`d.claves()`... las funciones de la librería estándar ahora también se
llaman sobre el propio valor (`t.mayusculas()` es `mayusculas(t)`).
Disponibles en los dos motores (árbol y VM) con paridad total, y en
diccionarios la clave siempre gana sobre el método. 173 tests.

v1.1.0 — **interpolación de strings**: `"hola {nombre}, tienes {edad + 10}"
` incrusta cualquier expresión entre llaves en las cadenas con comillas
dobles (las simples quedan como literales crudos, y `\{` escapa).
Implementada en las 8 capas (lexer trocea y empalma tokens, parser,
intérprete, opcode INTERPOLAR en la VM) con paridad total. 162 tests.

v1.0.0 — **IA en JP puro**: `ejemplos/red-neuronal.jp` es una red neuronal
2-4-1 con backpropagation completa, y `ejemplos/red-profunda.jp` va más
lejos: arquitectura GENÉRICA configurada por la lista `capas` (2-4-4-1 por
defecto, prueba cambiarla), matrices construidas en runtime y
backpropagation que recorre cualquier profundidad. Ambas aprenden XOR
escritas solo con JP (listas, dicts, bucles, `exp`).

v0.9.0 — **benchmark nativo oficial**: `ejemplos/benchmark-nativo.jp`
(auto-cronometrado con la nueva nativa `reloj()`). El MISMO programa:

| Motor | Tiempo | vs Python (2,16s) |
|---|---|---|
| VM de bytecode | 39,9 s | 18x más lento |
| **JIT `--nativo`** | **0,104 s** | **21x más rápido** |

Carga: suma de 5M + fib(25) + armónica de 2M — resultados idénticos bit a bit
en ambos motores y contra Python.

v0.8.0 — **flotantes en el JIT** (`--nativo`): si una función usa `/` o
literales con punto, el lote compila a SSE2 double (`movsd`, `addsd`...,
constantes en pool RIP-relativo, args SysV por `xmm0-2`). Suma armónica de
10M: **JP 63,9 ms vs Python 2.907,9 ms = 45x más rápido**, resultado
idéntico al dígito.

v0.7.0 — **JIT nativo** (`--nativo`): compila funciones numéricas JP a código
de máquina x86-64 (ensamblador propio, mmap RWX, llamadas SysV, recursión
nativa) y las ejecuta la CPU directamente. fib(32): 19x · suma 10M: 73x.

**JP le gana a Python en raw loop numérico.** Lo que no califica (strings,
I/O, demasiadas variables) corre en la VM normal, siempre correcta. 152 tests.

v0.6.0 — **modo turbo** (`--turbo`): si un programa es puro (sin teclado, red,
archivos ni azar), JP lo evalúa completo una vez, cachea la salida (`.jpc`)
y las ejecuciones siguientes son microsegundos (≈152.000x en runtime).

v0.5.0 — `romper`/`continuar`, nativas de **texto** y de **archivos** (agenda
persistente incluida como ejemplo), con paridad total VM↔árbol.

143 tests en verde. v0.4.0 — **máquina virtual de bytecode**: el programa se
compila una vez y se ejecuta sobre pila con frames iterativos, closures
reales y threaded code. Rendimiento en `ejemplos/benchmark.jp` (while de 1M
+ fib(22) recursivo):

| Versión | Tiempo | Nota |
|---|---|---|
| v0.2 (árbol) | 14.4s | línea base |
| v0.3 (árbol optimizado) | 13.4s | plegado + despacho por tipo |
| v0.4 (**VM**) | **6.7s** | ~2x vs v0.3 · 1.7x A/B mismo momento |

El camino VM/árbol se compara con `python -m jp --interprete`. La semántica es
idéntica en ambos motores (los tests de paridad lo garantizan). El siguiente
salto vendría de locales por slots y opcodes especializados.
Hecho con cariño desde cero.
