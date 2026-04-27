"""
LLVM IR code generator for VortexPy.

Transforms the VortexPy IR into optimized LLVM IR using llvmlite.
Supports:
  - All arithmetic operations with proper type handling
  - Control flow (if/else, while, for-range loops)
  - Function definitions and calls
  - Built-in functions (print, abs, min, max)
  - Type promotions (int -> float)
  - Entry point (main function)
"""

from __future__ import annotations

import sys
from ctypes import CFUNCTYPE, c_int, c_double, c_bool

from llvmlite import ir, binding

from .types import VortexType, type_name
from .parser import (
    IRModule, IRFunction, IRBinOp, IRUnaryOp, IRCompare, IRAssign,
    IRReturn, IRCall, IRIfElse, IRWhileLoop, IRForLoop, IRAugAssign,
    IRVariable,
)

# ── LLVM type mappings ───────────────────────────────────────────────────

def _llvm_type(vtype: VortexType) -> ir.Type:
    """Map VortexType to LLVM IR type."""
    mapping = {
        VortexType.INT: ir.IntType(64),
        VortexType.FLOAT: ir.DoubleType(),
        VortexType.BOOL: ir.IntType(1),
        VortexType.VOID: ir.VoidType(),
    }
    return mapping.get(vtype, ir.IntType(64))


def _c_type(vtype: VortexType):
    """Map VortexType to ctypes return type."""
    mapping = {
        VortexType.INT: c_int,
        VortexType.FLOAT: c_double,
        VortexType.BOOL: c_bool,
        VortexType.VOID: None,
    }
    return mapping.get(vtype, c_int)


# ── Standard library (printf for print) ──────────────────────────────────

_PRINTF_TYPE = ir.FunctionType(
    ir.IntType(32), [ir.IntType(8).as_pointer()], var_arg=True
)

_ABS_INT_TYPE = ir.FunctionType(ir.IntType(64), [ir.IntType(64)])
_ABS_FLOAT_TYPE = ir.FunctionType(ir.DoubleType(), [ir.DoubleType()])


