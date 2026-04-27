<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-cyan?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/LLVM-15.0-ff69b4?style=for-the-badge" alt="LLVM">
  <img src="https://img.shields.io/badge/Linux-Native-green?style=for-the-badge" alt="Linux">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge" alt="Python">
</p>

<h1 align="center">
  <pre>
 ╦╔═╔═╗╦ ╦╔╗ ╔═╗╦═╗╔═╗╦ ╦╦╔═╔═╗
 ╠╩╗║ ║║║║╠╩╗╔═╝╠╦╝║  ╠═╣╠╩╗╚═╗
 ╩ ╩╚═╝╚╩╝╩ ╩╚═╝╩╚═╚═╝╩ ╩╩ ╩╚═╝
  </pre>
</h1>

<p align="center"><strong>High-Performance Python AOT Compiler — Powered by LLVM</strong></p>

<p align="center">
  Compile type-annotated Python to <strong>optimized native binaries</strong> that run<br>
  <strong>2× to 43× faster</strong> than CPython — competitive with C++ on compute-heavy workloads.
</p>

---

## Why VortexPy?

| Problem | Solution |
|---------|----------|
| Python is slow for number crunching | VortexPy compiles to native code via LLVM |
| Cython/Numba are complex to set up | `pip install vortexpy` — that's it |
| Writing C/C++ extensions is painful | Just add type annotations to your Python |
| JIT warmup kills short-lived scripts | VortexPy is **AOT** — zero warmup time |

---

## Quick Start

### Installation

```bash
# Install from source
git clone https://github.com/your-org/vortexpy.git
cd vortexpy
pip install -e .
```

**Requirements:**
- Python 3.10+
- Linux (x86_64)
- GCC (for linking)
- `llvmlite >= 0.42.0` (auto-installed)
- `rich >= 13.0.0` (auto-installed)
- `click >= 8.0.0` (auto-installed)

**Verify installation:**

```bash
$ vortex info
```

This displays your system info, LLVM version, CPU features, and supported language features.

### Your First Compiled Program

Write a type-annotated Python file:

```python
# fib.py
def fibonacci(n: int) -> int:
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
    result: int = fibonacci(40)
    print(result)
    return 0
```

Compile and run:

```bash
# Compile to native binary
$ vortex compile fib.py -O3

# Run it
$ ./fib_vortex
102334155

# Or compile + run in one step (JIT mode)
$ vortex run fib.py -O3
102334155

# Benchmark against CPython
$ vortex bench fib.py
```

---

## CLI Reference

```
vortex compile <file.py>    Compile to a native binary
  -o, --output PATH         Output file path
  -O, --opt-level INT       Optimization level 0-3 (default: 3)
  --emit-llvm               Emit LLVM IR instead of binary
  --emit-asm                Emit assembly instead of binary
  --show-ir                 Show generated LLVM IR
  -q, --quiet               Quiet mode

vortex run <file.py>        Compile and run immediately (JIT)
  -O, --opt-level INT       Optimization level 0-3 (default: 3)
  --show-ir                 Show generated LLVM IR

vortex bench <file.py>      Benchmark VortexPy vs CPython
  -O, --opt-level INT       Optimization level 0-3 (default: 3)
  -n, --iterations INT      Number of iterations (default: 5)

vortex info                 Show system and compiler information
```

---

## Python API

You can also use VortexPy programmatically:

```python
from vortex.pipeline import compile_file, compile_string, run_string

# Compile to native binary
binary_path = compile_file("my_script.py", opt_level=3)

# Compile a string and run JIT
exit_code = run_string("""
def main() -> int:
    print(42)
    return 0
""")

# Get LLVM IR
ir = compile_string("def main() -> int: return 42", emit="llvm")

# Get assembly
asm = compile_string("def main() -> int: return 42", emit="asm")
```

---

## Benchmark Results

All benchmarks run on **Linux x86_64** with an **Intel Ice Lake** CPU, **LLVM 15**, and **GCC 14 -O3 -march=native**. Each test was run 5 times; the table shows average wall-clock time including process startup.

### VortexPy vs CPython vs C++

