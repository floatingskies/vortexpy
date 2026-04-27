"""
VortexPy CLI — Beautiful command-line interface.

Usage:
    vortex compile <file.py> [-o output] [-O level] [--emit-llvm] [--emit-asm]
    vortex run <file.py> [-O level]
    vortex bench <file.py>
    vortex info
"""

from __future__ import annotations

import os
import sys
import time
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.syntax import Syntax
from rich.tree import Tree
from rich.markdown import Markdown
from rich.text import Text
from rich.columns import Columns
from rich import box

from . import __version__
from .parser import VortexParser
from .codegen import CodeGenerator, NativeCompiler
from .optimizer import optimize_ir, get_optimization_stats, _OPT_NAMES

console = Console()

# ── VortexPy ASCII Art Logo ──────────────────────────────────────────────

LOGO = r"""
[bold cyan]
 ╦╔═╔═╗╦ ╦╔╗ ╔═╗╦═╗╔═╗╦ ╦╦╔═╔═╗
 ╠╩╗║ ║║║║╠╩╗╔═╝╠╦╝║  ╠═╣╠╩╗╚═╗
 ╩ ╩╚═╝╚╩╝╩ ╩╚═╝╩╚═╚═╝╩ ╩╩ ╩╚═╝
[/bold cyan]
[dim]High-Performance Python AOT Compiler — Powered by LLVM[/dim]
"""


def _print_banner():
    """Print the VortexPy banner."""
    console.print(LOGO)
    console.print(f"[bold]Version {__version__}[/bold] | [cyan]LLVM Backend[/cyan] | [green]Linux Native[/green]")
    console.print()


def _get_file_info(filepath: str) -> dict:
    """Get information about a Python source file."""
    path = Path(filepath)
    with open(filepath, "r") as f:
        source = f.read()
    lines = source.count('\n') + 1
    import ast
    tree = ast.parse(source)
    func_count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
    return {
        "path": str(path),
        "name": path.name,
        "size": path.stat().st_size,
        "lines": lines,
        "functions": func_count,
        "source": source,
    }


def _compile_source(source: str, filename: str, opt_level: int = 3, emit_llvm: bool = False,
                     emit_asm: bool = False, output_path: Optional[str] = None,
                     show_ir: bool = False) -> dict:
    """
    Core compilation pipeline.

    Returns a dict with compilation results and statistics.
    """
    start_total = time.perf_counter()

    # Stage 1: Parse
    stage1_start = time.perf_counter()
    parser = VortexParser()
    ir_module = parser.parse(source, filename=filename)
    stage1_time = time.perf_counter() - stage1_start

    if parser.errors:
        for err in parser.errors:
            console.print(f"[red]Parse error:[/red] {err}")
        raise click.Abort()

    # Stage 2: Generate LLVM IR
    stage2_start = time.perf_counter()
    codegen = CodeGenerator(module_name=filename.replace('.py', '_module'))
    llvm_ir = codegen.generate(ir_module)
    stage2_time = time.perf_counter() - stage2_start

    # Stage 3: Optimize
    stage3_start = time.perf_counter()
    optimized_ir = optimize_ir(llvm_ir, level=opt_level)
    stage3_time = time.perf_counter() - stage3_start

    # Optimization stats
    opt_stats = get_optimization_stats(llvm_ir, optimized_ir)

    total_time = time.perf_counter() - start_total

    result = {
        "ir_module": ir_module,
        "llvm_ir": llvm_ir,
        "optimized_ir": optimized_ir,
        "opt_stats": opt_stats,
        "timings": {
            "parse": stage1_time,
            "codegen": stage2_time,
            "optimize": stage3_time,
            "total": total_time,
        },
        "functions": len(ir_module.functions),
        "opt_level": opt_level,
    }

    # Stage 4: Output
    if emit_llvm:
        # Just emit LLVM IR to file or stdout
        if output_path:
            with open(output_path, "w") as f:
                f.write(optimized_ir)
            result["output"] = output_path
        else:
            result["emit_llvm"] = True

    elif emit_asm:
        # Emit assembly
        native = NativeCompiler()
        mod = __import__('llvmlite').binding.parse_assembly(optimized_ir)
        mod.verify()
        target = __import__('llvmlite').binding.Target.from_default_triple()
        tm = target.create_target_machine(
            cpu=__import__('llvmlite').binding.get_host_cpu_name(),
            features=__import__('llvmlite').binding.get_host_cpu_features().flatten(),
            opt=opt_level,
        )
        asm = tm.emit_assembly(mod)
        if output_path:
            with open(output_path, "w") as f:
                f.write(asm)
            result["output"] = output_path
        else:
            result["emit_asm"] = True
            result["asm"] = asm

    elif output_path:
        # Compile to native executable
        stage4_start = time.perf_counter()
        native = NativeCompiler()
        native.compile_to_executable(optimized_ir, output_path, opt_level=opt_level)
        stage4_time = time.perf_counter() - stage4_start
        result["timings"]["link"] = stage4_time
        result["timings"]["total"] = time.perf_counter() - start_total
        result["output"] = output_path
        # Get binary size
        result["binary_size"] = os.path.getsize(output_path)
    else:
        # Default: compile to executable with auto name
        base_name = Path(filename).stem
        auto_output = f"./{base_name}_vortex"
        stage4_start = time.perf_counter()
        native = NativeCompiler()
        native.compile_to_executable(optimized_ir, auto_output, opt_level=opt_level)
        stage4_time = time.perf_counter() - stage4_start
        result["timings"]["link"] = stage4_time
        result["timings"]["total"] = time.perf_counter() - start_total
        result["output"] = auto_output
        result["binary_size"] = os.path.getsize(auto_output)

    return result


