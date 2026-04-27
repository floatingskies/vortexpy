#!/usr/bin/env python3
"""
VortexPy Benchmark Suite
========================
Compiles the same algorithm in Python (VortexPy), CPython, and C++ (GCC -O3)
and compares execution times.

Usage:
    python3 benchmark_suite.py
"""

import os
import sys
import time
import subprocess
import tempfile
import statistics
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

BENCHMARK_DIR = Path(__file__).parent.parent / "examples"
ITERATIONS = 5

# ── C++ equivalents of the Python benchmarks ─────────────────────────────

CPP_FIBONACCI = r"""
#include <cstdio>

long long fibonacci(int n) {
    if (n <= 1) return n;
    long long a = 0, b = 1;
    for (int i = 2; i <= n; i++) {
        long long temp = b;
        b = a + b;
        a = temp;
    }
    return b;
}

int main() {
    int n = 40;
    long long result = fibonacci(n);
    printf("%lld\n", result);
    return 0;
}
"""

CPP_SUM_SQUARES = r"""
#include <cstdio>

long long sum_of_squares(long long n) {
    long long total = 0;
    for (long long i = 1; i <= n; i++) {
        total += i * i;
    }
    return total;
}

int main() {
    long long n = 100000000;
    long long result = sum_of_squares(n);
    printf("%lld\n", result);
    return 0;
}
"""

CPP_PRIMES = r"""
#include <cstdio>

int count_primes(int n) {
    int count = 0;
    for (int i = 2; i <= n; i++) {
        int is_prime = 1;
        for (int j = 2; j * j <= i; j++) {
            if (i % j == 0) { is_prime = 0; break; }
        }
        if (is_prime) count++;
    }
    return count;
}

int main() {
    int n = 50000;
    int result = count_primes(n);
    printf("%d\n", result);
    return 0;
}
"""

CPP_MANDELBROT = r"""
#include <cstdio>

int mandelbrot(int cx, int cy, int max_iter) {
    int x = 0, y = 0;
    for (int i = 0; i < max_iter; i++) {
        int x2 = x * x / 10000;
        int y2 = y * y / 10000;
        if (x2 + y2 > 40000) return i;
        y = 2 * x * y / 10000 + cy;
        x = x2 - y2 + cx;
    }
    return max_iter;
}

int main() {
    int max_iter = 100;
    int total = 0;
    for (int cy = -12000; cy < 12000; cy += 400) {
        for (int cx = -20000; cx < 5000; cx += 400) {
            total += mandelbrot(cx, cy, max_iter);
        }
    }
    printf("%d\n", total);
    return 0;
}
"""

CPP_MATMUL = r"""
#include <cstdio>

long long matmul(int size) {
    long long total = 0;
    for (int i = 0; i < size; i++) {
        for (int j = 0; j < size; j++) {
            long long sum_val = 0;
            for (int k = 0; k < size; k++) {
                long long a_val = i * size + k;
                long long b_val = k * size + j;
                sum_val += a_val * b_val;
            }
            total += sum_val;
        }
    }
    return total;
}

int main() {
    int size = 200;
    long long result = matmul(size);
    printf("%lld\n", result);
    return 0;
}
"""

BENCHMARKS = [
    ("Fibonacci (n=40)", "fibonacci.py", CPP_FIBONACCI),
    ("Sum of Squares (n=100M)", "sum_squares.py", CPP_SUM_SQUARES),
    ("Prime Counting (n=50K)", "primes.py", CPP_PRIMES),
    ("Mandelbrot (fixed-point)", "mandelbrot.py", CPP_MANDELBROT),
    ("Matrix Multiply (200x200)", "matmul.py", CPP_MATMUL),
]