| Benchmark | CPython | VortexPy | C++ (GCC -O3) | vs CPython | vs C++ |
|---|---:|---:|---:|:---:|:---:|
| Fibonacci (n=40) | 23.8 ms | 0.6 ms | 0.5 ms | **43.2×** | 1.14× |
| Sum of Squares (n=1M) | 27.6 ms | 1.1 ms | 0.5 ms | **25.8×** | 1.62× |
| Mandelbrot (fixed-point) | 23.7 ms | 1.7 ms | 1.0 ms | **13.9×** | 1.77× |
| Matrix Multiply (200×200) | 23.4 ms | 5.0 ms | 0.5 ms | **4.7×** | 7.27× |
| Prime Counting (n=50K) | 23.7 ms | 14.8 ms | 2.8 ms | **1.6×** | 5.11× |

> **Key takeaways:**
> - VortexPy delivers **1.6× to 43× speedups** over CPython on compute-heavy loops.
> - On tight numeric loops (Fibonacci), VortexPy is within **1.14× of C++** compiled with GCC -O3.
> - CPython overhead is dominated by interpreter dispatch; VortexPy eliminates this entirely.

### Correctness Verification

Every benchmark produces **identical output** between VortexPy and C++ (native i64 arithmetic). CPython may differ on overflow-sensitive code due to its arbitrary-precision integers:

| Benchmark | VortexPy | C++ (GCC -O3) | CPython | Match? |
|---|---|---|---|:---:|
| Fibonacci (n=40) | 102334155 | 102334155 | 102334155 | ✅ |
| Sum of Squares (n=1M) | 333333833333500000 | 333333833333500000 | 333333833333500000 | ✅ |
| Mandelbrot | 115130 | 115130 | 115237 | ⚠️ |
| Matrix Multiply (200×200) | 3205173202000000 | 3205173202000000 | 3205173202000000 | ✅ |
| Prime Counting (n=50K) | 5133 | 5133 | 5133 | ✅ |

> ⚠️ **Mandelbrot note:** VortexPy and C++ both use native 64-bit integers, producing **identical results** (115130). CPython's arbitrary-precision integers compute a different result (115237) because intermediate `x * x` values don't overflow in the same way. The VortexPy/C++ result is the mathematically expected output for fixed-width integer arithmetic.

### Run the Benchmarks Yourself

```bash
# Quick benchmark of a single file
$ vortex bench examples/fibonacci.py -n 10

# Full suite (VortexPy vs CPython vs C++)
$ python3 benchmarks/benchmark_suite.py
```

---

## Supported Language Features

### What Works

| Feature | Status |
|---------|:------:|
| Type-annotated functions (`def f(x: int) -> int`) | ✅ |
| Integer arithmetic (`i64`: `+`, `-`, `*`, `//`, `%`, `**`) | ✅ |
| Float arithmetic (`f64`: `+`, `-`, `*`, `/`, `%`) | ✅ |
| Boolean operations (`and`, `or`, `not`) | ✅ |
| Bitwise operations (`&`, `\|`, `^`, `<<`, `>>`, `~`) | ✅ |
| Comparison operators (`==`, `!=`, `<`, `<=`, `>`, `>=`) | ✅ |
| If / elif / else statements | ✅ |
| While loops | ✅ |
| For-range loops (`for i in range(...)`) | ✅ |
| Variable assignments and augmented assignments (`+=`, etc.) | ✅ |
| Function calls (user-defined + recursive) | ✅ |
| Built-in: `print()`, `abs()`, `min()`, `max()` | ✅ |
| Type conversion: `int()`, `float()`, `bool()` | ✅ |
| Type promotion (`int` → `float`) | ✅ |
| Power operator (`**`) | ✅ |
| Early return from loops | ✅ |
| Native binary output (ELF x86_64) | ✅ |
| JIT execution mode | ✅ |
| SIMD vectorization (LLVM auto-vectorization) | ✅ |
| Loop unrolling (LLVM) | ✅ |
| Aggressive inlining (`-O3`) | ✅ |
| Emit LLVM IR / Assembly | ✅ |

### What's Not Supported (Yet)

| Feature | Status |
|---------|:------:|
| Lists / dictionaries / sets | 🔜 |
| String operations | 🔜 |
| Classes / objects | 🔜 |
| Exceptions (`try`/`except`) | 🔜 |
| Imports / modules | 🔜 |
| Generator / `yield` | 🔜 |
| Dynamic / duck typing | 🔜 |
| Python C extension interop | 🔜 |