def _print_compile_report(result: dict, file_info: dict):
    """Print a beautiful compilation report."""
    console.print()

    # Header
    console.print(Panel(
        f"[bold cyan]{file_info['name']}[/bold cyan] → [bold green]{result.get('output', 'native binary')}[/bold green]",
        title="[bold]VortexPy Compilation Report[/bold]",
        border_style="cyan",
    ))

    # Timing table
    table = Table(title="⏱  Compilation Pipeline", box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Stage", style="white")
    table.add_column("Time", style="green", justify="right")
    table.add_column("Percentage", style="yellow", justify="right")

    total = result["timings"]["total"]
    for stage, time_val in result["timings"].items():
        if stage == "total":
            continue
        pct = (time_val / total * 100) if total > 0 else 0
        table.add_row(
            stage.capitalize(),
            f"{time_val*1000:.2f} ms",
            f"{pct:.1f}%",
        )
    table.add_row("[bold]Total[/bold]", f"[bold green]{total*1000:.2f} ms[/bold green]", "[bold]100%[/bold]")
    console.print(table)

    # Optimization stats
    if result["opt_stats"]:
        opt_table = Table(title="🔧 Optimization Results", box=box.ROUNDED, show_header=True, header_style="bold cyan")
        opt_table.add_column("Metric", style="white")
        opt_table.add_column("Before", style="red", justify="right")
        opt_table.add_column("After", style="green", justify="right")
        opt_table.add_column("Δ", style="yellow", justify="right")

        stats = result["opt_stats"]
        opt_table.add_row(
            "Instructions",
            str(stats["original"]["instructions"]),
            str(stats["optimized"]["instructions"]),
            f"[green]-{stats['instruction_reduction']}[/green]" if stats['instruction_reduction'] > 0 else f"[red]+{abs(stats['instruction_reduction'])}[/red]",
        )
        opt_table.add_row(
            "Lines",
            str(stats["original"]["lines"]),
            str(stats["optimized"]["lines"]),
            f"[green]-{stats['line_reduction']}[/green]" if stats['line_reduction'] > 0 else f"[red]+{abs(stats['line_reduction'])}[/red]",
        )

        console.print(opt_table)

    # Function tree
    if result["ir_module"].functions:
        tree = Tree("📋 [bold]Functions[/bold]")
        for func in result["ir_module"].functions:
            args_str = ", ".join(
                f"[cyan]{a.name}[/cyan]: [yellow]{a.vtype.name.lower()}[/yellow]"
                for a in func.args
            )
            ret_str = f"[green]{func.return_type.name.lower()}[/green]"
            entry_badge = " [dim][main][/dim]" if func.is_entry else ""
            tree.add(f"[bold]{func.name}[/bold]({args_str}) → {ret_str}{entry_badge}")
        console.print(tree)

    # Binary info
    if "binary_size" in result:
        size = result["binary_size"]
        if size > 1024 * 1024:
            size_str = f"{size / 1024 / 1024:.1f} MB"
        elif size > 1024:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size} B"
        console.print(f"\n📦 Binary size: [bold green]{size_str}[/bold green]")

    console.print(f"🚀 Optimization: [bold]{_OPT_NAMES.get(result['opt_level'], 'Unknown')}[/bold]")
    console.print()


