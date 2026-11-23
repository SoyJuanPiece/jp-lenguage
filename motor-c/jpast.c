/* jpast — volcado del AST de un archivo JP.
 *
 *   jpast archivo.jp
 *
 * Imprime el árbol en el mismo formato que `herramientas/ast_paridad.py`
 * produce desde Python, para comparar los dos parsers nodo a nodo.
 */

#include <stdio.h>
#include <stdlib.h>

#include "parser.h"

static char *leer_archivo(const char *ruta, size_t *largo) {
    FILE *f = fopen(ruta, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return NULL;
    }
    long tam = ftell(f);
    if (tam < 0) {
        fclose(f);
        return NULL;
    }
    rewind(f);
    char *datos = (char *)malloc((size_t)tam + 1);
    if (!datos) {
        fclose(f);
        return NULL;
    }
    size_t leidos = fread(datos, 1, (size_t)tam, f);
    fclose(f);
    datos[leidos] = '\0';
    *largo = leidos;
    return datos;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "uso: jpast archivo.jp\n");
        return 64;
    }
    size_t largo = 0;
    char *fuente = leer_archivo(argv[1], &largo);
    if (!fuente) {
        fprintf(stderr, "jpast: no pude leer %s\n", argv[1]);
        return 66;
    }
    JpPrograma programa;
    char error[512];
    if (!jp_parsear(fuente, largo, &programa, error, sizeof error)) {
        fprintf(stderr, "%s\n", error);
        free(fuente);
        return 1;
    }
    jp_ast_volcar(programa.raiz, stdout);
    jp_programa_liberar(&programa);
    free(fuente);
    return 0;
}
