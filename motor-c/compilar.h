/* Compilador de JP a bytecode (.jpb) en C: port de `jp/compilar_nativo.py`.
 *
 * `jp_compilar` hace el trabajo completo: lexer + parser + generador, y
 * resuelve los `importar` relativos al archivo de entrada. El blob que
 * devuelve es el mismo que produce el compilador de Python, byte a byte.
 */

#ifndef JP_COMPILAR_H
#define JP_COMPILAR_H

#include <stddef.h>

typedef struct {
    unsigned char *datos;
    size_t largo;
} JpBlob;

/* Compila `fuente` como si viviera en `ruta` (para resolver imports).
 * Devuelve 1 si todo fue bien; si no, deja "mensaje|linea|columna" en `error`. */
int jp_compilar(const char *fuente, size_t largo, const char *ruta,
                JpBlob *salida, char *error, size_t error_largo);

void jp_blob_liberar(JpBlob *blob);

#endif /* JP_COMPILAR_H */
