/* Parser de JP en C: port de `jp/parser.py`.
 *
 * `jp_parsear` tokeniza y construye el mismo AST que el parser de Python,
 * incluido el plegado de constantes (2 + 3 se guarda ya como 5). Los errores
 * salen con el formato "mensaje|linea|columna", igual que los del lexer.
 */

#ifndef JP_PARSER_H
#define JP_PARSER_H

#include <stddef.h>

#include "ast.h"

typedef struct {
    JpNodo *raiz;   /* nodo N_PROGRAMA */
    JpArena arena;  /* dueña de todos los nodos y textos del árbol */
} JpPrograma;

/* Devuelve 1 si el programa se parseó y 0 si hubo error (mensaje en `error`). */
int jp_parsear(const char *fuente, size_t largo, JpPrograma *salida,
               char *error, size_t error_largo);

void jp_programa_liberar(JpPrograma *programa);

#endif /* JP_PARSER_H */
