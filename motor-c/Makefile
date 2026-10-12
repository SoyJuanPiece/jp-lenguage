# Motor nativo de JP: la máquina virtual en C.
#
#   make            compila jpvm
#   make limpio     borra los binarios
#   make test       compila y corre los tests de paridad (necesitan Python)

CC      ?= cc
CFLAGS  ?= -O2 -std=c11 -Wall -Wextra -Wno-unused-parameter -fno-strict-aliasing
LDFLAGS ?= -lm

BIN = jpvm

todo: $(BIN)

$(BIN): jpvm.c
	$(CC) $(CFLAGS) -o $@ jpvm.c $(LDFLAGS)

limpio:
	rm -f $(BIN) *.o

test: $(BIN)
	cd .. && python -m unittest tests.test_motor_c -v

.PHONY: todo limpio test
