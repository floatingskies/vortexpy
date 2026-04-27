#!/usr/bin/env python3
"""
VortexPy example: Prime number sieve.
Computes the number of primes up to N using the Sieve of Eratosthenes.
"""

def count_primes(n: int) -> int:
    """Count primes up to n using a simple trial division approach."""
    count: int = 0
    i: int = 2
    
    while i <= n:
        is_prime: int = 1
        j: int = 2
        while j * j <= i:
            if i % j == 0:
                is_prime = 0
            j = j + 1
        if is_prime == 1:
            count = count + 1
        i = i + 1
    
    return count


def main() -> int:
    n: int = 50000
    result: int = count_primes(n)
    print(result)
    return 0