# ── CLI Commands ──────────────────────────────────────────────────────────

@click.group()
@click.version_option(version=__version__, prog_name="vortex", message="%(prog)s %(version)s")
def cli():
    """VortexPy — A high-performance Python AOT compiler."""
    pass


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("-o", "--output", "output", default=None, help="Output file path")
@click.option("-O", "--opt-level", "opt_level", default=3, type=click.IntRange(0, 3),
              help="Optimization level (0-3, default: 3)")
@click.option("--emit-llvm", is_flag=True, help="Emit LLVM IR instead of native binary")
@click.option("--emit-asm", is_flag=True, help="Emit assembly instead of native binary")
@click.option("--show-ir", is_flag=True, help="Show the generated LLVM IR")
@click.option("-q", "--quiet", is_flag=True, help="Quiet mode — only show errors")
def compile(file, output, opt_level, emit_llvm, emit_asm, show_ir, quiet):
    """Compile a Python file to a native binary."""
    if not quiet:
        _print_banner()

    file_info = _get_file_info(file)

    if not quiet:
        console.print(f"[bold]Compiling:[/bold] [cyan]{file_info['name']}[/cyan] ({file_info['lines']} lines, {file_info['functions']} functions)")
        console.print(f"[bold]Optimization:[/bold] {_OPT_NAMES.get(opt_level, 'Unknown')}")
        console.print()

    with console.status("[bold green]Compiling...[/bold green]", spinner="dots"):
        try:
            result = _compile_source(
                file_info["source"], file, opt_level=opt_level,
                emit_llvm=emit_llvm, emit_asm=emit_asm,
                output_path=output, show_ir=show_ir,
            )
        except Exception as e:
            console.print(f"[bold red]Compilation failed:[/bold red] {e}")
            sys.exit(1)

    if not quiet:
        _print_compile_report(result, file_info)

    if show_ir and not quiet:
        console.print(Panel(
            Syntax(result["optimized_ir"], "llvm", theme="monokai", line_numbers=True),
            title="Optimized LLVM IR",
            border_style="cyan",
        ))

    if emit_llvm and not output:
        console.print(result["optimized_ir"])

    if emit_asm and not output:
        console.print(Panel(
            Syntax(result.get("asm", ""), "asm", theme="monokai", line_numbers=True),
            title="Generated Assembly",
            border_style="cyan",
        ))

    if not quiet and result.get("output"):
        console.print(f"[bold green]✓ Output:[/bold green] {result['output']}")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("-O", "--opt-level", "opt_level", default=3, type=click.IntRange(0, 3),
              help="Optimization level (0-3, default: 3)")
