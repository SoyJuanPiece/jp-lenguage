/* jpcompilar — compila un .jp a bytecode .jpb con el compilador en C.
 *
 *   jpcompilar entrada.jp salida.jpb
 *   jpcompilar --version
 *
 * Es la pieza que usa `herramientas/jpb_paridad.py` para comparar el blob con
 * el del compilador de Python, y la que `jpvm` enlaza para leer `.jp` directo.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "compilar.h"

#define JP_VERSION "1.34.0"

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
    if (argc >= 2 && (strcmp(argv[1], "--version") == 0 || strcmp(argv[1], "-V") == 0)) {
        printf("jpcompilar %s\n", JP_VERSION);
        return 0;
    }
    if (argc != 3) {
        fprintf(stderr, "uso: jpcompilar entrada.jp salida.jpb\n");
        return 64;
    }
    size_t largo = 0;
    char *fuente = leer_archivo(argv[1], &largo);
    if (!fuente) {
        fprintf(stderr, "jpcompilar: no pude leer %s\n", argv[1]);
        return 66;
    }
    JpBlob blob = {0};
    char error[512];
    if (!jp_compilar(fuente, largo, argv[1], &blob, error, sizeof error)) {
        fprintf(stderr, "%s\n", error);
        free(fuente);
        return 1;
    }
    FILE *salida = fopen(argv[2], "wb");
    if (!salida) {
        fprintf(stderr, "jpcompilar: no pude escribir %s\n", argv[2]);
        jp_blob_liberar(&blob);
        free(fuente);
        return 73;
    }
    fwrite(blob.datos, 1, blob.largo, salida);
    fclose(salida);
    jp_blob_liberar(&blob);
    free(fuente);
    return 0;
}
