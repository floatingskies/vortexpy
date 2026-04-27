#!/usr/bin/env python3
"""
VortexPy example: Matrix multiplication.
Classic compute-intensive operation.
"""

def matmul(size: int) -> int:
    """Perform matrix multiplication and return sum of result matrix."""
    # We use flat arrays to avoid nested lists
    # A, B, C are size*size matrices stored as flat arrays
    # A[i][j] = A[i*size + j]
    
    # Initialize matrices
    total: int = 0
    i: int = 0
    
    while i < size:
        j: int = 0
        while j < size:
            sum_val: int = 0
            k: int = 0
            while k < size:
                # A[i][k] * B[k][j] = (i*size+k) * (k*size+j)
                a_val: int = i * size + k
                b_val: int = k * size + j
                sum_val = sum_val + a_val * b_val
                k = k + 1
            total = total + sum_val
            j = j + 1
        i = i + 1
    
    return total


def main() -> int:
    size: int = 200
    result: int = matmul(size)
    print(result)
    return 0
