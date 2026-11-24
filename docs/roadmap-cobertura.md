# 🧭 Plan de cobertura total

> De *"lenguaje pequeño que se lee como español"* a *"sirve para lo mismo que
> Python, Node, C++, Go y Rust"*.
>
> Regla del proyecto: **si no se puede medir, no entra al plan**. Cada fase de
> este documento se cierra con un **programa-puerta** que hoy falla y después
> corre, y con una cifra que se compara contra una línea base.

---

## 0. Qué significa "servir para todo" (definición operativa)

Ningún lenguaje sirve literalmente para todo. "Cobertura total" aquí significa
una cosa concreta: **para cada dominio de la tabla, existe al menos un programa
real que corre en JP con un solo comando y sin salir a otro lenguaje**.

| Dominio | Quién lo domina | Programa-puerta (lo que debe correr en JP) |
|---|---|---|
| Scripts y automatización | Python | tarea que lee CSV, filtra, escribe informe y manda correo |
| CLI | Go, Rust | herramienta con subcomandos, `--ayuda`, código de salida y binario único |
| API / backend web | Node, Go | 3 rutas, JSON, sesión, SQLite, 1.000 peticiones concurrentes |
| Datos y estadística | Python | 1M de filas agrupadas y promediadas sin reventar la memoria |
| Cálculo numérico | Python, C++ | multiplicación de matrices 500×500 en tiempo razonable |
| Concurrencia | Go | 10 tareas en 4 hilos con cola y cancelación, sin corromper el GC |
| Red y protocolos | Node, Go | cliente HTTPS con certificado real y servidor WebSocket |
| Sistemas / FFI | C++, Rust | llamar a `libz`, `libcurl` y `sqlite3` desde JP |
| Rendimiento | C++, Rust | `fib(35)` dentro de 3x de C compilado con `-O2` |
| Escritorio y 2D | C++, Rust | ventana con botón y bucle de dibujo (vía FFI) |
| Paquetes | todos | instalar `paquete@1.2.3` con versiones y *lockfile* |

Fuera de alcance (y se dice en voz alta): embeber en microcontroladores,
drivers del kernel, ABI completa de C++, apps móviles nativas y frameworks de
interfaz web. Ver §7.

---

## 1. La aritmética que hunde el plan (y la decisión que lo salva)

Hoy una feature de lenguaje hay que escribirla en **ocho capas**:

| # | Capa | Archivo |
|---|---|---|
| 1 | Lexer | `motor-c/lexer.c` + `jp/lexer.py` |
| 2 | Parser y AST | `motor-c/parser.c`, `motor-c/ast.c`, `jp/parser.py`, `jp/arbol.py` |
| 3 | Compilador a `.jpb` | `motor-c/compilar.c` + `jp/compilar_nativo.py` |
| 4 | VM en C | `motor-c/jpvm.c` |
| 5 | VM sobre Python | `jp/vm.py` |
| 6 | Intérprete de árbol | `jp/interprete.py` |
| 7 | Resaltado | `tree-sitter-jp/grammar.js` |
| 8 | Editor | `jp/lsp.py` |

A ese ritmo, `async` cuesta ocho implementaciones y ocho juegos de tests.
**Decisión que hace viable todo lo demás:** a partir de 1.35 el **motor en C es
la implementación de referencia** y la única que recibe features nuevas; los
motores de Python se congelan (siguen ejecutando lo que ya saben) y se retiran
en 2.0 con aviso de un año. De ocho capas se baja a **cuatro** (1-4, más 7-8
que se generan desde la gramática). Sin ese recorte, este plan no termina nunca.

---

## 2. Punto de partida honesto (2026-11-23)

