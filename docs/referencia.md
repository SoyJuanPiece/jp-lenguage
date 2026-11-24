# Referencia de la biblioteca estándar de JP

Generado por `herramientas/referencia.py` a partir de las 163 funciones nativas del intérprete (JP 1.37.0).
No se edita a mano: se regenera.

La columna «firma» la rellena el propio registro de nativas; el número de
argumentos es el mínimo obligatorio o el total, según la función.

Un «—» en la descripción significa que esa función todavía no tiene
docstring: es deuda de documentación de la biblioteca, no un error del
generador.

## Texto

| Firma | Qué hace |
|---|---|
| `mayusculas(a1)` | — |
| `minusculas(a1)` | — |
| `recortar(a1)` | — |
| `separar(...)` | — |
| `unir(...)` | — |
| `contiene(a1, a2)` | — |
| `reemplazar(a1, a2, a3)` | — |
| `subtexto(...)` | — |
| `letra(a1, a2)` | — |
| `longitud(a1)` | — |
| `empezar_con(a1, a2)` | — |
| `terminar_con(a1, a2)` | — |
| `buscar(a1, a2)` | Posición de un pedazo de texto, o -1 si no está. |
| `repetir(a1, a2)` | repetir("ab", 3) -> "ababab" (también con listas). |
| `invertir(a1)` | Copia al revés (no modifica el original). |
| `texto(a1)` | — |

## Números

| Firma | Qué hace |
|---|---|
| `entero(a1)` | — |
| `numero(a1)` | — |
| `absoluto(a1)` | — |
| `raiz(a1)` | — |
| `potencia(a1, a2)` | — |
| `piso(a1)` | — |
| `techo(a1)` | — |
| `redondear(...)` | Redondeo de escuela: 2.5 -> 3, -2.5 -> -3, 3.14159 con 2 -> 3.14. |
| `log(...)` | — |
| `minimo(...)` | — |
| `maximo(...)` | — |
| `sumar(a1)` | — |
| `pi()` | — |
| `aleatorio()` | Número decimal al azar entre 0 y 1 (azar(n) sigue siendo para 1..n). |
| `azar(a1)` | Número al azar entre 1 y n (inclusivo). |

## Listas y diccionarios

| Firma | Qué hace |
|---|---|
| `agregar(a1, a2)` | Agrega un elemento al final de la lista (y la devuelve). |
| `quitar(...)` | Quita por posición (la última si no se indica) y devuelve el elemento. |
| `insertar(a1, a2, a3)` | Inserta en la posición indicada (el resto se corre) y devuelve la lista. |
| `eliminar(a1, a2)` | Quita la primera aparición de un valor; devuelve si lo encontró. |
| `indice_de(a1, a2)` | Posición de un valor en una lista o texto, o -1 si no está. |
| `ordenar(...)` | Copia ordenada; con una función clave: ordenar(lista, funcion(x) { ... }). |
| `claves(a1)` | — |
| `valores(a1)` | — |
| `elementos(a1)` | Pares [clave, valor] para recorrer un diccionario con 'para'. |
| `rango(...)` | — |

## Funciones de orden superior

| Firma | Qué hace |
|---|---|
| `mapear(a1, a2)` | [f(x) para cada x]: mapear([1, 2], funcion(x) { devuelve x * 2 }). |
| `filtrar(a1, a2)` | — |
| `reducir(...)` | reducir(lista, f) o reducir(lista, f, inicial): acumula de izquierda a derecha. |
| `para_cada(a1, a2)` | — |

## Entrada/salida

| Firma | Qué hace |
|---|---|
| `imprime(...)` | — |
| `muestra(...)` | — |
| `leer(...)` | — |
| `reloj()` | Segundos (monotónicos) para medir tiempos: reloj() - reloj(). |

## Resto de la biblioteca

Funciones de los módulos (estadística, matrices, fechas, sistema,
patrones, tablas, servidor, seguridad, gráficos, base de datos, red).

