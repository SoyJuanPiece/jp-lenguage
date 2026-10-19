# 📚 biblioteca/ — módulos en JP puro

Se importan como cualquier archivo (la ruta es relativa a TU archivo):

```jp
importar "../biblioteca/mates.jp" como mates
imprime(mates.factorial(6))
```

| Módulo | Trae |
|---|---|
| `mates.jp` | `factorial`, `es_primo`, `primos_hasta`, `mcd`, `mcm`, `fibonacci`, `sumatoria`, `es_par` |
| `texto.jp` | `es_palindromo`, `contar_vocales`, `titulo`, `cesar`, `es_anagrama` |
| `listas.jp` | `aplanar`, `unicos`, `particionar`, `buscar_binario`, `indice_del_mayor`, `intercalar` |
| `colecciones.jp` | clases `Pila`, `Cola` y `Conjunto` (con `union`) |
| `ia.jp` | clase `RedNeuronal` multicapa que aprende con backprop (el XOR incluido) |
| `tabla.jp` | clase `Tabla` estilo pandas: `filtrar_con`, `ordenar_por`, `agrupar_por`, `agregar_columna`, `promedio_columna`... + `tabla_de_csv(ruta)` |

Además, el motor trae **120 funciones nativas** (51 nuevas en la v1.8.0,
en `jp/estadistica.py`, `jp/matrices.py`, `jp/fechas.py`, `jp/sistema.py` y
`jp/patrones.py`): `promedio`, `mediana`, `moda`, `varianza`, `desviacion`,
`percentil`, `frecuencias`, `contar`, `resumen` · `forma`, `crear_matriz`,
`identidad`, `transponer`, `sumar_matrices`, `restar_matrices`,
`multiplicar_matrices`, `escalar_matriz`, `matriz_vector`, `sumar_vectores`,
`restar_vectores`, `multiplicar_vectores`, `norma`, `distancia`,
`normalizar`, `softmax`, `matriz_aplicar` · `ahora`, `fecha_actual`,
`fecha_de`, `hoy`, `formatear_fecha`, `convertir_fecha` · `plataforma`,
`leer_entorno`, `carpeta_actual`, `cambiar_carpeta`, `unir_ruta`,
`nombre_base`, `carpeta_de`, `extension_de`, `existe_ruta`, `es_carpeta`,
`es_archivo`, `crear_carpeta`, `ejecutar` · `buscar_patron`,
`coincide_patron`, `encontrar_patrones`, `reemplazar_patron`, `separar_patron` ·
`leer_csv`, `leer_csv_texto`, `escribir_csv`, `convertir_csv`, `sublista` ·
`sumar_dias`, `dias_entre`. De ellas, `sigmoide`, `producto_punto`, `promedio`,
`mediana`, `norma`, `distancia` y `softmax` también están en el motor en C.

El motor en C aún no tiene las nativas nuevas: si las usas con `--c`, se
avisa y se sigue con el motor de Python (nunca hay resultados distintos).
