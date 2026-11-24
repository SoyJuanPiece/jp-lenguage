/* Lexer de JP en C — port fiel de `jp/lexer.py`.
 *
 * Mismo orden de tokens, mismos lexemas, mismas líneas/columnas y los mismos
 * errores. Se trabaja sobre la fuente decodificada a puntos de código para que
 * `avanzar()`/`mirar()` se comporten como los de Python (que cuenta
 * caracteres, no bytes): con esto un `ñ` o un `á` en un identificador no
 * desplazan la columna.
 */

#include "lexer.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---------- tabla de nombres ---------- */

static const char *const NOMBRES[] = {
    "PAREN_IZQ", "PAREN_DER", "LLAVE_IZQ", "LLAVE_DER",
    "CORCHETE_IZQ", "CORCHETE_DER", "COMA", "PUNTO_Y_COMA", "DOSPUNTOS",
    "MAS", "MENOS", "POR", "ENTRE", "MODULO", "PUNTO", "IGUAL", "MENOR", "MAYOR",
    "IGUAL_IGUAL", "DIFERENTE", "MENOR_IGUAL", "MAYOR_IGUAL", "PUNTO_PUNTO",
    "POTENCIA", "DOBLE_INTERROGACION", "INTERROGACION_PUNTO",
    "MAS_IGUAL", "MENOS_IGUAL", "POR_IGUAL", "ENTRE_IGUAL", "MODULO_IGUAL",
    "NUMERO", "CADENA", "CADENA_INI", "CADENA_MEDIO", "CADENA_FIN", "IDENTIFICADOR",
    "VAR", "FUN", "RETORNA", "SI", "SINO", "MIENTRAS", "PARA", "EN",
    "VERDADERO", "FALSO", "NULO", "Y", "O", "NO", "ROMPER", "CONTINUAR",
    "ELEGIR", "CASO", "INTENTA", "ATRAPA", "FINALMENTE", "LANZAR",
    "IMPORTAR", "CLASE", "HEREDA",
    "FIN_DE_ARCHIVO",
};

const char *jp_token_nombre(JpTokenType tipo) { return NOMBRES[tipo]; }

/* ---------- palabras clave (incluye los alias fáciles) ---------- */

typedef struct {
    const char *texto;
    JpTokenType tipo;
} PalabraClave;

static const PalabraClave CLAVES[] = {
    {"var", T_VAR}, {"variable", T_VAR},
    {"fun", T_FUN}, {"funcion", T_FUN}, {"función", T_FUN},
    {"retorna", T_RETORNA}, {"devuelve", T_RETORNA},
    {"si", T_SI}, {"sino", T_SINO}, {"mientras", T_MIENTRAS}, {"para", T_PARA},
    {"en", T_EN}, {"verdadero", T_VERDADERO}, {"falso", T_FALSO}, {"nulo", T_NULO},
    {"y", T_Y}, {"o", T_O}, {"no", T_NO}, {"romper", T_ROMPER},
    {"continuar", T_CONTINUAR}, {"elegir", T_ELEGIR}, {"caso", T_CASO},
    {"intenta", T_INTENTA}, {"atrapa", T_ATRAPA}, {"finalmente", T_FINALMENTE},
    {"lanzar", T_LANZAR}, {"importar", T_IMPORTAR}, {"clase", T_CLASE},
    {"hereda", T_HEREDA},
};

/* ---------- estado del lexer ---------- */

typedef struct Lexer {
    const uint32_t *cp;  /* fuente decodificada */
    const size_t *off;   /* off[i] = byte donde empieza el carácter i */
    size_t n;
    size_t inicio;
    size_t actual;
    int linea;
    int columna;
    int linea_inicial;
    int columna_inicial;
    JpTokens *salida;
    char *error;
    size_t error_largo;
    int fallo;
} Lexer;

/* ---------- memoria y utilidades ---------- */