| Pieza | Estado |
|---|---|
| Frontend propio en C (lexer, parser, compilador `.jpb`, VM) | ✅ 48/48 AST, 40/40 `.jpb` byte a byte |
| Nativas en C | 103 (faltan red, SQLite, imágenes, procesos) |
| Nativas en Python | 149 |
| Concurrencia | sólo `iniciar_proceso` (procesos del SO) |
| Enteros | 64 bits en C, arbitrarios en Python → JP cambia de comportamiento según el motor |
| Paquetes | copiar carpeta o `github:usuario/repo`, sin versiones |
| Herramientas | `--check`, `--revisar`, `--formatear`, `--cobertura`, `--depurar`, `--probar`, LSP, tree-sitter |
| Rendimiento | 2,7x sobre CPython en el *benchmark* mixto |

La deuda que había aquí (`.codebuff_tmp/` sin ignorar, 5 ramas fusionadas y
ningún medidor de cobertura) se pagó en la fase F0: hoy
`python herramientas/cobertura.py` dice, dominio por dominio, qué corre y qué
no, y con qué motivo.

---

## 3. Fases

Cada fase trae: versión, contenido, capas que toca, **puerta de aceptación**
medible y esfuerzo estimado para **una persona a media jornada**.

### ✅ F0 — v1.35 · Cimientos y medidor (hecha el 2026-11-24)

- `.codebuff_tmp/` a `.gitignore`; borrar las ramas fusionadas. ✅
- `herramientas/cobertura.py`: corre un programa-puerta por dominio y escupe
  una tabla `dominio · estado · motivo`. Es el marcador de todo el plan. ✅
- Fijar el *benchmark* en CI con umbral: una regresión de más del 10% falla. ✅
  (`herramientas/benchmark.py`, línea base por plataforma en
  `pruebas/linea-base-rendimiento.json`)

**Puerta:** ✅ `herramientas/cobertura.py` imprime los 11 dominios con estado y
motivo; `git status` limpio; paridad 48/40 y suite en verde.

**Resultado medido:** **2/11** dominios cubiertos (datos y cálculo numérico).
Los otros nueve ya traen su motivo exacto, que es la lista de tareas:
`correo` (F4), `argumentos`/`salir` (F1), `servir` (F4), `canal` (F5),
`http_get`+`websocket` (F4), `externo` y el tipo `puntero` (F3), `ventana`
(F9), versiones en `paquete.json` y `jp.lock` (F6) y `fib(35)` a 13x del C
`-O2` cuando el objetivo es 3x (F8).

### F1 — v1.36 · Ergonomía diaria (≈2 semanas) — ✅ cerrada

Comprensiones de lista, diccionario y con filtro; rebanadas (`l[1:3]`,
`l[::-1]`); `enumerar`, `zip`, `rango(a, b, paso)`; `para i, v en lista`;
`argumentos()` y `salir(código)`, que son lo que la puerta de CLI pide antes
que nada.

```jp
variable dobles = [x * 2 para x en numeros si x > 0]
variable mitad = texto[0:5]
para i, nombre en nombres { imprime(i, nombre) }
imprime({clave: valor para clave en notas})
```

**Puerta:** 30 programas nuevos en `pruebas/` que usan **sólo** sintaxis nueva,
todos en verde en el motor C, y tree-sitter + LSP reconocen lo nuevo.

**Estado (2026-11-24): cerrada.**

- ✅ `argumentos()` y `salir(código)` en los dos motores, con el código de
  salida pasando por `jp` y por `jp --c`. La puerta de CLI ya pasa.
- ✅ `enumerar(lista, inicio)` y `zip(a, b, ...)`, idénticos en C y Python.
- ✅ Rebanadas `x[a:b:c]` (partes opcionales, negativos y paso, en listas y
  textos): el parser las convierte en `rebanada(objeto, inicio, fin, paso)`,
  así que no hizo falta bytecode nuevo.
- ✅ **Comprensiones** de lista y de diccionario, con `si` de filtro y anidables:
  `[x * 2 para x en xs si x > 0]`, `{k: v para k en d}`. También son azúcar del
  parser: se convierten en `mapear`/`filtrar` con una `funcion` anónima, y las
  de diccionario en `a_diccionario(mapear(...))` (nativa nueva, en los dos
  motores). Cero nodos nuevos, cero bytecode nuevo, misma paridad.
  - Sólo una cláusula `para` por comprensión (no hay `para … para …`).
  - Las claves de los diccionarios son texto en todo el lenguaje, también aquí.
