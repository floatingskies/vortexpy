"""
Optimization pipeline for VortexPy.

Applies LLVM optimization passes to the generated IR:
  - Aggressive inlining
  - Loop vectorization
  - SLP vectorization
  - Dead code elimination
  - Constant propagation
  - Common subexpression elimination
  - Memory-to-register promotion
"""

from __future__ import annotations

from llvmlite import binding


class OptimizationLevel:
    """Optimization level configuration."""
    NONE = 0
    BASIC = 1
    STANDARD = 2
    AGGRESSIVE = 3


_OPT_NAMES = {
    0: "None (-O0)",
    1: "Basic (-O1)",
    2: "Standard (-O2)",
    3: "Aggressive (-O3)",
}


def optimize_ir(llvm_ir: str, level: int = 3) -> str:
    """
    Optimize LLVM IR with the specified optimization level.

    At level 3 (Aggressive), applies:
      - Function inlining with high threshold
      - Loop vectorization for SIMD
      - SLP (Superword-Level Parallelism) vectorization
      - Interprocedural constant propagation
      - Dead argument elimination
      - Aggressive DCE
      - Memory-to-register promotion (SSA)
      - Loop unrolling
      - CFG simplification

    Args:
        llvm_ir: The LLVM IR string to optimize.
        level: Optimization level (0-3).

    Returns:
        Optimized LLVM IR string.
    """
    mod = binding.parse_assembly(llvm_ir)
    mod.verify()

    if level == 0:
        return llvm_ir

    # Build pass manager
    pmb = binding.PassManagerBuilder()
    pmb.opt_level = level
    pmb.size_level = 0  # Optimize for speed, not size

    if level >= 2:
        pmb.loop_vectorize = True
        pmb.slp_vectorize = True

    if level >= 3:
        # Aggressive inlining threshold
        pmb.inlining_threshold = 275

    # Module-level passes
    mpm = binding.ModulePassManager()
    pmb.populate(mpm)

    # Additional aggressive passes at -O3
    if level >= 3:
        # Run function-level passes
        for func in mod.functions:
            fpm = binding.FunctionPassManager(mod)

            # Standard optimization passes (using llvmlite's named API)
            fpm.add_cfg_simplification_pass()
            fpm.add_reassociate_expressions_pass()
            fpm.add_loop_unroll_pass()
            fpm.add_gvn_pass()
            fpm.add_aggressive_dead_code_elimination_pass()
            fpm.add_instruction_combining_pass()
            fpm.add_licm_pass()
            fpm.add_sroa_pass()
            fpm.add_tail_call_elimination_pass()
            fpm.add_dead_store_elimination_pass()
            fpm.add_constant_merge_pass()

            fpm.initialize()
            fpm.run(func)
            fpm.finalize()

    mpm.run(mod)

    return str(mod)


def get_optimization_stats(original_ir: str, optimized_ir: str) -> dict:
    """Compute basic statistics comparing original and optimized IR."""
    def count_instrs(ir_text):
        lines = ir_text.strip().split('\n')
        instr_count = 0
        func_count = 0
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('define '):
                func_count += 1
            elif stripped and not stripped.startswith(';') and not stripped.startswith('}') and not stripped.startswith('{') and not stripped.startswith('source_filename') and not stripped.startswith('target') and not stripped.startswith('declare') and not stripped.startswith('attributes') and not stripped.startswith('!'):
                if '=' in stripped or stripped.startswith('ret') or stripped.startswith('br') or stripped.startswith('call') or stripped.startswith('store') or stripped.startswith('load'):
                    instr_count += 1
        return {
            "instructions": instr_count,
            "functions": func_count,
            "lines": len(lines),
        }

    orig_stats = count_instrs(original_ir)
    opt_stats = count_instrs(optimized_ir)

    return {
        "original": orig_stats,
        "optimized": opt_stats,
        "instruction_reduction": orig_stats["instructions"] - opt_stats["instructions"],
        "line_reduction": orig_stats["lines"] - opt_stats["lines"],
    }
