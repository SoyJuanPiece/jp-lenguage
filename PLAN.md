# 🗺️ PLAN — cómo mejorar JP hasta la v2.0

> Documento de trabajo. Nace de una **auditoría del repositorio** hecha el
> 2026-10-11 sobre `v1.3.0` (commit `de767f5`). Todo lo que se afirma en la
> sección 1 se puede reproducir con los comandos del [anexo](#anexo--reproducir-la-evidencia).
> Si algo de este plan no se puede medir, no entra al plan.

---

## ⚡ NUEVO RUMBO (2026-10-12): un motor propio, independiente y rápido

> **La petición del autor:** *"optimización máxima, que no dependa de Python
> (como CPython, que es un ejecutable y no necesita otro lenguaje), rápido,
> completo y sin romper nada"*. Esto entra **delante** de todo lo de abajo:
> los T-20/T-21 (optimizar la VM de Python) pasan a segundo plano, porque el
> trabajo equivalente se hace ahora en el motor propio.

### Lo que ya está hecho y medido (v1.5.0)

| Pieza | Archivo | Estado |
|---|---|---|
| Compilador JP → bytecode `.jpb` (palabras u32, slots, celdas para closures, saltos relativos) | `jp/compilar_nativo.py` | ✅ |
| VM en C11 sin dependencias: despacho con *computed goto*, enteros con caminos rápidos, GC mark-and-sweep, closures por celdas, upvalues, iteradores, errores con línea y fuente | `motor-c/jpvm.c` | ✅ |
| Nativas en C: lenguaje (`longitud`, `entero`, `numero`, `texto`, `tipo`, `agregar`, `invertir`, `unir`, `rango`, `leer`), matemáticas (`raiz`, `absoluto`, `piso`, `techo`, `redondear`, `log`, `exp`, `seno`, `coseno`, `potencia`, `minimo`, `maximo`, `sumar`, `pi`, `reloj`, `aleatorio`, `azar`, `muestra/imprime`), texto (`mayusculas`, `minusculas`, `recortar`, `contiene`), **orden superior** (`mapear`, `filtrar`, `reducir`, `para_cada`, `ordenar`) y **archivos/JSON** (`existe_archivo`, `leer_archivo`, `escribir_archivo`, `tamano_archivo`, `lista_archivos`, `json_leer`, `json_texto`) | `motor-c/jpvm.c` | ✅ 63 |
| CLI: `--c` (ejecuta), `--compilar` (`.jpb`), `--bytecode` (desensambla), `--binario` (ELF independiente) | `jp/cli.py` | ✅ |
| **Ejecutables independientes**: el bytecode se enlaza con la VM y el resultado no necesita Python ni JP | `jp/cli.py` + símbolos débiles en `jpvm.c` | ✅ |
| Semántica completa: diccionarios, métodos de valor, `elegir/caso`, `intenta/atrapa` con **niveles de protección** (`jmp_buf` por llamada: un error dentro de un callback atrapado en un marco externo no corrompe la pila) | `motor-c/jpvm.c` | ✅ |
| Arnés de paridad ejemplo por ejemplo (**20 idénticos · 2 no soportados · 0 fallos**) | `herramientas/paridad.py` | ✅ |
| Tests de paridad integrados en la suite (252 en total) | `tests/test_motor_c.py` | ✅ |
| CI: compila el motor en gcc y clang, corre la suite y la paridad, y publica `jpvm` + binarios de ejemplo como artefactos | `.github/workflows/motor-c.yml` | ✅ |

### ✅ v1.6.0 (2026-10-19): lo que faltaba del lenguaje, hecho

Implementado en el árbol y en la VM con paridad total (28 tests nuevos,
`tests/test_v16.py`; suite: 280 tests): módulos `importar "x.jp" [como n]`
(T-13, una ejecución, aislamiento de globales, ciclos detectados), parámetros
por defecto (T-15), desestructuración `variable [a, b] = ...` y `[a, b] = [b, a]`
(T-16), `para i, v en ...` / `para clave, v en dict` (T-14), `lanzar` (T-06),
`finalmente` (T-07, también antes de `devuelve`/`romper` y tras un error en el
propio `atrapa`) y el tope de recursión unificado en 6000 llamadas (T-08).
Además: `LICENSE` (T-01), `CHANGELOG.md` (T-02) y el arreglo del lexer para
`lista[0]=1` sin espacios. El motor en C y el JIT rechazan limpiamente lo
nuevo (módulos/defectos/`finalmente`/`para a, b`) y el CLI sigue con Python.

### ✅ v1.7.0 (2026-10-19): clases, errores con campos y kit de IA

`clase`/`hereda`/`este` con constructor `iniciar` (T-33, diseño minimalista:
sin `super` todavía), errores atrapables con `.tipo/.mensaje/.linea` (T-05),
`sigmoide`/`producto_punto` nativos, rangos perezosos en `para` y
`jp --check` (T-10). Paridad árbol↔VM en todo (19 tests, `tests/test_v17.py`).

### ✅ v1.8.0 (2026-10-19): la biblioteca estándar

51 nativas nuevas en `jp/estadistica.py`, `jp/matrices.py`, `jp/fechas.py`,
`jp/sistema.py` y `jp/patrones.py` (120 en total) + `biblioteca/` en JP puro
(`mates`, `texto`, `listas`, `colecciones` con `Pila`/`Cola`/`Conjunto` e
`ia` con una `RedNeuronal` que aprende XOR). 11 tests, `tests/test_v18.py`.

**Números (esta máquina, Xeon 2.6 GHz, gcc 12 -O2):**

| Medida | Motor Python | JIT | **Motor C** | CPython | Mejora |
|---|---|---|---|---|---|
| `benchmark.jp` (while 1M + fib(22)) | 2,708 s | — | **0,046 s** | 0,29 s | **58x vs VM** |
| suma 10M + fib(32) | 41,08 s | — | **0,481 s** | 0,813 s | **85x vs VM · 1,7x vs CPython** |
| armónica 10M (flotantes) | 28,96 s | — | **0,487 s** | 1,140 s | **59x vs VM · 2,3x vs CPython** |
| `benchmark-nativo.jp` (5M+fib25+arm2M) | 19,32 s | 0,109 s | 0,233 s | — | el JIT gana en micro-kernels puros |
| Binario generado | — | — | 44 KB, solo libc/libm | — | independiente ✅ |

Y sobre **no romper**: si un programa usa algo que el motor en C no tiene
todavía, el compilador se niega con mensaje y `--c` sigue con el motor de
Python; los enteros de más de 64 bits también se rechazan (Python usa
precisión arbitraria) — nunca hay números distintos en silencio.

### Lo que falta del motor propio, en orden de impacto

| # | Tarea | Criterio de aceptación | Esf. |
|---|---|---|---|
| N-1 | **Métodos de valor en C** (`"x".mayusculas()`, `lista.agregar(v)`) | los 14 ejemplos que hoy se rechazan por esto pasan a idénticos | L | ✅ **hecho** |
| N-2 | **Diccionarios en C** (tabla hash con claves de texto + `claves/valores/elementos/tiene`) | `agenda.jp`, `api-json.jp`, `discord-webhook.jp` con paridad | L | ✅ **hecho** (`discord-webhook` espera N-4) |
| N-3 | **`intenta/atrapa` y `elegir` en C** | `seguro.jp`, `calculadora.jp` con paridad; el motor nunca aborta el proceso ante un error capturable | M | ✅ **hecho** |
| N-4 | **Red y archivos nativos** (`leer_archivo`, `escribir_archivo`, `http_get/post`, `json_leer/texto`) | `bot-telegram.jp` y `api-json.jp` nativos | M | 🔶 archivos y JSON sí; red (`http_get/post`, telegram) pendiente |
| N-5 | **`mapear/filtrar/reducir/para_cada/ordenar`** (nativas de orden superior, que ya saben llamar a un cierre desde el motor) | `funcional.jp` con paridad | M | ✅ **hecho** |
| N-6 | **Frontend propio** (lexer+parser en C, o bootstrap del compilador en JP) | `jpvm` compila y ejecuta un `.jp` **sin Python**; `jp` queda como comando de conveniencia | L |
| N-7 | **Tier de compilación a máquina** dentro del motor C (AOT por función numérica, como el JIT actual pero sin Python) | superar al JIT en `benchmark-nativo.jp` y acercarse a C puro | L |
| N-8 | **Extras de tipo**: bignums (o error claro), GC generacional, cache de métodos, superinstrucciones | 500+ tests verdes y menos tiempo por despacho | L |
| N-9 | **Distribución**: `make install`, binarios para Linux/macOS/Windows, wheels en PyPI con el binario dentro | `pipx install jp-lang && jp --c hola.jp` en una máquina limpia | M |

**Meta de paridad:** los 23 ejemplos en verde bajo el motor en C
(**hoy: 20 idénticos · 2 no soportados todavía (`bot-telegram`,
`discord-webhook`, ambos esperando N-4) · 0 fallos** · 2 no deterministas
(`red-neuronal`, `red-profunda`: misma estructura, números distintos) ·
`espiral.jp` y `benchmark-nativo.jp` se omiten por tiempo/cronometraje).
El arnés `herramientas/paridad.py` es el marcador.

---

## 0. Cómo leer este documento

| Sección | Para qué sirve |
|---|---|
| 1. Diagnóstico | Qué hay, qué duele y por qué (con evidencia, no opiniones) |
| 2. Principios | El contrato del proyecto: lo que no se negocia |
| 3. Definition of Done | Cuándo una mejora está *terminada* |
| 4. Roadmap | Qué entra en cada versión, con criterios de aceptación |
| 5. Prioridades | Tabla impacto × esfuerzo (P0/P1/P2) |
| 6. Sprint de 2 semanas | Arranque listo para hoy, tarea por tarea |
| 7. Métricas | Cómo saber si el plan está funcionando |
| 8. Riesgos | Qué puede salir mal y cómo se mitiga |
| 9. No-hacer | Anti scope-creep |
| 10. Decisiones abiertas | Lo que necesito que decidas tú |

---

## 1. Diagnóstico honesto

### 1.1 Lo que está muy bien (y hay que proteger)

Medido en este sandbox (Linux x86-64, Python 3.11.2):

| Medida | Valor | Comando |
|---|---|---|
| Tests | **245 en verde en 0,25 s** | `python -m unittest discover -s tests -v` |
| Código del lenguaje | 5.820 líneas Python (14 módulos) | `wc -l jp/*.py` |
| Tests | 1.708 líneas | `wc -l tests/*.py` |
| Ejemplos | 23 programas, 1.135 líneas | `ls ejemplos/*.jp` |
| Librería estándar | ~53 nativas | `grep -c FuncionNativa jp/interprete.py` |
| Dependencias de runtime | **cero** (solo stdlib) | `pyproject.toml` |
| Documentación | README de 21 KB, honesto y con números | `wc -c README.md` |

Cuatro motores reales (árbol, VM, JIT x86-64, turbo) con paridad verificada por
tests, un JIT que emite máquina de verdad (`mmap` RWX, ensamblador propio) y un
modo turbo con caché `.jpc`. Para un lenguaje hecho desde cero, el nivel técnico
está muy por encima de la media de los "lenguajes en español" de hobby.

**Lo mejor del proyecto no es ninguna feature: es la disciplina de paridad.**
"Todo implementado en los dos motores con paridad total" es la razón por la que
esto se siente un lenguaje y no una demo. Este plan la convierte en ley escrita.

### 1.2 Lo que duele (hallazgos con evidencia)

#### H1 — La paridad tiene una grieta real (severidad P0)

El README promete "semántica idéntica en ambos motores". Falso en recursión
profunda:

```bash
python -m jp            /tmp/deep.jp   # VM:        imprime 0        ✅
python -m jp --interprete /tmp/deep.jp # árbol:     "desbordamiento de pila" ❌
```

El árbol hereda el límite de recursión de Python (~1000 frames *de Python* en
total, y cada llamada JP consume varios), la VM usa `_MAX_FRAMES = 6000`, y
**nadie declara ese límite en el lenguaje**. Es el único fallo de paridad
conocido y el más grave: un mismo programa da resultados distintos según la
bandera.

#### H2 — Los errores no dicen dónde estabas (P0)

```bash
$ python -m jp /tmp/probe1.jp
Error de ejecución: división por cero
    --> línea 1, columna 0
    1 | funcion dividir(a, b) { devuelve a / b }
```

La línea es correcta, pero **falta la cadena**: `calcular()` la llamó en la
línea 5, y el programa la llamó en la línea 7. Sin traza, depurar cualquier
programa de más de 20 líneas es a ciegas — y JP está pensado para principiantes,
que son justo quienes más necesitan ver "quién llamó a quién".

#### H3 — `intenta/atrapa` captura un texto, no un error (P0)

```jp
intenta { variable x = 1 / 0 } atrapa e { imprime(tipo(e)) }   # => texto
```

El valor capturado es una cadena plana: no hay `e.tipo`, ni `e.linea`, ni
causa, ni forma de distinguir "división por cero" de "índice fuera de rango"
sin comparar textos. Tampoco existen `lanzar` (errores propios) ni `finalmente`.

#### H4 — No hay red de seguridad automática (P0)

No existe `.github/`: **0 workflows de CI**. Los 245 tests solo corren si
alguien se acuerda de escribirlos a mano, y no hay verificación de que los 23
ejemplos sigan funcionando en cada cambio. Con cuatro motores y paridad
prometida, esta es la deuda estructural más cara de pagar más adelante.

#### H5 — El JIT falla en silencio y solo vive en x86-64 (P1)

`jp/nativo.py` emite x86-64 y usa `mmap` RWX sin ninguna comprobación de
plataforma (`grep platform jp/nativo.py` → nada). En un Mac ARM o en Windows,
`--nativo` simplemente no hace nada: el usuario cree que activó el JIT.

#### H6 — La VM deja rendimiento sobre la mesa (P1)

- Los locales se buscan **por nombre, caminando la cadena de ámbitos** en cada
  lectura (`LEER_LOCAL` en `vm.py` hace `a.vars.get(nombre)` en un `while`).
  El compilador ya sabe qué nombres son locales: puede asignarles **slots**.
- No hay superinstrucciones (`LEER_LOCAL x; LEER_LOCAL y; SUMAR` son tres
  despachos) ni inline caches para globals/llamadas.
- En este sandbox: `benchmark.jp` tarda **2,94 s** en la VM contra **0,075 s**
  de Python puro (≈39x).
- El JIT solo compila **funciones declaradas en el nivel superior**
  (`compilar_lote` recorre `programa.sentencias` buscando `NodoFuncion`): el
  código de arriba siempre corre en la VM. Medido: un `mientras` de 3M a nivel
  superior tarda **7,37 s** con y sin `--nativo`; el mismo bucle dentro de una
  función pasa de **6,92 s a 0,083 s** (83x). Hoy el ejemplo oficial lo admite
  como nota al pie en un comentario; debería ser un objetivo.

#### H7 — Falta el "kit de proyecto" (P1)

| Falta | Por qué importa |
|---|---|
| `LICENSE` | `pyproject.toml` declara MIT pero **no hay archivo de licencia**; sin él no es legalmente open source ni publicable en PyPI |
| `.github/workflows/` | CI (ver H4) |
| `CHANGELOG.md` | El historial vive en el README; ya pesa 21 KB y crece cada release |
| `CONTRIBUTING.md` + plantillas | Cualquiera que quiera aportar no sabe cómo |
| `docs/` | 21 KB de README monohilo no escalan |
| `readline` en el REPL | Sin historial ni flechas en la línea de comandos |
| `jp --check` | No se puede validar sintaxis sin ejecutar |
| `jp --bytecode` | Existe `desensamblar()` en `bytecode.py` y no está expuesto |

#### H8 — Huecos de lenguaje frente a lo que la gente espera (P1/P2)

Verificado que **no** funcionan hoy:

```jp
funcion f(a, b = 2) { ... }        # Error de sintaxis (no hay parámetros por defecto)
importar "utilidades.jp"           # "variable no definida: 'importar'"
para i, v en lista { ... }         # no existe índice+valor
variable [a, b] = par             # no hay desestructuración
lanzar "mensaje"                  # no existe
intenta { } atrapa { } finalmente { }  # no hay rama final
```

Sin módulos, todo programa grande termina en un solo archivo de 500 líneas.

---

## 2. Principios (el contrato del proyecto)

Estos siete puntos deciden cualquier discusión futura. Si una idea choca con
uno, se descarta o se rediseña:

1. **Fácil primero.** Si una feature hace el lenguaje más difícil de leer para
   un principiante, no entra (aunque sea "más potente").
2. **Paridad total.** Toda feature funciona en árbol y en VM, y hay un test que
   lo prueba con la misma salida. El JIT y el turbo son *optimizaciones*, nunca
   semántica distinta.
3. **Cero dependencias de runtime.** Solo la stdlib de Python, siempre.
4. **Números honestos.** Benchmarks reproducibles, con máquina y versión; se
   publican también cuando JP pierde.
5. **Español natural.** `romper`, `devuelve`, `para ... en`, no traducciones
   raras de conceptos ingleses.
6. **Nada entra sin test y sin README.**
7. **Nada se rompe sin deprecación.** Compatibilidad hacia atrás; lo que cambia
   de forma incompatible sube de versión mayor.

## 3. Definition of Done (por feature)

Una mejora está terminada solo cuando cumple **los seis**:

- [ ] Implementada en el **árbol** y en la **VM** (y en el JIT si califica).
- [ ] **Tests nuevos**: caso feliz + errores + `test_vm.py` de paridad.
- [ ] **README/PLAN actualizados** (tabla de librería si es nativa).
- [ ] **Ejemplo** nuevo o existente que la use (`ejemplos/`).
- [ ] Si toca rendimiento: **medición antes/después** en la misma máquina.
- [ ] `python -m unittest discover -s tests -v` en verde (todos).

---

## 4. Roadmap por versiones

Cada tarea: **qué** · **cómo** (archivos) · **criterio de aceptación** · **esfuerzo**
(S = ≤1 día, M = 2-4 días, L = 1-2 semanas).

### v1.3.1 — "Cimientos" (≈1 semana, sin features de lenguaje)

*Objetivo: cerrar los agujeros que hacen daño cada día.*

| # | Tarea | Cómo | Aceptación | Esf. |
|---|---|---|---|---|
| T-01 | **Archivo `LICENSE`** (MIT) | raíz | GitHub lo detecta y `pyproject` apunta a él | S |
| T-02 | **`CHANGELOG.md`** | mover el historial del README tal cual | README queda ≤40% más corto y enlaza al changelog | S |
| T-03 | **CI con GitHub Actions** | `.github/workflows/tests.yml`: 3.10/3.11/3.12 × `unittest` + *smoke* de los 23 ejemplos | badge en README; un PR roto se ve en rojo | M |
| T-04 | **Traza de llamadas en errores** (H2) | `vm.py`: llevar `(nombre, ruta, linea_llamada)` en `frames`; `interprete.py`: pila de llamadas explícita; `errores.py`: formatear `en f() línea X ← g() línea Y` | `/tmp/probe1.jp` muestra las 3 líneas de la cadena | M |
| T-05 | **Error atrapable con campos** (H3) | valor de `atrapa` = `class ErrorValor(str)` con `.tipo/.mensaje/.linea/.columna`; al ser subclase de `str`, `"algo: " + e` sigue funcionando | `e.tipo == "division_por_cero"`; compatibilidad 245 tests | M |
| T-06 | **`lanzar expr`** | token + nodo + compilador + ambos motores; produce un error capturable con `.tipo == "usuario"` | `intenta { lanzar "x" } atrapa e { ... }` en los dos motores | S |
| T-07 | **`finalmente`** | parser + compilador (ENDTRY con salto final) + árbol | corre siempre, incluso con `devuelve` dentro del `intenta` | S |
| T-08 | **Unificar el límite de recursión** (H1) | constante única del lenguaje (p. ej. 10.000 frames) aplicada en ambos motores; el árbol deja de depender del límite de Python | `deep.jp` da **la misma** salida en árbol y VM; test de paridad | M |
| T-09 | **Guard de plataforma del JIT** (H5) | `nativo.py`: `platform.machine()`/`sys.platform`; si no es x86-64 → aviso claro una sola vez y mensaje "el JIT no aplica aquí, sigo en la VM" | en ARM/Windows no hay silencio | S |
| T-10 | **`jp --check`** | `cli.py`: tokenizar+parsear sin ejecutar; salida = errores de sintaxis | `jp --check ejemplos/*.jp` → 0 errores, exit 0 | S |
| T-11 | **`jp --bytecode`** | `cli.py` expone `desensamblar()` | imprime el chunk del programa | S |
| T-12 | **REPL con historial** | `import readline` (stdlib) + archivo `~/.jp_historial`; `ayuda` con la lista completa de nativas | flechas e historial funcionan | S |

**Al cerrar v1.3.1:** nada nuevo que aprender, pero el proyecto pasa de "funciona
en mi máquina" a "verificable por cualquiera".

### v1.4.0 — "Programas que se componen" (3-4 semanas)

*Objetivo: que se pueda escribir un proyecto de varios archivos, con errores
que enseñan.*

| # | Tarea | Cómo | Aceptación | Esf. |
|---|---|---|---|---|
| T-13 | **Módulos: `importar "ruta.jp" como util`** | token + parser + resolución de ruta canónica; cada módulo se ejecuta **una vez** y su ámbito queda aislado; `util.doble(2)` | dos archivos: `utilidades.jp` + `main.jp`; sin ejecuciones duplicadas ni ciclos infinitos | L |
| T-14 | **`para i, valor en lista`** y `para clave, valor en dict` | parser acepta 1-2 nombres; `ITERAR_SIGUIENTE` empuja par | funciona en árbol, VM y `reducir/mapear` | M |
| T-15 | **Parámetros por defecto** `funcion f(a, b = 2)` | parser guarda valores por defecto; ambos motores rellenan | `f(1)` → 3; error claro si faltan obligatorios | M |
| T-16 | **Desestructuración mínima** `variable [a, b] = par` | parser + ambos motores; error si el largo no coincide | intercambio sin variable temporal: `variable [a, b] = [b, a]` | M |
| T-17 | **Errores con pista** | `ErrorEjecucion(..., pista="¿querías usar 'lista.agregar'?")`; `errores.py` la imprime | índice/clave/método inexistente dan pista | S |
| T-19 | **`jp probar` básico** | mini-runner: `prueba("nombre") { espera(expr, valor) }` como nativa | se puede testear en JP puro | M |

### v1.5.0 — "Rápido de verdad" (3-4 semanas)

*Objetivo: acercar la VM a Python y dejar la metodología de benchmarks.*

| # | Tarea | Cómo | Aceptación | Esf. |
|---|---|---|---|---|
| T-18 | **JIT del nivel superior** (H6) | `compilar_lote` solo compila `NodoFuncion` de primer nivel: envolver el código de arriba en una función sintética (o compilar el chunk principal) para que sus bucles también sean nativos | el `mientras` de 3M a nivel superior baja de **7,37 s a <0,2 s**; el ejemplo deja de necesitar su nota al pie | L |
| T-20 | **Locales por slots** (H6) | el compilador asigna índice; `LEER_LOCAL slot` accede a `frame.slots[i]` (lista) en vez de caminar nombres; los upvalues se resuelven explícitamente | `benchmark.jp` ≤1,5 s (de 2,94 s) sin cambiar semántica | L |
| T-21 | **Superinstrucciones** | fusión en `compilador.py`: `LEER_LOCAL+LEER_LOCAL+SUMAR` → `SUMA_LL`, `LEER_LOCAL+CONSTANTE+COMPARAR` → `COMPARA_LC`, etc.; opcodes nuevos en `bytecode.py` y `vm.py` | ≥20% menos despachos medidos con `--bytecode` | L |
| T-22 | **Inline cache de `LEER_GLOBAL`/`LLAMAR`** | guardar en el closure el último `(ámbito, valor)` resuelto y validar por identidad | 10-25% en programas con globals en bucle | M |
| T-23 | **`jp --bench` con historial** | `benchmarks/HISTORIAL.md`: fecha, CPU, Python, motor, tiempo; script que corre los 3 benchmarks y agrega fila | tabla histórica con la que cualquiera compare su máquina | M |
| T-24 | **Turbo: puridad más fina** | clasificar nativas por acceso a mundo exterior; permitir turbo con salida pura y entrada declarada; invalidar caché también por versión de Python | documentado en `turbo.py`; tests | M |
| T-36 | **Informe del JIT** | `jp --nativo --explica`: qué funciones se compilaron, cuáles se descartaron y por qué | se acabó el "falla en silencio" del JIT | S |

### v1.6.0 — "Herramientas" (3-4 semanas)

*Objetivo: que trabajar **en** JP sea tan agradable como escribir **en** JP.*

| # | Tarea | Cómo | Aceptación | Esf. |
|---|---|---|---|---|
| T-25 | **`jp fmt`** | formateador propio (sangría, espacios, llaves) reusando el AST; idempotente | `jp fmt --diff` no cambia código ya formateado | L |
| T-26 | **`jp lint`** | avisos: variable sin usar, nombre repetido que sombrea, comparar con `nulo` usando `==`, `funcion` vacía, `para` sin usar la variable | ≥6 reglas con tests | M |
| T-27 | **Resaltado de sintaxis** | extensión TextMate (`.tmLanguage.json`) con todas las palabras clave + snippets; carpeta `editores/vscode/` | instalar y ver colores; publicable al marketplace | M |
| T-28 | **REPL 2.0** | `--nativo` y `--turbo` en el REPL, `ayuda` por temas, `cargar("archivo.jp")` | ejecutar un archivo desde el REPL | M |
| T-29 | **Perfilador simple** | contador por función (llamadas + tiempo con `reloj()`), activado con `jp --perfil` | dice dónde se va el tiempo en `benchmark-nativo.jp` | L |

### v2.0.0 — "Ecosistema" (6-8 semanas)

*Objetivo: que JP sea algo que otros usen, no solo un logro técnico.*

| # | Tarea | Cómo | Aceptación | Esf. |
|---|---|---|---|---|
| T-30 | **`pip install jp-lang`** | `pyproject` con clasificadores, `LICENSE`, `python -m build`, publicar a PyPI, badge | `pipx install jp-lang && jp hola.jp` en máquina limpia | M |
| T-31 | **Docs en `docs/`** | tutorial de 30 min, referencia del lenguaje, referencia de librería generada desde la tabla | sitio servible en GitHub Pages | L |
| T-32 | **Playground web** | Pyodide + el paquete `jp`; editor en una página estática | pegar `ejemplos/ahorcado.jp` en el navegador y jugar | L |
| T-33 | **Clases/objetos minimalistas** | `objeto` + `metodos`, o `registro` + funciones; diseño *antes* de código, con RFC en `docs/rfc/` | decisión escrita y aprobada antes de implementar | L |
| T-34 | **Avisos de deprecación** | marco de avisos con versión objetivo | un cambio incompatible planeado se avisa 1 versión menor antes | M |
| T-35 | **JP en JP** | reescribir tests o la stdlib en JP puro; medir cuántas líneas hacen falta | la suite se corre con `jp tests/` (al menos en parte) | L |

---

## 5. Prioridades (impacto × esfuerzo)

| Prioridad | Significado | Tareas |
|---|---|---|
| **P0 — ahora** | rompen confianza o bloquean todo lo demás | T-01…T-12 |
| **P1 — siguiente** | lo que más se nota al usarlo de verdad | T-13, T-14, T-15, T-20, T-21, T-23 |
| **P2 — cuando haya aire** | pulido y ecosistema | T-16…T-19, T-22, T-24…T-36 |

**Camino crítico:**

```
LICENSE + CI (T-01,T-03)  →  todo lo demás se apoya en que los tests corran solos
        │
        ├── errores (T-04,T-05,T-06,T-07)  →  enseñan y se depuran
        │        └── pistas (T-17)  →  tutoriales que no dan miedo
        ├── módulos (T-13)  →  programas >100 líneas  →  stdlib en JP (T-35)
        └── paridad de recursión (T-08)  →  el árbol recupera el título de "referencia"
```

---

## 6. Sprint de 2 semanas (arranque listo para hoy)

| Día | Tarea | Entregable |
|---|---|---|
| 1 | T-01, T-02 | `LICENSE`, `CHANGELOG.md`, README más corto |
| 2 | T-03 | CI verde en 3 versiones de Python |
| 3-4 | T-04 | trazas de llamadas en árbol y VM + tests |
| 5-6 | T-05, T-06, T-07 | errores con campos, `lanzar`, `finalmente` + tests de paridad |
| 7 | T-08 | límite de recursión único + test que compara árbol vs VM |
| 8 | T-09, T-10, T-11, T-12 | guard del JIT, `--check`, `--bytecode`, REPL con historial |
| 9 | — | **release v1.3.1**: tag, GitHub Release, README "Estado" |
| 10 | T-13 (diseño) | RFC de módulos en `docs/rfc/modulos.md`: rutas, ciclos, alcance |

Al terminar este sprint: mismo lenguaje, pero un proyecto que *cualquiera* puede
clonar, ejecutar y verificar con un comando.

---

## 7. Métricas y seguimiento

Tablero que se revisa en cada release:

| Métrica | Hoy (v1.3.0) | Meta v1.4 | Meta v1.5 | Meta v2.0 |
|---|---|---|---|---|
| Tests | 245 | 350 | 420 | 500+ |
| CI | ❌ | ✅ 3 versiones | ✅ + ejemplos | ✅ + benchmarks |
| Fallos de paridad conocidos | 1 (recursión) | 0 | 0 | 0 |
| `benchmark.jp` (VM) | 2,94 s | 2,94 s | **≤1,5 s** | ≤1,5 s |
| `mientras` de 3M a nivel superior | 7,37 s | 7,37 s | **<0,2 s** | <0,2 s |
| Categorías de error con tipo/línea | ❌ | ✅ | ✅ | ✅ |
| Archivos `.jp` de ejemplo | 23 | 30 | 30 | 40 |
| Nativas | 53 | 60 | 60 | 75 |

**Protocolo de release** (ya lo usas, se escribe para no olvidarlo):
1. `python -m unittest discover -s tests -v` en verde.
2. Actualizar `CHANGELOG.md`, `pyproject.toml`, `jp/__init__.py` y la sección
   "Estado" del README.
3. PR a `main` con la tabla de números nuevos (si toca rendimiento).
4. Tag `vX.Y.Z` + GitHub Release con las notas del changelog.

## 8. Riesgos

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Romper la paridad al optimizar | Alta | Alto | el test de paridad corre en CI; ninguna optimización entra sin él |
| Scope creep (demasiadas features) | Alta | Alto | sección 9; una feature por versión temática |
| El JIT se vuelve un lastre en máquinas nuevas | Media | Medio | T-09 + fallback silencioso a VM + CI en Linux |
| Complejidad creciente para principiantes | Media | Alto | principio 1: toda feature nueva se prueba escribiéndola "como un niño" |
| Sin contribuyentes, el bus factor = 1 | Alta | Medio | docs, CONTRIBUTING, issues etiquetadas `bueno-para-empezar` |
| El README monohilo deja de ser mantenible | Media | Medio | T-02 + `docs/` en v2.0 |

## 9. Lo que NO hacemos (por ahora)

Para no romper el principio 1 ni diluir el esfuerzo:

- ❌ Garbage collector propio, hilos/concurrencia, macros, tipado estático.
- ❌ Reescribir la VM en C o Rust (el JIT ya cubre el cálculo numérico).
- ❌ Frameworks web, ORMs, "todo lo que hace Python".
- ❌ Cambiar la sintaxis por moda: JP ya eligió "fácil primero".
- ❌ Features nuevas **antes** de cerrar P0 (con una excepción: T-13 módulos,
  que es P0 encubierta porque sin él no hay programas grandes).

## 10. Decisiones abiertas (necesito tu palabra)

1. **¿Prioridad features o rendimiento?** El plan asume *primero confianza
   (P0) → después features (v1.4) → después velocidad (v1.5)*. Si prefieres
   velocidad antes, se reordena la sección 4 sin tocar los principios.
2. **¿Publicar en PyPI?** Si sí, ¿`jp-lang` sigue libre? (verificable antes de
   la v2.0).
3. **¿Clases/objetos (T-33) o estilo "registro + funciones"?** Es la decisión
   de diseño más grande que queda; propongo escribir el RFC antes de votar.
4. **¿JP como lenguaje para enseñar?** Si es sí, el tutorial y los mensajes de
   error suben a P0 y las clases bajan.

---

## Anexo — reproducir la evidencia

```bash
# 1. La suite completa (245 tests)
python -m unittest discover -s tests -v | tail -2

# 2. La grieta de paridad (H1)
printf 'funcion f(n) { si n <= 0: devuelve 0\ndevuelve f(n - 1) }\nimprime(f(3000))\n' > /tmp/deep.jp
python -m jp /tmp/deep.jp            # imprime 0
python -m jp --interprete /tmp/deep.jp   # Error: desbordamiento de pila

# 3. Errores sin traza (H2)
printf 'funcion dividir(a, b) { devuelve a / b }\nfuncion calcular() {\n variable total = 0\n para i en 1..3 { total += dividir(10, i - 1) }\n devuelve total\n}\nimprime(calcular())\n' > /tmp/probe1.jp
python -m jp /tmp/probe1.jp

# 4. Errores atrapados como texto (H3)
python -m jp -c 'intenta { variable x = 1/0 } atrapa e { imprime(tipo(e)) }'

# 5. Huecos de lenguaje (H8)
python -m jp -c 'funcion f(a, b = 2) { devuelve a + b }'
python -m jp -c 'importar "otro.jp"'

# 6. Rendimiento (H6) — mismos números, misma máquina
time python -m jp ejemplos/benchmark.jp
time python -m jp --nativo ejemplos/benchmark-nativo.jp
python -m jp --turbo ejemplos/benchmark-grande.jp && time python -m jp --turbo ejemplos/benchmark-grande.jp

# 7. El JIT no toca el nivel superior (H6) — 7,4 s con y sin --nativo
printf 'variable s = 0\nvariable i = 0\nmientras i < 3000000 { s += i\ni += 1 }\nimprime(s)\n' > /tmp/while.jp
time python -m jp /tmp/while.jp
time python -m jp --nativo /tmp/while.jp
# el mismo bucle DENTRO de una función: 6,92 s (VM) → 0,083 s (nativo)

# 8. Kit de proyecto ausente (H7)
ls LICENSE .github docs CHANGELOG.md CONTRIBUTING.md 2>&1
```

---

*Hecho con cariño desde cero: JP ya es un lenguaje. Este plan es para que sea
también un proyecto.* 🇪🇸