static char *duplicar_bytes(const char *datos, size_t largo) {
    char *copia = (char *)malloc(largo + 1);
    if (!copia) return NULL;
    if (largo) memcpy(copia, datos, largo);
    copia[largo] = '\0';
    return copia;
}

static void reservar(JpTokens *tokens, size_t necesarios) {
    if (tokens->n + necesarios <= tokens->capacidad) return;
    size_t nueva = tokens->capacidad ? tokens->capacidad * 2 : 64;
    while (nueva < tokens->n + necesarios) nueva *= 2;
    JpToken *datos = (JpToken *)realloc(tokens->datos, nueva * sizeof(JpToken));
    if (!datos) return; /* sin memoria: el llamador verá fallo de lexeo */
    tokens->datos = datos;
    tokens->capacidad = nueva;
}

void jp_tokens_liberar(JpTokens *tokens) {
    if (!tokens) return;
    for (size_t i = 0; i < tokens->n; i++) {
        free(tokens->datos[i].lexema);
        free(tokens->datos[i].literal);
    }
    free(tokens->datos);
    tokens->datos = NULL;
    tokens->n = 0;
    tokens->capacidad = 0;
}

static int fallar(Lexer *lx, int linea, int columna, const char *mensaje) {
    if (!lx->fallo && lx->error && lx->error_largo) {
        snprintf(lx->error, lx->error_largo, "%s|%d|%d", mensaje, linea, columna);
    }
    lx->fallo = 1;
    return 0;
}

/* ---------- lectura ---------- */

static int fin(Lexer *lx) { return lx->actual >= lx->n; }

static uint32_t avanzar(Lexer *lx) {
    uint32_t c = lx->cp[lx->actual];
    lx->actual++;
    if (c == '\n') {
        lx->linea++;
        lx->columna = 1;
    } else {
        lx->columna++;
    }
    return c;
}

static uint32_t mirar(Lexer *lx, size_t desplazamiento) {
    size_t i = lx->actual + desplazamiento;
    if (i >= lx->n) return 0;
    return lx->cp[i];
}

static int coincide(Lexer *lx, uint32_t esperado) {
    if (fin(lx) || lx->cp[lx->actual] != esperado) return 0;
    avanzar(lx);
    return 1;
}

/* El texto se recorta de los bytes originales: así el lexema es exactamente
 * lo que escribió el usuario, sin recomponer UTF-8. */
static char *recorte(Lexer *lx, const char *bytes, size_t desde, size_t hasta) {
    size_t ini = lx->off[desde];
    size_t finb = lx->off[hasta];
    return duplicar_bytes(bytes + ini, finb - ini);
}

static void agregar(Lexer *lx, const char *bytes, JpTokenType tipo, char *literal,
                    int es_entero, double numero) {
    reservar(lx->salida, 1);
    if (lx->salida->n >= lx->salida->capacidad) {
        lx->fallo = 1;
        free(literal);
        return;
    }
    JpToken *t = &lx->salida->datos[lx->salida->n++];
    t->tipo = tipo;
    t->lexema = recorte(lx, bytes, lx->inicio, lx->actual);
    t->literal = literal;
    t->linea = lx->linea_inicial;
    t->columna = lx->columna_inicial;
    t->es_entero = es_entero;
    t->numero = numero;
}

/* ---------- cadenas ---------- */

typedef struct {
    char *datos;
    size_t n;
    size_t capacidad;
} Texto;

static void texto_agregar_char(Texto *t, uint32_t c);
static void texto_agregar_utf8(Texto *t, uint32_t c);

static void texto_reservar(Texto *t, size_t extra) {
    if (t->n + extra + 1 <= t->capacidad) return;
    size_t nueva = t->capacidad ? t->capacidad * 2 : 32;
    while (nueva < t->n + extra + 1) nueva *= 2;
    char *datos = (char *)realloc(t->datos, nueva);
    if (!datos) return;
    t->datos = datos;
    t->capacidad = nueva;
}

