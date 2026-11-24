/* Línea base del dominio «rendimiento»: el mismo fib(35) que la puerta en JP.
 *
 * `herramientas/cobertura.py` lo compila con -O2 y compara: JP tiene que estar
 * dentro de 3x de este tiempo para que la puerta pase (fase F8).
 *
 *   cc -O2 -o fib35 pruebas/cobertura/fib35.c
 */
#include <stdio.h>

static long fib(long n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}

int main(void) {
    printf("fib(35): %ld\n", fib(35));
    return 0;
}
