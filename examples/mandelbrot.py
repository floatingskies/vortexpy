#!/usr/bin/env python3
"""
VortexPy example: Mandelbrot set computation.
A compute-heavy benchmark perfect for demonstrating VortexPy's speed.
"""

def mandelbrot(cx: int, cy: int, max_iter: int) -> int:
    """Compute Mandelbrot iterations for a point."""
    # Fixed-point arithmetic: values are scaled by 10000
    x: int = 0
    y: int = 0
    i: int = 0
    
    while i < max_iter:
        x2: int = x * x // 10000
        y2: int = y * y // 10000
        
        if x2 + y2 > 40000:
            return i
        
        y = 2 * x * y // 10000 + cy
        x = x2 - y2 + cx
        i = i + 1
    
    return max_iter


def main() -> int:
    max_iter: int = 100
    # Compute for center region of Mandelbrot set
    cx_start: int = -20000   # -2.0 in fixed point
    cx_end: int = 5000       # 0.5
    cy_start: int = -12000   # -1.2
    cy_end: int = 12000      # 1.2
    step: int = 400          # 0.04
    
    total: int = 0
    cy: int = cy_start
    
    while cy < cy_end:
        cx: int = cx_start
        while cx < cx_end:
            total = total + mandelbrot(cx, cy, max_iter)
            cx = cx + step
        cy = cy + step
    
    print(total)
    return 0