static void texto_agregar_utf8(Texto *t, uint32_t c) {
    unsigned char buffer[4];
    size_t largo = 0;
    if (c < 0x80) {
        buffer[largo++] = (unsigned char)c;
    } else if (c < 0x800) {
        buffer[largo++] = (unsigned char)(0xC0 | (c >> 6));
        buffer[largo++] = (unsigned char)(0x80 | (c & 0x3F));
    } else if (c < 0x10000) {
        buffer[largo++] = (unsigned char)(0xE0 | (c >> 12));
        buffer[largo++] = (unsigned char)(0x80 | ((c >> 6) & 0x3F));
        buffer[largo++] = (unsigned char)(0x80 | (c & 0x3F));
    } else {
        buffer[largo++] = (unsigned char)(0xF0 | (c >> 18));
        buffer[largo++] = (unsigned char)(0x80 | ((c >> 12) & 0x3F));
        buffer[largo++] = (unsigned char)(0x80 | ((c >> 6) & 0x3F));
        buffer[largo++] = (unsigned char)(0x80 | (c & 0x3F));
    }
    texto_reservar(t, largo);
    memcpy(t->datos + t->n, buffer, largo);
    t->n += largo;
    t->datos[t->n] = '\0';
}

static void texto_agregar_char(Texto *t, uint32_t c) { texto_agregar_utf8(t, c); }

static void texto_libre(Texto *t) {
    free(t->datos);
    t->datos = NULL;
    t->n = t->capacidad = 0;
}

static char *texto_quitar(Texto *t) {
    char *datos = t->datos;
    if (!datos) datos = duplicar_bytes("", 0);
    t->datos = NULL;
    t->n = t->capacidad = 0;
    return datos;
}

/* Escapes válidos dentro de una cadena. */
static int escape_a_char(uint32_t e, char *salida, size_t *largo) {
    switch (e) {
        case 'n': salida[0] = '\n'; *largo = 1; return 1;
        case 't': salida[0] = '\t'; *largo = 1; return 1;
        case 'r': salida[0] = '\r'; *largo = 1; return 1;
        case '"': salida[0] = '"'; *largo = 1; return 1;
        case '\\': salida[0] = '\\'; *largo = 1; return 1;
        case '{': salida[0] = '{'; *largo = 1; return 1;
        case '}': salida[0] = '}'; *largo = 1; return 1;
        default: *largo = 0; return 0;
    }
}

static int leer_hasta_llave(Lexer *lx, Texto *expr);

static int saltar_cadena_simple(Lexer *lx, uint32_t delim, Texto *trozo) {
    for (;;) {
        if (fin(lx)) return 0;
        uint32_t c = avanzar(lx);
        if (c == '\\') {
            texto_agregar_char(trozo, c);
            if (fin(lx)) return 0;
            texto_agregar_char(trozo, avanzar(lx));
            continue;
        }
        texto_agregar_char(trozo, c);
        if (c == delim) return 1;
    }
}

static int leer_hasta_llave(Lexer *lx, Texto *expr) {
    int linea_inicial = lx->linea;
    int columna_inicial = lx->columna - 1;
    int llaves = 1;
    int parentesis = 0;
    int corchetes = 0;
    for (;;) {
        if (fin(lx)) {
            return fallar(lx, linea_inicial, columna_inicial,
                          "interpolación sin cerrar (falta '}')");
        }
        uint32_t c = avanzar(lx);
        if (c == '"' || c == '\'') {
            texto_agregar_char(expr, c);
            if (!saltar_cadena_simple(lx, c, expr)) {
                return fallar(lx, lx->linea, lx->columna,
                              "cadena sin cerrar dentro de una interpolación");
            }
            continue;
        }
        if (c == '\\') {
            texto_agregar_char(expr, c);
            if (fin(lx)) {
                return fallar(lx, lx->linea, lx->columna,
                              "escape incompleto en interpolación");
            }
            texto_agregar_char(expr, avanzar(lx));
            continue;
        }
        if (c == '{') {
            llaves++;
        } else if (c == '}') {
            llaves--;
            if (llaves == 0 && parentesis == 0 && corchetes == 0) return 1;
        } else if (c == '(') {
            parentesis++;
        } else if (c == ')') {
            parentesis--;
        } else if (c == '[') {
            corchetes++;
        } else if (c == ']') {
            corchetes--;
        }
        texto_agregar_char(expr, c);
    }
}