| Firma | Qué hace |
|---|---|
| `_externo_llamar(...)` | FFI y memoria de `externo`: sólo en el motor C (`jp --c`). |
| `a_diccionario(...)` | a_diccionario([[clave, valor], ...]) -> diccionario. |
| `abrir_bd(...)` | — |
| `agregar_archivo(a1, a2)` | — |
| `ahora()` | Segundos desde 1970 (la 'marca de tiempo' de siempre). |
| `argumentos()` | — |
| `bd_cerrar(...)` | — |
| `bd_consultar(...)` | — |
| `bd_ejecutar(...)` | — |
| `buscar_patron(a1, a2)` | {texto, inicio, fin, grupos} de la primera aparición, o nulo. |
| `cambiar_carpeta(a1)` | — |
| `carpeta_actual()` | — |
| `carpeta_de(a1)` | — |
| `codificar64(a1)` | — |
| `coincide_patron(a1, a2)` | ¿El texto ENERO coincide con el patrón? (para validar formatos). |
| `contar(a1, a2)` | — |
| `convertir_csv(a1)` | — |
| `convertir_fecha(...)` | — |
| `coseno(a1)` | — |
| `crear_carpeta(a1)` | — |
| `crear_matriz(...)` | — |
| `crear_svg(...)` | — |
| `decodificar64(a1)` | — |
| `desviacion(a1)` | — |
| `dias_entre(a1, a2)` | — |
| `distancia(a1, a2)` | — |
| `ejecutar(a1)` | Ejecuta un programa y devuelve {codigo, salida, error}. |
| `encontrar_patrones(a1, a2)` | — |
| `enumerar(...)` | enumerar(lista) -> [[0, x], [1, y], ...]; el inicio es opcional. |
| `es_archivo(a1)` | — |
| `es_carpeta(a1)` | — |
| `escalar_matriz(a1, a2)` | — |
| `escribir_archivo(a1, a2)` | — |
| `escribir_csv(a1, a2)` | — |
| `escribir_entero(...)` | FFI y memoria de `externo`: sólo en el motor C (`jp --c`). |
| `escribir_puntero(...)` | FFI y memoria de `externo`: sólo en el motor C (`jp --c`). |
| `esperar(a1)` | — |
| `esperar_proceso(...)` | — |
| `existe_archivo(a1)` | — |
| `existe_ruta(a1)` | — |
| `exp(a1)` | e^x (para sigmoides y matemática de redes neuronales). |
| `extension_de(a1)` | — |
| `fecha_actual()` | — |
| `fecha_de(a1)` | — |
| `forma(a1)` | — |
| `formatear_fecha(...)` | — |
| `frecuencias(a1)` | {valor_en_texto: veces} — las claves de un diccionario JP son texto. |
| `guardar_svg(...)` | — |
| `hash_texto(...)` | — |
| `hoy()` | — |
| `http_get(a1)` | — |
| `http_post(...)` | — |
| `id_unico()` | — |
| `identidad(a1)` | — |
| `iniciar_proceso(...)` | — |
| `json_leer(a1)` | — |
| `json_texto(a1)` | — |
| `leer_archivo(a1)` | — |
| `leer_csv(a1)` | — |
| `leer_csv_texto(a1)` | — |
| `leer_entero(...)` | FFI y memoria de `externo`: sólo en el motor C (`jp --c`). |
| `leer_entorno(...)` | — |
| `leer_puntero(...)` | FFI y memoria de `externo`: sólo en el motor C (`jp --c`). |
| `leer_texto(...)` | FFI y memoria de `externo`: sólo en el motor C (`jp --c`). |
| `liberar(...)` | FFI y memoria de `externo`: sólo en el motor C (`jp --c`). |
| `lista_archivos(a1)` | — |
| `matriz_aplicar(a1, a2)` | — |
| `matriz_vector(a1, a2)` | — |
| `media(a1)` | — |
| `mediana(a1)` | — |
| `moda(a1)` | — |
| `multiplicar_matrices(a1, a2)` | — |
| `multiplicar_vectores(a1, a2)` | — |
| `nombre_base(a1)` | — |
| `norma(a1)` | — |
| `normalizar(a1)` | — |
| `pedir(...)` | pedir(url[, metodo, datos, cabeceras]) -> {estado, cuerpo, json, cabeceras}. |
| `percentil(a1, a2)` | — |
| `plataforma()` | — |
| `proceso_en_curso(...)` | — |
| `producto_punto(a1, a2)` | Suma de a[i]*b[i] de dos listas del mismo largo (nucleo de toda IA). |
| `promedio(a1)` | — |
| `rebanada(...)` | El corte x[a:b:c] de Python: partes opcionales y negativos. |
| `reemplazar_patron(a1, a2, a3)` | — |
| `reservar(...)` | FFI y memoria de `externo`: sólo en el motor C (`jp --c`). |
| `restar_matrices(a1, a2)` | — |
| `restar_vectores(a1, a2)` | — |
| `resumen(a1)` | — |
| `salir(...)` | — |
| `seno(a1)` | — |
| `separar_patron(a1, a2)` | — |
| `servir(...)` | servir(puerto, manejador[, anfitrion]): escucha para siempre. |
| `sigmoide(a1)` | 1 / (1 + e^-x): la activacion clasica de las redes neuronales. |
| `softmax(a1)` | — |
| `sublista(...)` | sublista(lista, inicio[, fin]): el trozo, con negativos como en listas. |
| `sumar_dias(a1, a2)` | — |
| `sumar_matrices(a1, a2)` | — |
| `sumar_vectores(a1, a2)` | — |
| `svg_camino(...)` | — |
| `svg_circulo(...)` | — |
| `svg_linea(...)` | — |
| `svg_lineas(...)` | — |
| `svg_rectangulo(...)` | — |
| `svg_texto(...)` | — |
| `tamano_archivo(a1)` | — |
| `telegram_leer(a1)` | — |
| `telegram_responder(a1, a2, a3)` | — |
| `terminar_proceso(...)` | — |
| `tiene(a1, a2)` | — |
| `tipo(a1)` | Nombre del tipo de un valor, en español. |
| `transponer(a1)` | — |
| `unir_ruta(...)` | — |
| `varianza(a1)` | Varianza de la población (la de statistics.pvariance). |
| `zip(...)` | zip(a, b) -> [[a0, b0], [a1, b1], ...] hasta el más corto. |

## Palabras clave

| Palabra | Alias |
|---|---|
| `atrapa` | — |
| `caso` | — |
| `clase` | — |
| `continuar` | — |
| `elegir` | — |
| `en` | — |
| `externo` | — |
| `falso` | — |
| `finalmente` | — |
| `fun` | funcion, función |
| `hereda` | — |
| `importar` | — |
| `intenta` | — |
| `lanzar` | — |
| `mientras` | — |
| `no` | — |
| `nulo` | — |
| `o` | — |
| `para` | — |
| `retorna` | devuelve |
| `romper` | — |
| `si` | — |
| `sino` | — |
| `var` | variable |
| `verdadero` | — |
| `y` | — |