@click.option("--show-ir", is_flag=True, help="Show generated LLVM IR before execution")
def run(file, opt_level, show_ir):
    """Compile and run a Python file immediately (JIT mode)."""
    _print_banner()

    file_info = _get_file_info(file)
    console.print(f"[bold]Running:[/bold] [cyan]{file_info['name']}[/cyan] ({file_info['lines']} lines)")
    console.print(f"[bold]Optimization:[/bold] {_OPT_NAMES.get(opt_level, 'Unknown')}")
    console.print()

    # Parse
    with console.status("[bold cyan]Parsing...[/bold cyan]", spinner="dots"):
        parser = VortexParser()
        ir_module = parser.parse(file_info["source"], filename=file)

    # Generate IR
    with console.status("[bold cyan]Generating LLVM IR...[/bold cyan]", spinner="dots"):
        codegen = CodeGenerator(module_name=file.replace('.py', '_module'))
        llvm_ir = codegen.generate(ir_module)

    # Optimize
    with console.status("[bold cyan]Optimizing...[/bold cyan]", spinner="dots"):
        optimized_ir = optimize_ir(llvm_ir, level=opt_level)

    if show_ir:
        console.print(Panel(
            Syntax(optimized_ir, "llvm", theme="monokai", line_numbers=True),
            title="Optimized LLVM IR",
            border_style="cyan",
        ))

    # JIT compile and run
    console.print("[bold green]▶ Executing...[/bold green]\n")
    console.rule()

    try:
        native = NativeCompiler()
        result = native.compile_and_execute(optimized_ir, opt_level=opt_level)
        exit_code = result if isinstance(result, int) else 0
    except Exception as e:
        console.print(f"\n[bold red]Runtime error:[/bold red] {e}")
        exit_code = 1

    console.rule()
    console.print(f"\n[dim]Process exited with code {exit_code}[/dim]")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("-O", "--opt-level", "opt_level", default=3, type=click.IntRange(0, 3),
              help="Optimization level (0-3, default: 3)")
@click.option("-n", "--iterations", "iterations", default=5, type=int,
              help="Number of benchmark iterations")
def bench(file, opt_level, iterations):
    """Benchmark VortexPy-compiled code vs CPython."""
    _print_banner()

    file_info = _get_file_info(file)
    console.print(f"[bold]Benchmarking:[/bold] [cyan]{file_info['name']}[/cyan]")
    console.print(f"[bold]Iterations:[/bold] {iterations}")
    console.print()

    # Benchmark CPython
    console.print("[bold yellow]📊 Running CPython benchmark...[/bold yellow]")
    cpython_times = []
    for i in range(iterations):
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, file],
            capture_output=True, text=True, timeout=60,
        )
        elapsed = time.perf_counter() - start
        cpython_times.append(elapsed)
        console.print(f"  Run {i+1}: {elapsed*1000:.2f} ms")

    cpython_avg = sum(cpython_times) / len(cpython_times)
    cpython_min = min(cpython_times)

    # Compile with VortexPy
    console.print("\n[bold cyan]⚙ Compiling with VortexPy...[/bold cyan]")
    with console.status("[bold cyan]Compiling...[/bold cyan]", spinner="dots"):
        try:
            result = _compile_source(
                file_info["source"], file, opt_level=opt_level,
            )
        except Exception as e:
            console.print(f"[bold red]Compilation failed:[/bold red] {e}")
            sys.exit(1)

    binary_path = result.get("output", "")
    if not binary_path or not os.path.exists(binary_path):
        console.print("[bold red]Binary not found![/bold red]")
        sys.exit(1)

    # Make executable
    os.chmod(binary_path, 0o755)

    # Benchmark VortexPy
    console.print("[bold green]🚀 Running VortexPy benchmark...[/bold green]")
    vortex_times = []
    for i in range(iterations):
        start = time.perf_counter()
        proc = subprocess.run(
            [binary_path],
            capture_output=True, text=True, timeout=60,
        )
        elapsed = time.perf_counter() - start
        vortex_times.append(elapsed)
        console.print(f"  Run {i+1}: {elapsed*1000:.2f} ms")

    vortex_avg = sum(vortex_times) / len(vortex_times)
    vortex_min = min(vortex_times)

    # Also benchmark with GCC C++ equivalent if available
    gcc_time = None
    cpp_file = file.replace('.py', '_bench.cpp')
    # We'll skip C++ benchmark for now - user can add manually

    # Results
    console.print()
    speedup_avg = cpython_avg / vortex_avg if vortex_avg > 0 else float('inf')
    speedup_min = cpython_min / vortex_min if vortex_min > 0 else float('inf')

    bench_table = Table(title="🏆 Benchmark Results", box=box.ROUNDED, show_header=True, header_style="bold cyan")
    bench_table.add_column("Metric", style="white")
    bench_table.add_column("CPython", style="yellow", justify="right")
    bench_table.add_column("VortexPy", style="green", justify="right")
    bench_table.add_column("Speedup", style="bold magenta", justify="right")

    bench_table.add_row(
        "Average Time",
        f"{cpython_avg*1000:.2f} ms",
        f"{vortex_avg*1000:.2f} ms",
        f"[bold green]{speedup_avg:.1f}x[/bold green]",
    )
    bench_table.add_row(
        "Best Time",
        f"{cpython_min*1000:.2f} ms",
        f"{vortex_min*1000:.2f} ms",
        f"[bold green]{speedup_min:.1f}x[/bold green]",
    )

    console.print(bench_table)

    if speedup_avg >= 10:
        console.print("\n[bold green]🔥 BLAZING FAST! VortexPy is {}x faster than CPython![/bold green]".format(int(speedup_avg)))
    elif speedup_avg >= 5:
        console.print(f"\n[bold green]⚡ Excellent! VortexPy is {speedup_avg:.1f}x faster than CPython![/bold green]")
    elif speedup_avg >= 2:
        console.print(f"\n[bold green]✓ VortexPy is {speedup_avg:.1f}x faster than CPython![/bold green]")
    else:
        console.print(f"\n[yellow]VortexPy is {speedup_avg:.1f}x faster than CPython.[/yellow]")