static int tokenizar_en(Lexer *lx, const char *bytes, size_t largo);

/* Tokeniza el texto de una interpolación y EMPALMA sus tokens (sin el
 * FIN_DE_ARCHIVO del sub-lexer). */
static int empalmar_expresion(Lexer *lx, const char *bytes, size_t largo) {
    size_t antes = lx->salida->n;
    if (!tokenizar_en(lx, bytes, largo)) return 0;
    if (lx->salida->n <= antes + 1) {
        /* Sólo se añadió el FIN_DE_ARCHIVO: la interpolación estaba vacía. */
        return fallar(lx, lx->linea_inicial, lx->columna_inicial,
                      "interpolación vacía {}");
    }
    /* Quitar el FIN_DE_ARCHIVO del sub-lexer. */
    JpToken *ultimo = &lx->salida->datos[lx->salida->n - 1];
    free(ultimo->lexema);
    free(ultimo->literal);
    lx->salida->n--;
    return 1;
}

static int escanear_cadena(Lexer *lx, const char *bytes, uint32_t delim) {
    if (delim == '\'') {
        Texto valor = {0};
        for (;;) {
            if (fin(lx)) {
                texto_libre(&valor);
                return fallar(lx, lx->linea_inicial, lx->columna_inicial,
                              "cadena sin cerrar (falta ')");
            }
            uint32_t c = avanzar(lx);
            if (c == '\'') break;
            if (c == '\\') {
                uint32_t escape = fin(lx) ? 0 : avanzar(lx);
                char ch;
                size_t largo_ch;
                if (!escape_a_char(escape, &ch, &largo_ch)) {
                    char mensaje[96];
                    snprintf(mensaje, sizeof mensaje, "escape no válido: \\%c", (char)escape);
                    texto_libre(&valor);
                    return fallar(lx, lx->linea, lx->columna - 1, mensaje);
                }
                texto_reservar(&valor, largo_ch);
                memcpy(valor.datos + valor.n, &ch, largo_ch);
                valor.n += largo_ch;
                valor.datos[valor.n] = '\0';
            } else {
                texto_agregar_char(&valor, c);
            }
        }
        char *literal = texto_quitar(&valor);
        agregar(lx, bytes, T_CADENA, literal, 0, 0);
        return !lx->fallo;
    }

    /* Comillas dobles: pueden interpolar. */
    Texto *trozos = NULL;
    char **expresiones = NULL;
    size_t n_trozos = 0;
    size_t n_expr = 0;
    Texto actual = {0};

    for (;;) {
        if (fin(lx)) {
            texto_libre(&actual);
            for (size_t i = 0; i < n_trozos; i++) texto_libre(&trozos[i]);
            free(trozos);
            for (size_t i = 0; i < n_expr; i++) free(expresiones[i]);
            free(expresiones);
            return fallar(lx, lx->linea_inicial, lx->columna_inicial,
                          "cadena sin cerrar (falta \")");
        }
        uint32_t c = avanzar(lx);
        if (c == '"') break;
        if (c == '\\') {
            uint32_t escape = fin(lx) ? 0 : avanzar(lx);
            char ch;
            size_t largo_ch;
            if (!escape_a_char(escape, &ch, &largo_ch)) {
                char mensaje[96];
                snprintf(mensaje, sizeof mensaje, "escape no válido: \\%c", (char)escape);
                texto_libre(&actual);
                for (size_t i = 0; i < n_trozos; i++) texto_libre(&trozos[i]);
                free(trozos);
                for (size_t i = 0; i < n_expr; i++) free(expresiones[i]);
                free(expresiones);
                return fallar(lx, lx->linea, lx->columna - 1, mensaje);
            }
            texto_reservar(&actual, largo_ch);
            memcpy(actual.datos + actual.n, &ch, largo_ch);
            actual.n += largo_ch;
            actual.datos[actual.n] = '\0';
            continue;
        }
        if (c == '{') {
            trozos = (Texto *)realloc(trozos, (n_trozos + 1) * sizeof(Texto));
            trozos[n_trozos++] = (Texto){0};
            trozos[n_trozos - 1].datos = texto_quitar(&actual);
            trozos[n_trozos - 1].n = trozos[n_trozos - 1].datos ? strlen(trozos[n_trozos - 1].datos) : 0;

            Texto expr = {0};
            if (!leer_hasta_llave(lx, &expr)) {
                texto_libre(&expr);
                for (size_t i = 0; i < n_trozos; i++) texto_libre(&trozos[i]);
                free(trozos);
                for (size_t i = 0; i < n_expr; i++) free(expresiones[i]);
                free(expresiones);
                return 0;
            }
            expresiones = (char **)realloc(expresiones, (n_expr + 1) * sizeof(char *));
            size_t largo_expr = expr.n;
            expresiones[n_expr++] = texto_quitar(&expr);
            (void)largo_expr;
            continue;
        }
        texto_agregar_char(&actual, c);
    }

    trozos = (Texto *)realloc(trozos, (n_trozos + 1) * sizeof(Texto));
    trozos[n_trozos].datos = texto_quitar(&actual);
    trozos[n_trozos].n = trozos[n_trozos].datos ? strlen(trozos[n_trozos].datos) : 0;
    n_trozos++;

    if (n_expr == 0) {
        char *literal = trozos[0].datos ? trozos[0].datos : duplicar_bytes("", 0);
        agregar(lx, bytes, T_CADENA, literal, 0, 0);
        trozos[0].datos = NULL;
        free(trozos);
        return !lx->fallo;
    }

    {
        char *inicio = duplicar_bytes(trozos[0].datos ? trozos[0].datos : "",
                                      trozos[0].n);
        agregar(lx, bytes, T_CADENA_INI, inicio, 0, 0);
    }
    for (size_t i = 0; i < n_expr; i++) {
        if (!empalmar_expresion(lx, expresiones[i], strlen(expresiones[i]))) {
            for (size_t j = i; j < n_expr; j++) free(expresiones[j]);
            free(expresiones);
            for (size_t j = 0; j < n_trozos; j++) texto_libre(&trozos[j]);
            free(trozos);
            return 0;
        }
        Texto *texto = &trozos[i + 1];
        char *copia = duplicar_bytes(texto->datos ? texto->datos : "", texto->n);
        agregar(lx, bytes, (i == n_expr - 1) ? T_CADENA_FIN : T_CADENA_MEDIO,
                copia, 0, 0);
    }

    for (size_t i = 0; i < n_trozos; i++) texto_libre(&trozos[i]);
    free(trozos);
    for (size_t i = 0; i < n_expr; i++) free(expresiones[i]);
    free(expresiones);
    return !lx->fallo;
}