- ✅ `para i, v en ...` ya existía (índice/valor en listas, clave/valor en
  diccionarios) y se queda como está: cambiarlo rompía `biblioteca/ia.jp`,
  `biblioteca/graficas.jp` y `ejemplos/ia-perceptron.jp`.
- ✅ `rango()` daba resultados distintos en C (`rango(3)` empezaba en 1 y con
  dos números descendía solo); ya es igual que en Python.
- ✅ **Puerta cumplida**: 30 programas en `pruebas/f1/` (comprensiones, rebanadas,
  `enumerar`, `zip`, `rango`, `para i, v`, `argumentos`, `salir`) con paridad
  exacta en los dos motores, más 30/30 de AST y de bytecode. `tree-sitter`
  reconoce comprensiones (`comprension_lista`, `comprension_diccionario`) y
  rebanadas (nodo `rebanada`): los 65 `.jp` del repo parsean sin `ERROR`. El
  LSP no necesitó cambios: usa el mismo parser y saca las nativas de la tabla
  del intérprete, así que `a_diccionario` aparece sola.

### F2 — v1.38 · Generadores e iteradores perezosos (≈3 semanas)

> Se adelantó F3 a 1.37: el §4 pone el FFI como el número 1 por impacto ÷
esfuerzo, y sin él ni la red ni SQLite ni las imágenes se pueden usar. Los
generadores no cambian qué se puede hacer, sólo cuánto ocupa hacerlo.

`cede` (equivalente a `yield`), `siguiente(iter)`, funciones generadoras,
`para` sobre generador, `mapa`/`filtro` perezosos.

**Puerta:** `para x en contador(10_000_000)` con memoria constante (medida con
`plataforma()` y el contador del GC); `siguiente()` manual; 3 ejemplos nuevos.

### F3 — v1.37 · FFI: el multiplicador (≈4 semanas) — base hecha

`dlopen`/`dlsym`, declaración de funciones externas con tipos C, cadenas,
enteros, punteros opacos, *structs* por valor y **callbacks de C a JP**.

```jp
externo "libz" {
  funcion comprimir(destino: puntero, n: entero) -> entero
}
```

**Puerta:** llamar a `libz`, a `libcurl` y a `sqlite3` desde JP en Linux y
Windows; un callback de C que invoque una función JP; 3 ejemplos nuevos.
Esta fase es la que convierte "no tengo numpy" en "uso numpy".

**Estado (2026-11-24): base hecha en 1.37.0.** El dominio «Sistemas / FFI» ya
pasa en el medidor: `externo` enlaza bibliotecas de verdad y zlib comprime
9.000 bytes a 53 desde JP, y sqlite3 abre en memoria, crea una tabla e inserta
3 filas. Lo que hay:

- ✅ `externo "lib" { funcion f(a: tipo, ...) -> tipo }` como azúcar del parser
  (cero nodos, cero bytecode), con `dlopen`/`LoadLibrary` en la VM.
- ✅ `entero`, `texto`, `puntero` y `booleano` como argumentos; `entero`,
  `numero`, `texto`, `puntero`, `booleano` y `nulo` como retorno.
- ✅ Tipo `puntero` opaco, `reservar`/`liberar`/`leer_*`/`escribir_*` para las
  funciones que devuelven por puntero, y errores atrapables.
- ✅ Búsqueda de la biblioteca por nombres reales (`libz.so.N`, `zlib1.dll`,
  `sqlite3.dll`, ...), con `externo "c"` para el runtime de C.
- ✅ 7 programas en `pruebas/f3/` y un ejemplo (`ejemplos/ffi-libc.jp`).

Lo que falta para tacharla del todo: argumentos `numero` (`double`), *structs*
por valor, **callbacks de C a JP** (el camino inverso), `libcurl` probado en CI
y los 3 ejemplos del plan. Mientras eso no esté, la fase no se tacha: la base
corre, la puerta entera no.

