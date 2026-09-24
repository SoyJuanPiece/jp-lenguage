# JP — un pequeño lenguaje de programación en español 🇪🇸

**JP** es un lenguaje de programación hecho desde cero, con palabras clave en
español y una sintaxis pensada para ser **lo más fácil posible**:

- ✍️ Sin paréntesis obligatorios: `si edad >= 18 { ... }`
- 📝 Una sola línea sin llaves: `si 1 < 2: imprime("sí")`
- 🇪🇸 Palabras en español con alias: `variable`, `funcion`, `devuelve`, `imprime`
- 🔢 Rangos inclusivos intuitivos: `para i en 1..5`
- 💬 Comillas simples o dobles: `'hola'` y `"hola"`
- 📦 Diccionarios: `variable d = {clave: valor}` y acceso `d.clave`
- 🌐 Internet incluido: `http_get`, `json_leer`, bots de Telegram en 10 líneas

```
código .jp → [Lexer] → tokens → [Parser] → AST → [Compilador] → bytecode → [VM] → resultado
                                                            └─ (modo --interprete: AST → ejecución)
```

Desde la v0.4 el programa se **compila a bytecode** y se ejecuta en una máquina
virtual (threaded code por cierres). El intérprete de árbol original sigue
disponible con `python -m jp --interprete archivo.jp`.

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

### Números y cadenas

```jp
"hola" + " " + "mundo"   # => "hola mundo"
'hola' + 42               # comillas simples o dobles
"ab" * 3                  # => "ababab"
[1, 2] + [3]              # => [1, 2, 3]
lista[0]                  # indexar
lista[-1]                 # índice negativo = desde el final
```

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
│   ├── interprete.py    # AST -> ejecución (modo --interprete)
│   ├── red.py           # HTTP, JSON, bots (urllib estándar)
│   └── cli.py           # CLI + REPL
├── tests/
│   ├── test_jp.py       # lenguaje completo (81 tests)
│   └── test_vm.py       # paridad VM vs árbol (32 tests)
├── ejemplos/            # programas de muestra .jp
└── pyproject.toml       # para instalar el comando jp
```

## Próximos pasos posibles

- Strings interpolados `"hola {nombre}"`
- Websockets (bots de Discord en vivo)
- Bootstrapping: reescribir el intérprete... ¡en el propio JP!

## Estado

v0.6.0 — **modo turbo** (`--turbo`): si un programa es puro (sin teclado, red,
archivos ni azar), JP lo evalúa completo una vez, cachea la salida (`.jpc`)
y las ejecuciones siguientes son microsegundos. Medido con el mismo programa
en ambos runtimes (while 5M + fib(25)):

| Runtime | Tiempo |
|---|---|
| Python (mismo runtime, in-process) | 1.315,7 ms |
| **JP --turbo (cache en memoria)** | **0,0086 ms** |
| Ratio | **≈ 152.000x más rápido** |

La primera corrida paga el costo (compila y ejecuta una vez); las siguientes
no vuelven a ejecutar el programa: imprimen el resultado cacheado, como el
`constexpr` de C++ llevado al programa entero. Si el programa usa algo impuro,
el turbo se rinde con gracia y corre en la VM normal.

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