/* ---------- números e identificadores ---------- */

static int es_digito(uint32_t c) { return c >= '0' && c <= '9'; }

static int es_letra(uint32_t c) {
    if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_') return 1;
    /* Letras con tilde/ñ y demás alfabetos: todo lo que no es ASCII se trata
     * como letra, igual que hace Python con isalpha en la práctica. */
    return c >= 0x80;
}

static int es_alfanumerico(uint32_t c) { return es_letra(c) || es_digito(c); }

static void escanear_numero(Lexer *lx, const char *bytes) {
    while (es_digito(mirar(lx, 0))) avanzar(lx);
    int entero = 1;
    if (mirar(lx, 0) == '.' && es_digito(mirar(lx, 1))) {
        entero = 0;
        avanzar(lx); /* el punto */
        while (es_digito(mirar(lx, 0))) avanzar(lx);
    }
    /* Valor: se parsea del texto, que es ASCII (dígitos y punto). */
    size_t ini = lx->off[lx->inicio];
    size_t finb = lx->off[lx->actual];
    char *texto = duplicar_bytes(bytes + ini, finb - ini);
    double valor = texto ? strtod(texto, NULL) : 0;
    free(texto);
    agregar(lx, bytes, T_NUMERO, NULL, entero, valor);
}

static JpTokenType tipo_de_palabra(const char *texto) {
    for (size_t i = 0; i < sizeof CLAVES / sizeof CLAVES[0]; i++) {
        if (strcmp(CLAVES[i].texto, texto) == 0) return CLAVES[i].tipo;
    }
    return T_IDENTIFICADOR;
}