### F4 — v1.39 · Red de verdad en C (≈4 semanas)

`http_get`/`http_post` con TLS (vía FFI a OpenSSL o mbedTLS, dependencia
opcional en tiempo de compilación), servidor HTTP con rutas y plantillas,
sesiones, WebSocket, DNS, timeouts y `correo` (SMTP), que es la segunda mitad
de la puerta de scripts.

**Puerta:** servidor con 3 rutas, JSON y sesión atendiendo 1.000 peticiones
concurrentes desde `jpvm` **sin Python**; cliente HTTPS con certificado real;
los 8 ejemplos que hoy exigen Python corren en C.

### F5 — v1.40 · Concurrencia (≈6 semanas)

Modelo elegido: **tareas con hilos del SO y un cerrojo global** (estilo GIL),
no `async` con coloreo. `tarea`, `esperar`, canales, temporizadores y
cancelación. Requiere GC seguro entre hilos: pausa del mundo o GC por hilo.

**Puerta:** 10 tareas en 4 hilos, 1.000.000 de operaciones, 100 corridas de
`--probar` sin corrupción del montículo; servidor de F4 con *pool* de hilos.

### F6 — v2.0 · Paquetes y ecosistema (≈6 semanas)

Registro con versiones semánticas, `jp.lock` con hashes, índice de paquetes,
`jp --instalar nombre@1.2.3`, binarios precompilados por plataforma, documentación
generada de las 149+ nativas con un ejemplo por función, LSP completo
(autocompletado de biblioteca y de paquetes).

**Puerta:** instalar dos versiones del mismo paquete en árboles distintos con
*lockfile* reproducible; `pipx install jp-lang && jp --c hola.jp` en máquina
limpia; `docs/referencia.md` regenerada sin intervención manual.

> **Corte 2.0:** aquí se retiran los motores de Python y se declara el motor C
> como único. Es el punto de no retorno de la decisión de §1.

### F7 — v2.1 · Datos y números (≈4 semanas)

Bignums (o error claro y explícito), `decimal`, conjuntos, ordenamiento estable
con clave, CSV en *streaming*, SQLite por FFI, matrices y estadística portadas.

**Puerta:** `2 ** 200` exacto; 1M de filas agrupadas en menos de 3 s y menos de
200 MB; 100.000 *inserts* en SQLite; igual resultado en C y en Python.

### F8 — v2.2 · Rendimiento de verdad (≈8 semanas)

Compilación AOT por función (N-7), tipos opcionales **verificados** que el
compilador pueda aprovechar, GC generacional, caché de métodos, superinstrucciones.

**Puerta:** `fib(35)` dentro de 3x de C `-O2`; `benchmark-grande.jp` sin VM en
el camino caliente; el JIT de Python se retira o queda como referencia.

### F9 — v3.0 · Interfaz y 2D (≈6 semanas, opcional)

GUI nativa y ventana 2D por FFI a SDL/GTK/Win32. No se escribe un *toolkit*
propio: se envuelve lo que ya existe, que es lo que hacen Rust y C++.

**Puerta:** ventana con botón, entrada de teclado y bucle de dibujo a 60 fps,
en Linux y Windows.

---

## 4. Orden por impacto ÷ esfuerzo

| # | Qué | Impacto | Esfuerzo | Fase |
|---|---|---|---|---|
| 1 | FFI | desbloquea todo el universo de bibliotecas de C | 4 sem | F3 |
| 2 | Comprensiones y rebanadas | se usan todos los días | 2 sem | F1 |
| 3 | Red en C | quita la dependencia de Python de 8 ejemplos | 4 sem | F4 |
| 4 | Paquetes con versiones | sin esto no hay ecosistema | 6 sem | F6 |
| 5 | Generadores | iteradores perezosos y *streaming* | 3 sem | F2 |
| 6 | Concurrencia | servicios de verdad | 6 sem | F5 |
| 7 | Bignums y conjuntos | corrige una diferencia entre motores | 4 sem | F7 |
| 8 | AOT | cierra la brecha de rendimiento con C | 8 sem | F8 |

