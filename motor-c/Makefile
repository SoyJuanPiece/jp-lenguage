# Motor nativo de JP: la máquina virtual en C.
#
#   make            compila jpvm y jptokens
#   make limpio     borra los binarios
#   make test       compila y corre los tests de paridad (necesitan Python)
#   make lexer      compara el lexer en C con jp/lexer.py en todos los .jp

CC      ?= cc
CFLAGS  ?= -O2 -std=c11 -Wall -Wextra -Wno-unused-parameter -fno-strict-aliasing
LDFLAGS ?= -lm

BIN = jpvm
TOKENS = jptokens

todo: $(BIN) $(TOKENS)

$(BIN): jpvm.c
	$(CC) $(CFLAGS) -o $@ jpvm.c $(LDFLAGS)

# Frontend nativo: el lexer en C, con su volcador de tokens.
$(TOKENS): lexer.c lexer.h jptokens.c
	$(CC) $(CFLAGS) -o $@ lexer.c jptokens.c $(LDFLAGS)

limpio:
	rm -f $(BIN) $(TOKENS) *.o

test: $(BIN)
	cd .. && python -m unittest tests.test_motor_c -v

lexer: $(TOKENS)
	cd .. && python herramientas/lexer_paridad.py

.PHONY: todo limpio test lexer