static void escanear_identificador(Lexer *lx, const char *bytes) {
    while (es_alfanumerico(mirar(lx, 0))) avanzar(lx);
    char *texto = recorte(lx, bytes, lx->inicio, lx->actual);
    JpTokenType tipo = tipo_de_palabra(texto ? texto : "");
    char *literal = NULL;
    if (tipo == T_VERDADERO) {
        literal = duplicar_bytes("1", 1);
        free(texto);
        texto = NULL;
    } else if (tipo == T_FALSO) {
        literal = duplicar_bytes("0", 1);
        free(texto);
        texto = NULL;
    } else if (tipo == T_IDENTIFICADOR) {
        literal = texto; /* el literal del identificador es su nombre */
        texto = NULL;
    }
    free(texto);
    reservar(lx->salida, 1);
    if (lx->salida->n >= lx->salida->capacidad) {
        lx->fallo = 1;
        free(literal);
        return;
    }
    JpToken *t = &lx->salida->datos[lx->salida->n++];
    t->tipo = tipo;
    t->lexema = recorte(lx, bytes, lx->inicio, lx->actual);
    t->literal = literal;
    t->linea = lx->linea_inicial;
    t->columna = lx->columna_inicial;
    t->es_entero = 0;
    t->numero = 0;
}

/* ---------- escaneo de un token ---------- */

