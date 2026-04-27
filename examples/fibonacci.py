#!/usr/bin/env python3
"""
VortexPy example: Fibonacci computation.
Computes the Nth Fibonacci number using an iterative approach.
"""

def fibonacci(n: int) -> int:
    """Compute the Nth Fibonacci number iteratively."""
    if n <= 1:
        return n
    
    a: int = 0
    b: int = 1
    
    for i in range(2, n + 1):
        temp: int = b
        b = a + b
        a = temp
    
    return b


def main() -> int:
    n: int = 40
    result: int = fibonacci(n)
    print(result)
    return 0