class CodeGenerator:
    """
    Generates LLVM IR from VortexPy IR modules.

    The code generator maintains a variable environment mapping
    variable names to their LLVM SSA values, and handles:
      - Type conversions (int <-> float, bool <-> int)
      - Control flow with proper basic block structure
      - Built-in function calls
      - Entry point generation
    """

    def __init__(self, module_name: str = "vortex_module"):
        # Initialize LLVM
        binding.initialize()
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()

        self.module = ir.Module(name=module_name)
        self.module.triple = binding.get_default_triple()

        self.builder: ir.IRBuilder | None = None
        self.func: ir.Function | None = None
        self._vars: dict[str, ir.AllocaInstr] = {}
        self._funcs: dict[str, ir.Function] = {}
        self._fmt_added = False
        self._printf_added = False

    def _ensure_printf(self):
        """Add printf declaration if not already added."""
        if not self._printf_added:
            printf = ir.Function(self.module, _PRINTF_TYPE, name="printf")
            self._funcs["printf"] = printf
            self._printf_added = True

    def _ensure_fmt_strings(self):
        """Add format string globals if not already added."""
        if not self._fmt_added:
            self._fmt_added = True

    def _get_constant(self, value_str: str, vtype: VortexType) -> ir.Constant:
        """Parse a value string and return an LLVM constant."""
        if vtype == VortexType.INT:
            try:
                return ir.Constant(ir.IntType(64), int(value_str))
            except (ValueError, TypeError):
                return ir.Constant(ir.IntType(64), 0)
        elif vtype == VortexType.FLOAT:
            try:
                return ir.Constant(ir.DoubleType(), float(value_str))
            except (ValueError, TypeError):
                return ir.Constant(ir.DoubleType(), 0.0)
        elif vtype == VortexType.BOOL:
            if isinstance(value_str, str):
                return ir.Constant(ir.IntType(1), value_str.lower() in ("true", "1"))
            return ir.Constant(ir.IntType(1), bool(value_str))
        return ir.Constant(ir.IntType(64), 0)

    def _parse_value(self, name: str, vtype: VortexType) -> ir.Value:
        """Get the LLVM value for a variable name or literal."""
        # Check if it's a literal
        if name.startswith("'") or name.startswith('"'):
            # String literal - not fully supported, return 0
            return ir.Constant(ir.IntType(64), 0)

        # Check boolean literals
        if name == "True":
            return ir.Constant(ir.IntType(1), 1)
        if name == "False":
            return ir.Constant(ir.IntType(1), 0)

        # Try numeric literal
        try:
            if vtype == VortexType.FLOAT or '.' in name:
                return ir.Constant(ir.DoubleType(), float(name))
            elif vtype == VortexType.BOOL:
                return ir.Constant(ir.IntType(1), int(name))
            else:
                return ir.Constant(ir.IntType(64), int(name))
        except (ValueError, TypeError):
            pass

        # Must be a variable
        if name in self._vars:
            alloca = self._vars[name]
            llvm_type = _llvm_type(vtype)
            return self.builder.load(alloca, name=name)

        # Unknown - return 0
        return ir.Constant(ir.IntType(64), 0)

    def _create_entry_alloca(self, name: str, vtype: VortexType) -> ir.AllocaInstr:
        """Create an alloca at the function entry point."""
        llvm_type = _llvm_type(vtype)
        with self.builder.goto_entry_block():
            alloca = self.builder.alloca(llvm_type, name=name)
        return alloca

    def _store_var(self, name: str, value: ir.Value, vtype: VortexType):
        """Store a value into a variable's alloca."""
        if name not in self._vars:
            self._vars[name] = self._create_entry_alloca(name, vtype)
        self.builder.store(value, self._vars[name])

    def _load_var(self, name: str, vtype: VortexType) -> ir.Value:
        """Load a value from a variable's alloca."""
        if name in self._vars:
            return self.builder.load(self._vars[name], name=name)
        return ir.Constant(_llvm_type(vtype), 0)

    def _get_value(self, name: str, vtype: VortexType) -> ir.Value:
        """Get a value — either from variable or as a literal constant."""
        # Boolean literals
        if name == "True":
            return ir.Constant(ir.IntType(1), 1)
        if name == "False":
            return ir.Constant(ir.IntType(1), 0)

        # Variable lookup FIRST (before trying numeric parse)
        if name in self._vars:
            return self.builder.load(self._vars[name], name=name + "_load")

        # Try as numeric literal
        try:
            if vtype == VortexType.FLOAT or '.' in name:
                return ir.Constant(ir.DoubleType(), float(name))
            elif vtype == VortexType.BOOL:
                if name.isdigit():
                    return ir.Constant(ir.IntType(1), int(name))
                # Not a literal - return 0 as fallback (variable not found)
                return ir.Constant(ir.IntType(1), 0)
            else:
                return ir.Constant(ir.IntType(64), int(name))
        except (ValueError, TypeError):
            pass

        return ir.Constant(_llvm_type(vtype), 0)

    def _convert_type(self, value: ir.Value, from_type: VortexType, to_type: VortexType) -> ir.Value:
        """Convert a value from one type to another."""
        if from_type == to_type:
            return value

        # int -> float
        if from_type == VortexType.INT and to_type == VortexType.FLOAT:
            return self.builder.sitofp(value, ir.DoubleType(), name="int_to_float")

        # bool -> int
        if from_type == VortexType.BOOL and to_type == VortexType.INT:
            return self.builder.zext(value, ir.IntType(64), name="bool_to_int")

        # bool -> float
        if from_type == VortexType.BOOL and to_type == VortexType.FLOAT:
            int_val = self.builder.zext(value, ir.IntType(64), name="bool_to_int")
            return self.builder.sitofp(int_val, ir.DoubleType(), name="int_to_float")

        # float -> int
        if from_type == VortexType.FLOAT and to_type == VortexType.INT:
            return self.builder.fptosi(value, ir.IntType(64), name="float_to_int")

        # int -> bool
        if from_type == VortexType.INT and to_type == VortexType.BOOL:
            return self.builder.icmp_signed("!=", value, ir.Constant(ir.IntType(64), 0), name="int_to_bool")

        return value

    # ── Statement code generation ────────────────────────────────────────

    def _gen_binop(self, inst: IRBinOp):
        """Generate LLVM IR for a binary operation."""
        left = self._get_value(inst.left, inst.left_type)
        right = self._get_value(inst.right, inst.right_type)

        # Promote types if needed
        if inst.left_type != inst.right_type:
            if inst.left_type == VortexType.INT and inst.right_type == VortexType.FLOAT:
                left = self._convert_type(left, VortexType.INT, VortexType.FLOAT)
            elif inst.left_type == VortexType.FLOAT and inst.right_type == VortexType.INT:
                right = self._convert_type(right, VortexType.INT, VortexType.FLOAT)

        is_float = inst.left_type == VortexType.FLOAT or inst.right_type == VortexType.FLOAT
        result_type = _llvm_type(inst.result_type if hasattr(inst, 'result_type') else VortexType.INT)

        if is_float:
            result_type = ir.DoubleType()

        op_map_int = {
            "+": self.builder.add,
            "-": self.builder.sub,
            "*": self.builder.mul,
            "//": self.builder.sdiv,
            "%": self.builder.srem,
            "&": self.builder.and_,
            "|": self.builder.or_,
            "^": self.builder.xor,
            "<<": self.builder.shl,
            ">>": self.builder.ashr,
        }
        op_map_float = {
            "+": self.builder.fadd,
            "-": self.builder.fsub,
            "*": self.builder.fmul,
            "/": self.builder.fdiv,
            "//": self.builder.fdiv,
            "%": self.builder.frem,
        }

        if inst.op == "**":
            # Power operation - use multiplication loop or call pow
            if is_float:
                result = self.builder.call(
                    self._get_pow_func(True), [left, right], name="pow_result"
                )
            else:
                # Convert to float, call pow, convert back
                left_f = self._convert_type(left, VortexType.INT, VortexType.FLOAT) if not is_float else left
                right_f = self._convert_type(right, VortexType.INT, VortexType.FLOAT) if not is_float else right
                result_f = self.builder.call(
                    self._get_pow_func(True), [left_f, right_f], name="pow_result"
                )
                result = self.builder.fptosi(result_f, ir.IntType(64), name="pow_int")
                self._store_var(inst.result, result, VortexType.INT)
                return
        elif is_float:
            op_func = op_map_float.get(inst.op, self.builder.fadd)
            result = op_func(left, right, name=inst.result)
        else:
            op_func = op_map_int.get(inst.op, self.builder.add)
            result = op_func(left, right, name=inst.result)

        result_vtype = VortexType.FLOAT if is_float else VortexType.INT
        self._store_var(inst.result, result, result_vtype)

    def _get_pow_func(self, is_float: bool) -> ir.Function:
        """Get or create the pow function declaration."""
        if "pow" not in self._funcs:
            pow_type = ir.FunctionType(ir.DoubleType(), [ir.DoubleType(), ir.DoubleType()])
            pow_func = ir.Function(self.module, pow_type, name="pow")
            self._funcs["pow"] = pow_func
        return self._funcs["pow"]

    def _gen_unaryop(self, inst: IRUnaryOp):
        """Generate LLVM IR for a unary operation."""
        operand = self._get_value(inst.operand, inst.operand_type)

        if inst.op == "-":
            if inst.operand_type == VortexType.FLOAT:
                result = self.builder.fneg(operand, name=inst.result)
            else:
                result = self.builder.neg(operand, name=inst.result)
        elif inst.op == "+":
            result = operand
        elif inst.op == "not":
            if inst.operand_type == VortexType.FLOAT:
                cmp = self.builder.fcmp_ordered("==", operand, ir.Constant(ir.DoubleType(), 0.0))
                result = self.builder.zext(cmp, ir.IntType(1), name=inst.result)
            else:
                result = self.builder.icmp_signed("==", operand, ir.Constant(ir.IntType(64), 0), name=inst.result)
        elif inst.op == "~":
            result = self.builder.xor(operand, ir.Constant(ir.IntType(64), -1), name=inst.result)
        else:
            result = operand

        self._store_var(inst.result, result, inst.operand_type)

    def _gen_compare(self, inst: IRCompare):
        """Generate LLVM IR for a comparison."""
        left = self._get_value(inst.left, inst.left_type)
        right = self._get_value(inst.right, inst.right_type)

        # Promote types
        if inst.left_type != inst.right_type:
            if inst.left_type == VortexType.INT and inst.right_type == VortexType.FLOAT:
                left = self._convert_type(left, VortexType.INT, VortexType.FLOAT)
            elif inst.left_type == VortexType.FLOAT and inst.right_type == VortexType.INT:
                right = self._convert_type(right, VortexType.INT, VortexType.FLOAT)

        is_float = inst.left_type == VortexType.FLOAT or inst.right_type == VortexType.FLOAT

        op_map_int = {
            "==": "==",
            "!=": "!=",
            "<": "<",
            "<=": "<=",
            ">": ">",
            ">=": ">=",
        }
        op_map_float = {
            "==": "oeq",
            "!=": "one",
            "<": "olt",
            "<=": "ole",
            ">": "ogt",
            ">=": "oge",
        }

        op = inst.ops[0] if inst.ops else "=="

        if is_float:
            cmp_op = op_map_float.get(op, "oeq")
            cmp = self.builder.fcmp_ordered(cmp_op, left, right, name="cmp")
        else:
            cmp_op = op_map_int.get(op, "==")
            cmp = self.builder.icmp_signed(cmp_op, left, right, name="cmp")

        # Extend to i64 for consistent storage
        result = self.builder.zext(cmp, ir.IntType(1), name=inst.result)
        self._store_var(inst.result, result, VortexType.BOOL)

    def _gen_assign(self, inst: IRAssign):
        """Generate LLVM IR for an assignment."""
        value = self._get_value(inst.value, inst.value_type)

        # Type conversion
        if inst.target_type != inst.value_type and inst.target_type != VortexType.UNKNOWN and inst.value_type != VortexType.UNKNOWN:
            value = self._convert_type(value, inst.value_type, inst.target_type)

        self._store_var(inst.target, value, inst.target_type)

    def _gen_augassign(self, inst: IRAugAssign):
        """Generate LLVM IR for an augmented assignment (e.g., x += 1)."""
        current = self._get_value(inst.target, inst.target_type)
        value = self._get_value(inst.value, inst.value_type)

        # Promote types
        if inst.target_type != inst.value_type:
            if inst.target_type == VortexType.INT and inst.value_type == VortexType.FLOAT:
                current = self._convert_type(current, VortexType.INT, VortexType.FLOAT)
            elif inst.target_type == VortexType.FLOAT and inst.value_type == VortexType.INT:
                value = self._convert_type(value, VortexType.INT, VortexType.FLOAT)

        is_float = inst.target_type == VortexType.FLOAT or inst.value_type == VortexType.FLOAT

        if is_float:
            op_map = {
                "+": self.builder.fadd,
                "-": self.builder.fsub,
                "*": self.builder.fmul,
                "/": self.builder.fdiv,
                "//": self.builder.fdiv,
                "%": self.builder.frem,
            }
        else:
            op_map = {
                "+": self.builder.add,
                "-": self.builder.sub,
                "*": self.builder.mul,
                "//": self.builder.sdiv,
                "%": self.builder.srem,
                "&": self.builder.and_,
                "|": self.builder.or_,
                "^": self.builder.xor,
                "<<": self.builder.shl,
                ">>": self.builder.ashr,
            }

        op_func = op_map.get(inst.op, self.builder.add)
        result = op_func(current, value, name=inst.target + "_aug")

        result_type = VortexType.FLOAT if is_float else inst.target_type
        self._store_var(inst.target, result, result_type)

    def _gen_return(self, inst: IRReturn):
        """Generate LLVM IR for a return statement."""
        if inst.value is not None and inst.return_type != VortexType.VOID:
            value = self._get_value(inst.value, inst.return_type)
            self.builder.ret(value)
        else:
            if inst.return_type == VortexType.INT:
                self.builder.ret(ir.Constant(ir.IntType(64), 0))
            else:
                self.builder.ret_void()

    def _gen_call(self, inst: IRCall):
        """Generate LLVM IR for a function call."""
        self._ensure_printf()

        if inst.func_name == "print":
            # Generate printf call
            if not inst.args:
                return

            arg_name = inst.args[0]
            # Determine type - check variable env or default to int
            arg_type = inst.arg_types[0] if inst.arg_types else VortexType.INT

            value = self._get_value(arg_name, arg_type)

            # Get or create format string global
            fmt_name = f".fmt_{type_name(arg_type)}"
            existing_globals = set()
            for g in self.module.globals:
                if isinstance(g, str):
                    existing_globals.add(g)
                elif hasattr(g, 'name'):
                    existing_globals.add(g.name)
            if fmt_name not in existing_globals:
                if arg_type == VortexType.FLOAT:
                    fmt_data = bytearray(b"%.6f\n\0")
                    fmt_type = ir.ArrayType(ir.IntType(8), len(fmt_data))
                    fmt_global = ir.GlobalVariable(self.module, fmt_type, name=fmt_name)
                    fmt_global.global_constant = True
                    fmt_global.initializer = ir.Constant(fmt_type, fmt_data)
                elif arg_type == VortexType.BOOL:
                    # Print True/False for booleans
                    # We'll handle this specially
                    fmt_data = bytearray(b"%ld\n\0")
                    fmt_type = ir.ArrayType(ir.IntType(8), len(fmt_data))
                    fmt_global = ir.GlobalVariable(self.module, fmt_type, name=fmt_name)
                    fmt_global.global_constant = True
                    fmt_global.initializer = ir.Constant(fmt_type, fmt_data)
                else:
                    fmt_data = bytearray(b"%ld\n\0")
                    fmt_type = ir.ArrayType(ir.IntType(8), len(fmt_data))
                    fmt_global = ir.GlobalVariable(self.module, fmt_type, name=fmt_name)
                    fmt_global.global_constant = True
                    fmt_global.initializer = ir.Constant(fmt_type, fmt_data)

            # Get format string pointer
            fmt_global = self.module.get_global(fmt_name)
            zero = ir.Constant(ir.IntType(32), 0)
            fmt_ptr = self.builder.gep(fmt_global, [zero, zero], name="fmt_ptr")

            # Extend bool to int for printf
            if arg_type == VortexType.BOOL:
                value = self.builder.zext(value, ir.IntType(64), name="bool_to_int_print")
            elif arg_type == VortexType.FLOAT:
                # printf with %f needs double, already double
                pass
            elif arg_type == VortexType.INT:
                pass

            self.builder.call(self._funcs["printf"], [fmt_ptr, value], name="print_call")
            return

        elif inst.func_name == "abs":
            arg_name = inst.args[0]
            arg_type = inst.arg_types[0] if inst.arg_types else VortexType.INT
            value = self._get_value(arg_name, arg_type)

            if arg_type == VortexType.FLOAT:
                # Call fabs
                if "fabs" not in self._funcs:
                    fabs_type = ir.FunctionType(ir.DoubleType(), [ir.DoubleType()])
                    fabs_func = ir.Function(self.module, fabs_type, name="fabs")
                    self._funcs["fabs"] = fabs_func
                result = self.builder.call(self._funcs["fabs"], [value], name="abs_result")
            else:
                # Integer abs: x < 0 ? -x : x
                zero = ir.Constant(ir.IntType(64), 0)
                is_neg = self.builder.icmp_signed("<", value, zero, name="is_neg")
                neg_val = self.builder.neg(value, name="neg_val")
                result = self.builder.select(is_neg, neg_val, value, name="abs_result")

            if inst.target:
                self._store_var(inst.target, result, inst.result_type)
            return

        elif inst.func_name in ("min", "max"):
            if len(inst.args) < 2:
                return
            left_type = inst.arg_types[0] if inst.arg_types else VortexType.INT
            right_type = inst.arg_types[1] if len(inst.arg_types) > 1 else VortexType.INT
            left = self._get_value(inst.args[0], left_type)
            right = self._get_value(inst.args[1], right_type)

            # Promote
            if left_type != right_type:
                if left_type == VortexType.INT and right_type == VortexType.FLOAT:
                    left = self._convert_type(left, VortexType.INT, VortexType.FLOAT)
                elif left_type == VortexType.FLOAT and right_type == VortexType.INT:
                    right = self._convert_type(right, VortexType.INT, VortexType.FLOAT)

            is_float = left_type == VortexType.FLOAT or right_type == VortexType.FLOAT
            if inst.func_name == "min":
                op = "olt" if is_float else "<"
            else:
                op = "ogt" if is_float else ">"

            if is_float:
                cmp = self.builder.fcmp_ordered(op, left, right, name="cmp")
            else:
                cmp = self.builder.icmp_signed(op, left, right, name="cmp")

            result = self.builder.select(cmp, left, right, name=f"{inst.func_name}_result")

            if inst.target:
                result_type = VortexType.FLOAT if is_float else VortexType.INT
                self._store_var(inst.target, result, result_type)
            return

        elif inst.func_name in ("int", "float", "bool"):
            # Type conversion
            arg_name = inst.args[0]
            arg_type = inst.arg_types[0] if inst.arg_types else VortexType.INT
            value = self._get_value(arg_name, arg_type)

            target_type = {
                "int": VortexType.INT,
                "float": VortexType.FLOAT,
                "bool": VortexType.BOOL,
            }[inst.func_name]

            result = self._convert_type(value, arg_type, target_type)

            if inst.target:
                self._store_var(inst.target, result, target_type)
            return

        # User-defined function call
        if inst.func_name in self._funcs:
            func = self._funcs[inst.func_name]
            arg_values = []
            for i, arg_name in enumerate(inst.args):
                arg_type = inst.arg_types[i] if i < len(inst.arg_types) else VortexType.INT
                arg_values.append(self._get_value(arg_name, arg_type))

            result = self.builder.call(func, arg_values, name=inst.func_name + "_call")

            if inst.target and inst.result_type != VortexType.VOID:
                self._store_var(inst.target, result, inst.result_type)

    def _gen_ifelse(self, inst: IRIfElse):
        """Generate LLVM IR for an if-else statement."""
        # Get condition value
        cond = self._get_value(inst.condition, VortexType.BOOL)

        # If it's an i64 (from comparison stored as int), truncate to i1
        if isinstance(cond.type, ir.IntType) and cond.type.width == 64:
            cond = self.builder.icmp_signed(
                "!=", cond, ir.Constant(ir.IntType(64), 0), name="if_cond"
            )
        elif isinstance(cond.type, ir.IntType) and cond.type.width != 1:
            cond = self.builder.icmp_signed(
                "!=", cond, ir.Constant(cond.type, 0), name="if_cond"
            )

        then_bb = self.func.append_basic_block(name="then")
        else_bb = self.func.append_basic_block(name="else") if inst.else_body else None
        merge_bb = self.func.append_basic_block(name="if_merge")

        if else_bb:
            self.builder.cbranch(cond, then_bb, else_bb)
        else:
            self.builder.cbranch(cond, then_bb, merge_bb)

        # Then block
        self.builder.position_at_start(then_bb)
        for stmt in inst.then_body:
            self._gen_stmt(stmt)
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)

        # Else block
        if else_bb:
            self.builder.position_at_start(else_bb)
            for stmt in inst.else_body:
                self._gen_stmt(stmt)
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_bb)

        # Merge block
        self.builder.position_at_start(merge_bb)

    def _gen_while(self, inst: IRWhileLoop):
        """Generate LLVM IR for a while loop."""
        cond_bb = self.func.append_basic_block(name="while_cond")
        body_bb = self.func.append_basic_block(name="while_body")
        after_bb = self.func.append_basic_block(name="while_after")

        self.builder.branch(cond_bb)

        # Condition block - re-execute condition instructions each iteration
        self.builder.position_at_start(cond_bb)
        for ci in inst.condition_instrs:
            self._gen_stmt(ci)
        cond = self._get_value(inst.condition, VortexType.BOOL)
        if isinstance(cond.type, ir.IntType) and cond.type.width == 64:
            cond = self.builder.icmp_signed(
                "!=", cond, ir.Constant(ir.IntType(64), 0), name="while_cond"
            )
        elif isinstance(cond.type, ir.IntType) and cond.type.width != 1:
            cond = self.builder.icmp_signed(
                "!=", cond, ir.Constant(cond.type, 0), name="while_cond"
            )
        self.builder.cbranch(cond, body_bb, after_bb)

        # Body block
        self.builder.position_at_start(body_bb)
        for stmt in inst.body:
            self._gen_stmt(stmt)
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_bb)

        # After block
        self.builder.position_at_start(after_bb)

    def _gen_for(self, inst: IRForLoop):
        """Generate LLVM IR for a for-range loop."""
        cond_bb = self.func.append_basic_block(name="for_cond")
        body_bb = self.func.append_basic_block(name="for_body")
        step_bb = self.func.append_basic_block(name="for_step")
        after_bb = self.func.append_basic_block(name="for_after")

        # Initialize loop variable
        start_val = self._get_value(inst.start, VortexType.INT)
        self._store_var(inst.target, start_val, VortexType.INT)

        self.builder.branch(cond_bb)

        # Condition block
        self.builder.position_at_start(cond_bb)
        current = self._get_value(inst.target, VortexType.INT)
        stop_val = self._get_value(inst.stop, VortexType.INT)
        step_val = self._get_value(inst.step, VortexType.INT)

        # Check step sign and compare accordingly
        zero = ir.Constant(ir.IntType(64), 0)
        step_positive = self.builder.icmp_signed(">", step_val, zero, name="step_pos")

        cmp_forward = self.builder.icmp_signed("<", current, stop_val, name="cmp_forward")
        cmp_backward = self.builder.icmp_signed(">", current, stop_val, name="cmp_backward")
        cond = self.builder.select(step_positive, cmp_forward, cmp_backward, name="loop_cond")

        self.builder.cbranch(cond, body_bb, after_bb)

        # Body block
        self.builder.position_at_start(body_bb)
        for stmt in inst.body:
            self._gen_stmt(stmt)
        if not self.builder.block.is_terminated:
            self.builder.branch(step_bb)

        # Step block
        self.builder.position_at_start(step_bb)
        current = self._get_value(inst.target, VortexType.INT)
        next_val = self.builder.add(current, step_val, name="next_iter")
        self._store_var(inst.target, next_val, VortexType.INT)
        self.builder.branch(cond_bb)

        # After block
        self.builder.position_at_start(after_bb)

    def _gen_stmt(self, inst):
        """Generate LLVM IR for a single IR statement."""
        if isinstance(inst, IRBinOp):
            self._gen_binop(inst)
        elif isinstance(inst, IRUnaryOp):
            self._gen_unaryop(inst)
        elif isinstance(inst, IRCompare):
            self._gen_compare(inst)
        elif isinstance(inst, IRAssign):
            self._gen_assign(inst)
        elif isinstance(inst, IRAugAssign):
            self._gen_augassign(inst)
        elif isinstance(inst, IRReturn):
            self._gen_return(inst)
        elif isinstance(inst, IRCall):
            self._gen_call(inst)
        elif isinstance(inst, IRIfElse):
            self._gen_ifelse(inst)
        elif isinstance(inst, IRWhileLoop):
            self._gen_while(inst)
        elif isinstance(inst, IRForLoop):
            self._gen_for(inst)

    def _gen_function(self, ir_func: IRFunction) -> ir.Function:
        """Generate LLVM IR for a function."""
        # Create function type
        param_types = [_llvm_type(arg.vtype) for arg in ir_func.args]
        ret_type = _llvm_type(ir_func.return_type)
        func_type = ir.FunctionType(ret_type, param_types)
        func = ir.Function(self.module, func_type, name=ir_func.name)

        # Name parameters
        for i, arg in enumerate(ir_func.args):
            func.args[i].name = arg.name

        # Create entry block
        entry = func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(entry)
        self.func = func
        self._vars = {}

        # Store arguments in allocas
        for i, arg in enumerate(ir_func.args):
            alloca = self.builder.alloca(_llvm_type(arg.vtype), name=arg.name)
            self.builder.store(func.args[i], alloca)
            self._vars[arg.name] = alloca

        # Generate body
        for stmt in ir_func.body:
            self._gen_stmt(stmt)

        # Add default return if needed
        if not self.builder.block.is_terminated:
            if ir_func.return_type == VortexType.VOID:
                self.builder.ret_void()
            elif ir_func.return_type == VortexType.FLOAT:
                self.builder.ret(ir.Constant(ir.DoubleType(), 0.0))
            else:
                self.builder.ret(ir.Constant(ir.IntType(64), 0))

        self._funcs[ir_func.name] = func
        return func

    def generate(self, ir_module: IRModule) -> str:
        """Generate LLVM IR for the entire module."""
        # Generate all functions
        for func in ir_module.functions:
            self._gen_function(func)

        # If no main function, create one
        if "main" not in self._funcs:
            main_type = ir.FunctionType(ir.IntType(32), [])
            main_func = ir.Function(self.module, main_type, name="main")
            entry = main_func.append_basic_block(name="entry")
            self.builder = ir.IRBuilder(entry)
            self.builder.ret(ir.Constant(ir.IntType(32), 0))
            self._funcs["main"] = main_func

        return str(self.module)


