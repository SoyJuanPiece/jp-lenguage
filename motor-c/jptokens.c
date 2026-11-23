/* jptokens — volcado de tokens del lexer en C, en JSON.
 *
 *   jptokens archivo.jp        # imprime la lista de tokens
 *   jptokens --version
 *
 * Existe para que `herramientas/lexer_paridad.py` compare el lexer de C con
 * `jp/lexer.py` token a token. Es también la primera pieza reutilizable del
 * frontend nativo: `jpvm` enlazará `lexer.c` igual que hace este programa.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lexer.h"

#define JP_VERSION "1.34.0"

static void imprimir_texto(const char *texto) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)texto; *p; p++) {
        switch (*p) {
            case '"': fputs("\\\"", stdout); break;
            case '\\': fputs("\\\\", stdout); break;
            case '\n': fputs("\\n", stdout); break;
            case '\t': fputs("\\t", stdout); break;
            case '\r': fputs("\\r", stdout); break;
            default:
                if (*p < 0x20) {
                    printf("\\u%04x", *p);
                } else {
                    putchar(*p);
                }
        }
    }
    putchar('"');
}

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
        printf("jptokens %s\n", JP_VERSION);
        return 0;
    }
    if (argc != 2) {
        fprintf(stderr, "uso: jptokens archivo.jp\n");
        return 64;
    }

    size_t largo = 0;
    char *fuente = leer_archivo(argv[1], &largo);
    if (!fuente) {
        fprintf(stderr, "jptokens: no pude leer %s\n", argv[1]);
        return 66;
    }

    JpTokens tokens;
    char error[512];
    if (!jp_tokenizar(fuente, largo, &tokens, error, sizeof error)) {
        fprintf(stderr, "%s\n", error);
        free(fuente);
        return 1;
    }

    printf("[");
    for (size_t i = 0; i < tokens.n; i++) {
        JpToken *t = &tokens.datos[i];
        if (i) printf(",");
        printf("{\"tipo\":\"%s\",\"lexema\":", jp_token_nombre(t->tipo));
        imprimir_texto(t->lexema ? t->lexema : "");
        printf(",\"literal\":");
        if (t->literal) {
            imprimir_texto(t->literal);
        } else {
            printf("null");
        }
        printf(",\"linea\":%d,\"columna\":%d", t->linea, t->columna);
        if (t->tipo == T_NUMERO) {
            if (t->es_entero) {
                printf(",\"numero\":\"%.0f\"", t->numero);
            } else {
                printf(",\"numero\":\"%.17g\"", t->numero);
            }
        }
        printf("}");
    }
    printf("]\n");

    jp_tokens_liberar(&tokens);
    free(fuente);
    return 0;
}