def benchmark_command(cmd: list[str], iterations: int = ITERATIONS) -> list[float]:
    """Run a command multiple times and return elapsed times."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    return times


def compile_cpp(cpp_source: str) -> str:
    """Compile C++ source to a native binary using GCC -O3 -march=native."""
    tmpdir = tempfile.mkdtemp(prefix="vortex_bench_")
    cpp_file = os.path.join(tmpdir, "bench.cpp")
    bin_file = os.path.join(tmpdir, "bench_cpp")

    with open(cpp_file, "w") as f:
        f.write(cpp_source)

    result = subprocess.run(
        ["g++", "-O3", "-march=native", "-o", bin_file, cpp_file, "-lm"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"C++ compilation failed: {result.stderr}")

    return bin_file


def compile_vortex(py_file: str) -> str:
    """Compile a Python file with VortexPy."""
    from vortex.pipeline import compile_file

    py_path = str(BENCHMARK_DIR / py_file)
    output = compile_file(py_path, opt_level=3)
    return output


def run_benchmarks():
    """Run the full benchmark suite."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich import box
        USE_RICH = True
    except ImportError:
        USE_RICH = False

    if USE_RICH:
        console = Console()
        console.print(Panel(
            "[bold cyan]VortexPy Benchmark Suite[/bold cyan]\n"
            "[dim]Comparing VortexPy (-O3) vs CPython vs C++ (GCC -O3 -march=native)[/dim]",
            border_style="cyan",
        ))
    else:
        print("=" * 60)
        print("VortexPy Benchmark Suite")
        print("=" * 60)

    results = []

    for name, py_file, cpp_source in BENCHMARKS:
        py_path = str(BENCHMARK_DIR / py_file)

        if USE_RICH:
            console.print(f"\n[bold]▶ {name}[/bold]")
        else:
            print(f"\n▶ {name}")

        # CPython benchmark
        cpython_times = benchmark_command([sys.executable, py_path])
        cpython_avg = statistics.mean(cpython_times)
        cpython_min = min(cpython_times)

        # Compile VortexPy
        try:
            vortex_bin = compile_vortex(py_file)
            vortex_times = benchmark_command([vortex_bin])
            vortex_avg = statistics.mean(vortex_times)
            vortex_min = min(vortex_times)
            vortex_ok = True
        except Exception as e:
            if USE_RICH:
                console.print(f"[red]VortexPy compilation failed: {e}[/red]")
            else:
                print(f"VortexPy compilation failed: {e}")
            vortex_avg = float('inf')
            vortex_min = float('inf')
            vortex_ok = False

        # Compile and benchmark C++
        try:
            cpp_bin = compile_cpp(cpp_source)
            cpp_times = benchmark_command([cpp_bin])
            cpp_avg = statistics.mean(cpp_times)
            cpp_min = min(cpp_times)
            cpp_ok = True
        except Exception as e:
            if USE_RICH:
                console.print(f"[yellow]C++ compilation failed: {e}[/yellow]")
            else:
                print(f"C++ compilation failed: {e}")
            cpp_avg = float('inf')
            cpp_min = float('inf')
            cpp_ok = False

        # Speedup calculations
        speedup_cpython = cpython_avg / vortex_avg if vortex_avg > 0 else 0
        speedup_vs_cpp = vortex_avg / cpp_avg if cpp_avg > 0 else 0

        results.append({
            "name": name,
            "cpython_avg": cpython_avg,
            "cpython_min": cpython_min,
            "vortex_avg": vortex_avg,
            "vortex_min": vortex_min,
            "cpp_avg": cpp_avg,
            "cpp_min": cpp_min,
            "speedup_cpython": speedup_cpython,
            "speedup_vs_cpp": speedup_vs_cpp,
            "vortex_ok": vortex_ok,
            "cpp_ok": cpp_ok,
        })

    # Print results table
    if USE_RICH:
        table = Table(
            title="🏆 Benchmark Results",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Benchmark", style="white", min_width=24)
        table.add_column("CPython", style="yellow", justify="right")
        table.add_column("VortexPy", style="green", justify="right")
        table.add_column("C++ (GCC -O3)", style="magenta", justify="right")
        table.add_column("vs CPython", style="bold green", justify="right")
        table.add_column("vs C++", style="bold", justify="right")

        for r in results:
            cpython_str = f"{r['cpython_avg']*1000:.1f} ms"
            vortex_str = f"{r['vortex_avg']*1000:.1f} ms" if r['vortex_ok'] else "FAIL"
            cpp_str = f"{r['cpp_avg']*1000:.1f} ms" if r['cpp_ok'] else "N/A"
            vs_cpython = f"{r['speedup_cpython']:.1f}x" if r['vortex_ok'] else "—"

            if r['cpp_ok'] and r['vortex_ok']:
                ratio = r['speedup_vs_cpp']
                if ratio <= 1.0:
                    vs_cpp = f"[green]{ratio:.2f}x[/green]"
                elif ratio <= 1.5:
                    vs_cpp = f"[yellow]{ratio:.2f}x[/yellow]"
                else:
                    vs_cpp = f"[red]{ratio:.2f}x[/red]"
            else:
                vs_cpp = "—"

            table.add_row(r["name"], cpython_str, vortex_str, cpp_str, vs_cpython, vs_cpp)

        console.print()
        console.print(table)

        # Summary
        console.print()
        avg_speedup = statistics.mean([r['speedup_cpython'] for r in results if r['vortex_ok']])
        console.print(f"[bold green]⚡ Average speedup vs CPython: {avg_speedup:.1f}x[/bold green]")

        cpp_results = [r for r in results if r['cpp_ok'] and r['vortex_ok']]
        if cpp_results:
            avg_vs_cpp = statistics.mean([r['speedup_vs_cpp'] for r in cpp_results])
            if avg_vs_cpp <= 1.0:
                console.print(f"[bold green]🚀 Average ratio vs C++: {avg_vs_cpp:.2f}x (VortexPy is faster!)[/bold green]")
            elif avg_vs_cpp <= 1.5:
                console.print(f"[bold yellow]📊 Average ratio vs C++: {avg_vs_cpp:.2f}x (close to C++)[/bold yellow]")
            else:
                console.print(f"[bold]📊 Average ratio vs C++: {avg_vs_cpp:.2f}x[/bold]")
    else:
        print("\n" + "=" * 90)
        print(f"{'Benchmark':<24} {'CPython':>12} {'VortexPy':>12} {'C++ -O3':>12} {'vs CPy':>10} {'vs C++':>10}")
        print("-" * 90)
        for r in results:
            cp = f"{r['cpython_avg']*1000:.1f}ms"
            vp = f"{r['vortex_avg']*1000:.1f}ms" if r['vortex_ok'] else "FAIL"
            cpp = f"{r['cpp_avg']*1000:.1f}ms" if r['cpp_ok'] else "N/A"
            vs_cp = f"{r['speedup_cpython']:.1f}x" if r['vortex_ok'] else "—"
            vs_cpp = f"{r['speedup_vs_cpp']:.2f}x" if r['cpp_ok'] and r['vortex_ok'] else "—"
            print(f"{r['name']:<24} {cp:>12} {vp:>12} {cpp:>12} {vs_cp:>10} {vs_cpp:>10}")
        print("=" * 90)


if __name__ == "__main__":
    run_benchmarks()
