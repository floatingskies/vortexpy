#!/usr/bin/env python3
"""
VortexPy example: Sum of squares.
A simple but effective benchmark for loop performance.
"""

def sum_of_squares(n: int) -> int:
    """Compute the sum of squares from 1 to n."""
    total: int = 0
    i: int = 1
    
    while i <= n:
        total = total + i * i
        i = i + 1
    
    return total


def main() -> int:
    n: int = 1000000
    result: int = sum_of_squares(n)
    print(result)
    return 0