static int escanear_token(Lexer *lx, const char *bytes) {
    uint32_t c = avanzar(lx);

    if (c == '#') {
        while (!fin(lx) && mirar(lx, 0) != '\n') avanzar(lx);
        return 1;
    }
    if (c == ' ' || c == '\t' || c == '\r' || c == '\n') return 1;

    switch (c) {
        case '(': agregar(lx, bytes, T_PAREN_IZQ, NULL, 0, 0); return !lx->fallo;
        case ')': agregar(lx, bytes, T_PAREN_DER, NULL, 0, 0); return !lx->fallo;
        case '{': agregar(lx, bytes, T_LLAVE_IZQ, NULL, 0, 0); return !lx->fallo;
        case '}': agregar(lx, bytes, T_LLAVE_DER, NULL, 0, 0); return !lx->fallo;
        case '[': agregar(lx, bytes, T_CORCHETE_IZQ, NULL, 0, 0); return !lx->fallo;
        case ']': agregar(lx, bytes, T_CORCHETE_DER, NULL, 0, 0); return !lx->fallo;
        case ',': agregar(lx, bytes, T_COMA, NULL, 0, 0); return !lx->fallo;
        case ';': agregar(lx, bytes, T_PUNTO_Y_COMA, NULL, 0, 0); return !lx->fallo;
        case ':': agregar(lx, bytes, T_DOSPUNTOS, NULL, 0, 0); return !lx->fallo;
        case '+':
            if (coincide(lx, '=')) agregar(lx, bytes, T_MAS_IGUAL, NULL, 0, 0);
            else agregar(lx, bytes, T_MAS, NULL, 0, 0);
            return !lx->fallo;
        case '-':
            if (coincide(lx, '=')) agregar(lx, bytes, T_MENOS_IGUAL, NULL, 0, 0);
            else agregar(lx, bytes, T_MENOS, NULL, 0, 0);
            return !lx->fallo;
        case '*':
            if (coincide(lx, '*')) agregar(lx, bytes, T_POTENCIA, NULL, 0, 0);
            else if (coincide(lx, '=')) agregar(lx, bytes, T_POR_IGUAL, NULL, 0, 0);
            else agregar(lx, bytes, T_POR, NULL, 0, 0);
            return !lx->fallo;
        case '/':
            if (coincide(lx, '=')) agregar(lx, bytes, T_ENTRE_IGUAL, NULL, 0, 0);
            else agregar(lx, bytes, T_ENTRE, NULL, 0, 0);
            return !lx->fallo;
        case '%':
            if (coincide(lx, '=')) agregar(lx, bytes, T_MODULO_IGUAL, NULL, 0, 0);
            else agregar(lx, bytes, T_MODULO, NULL, 0, 0);
            return !lx->fallo;
        case '=':
            if (coincide(lx, '=')) agregar(lx, bytes, T_IGUAL_IGUAL, NULL, 0, 0);
            else agregar(lx, bytes, T_IGUAL, NULL, 0, 0);
            return !lx->fallo;
        case '<':
            if (coincide(lx, '=')) agregar(lx, bytes, T_MENOR_IGUAL, NULL, 0, 0);
            else agregar(lx, bytes, T_MENOR, NULL, 0, 0);
            return !lx->fallo;
        case '>':
            if (coincide(lx, '=')) agregar(lx, bytes, T_MAYOR_IGUAL, NULL, 0, 0);
            else agregar(lx, bytes, T_MAYOR, NULL, 0, 0);
            return !lx->fallo;
        default: break;
    }

    if (c == '!') {
        if (coincide(lx, '=')) {
            agregar(lx, bytes, T_DIFERENTE, NULL, 0, 0);
            return !lx->fallo;
        }
        return fallar(lx, lx->linea, lx->columna - 1,
                      "carácter inesperado '!'. ¿Quisiste decir '!=' ?");
    }

    if (c == '?') {
        if (coincide(lx, '?')) {
            agregar(lx, bytes, T_DOBLE_INTERROGACION, NULL, 0, 0);
            return !lx->fallo;
        }
        if (coincide(lx, '.')) {
            agregar(lx, bytes, T_INTERROGACION_PUNTO, NULL, 0, 0);
            return !lx->fallo;
        }
        return fallar(lx, lx->linea, lx->columna - 1,
                      /* Partido para que '??' no forme un trígrafo ('^'). */
                      "carácter inesperado '?'. ¿Quisiste decir '?" "?' (valor si es nulo) "
                      "o '?.' (acceso seguro)?");
    }

    if (c == '"' || c == '\'') return escanear_cadena(lx, bytes, c);

    if (c == '.') {
        if (mirar(lx, 0) == '.') {
            avanzar(lx);
            agregar(lx, bytes, T_PUNTO_PUNTO, NULL, 0, 0);
            return !lx->fallo;
        }
        if (es_letra(mirar(lx, 0))) {
            agregar(lx, bytes, T_PUNTO, NULL, 0, 0);
            return !lx->fallo;
        }
        return fallar(lx, lx->linea, lx->columna - 1,
                      "el '.' inesperado (los rangos van 1..10 y las claves van d.clave)");
    }

    if (es_digito(c)) {
        /* El carácter ya está consumido: se retrocede el índice de lectura
         * sin tocar línea/columna (es un solo carácter ASCII). */
        lx->actual--;
        lx->columna--;
        escanear_numero(lx, bytes);
        return !lx->fallo;
    }

    if (es_letra(c)) {
        lx->actual--;
        lx->columna--;
        escanear_identificador(lx, bytes);
        return !lx->fallo;
    }

    {
        char mensaje[64];
        char texto[8] = {0};
        size_t usado = 0;
        /* Repr aproximado del carácter no reconocido. */
        if (c < 0x80) {
            texto[usado++] = (char)c;
        } else {
            usado = 0; /* se deja vacío; el carácter se ve en la columna */
        }
        snprintf(mensaje, sizeof mensaje, "carácter no reconocido: '%s'", texto);
        return fallar(lx, lx->linea, lx->columna - 1, mensaje);
    }
}