@cli.command()
def info():
    """Show system and compiler information."""
    _print_banner()

    from llvmlite import binding
    binding.initialize()
    binding.initialize_native_target()
    binding.initialize_native_asmprinter()

    info_table = Table(title="System Information", box=box.ROUNDED, show_header=True, header_style="bold cyan")
    info_table.add_column("Property", style="white")
    info_table.add_column("Value", style="green")

    info_table.add_row("VortexPy Version", __version__)
    info_table.add_row("Python Version", sys.version.split()[0])
    info_table.add_row("LLVM Version", f"{binding.llvm_version_info[0]}.{binding.llvm_version_info[1]}.{binding.llvm_version_info[2]}")
    info_table.add_row("Target Triple", binding.get_default_triple())
    info_table.add_row("Host CPU", binding.get_host_cpu_name())

    # CPU features
    features = binding.get_host_cpu_features().flatten()
    notable = []
    for feat in ["+avx", "+avx2", "+avx512", "+sse4", "+fma", "+neon", "+simd"]:
        if feat in features:
            notable.append(feat)
    info_table.add_row("SIMD Features", ", ".join(notable) if notable else "Basic")

    info_table.add_row("Platform", sys.platform)
    info_table.add_row("GCC", subprocess.getoutput("gcc --version | head -1").strip())

    console.print(info_table)

    # Supported features
    feat_table = Table(title="Supported Language Features", box=box.ROUNDED, show_header=True, header_style="bold cyan")
    feat_table.add_column("Feature", style="white")
    feat_table.add_column("Status", style="green")

    features_list = [
        ("Type-annotated functions", "✓"),
        ("Integer arithmetic (i64)", "✓"),
        ("Float arithmetic (f64)", "✓"),
        ("Boolean operations", "✓"),
        ("If/elif/else", "✓"),
        ("While loops", "✓"),
        ("For-range loops", "✓"),
        ("Function calls", "✓"),
        ("Augmented assignment (+=, etc.)", "✓"),
        ("Built-in: print, abs, min, max", "✓"),
        ("Type promotion (int→float)", "✓"),
        ("Power operator (**)", "✓"),
        ("Bitwise operations", "✓"),
        ("Comparison operators", "✓"),
        ("Native binary output", "✓"),
        ("JIT execution mode", "✓"),
        ("SIMD vectorization (LLVM)", "✓"),
        ("Loop unrolling (LLVM)", "✓"),
        ("Aggressive inlining (O3)", "✓"),
    ]

    for feat, status in features_list:
        feat_table.add_row(feat, f"[green]{status}[/green]")

    console.print(feat_table)


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