class NativeCompiler:
    """
    Compiles LLVM IR to a native shared library or executable
    using llvmlite's execution engine and system linker.
    """

    def __init__(self):
        binding.initialize()
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()

    def compile_to_object(self, llvm_ir: str, output_path: str, opt_level: int = 3) -> str:
        """Compile LLVM IR to an object file."""
        mod = binding.parse_assembly(llvm_ir)
        mod.verify()

        # Create target machine
        target = binding.Target.from_default_triple()
        target_machine = target.create_target_machine(
            cpu=binding.get_host_cpu_name(),
            features=binding.get_host_cpu_features().flatten(),
            opt=opt_level,
        )

        # Generate object code
        obj_code = target_machine.emit_object(mod)

        obj_path = output_path + ".o"
        with open(obj_path, "wb") as f:
            f.write(obj_code)

        return obj_path

    def compile_to_executable(self, llvm_ir: str, output_path: str, opt_level: int = 3) -> str:
        """Compile LLVM IR to a native executable."""
        obj_path = self.compile_to_object(llvm_ir, output_path, opt_level)

        # Link using gcc
        import subprocess
        result = subprocess.run(
            ["gcc", "-O3", "-march=native", "-o", output_path, obj_path, "-lm"],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Linking failed: {result.stderr}")

        # Clean up object file
        import os
        try:
            os.remove(obj_path)
        except OSError:
            pass

        return output_path

    def compile_to_shared(self, llvm_ir: str, output_path: str, opt_level: int = 3) -> str:
        """Compile LLVM IR to a shared library."""
        obj_path = self.compile_to_object(llvm_ir, output_path, opt_level)

        import subprocess
        result = subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O3", "-march=native", "-o", output_path, obj_path, "-lm"],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Linking failed: {result.stderr}")

        import os
        try:
            os.remove(obj_path)
        except OSError:
            pass

        return output_path

    def compile_and_execute(self, llvm_ir: str, opt_level: int = 3) -> int:
        """Compile LLVM IR, JIT it, and execute the main function."""
        mod = binding.parse_assembly(llvm_ir)
        mod.verify()

        # Create execution engine with optimizations
        target = binding.Target.from_default_triple()
        target_machine = target.create_target_machine(
            cpu=binding.get_host_cpu_name(),
            features=binding.get_host_cpu_features().flatten(),
            opt=opt_level,
        )

        backing_mod = binding.parse_assembly("")
        engine = binding.create_mcjit_compiler(backing_mod, target_machine)
        engine.add_module(mod)
        engine.finalize_object()
        engine.run_static_constructors()

        # Get main function pointer
        main_ptr = engine.get_function_address("main")
        cfunc = CFUNCTYPE(c_int)(main_ptr)
        result = cfunc()

        return result

    def get_llvm_ir_optimized(self, llvm_ir: str, opt_level: int = 3) -> str:
        """Run LLVM optimization passes and return optimized IR."""
        mod = binding.parse_assembly(llvm_ir)
        mod.verify()

        # Create module pass manager with optimizations
        pmb = binding.PassManagerBuilder()
        pmb.opt_level = opt_level
        pmb.size_level = 0
        pmb.loop_vectorize = True
        pmb.slp_vectorize = True

        pm = binding.ModulePassManager()
        pmb.populate(pm)

        pm.run(mod)

        return str(mod)
