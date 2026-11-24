# JP frente a Python y otros lenguajes

JP es un lenguaje de scripts **dinámico**, con palabras clave en español y
motor propio (bytecode `.jpb` ejecutado por una VM en C11). La comparación
justa no es "JP contra Rust": es **JP contra Python para programas pequeños y
medianos**, que es donde compite de verdad. Este documento dice qué gana JP,
qué pierde y con qué datos.

## 1. Ficha técnica

| | JP 1.34 | Python 3.14 | JavaScript (Node) | Go | Rust | C |
|---|---|---|---|---|---|---|
| Palabras clave | español | inglés | inglés | inglés | inglés | inglés |
| Tipado | dinámico; anotaciones opcionales que revisa `--revisar` | dinámico + type hints | dinámico (TypeScript: estático) | estático | estático | estático |
| Cómo se ejecuta | bytecode en VM C11 (`jpvm`), VM sobre Python, JIT x86-64 opcional | bytecode de CPython | JIT (V8) | binario nativo | binario nativo | binario nativo |
| Memoria | recolector mark-and-sweep en el motor C | conteo de referencias + GC de ciclos | GC generacional | GC concurrente | *ownership*, sin GC | manual |
| Enteros | 64 bits en el motor C | precisión arbitraria | dobles de 53 bits (BigInt aparte) | 64 bits | 64/128 bits | según el tipo |
| Concurrencia | procesos del SO (`iniciar_proceso`); sin hilos ni `async` | hilos, `asyncio`, `multiprocessing` | *event loop*, *workers* | goroutines | hilos/`async` (tokio) | pthreads |
| Biblioteca | 149 nativas en el motor Python, 103 en el de C | PyPI (cientos de miles) | npm (millones) | estándar + proxy | crates.io | libc |
| Herramientas | `--check`, `--revisar`, `--formatear`, `--cobertura`, `--depurar`, `--probar`, LSP y tree-sitter | maduras | maduras | buenas | excelentes | mínimas |
| Curva de entrada | muy baja | baja | media | media | alta | alta |

## 2. Lo que JP hace distinto (y a veces mejor)

- **Se lee como español.** `si edad >= 18 { ... }`, `para i en 1..5 { ... }`,
  `mientras haya turnos { ... }`. Sin paréntesis obligatorios y con alias
  (`variable`/`var`, `funcion`/`fun`, `devuelve`/`retorna`).
- **Rangos inclusivos.** `1..5` incluye el 5. En Python `range(1, 5)` lo deja
  fuera y es uno de los errores clásicos de quien empieza.
- **Texto en español de verdad.** `longitud("Maturín")` es 7 y
  `mayusculas("ñandú")` es `ÑANDÚ`, también en el motor en C.
- **Una línea sin llaves.** `si 1 < 2: imprime("sí")`, sin bloques de tres
  líneas para una decisión de una.
- **Decisiones y errores explícitos.** `elegir n { caso 1 { ... } sino { ... } }`
  y `intenta { ... } atrapa error { ... } finalmente { ... }`.
- **Todo incluido.** HTTP, JSON, CSV, SQLite, SVG, matrices, estadística y
  vectores vienen en la biblioteca: no hay `pip install` para empezar.
- **Un ejecutable de verdad.** `jp --binario` deja un binario con el bytecode
  dentro que no necesita Python ni JP para correr.
- **Un solo comando para todo.** `jp --probar`, `--cobertura`, `--formatear`,
  `--depurar`, `--revisar` y `--instalar github:usuario/repo`. Python tiene lo
  mismo, pero repartido en `pytest`, `coverage`, `black`, `pdb`, `mypy` y `pip`.
- **Errores en español con el fuente señalado**, línea y columna.

## 3. Lo que Python y los demás tienen y JP no

| Falta en JP | Quién lo tiene | Qué implica en la práctica |
|---|---|---|
| Comprensiones (`[x*2 para x en l]`) | Python, JS, Ruby | se usa `mapear`/`filtrar` |
| Generadores (`yield`) y `async`/`await` | Python, JS, Rust | sin iteradores perezosos ni concurrencia cooperativa |
| Rebanadas (`l[1:3]`) | Python, JS, Go | solo índices sueltos (los negativos sí funcionan) |
| Hilos reales | casi todos | paralelismo solo con procesos del SO |
| Decoradores, metaclases, sobrecarga de operadores | Python, Ruby, C++ | el modelo de objetos es simple a propósito |
| Precisión arbitraria en el motor C | Python, BigInt en JS | los enteros grandes se cortan a 64 bits |
| Biblioteca mantenida por miles de personas | todos | si falta algo, lo escribes tú |
| Registro central de paquetes con versiones | todos | `--instalar` copia carpetas o repos de GitHub |
| Verificación estática de tipos que impida ejecutar | Go, Rust, TypeScript | `--revisar` avisa, pero no bloquea |

## 4. Rendimiento (medido, no de folleto)

Mismo trabajo: bucle `mientras` de 1.000.000 de vueltas + `fib(22)` recursivo.
Windows 11, tiempo total del proceso (incluye el arranque), mejor de 2 corridas.

| Motor | Tiempo | Frente a CPython |
|---|---|---|
| **JP, motor en C** (`jpvm archivo.jp`) | **0,144 s** | **2,7x más rápido** |
| CPython 3.14 (el mismo algoritmo en Python) | 0,394 s | 1x |
| JP, VM sobre Python | 5,43 s | 13,8x más lento |

Con el JIT (`--nativo`, solo cálculo numérico) el proyecto documenta 19–73x
sobre Python en `fib` y sumas de millones; el motor en C **no** tiene JIT y
compensa con bytecode más simple y un recolector propio.

Contra Go o Rust, JP pierde por uno o dos órdenes de magnitud. No es su liga:
su liga es "scripts que se leen como español y arrancan sin instalar nada".

## 5. Cuándo usar qué

| Quiero… | Usa |
|---|---|
| enseñar a programar, o un programa de una persona y pocos cientos de líneas | **JP** |
| un bot, una API pequeña, una gráfica, un ejercicio, una red neuronal didáctica | **JP** |
| `numpy`, `pandas`, `torch`, o `async`/hilos de verdad | Python |
| interfaz en el navegador | JavaScript/TypeScript |
| un servicio de red con concurrencia y un binario fácil de desplegar | Go |
| rendimiento y control de memoria | Rust o C |

## 6. Lo que le falta a JP para dejar de ser "un lenguaje pequeño"

1. **Comprensiones, generadores y `async`**: los tres pilares de la ergonomía
   moderna. Sin ellos, cada programa arrastra un poco más de ceremonia.
2. **Red en el motor en C**: `http_get`, `http_post`, Telegram y Discord solo
   existen en el motor de Python, así que esos 8 ejemplos no corren sin Python.
3. **Paquetes con versiones** y un índice, en vez de copiar carpetas.
4. **Documentación generada** de las 149 nativas, con un ejemplo por función.
5. **Más de una persona manteniéndolo**: es el factor que decide si un lenguaje
   crece o se queda en casa.