Total hasta v2.0: **≈7 meses** a media jornada. Hasta v3.0: **≈11 meses**.
Son estimaciones de una persona, no promesas: cada fase puede duplicarse si
aparece un fallo de diseño en el GC o en el FFI.

---

## 5. Reglas de trabajo (el contrato)

1. **C primero.** Toda feature nueva nace en `motor-c/`; los motores de Python
   sólo la reciben si es trivial y hasta 2.0.
2. **Cuatro capas, no ocho.** Lexer, parser/AST, compilador y VM. tree-sitter y
   LSP se actualizan en el mismo *commit*.
3. **Nada entra sin programa-puerta.** El ejemplo se escribe antes que el código
   y vive en `pruebas/`.
4. **Retrocompatibilidad estricta en 1.x.** Las rupturas van en 2.0 y 3.0, con
   `jp --migrar` y una versión de aviso previa.
5. **Cada fase cierra** con CHANGELOG, versión, `docs/referencia.md`, paridad y
   CI verde. Si algo de eso falta, la fase no está hecha.

---

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Mantener 4 capas sigue siendo mucho para una persona | el frontend ya está portado; el trabajo futuro es incremental, no reescritura |
| TLS añade la primera dependencia externa | FFI opcional: si no hay OpenSSL, `http_get` avisa y ofrece sólo HTTP plano |
| Hilos + GC *mark-and-sweep* es delicado | cerrojo global, como CPython; paralelismo real sólo en FFI y procesos |
| Bignums rompen el rendimiento y la paridad | modo explícito (`entero_grande`), 64 bits por defecto |
| Un registro de paquetes necesita infraestructura y confianza | empezar con índice estático en un repositorio Git y hashes; servidor después |
| El autor es una sola persona | el plan está ordenado para que **cada fase sirva sola**, sin depender de la siguiente |

---

## 7. Lo que este plan NO incluye

- Embeber en microcontroladores, RTOS o kernel.
- ABI completa de C++ (sólo funciones con enlace C).
- Un *framework* de interfaz web (se sirve HTML y JSON; el navegador hace el resto).
- Apps móviles nativas.
- Reemplazar a `numpy` o `pandas` con implementación propia: se usan por FFI o
  se escribe la parte que falte.
- Cambiar la sintaxis por moda: JP ya eligió "fácil primero".

---

## 8. Decisiones que necesito de ti

1. **¿Congelamos los motores de Python en 1.35** y los retiramos en 2.0?
   Sin esto, cada fase cuesta el doble.
2. **¿Hilos con cerrojo global o `async`/`await`?** La recomendación es hilos:
   `async` contamina toda función que toque red o disco.
3. **¿FFI antes que red?** La recomendación es sí: TLS, SQLite y curl llegan
   gratis por FFI en vez de reescribirse.
4. **¿Aceptas una dependencia opcional de C** (OpenSSL/mbedTLS) a cambio de
   HTTPS? La alternativa es no tener HTTPS nativo.
5. **¿La 2.0 rompe sintaxis** o se queda sólo en retirar motores?

---

## 9. Seguimiento

- Marcador único: `python herramientas/cobertura.py` → tabla de 11 dominios.
- Cada fase añade su programa-puerta a esa tabla y a `pruebas/`.
- `PLAN.md` guarda el detalle histórico; este documento manda en el orden.
- Una fase se tacha **sólo** cuando su puerta corre en CI, no cuando compila.
- Cada «no» de la tabla es una fila de trabajo: el medidor es también la lista
  de tareas. Estado al cerrar F0: 2/11 dominios (datos y cálculo numérico).
  Al cerrar F1: **3/11**, porque la puerta de CLI ya pasa. Con la base de F3:
  **4/11** (Sistemas / FFI), medido con zlib y sqlite3 instalados.