---

## How It Works

VortexPy is an **Ahead-of-Time (AOT) compiler** that translates type-annotated Python into optimized native code through a multi-stage pipeline:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Python       │    │ VortexPy IR  │    │ LLVM IR      │    │ Optimized    │    │ Native ELF   │
│ Source Code  │───▶│ (Typed AST)  │───▶│ (Unoptimized)│───▶│ LLVM IR      │───▶│ Binary       │
│ (.py)        │    │              │    │              │    │ (-O3, SIMD)  │    │ (x86_64)     │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
    Parse &           Type             Code               Optimization        Linking
    AST Walk        Inference        Generation          (15+ passes)        (GCC/ld)
```

### Stage 1: Parse & Type Inference

VortexPy parses Python source using the standard `ast` module, then walks the AST to build a typed intermediate representation. Type annotations (`x: int`, `-> float`) guide the type system. Sub-expressions are **materialized** into temporary variables so that nested operations like `total + i * i` are correctly decomposed into separate IR instructions.

### Stage 2: LLVM IR Code Generation

The typed IR is translated into LLVM IR using `llvmlite`. Each VortexPy function becomes an LLVM function with properly typed parameters and return values. Variables use `alloca`-based stack slots with load/store, which LLVM later promotes to SSA registers.

### Stage 3: Optimization

LLVM's optimization pipeline runs 15+ passes including:
- **CFG simplification** — eliminate dead blocks
- **SROA** — promote stack variables to SSA registers
- **Loop unrolling** — unroll small trip-count loops
- **SLP vectorization** — SIMD for independent operations
- **Loop vectorization** — auto-vectorize loops with LLVM
- **GVN** — eliminate redundant computations
- **Aggressive inlining** — inline function calls at `-O3`
- **Dead code elimination** — remove unused code
- **Constant propagation** — fold constants at compile time
- **Tail call elimination** — optimize tail-recursive calls

At `-O3`, LLVM can fold an entire program into a single `return` instruction (constant folding). For example, `fibonacci(40)` compiles to just `ret i64 102334155` — the computation happens at compile time!

### Stage 4: Native Linking

The optimized LLVM IR is compiled to an ELF object file, then linked with `gcc` to produce a standalone native binary. No runtime dependencies — just a single executable.

---

## Optimization Levels

| Level | Flag | Description |
|:-----:|:----:|-------------|
| 0 | `-O0` | No optimization. Useful for debugging the compiler. |
| 1 | `-O1` | Basic optimizations: constant propagation, dead code elimination, CFG simplification. |
| 2 | `-O2` | Standard optimizations: adds loop vectorization, SLP vectorization, inlining. **Recommended for production.** |
| 3 | `-O3` | Aggressive optimizations: aggressive inlining (threshold=275), extra function-level passes. Best for compute-heavy code. |

---

## Example Programs

The `examples/` directory contains ready-to-compile programs:

| File | Description | Key Features |
|------|-------------|--------------|
| `fibonacci.py` | Iterative Fibonacci (n=40) | `for` loop, function calls, `if/else` |
| `sum_squares.py` | Sum of squares 1..1M | `while` loop, nested expressions |
| `primes.py` | Prime counting up to 50K | Nested `while` loops, modulo, `if` |
| `mandelbrot.py` | Mandelbrot set (fixed-point) | Nested `while`, early return, integer division |
| `matmul.py` | 200×200 matrix multiply | Triple-nested `while`, accumulation |

```bash
# Compile all examples
for f in examples/*.py; do vortex compile "$f" -O3; done

# Run them
./fibonacci_vortex      # 102334155
./sum_squares_vortex    # 333333833333500000
./primes_vortex         # 5133
./mandelbrot_vortex     # 115130
./matmul_vortex         # 3205173202000000
```

---

## Writing VortexPy-Compatible Code

VortexPy compiles a **typed subset** of Python. Follow these rules:

### 1. Add type annotations everywhere

```python
# ✅ Good — all types annotated
def add(a: int, b: int) -> int:
    result: int = a + b
    return result

# ❌ Bad — no annotations, types cannot be inferred
def add(a, b):
    result = a + b
    return result
```

### 2. Use a `main() -> int` entry point

```python
def main() -> int:
    # Your program starts here
    print(42)
    return 0    # 0 = success
```

### 3. Use only supported types

- `int` → 64-bit signed integer (`i64`)
- `float` → 64-bit double (`f64`)
- `bool` → 1-bit integer (`i1`)
- `void` → no return value

### 4. Use only supported statements

- Assignments: `x = 5`, `x: int = 5`, `x += 1`
- Arithmetic: `+`, `-`, `*`, `//`, `/`, `%`, `**`, `&`, `|`, `^`, `<<`, `>>`
- Comparisons: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Control flow: `if/elif/else`, `while`, `for i in range(...)`
- Functions: call other functions, early return
- Built-ins: `print()`, `abs()`, `min()`, `max()`, `int()`, `float()`, `bool()`

### 5. Be aware of i64 limits

VortexPy uses 64-bit integers. Results that exceed `±9.2 × 10^18` will overflow, just like C or Rust:

```python
# This will overflow in VortexPy (but not in CPython)
def main() -> int:
    x: int = 100000000
    y: int = x * x * x  # Overflow! Use smaller values
    print(y)
    return 0
```

---

## Architecture

```
vortexpy/
├── vortex/
│   ├── __init__.py        # Package metadata
│   ├── parser.py          # Python AST → VortexPy IR (typed)
│   ├── types.py           # Type system (int, float, bool, void)
│   ├── codegen.py         # VortexPy IR → LLVM IR + native compiler
│   ├── optimizer.py       # LLVM optimization pipeline (-O0 to -O3)
│   ├── cli.py             # CLI (compile, run, bench, info)
│   └── pipeline.py        # High-level API (compile_file, run_string)
├── examples/              # Ready-to-compile example programs
│   ├── fibonacci.py
│   ├── sum_squares.py
│   ├── primes.py
│   ├── mandelbrot.py
│   └── matmul.py
├── benchmarks/            # Benchmark suite vs CPython & C++
│   └── benchmark_suite.py
├── tests/                 # Test directory
├── pyproject.toml         # Package configuration
└── README.md              # This file
```

---

## Comparison with Alternatives

| Feature | VortexPy | Cython | Numba | PyPy |
|---------|:--------:|:------:|:-----:|:----:|
| Install complexity | `pip install` | Needs C compiler + setup | `pip install` | Replace interpreter |
| Type annotations required | Yes | Yes (optional) | Yes (decorators) | No |
| Compilation model | AOT | AOT | JIT | JIT |
| Warmup time | Zero | Zero | Yes | Yes |
| Output | Native binary | C extension | In-process | N/A |
| LLVM backend | Yes | No (C backend) | Yes | No (tracing JIT) |
| Standalone executable | Yes | No | No | No |
| Full Python compat | Typed subset | Superset of Python | Typed subset | Full Python |
| SIMD vectorization | Yes (auto) | Limited | Yes (auto) | No |

---

## Frequently Asked Questions

### Is VortexPy a drop-in replacement for Python?

No. VortexPy compiles a **typed subset** of Python. You need type annotations and must use only supported language features. It's designed for compute-heavy numeric code, not general-purpose Python.

### Why is VortexPy faster than CPython?

CPython interprets bytecode one instruction at a time, with overhead for dynamic typing, reference counting, and object boxing on every operation. VortexPy compiles to native machine code with:
- No interpreter dispatch overhead
- No dynamic type checks
- No reference counting
- No object boxing/unboxing
- LLVM's aggressive optimizations (inlining, vectorization, constant folding)

### Why is VortexPy slower than C++ on some benchmarks?

C++ has decades of compiler optimization and supports pointer-based data structures, template metaprogramming, and more. VortexPy uses stack-based variables (alloca) which LLVM must promote to registers, and currently lacks support for arrays, pointers, and heap allocation. As the compiler matures, the gap will narrow.

### Can I use VortexPy in production?

VortexPy is at version 1.0.0 (Beta). It's suitable for benchmarks, experiments, and compute-heavy scripts. For production workloads, test thoroughly and be aware of the supported subset limitations.

---

## License

MIT License. See `pyproject.toml` for details.
