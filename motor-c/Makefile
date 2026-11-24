# Motor nativo de JP: la máquina virtual en C y el frontend (lexer, parser,
# compilador a .jpb).
#
#   make            compila jpvm y las herramientas del frontend
#   make limpio     borra los binarios
#   make test       compila y corre los tests (necesitan Python)
#   make paridad    los tres arneses: lexer, AST y bytecode
#   make lexer      compara el lexer en C con jp/lexer.py en todos los .jp
#   make ast        compara el parser en C con jp/parser.py
#   make jpb        compara el bytecode generado por los dos compiladores

CC      ?= cc
CFLAGS  ?= -O2 -std=c11 -Wall -Wextra -Wno-unused-parameter -fno-strict-aliasing
LDFLAGS ?= -lm

BIN = jpvm
TOKENS = jptokens
JPAST = jpast
JPCOMPILAR = jpcompilar

FRONTEND = ast.c parser.c lexer.c compilar.c
CABECERAS = ast.h parser.h lexer.h compilar.h

todo: $(BIN) $(TOKENS) $(JPAST) $(JPCOMPILAR)

$(BIN): jpvm.c $(FRONTEND) $(CABECERAS)
	$(CC) $(CFLAGS) -o $@ jpvm.c $(FRONTEND) $(LDFLAGS)

$(TOKENS): lexer.c lexer.h jptokens.c
	$(CC) $(CFLAGS) -o $@ lexer.c jptokens.c $(LDFLAGS)

$(JPAST): jpast.c ast.c parser.c lexer.c $(CABECERAS)
	$(CC) $(CFLAGS) -o $@ jpast.c ast.c parser.c lexer.c $(LDFLAGS)

$(JPCOMPILAR): jpcompilar.c $(FRONTEND) $(CABECERAS)
	$(CC) $(CFLAGS) -o $@ jpcompilar.c $(FRONTEND) $(LDFLAGS)

limpio:
	rm -f $(BIN) $(TOKENS) $(JPAST) $(JPCOMPILAR) *.o

test: $(BIN)
	cd .. && python -m unittest tests.test_motor_c tests.test_lexer_c tests.test_frontend_c -v

lexer: $(TOKENS)
	cd .. && python herramientas/lexer_paridad.py

ast: $(JPAST)
	cd .. && python herramientas/ast_paridad.py

jpb: $(JPCOMPILAR)
	cd .. && python herramientas/jpb_paridad.py

paridad: $(TOKENS) $(JPAST) $(JPCOMPILAR)
	cd .. && python herramientas/lexer_paridad.py
	cd .. && python herramientas/ast_paridad.py
	cd .. && python herramientas/jpb_paridad.py

.PHONY: todo limpio test lexer ast jpb paridad