/* ---------- decodificación UTF-8 ---------- */

static void decodificar(const char *fuente, size_t largo, uint32_t **cp_out,
                        size_t **off_out, size_t *n_out) {
    size_t maximo = largo + 1;
    uint32_t *cp = (uint32_t *)malloc(maximo * sizeof(uint32_t));
    size_t *off = (size_t *)malloc((maximo + 1) * sizeof(size_t));
    size_t n = 0;
    size_t i = 0;
    while (i < largo) {
        unsigned char b = (unsigned char)fuente[i];
        uint32_t c;
        size_t extra;
        if (b < 0x80) {
            c = b;
            extra = 0;
        } else if ((b & 0xE0) == 0xC0) {
            c = b & 0x1F;
            extra = 1;
        } else if ((b & 0xF0) == 0xE0) {
            c = b & 0x0F;
            extra = 2;
        } else if ((b & 0xF8) == 0xF0) {
            c = b & 0x07;
            extra = 3;
        } else {
            c = b; /* byte inválido: se deja tal cual */
            extra = 0;
        }
        off[n] = i;
        size_t j = 1;
        while (j <= extra && i + j < largo) {
            c = (c << 6) | ((unsigned char)fuente[i + j] & 0x3F);
            j++;
        }
        cp[n++] = c;
        i += extra + 1;
    }
    off[n] = largo;
    *cp_out = cp;
    *off_out = off;
    *n_out = n;
}

/* ---------- API ---------- */

static int tokenizar_en(Lexer *lx, const char *bytes, size_t largo) {
    uint32_t *cp = NULL;
    size_t *off = NULL;
    size_t n = 0;
    decodificar(bytes, largo, &cp, &off, &n);

    Lexer sub = *lx;
    sub.cp = cp;
    sub.off = off;
    sub.n = n;
    sub.inicio = 0;
    sub.actual = 0;
    sub.linea = 1;
    sub.columna = 1;
    sub.fallo = 0;

    while (!fin(&sub)) {
        sub.linea_inicial = sub.linea;
        sub.columna_inicial = sub.columna;
        sub.inicio = sub.actual;
        if (!escanear_token(&sub, bytes)) {
            /* `sub.error` es el MISMO buffer que `lx->error`: el mensaje ya
             * está escrito, sólo hay que propagar el fallo. Copiarlo sobre sí
             * mismo era comportamiento indefinido (y con gcc -O2 reventaba). */
            lx->fallo = 1;
            break;
        }
    }

    if (!sub.fallo) {
        sub.linea_inicial = sub.linea;
        sub.columna_inicial = sub.columna;
        sub.inicio = sub.actual;
        agregar(&sub, bytes, T_FIN_DE_ARCHIVO, NULL, 0, 0);
    }
    lx->fallo = sub.fallo;
    free(cp);
    free(off);
    return !lx->fallo;
}

int jp_tokenizar(const char *fuente, size_t largo, JpTokens *salida,
                 char *error, size_t error_largo) {
    salida->datos = NULL;
    salida->n = 0;
    salida->capacidad = 0;

    Lexer lx;
    memset(&lx, 0, sizeof lx);
    lx.linea = 1;
    lx.columna = 1;
    lx.salida = salida;
    lx.error = error;
    lx.error_largo = error_largo;
    if (error && error_largo) error[0] = '\0';

    if (!tokenizar_en(&lx, fuente, largo)) {
        jp_tokens_liberar(salida);
        return 0;
    }
    return 1;
}
