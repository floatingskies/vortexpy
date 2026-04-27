"""
Python AST parser for VortexPy.

Parses Python source code, extracts type-annotated functions,
validates the supported subset, and produces a typed intermediate
representation ready for code generation.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass, field
from typing import Optional

from .types import (
    VortexType,
    VortexFuncType,
    type_from_annotation,
    type_from_literal,
    type_name,
    resolve_binop,
    promote_type,
)


# ── Intermediate Representation ──────────────────────────────────────────

@dataclass
class IRVariable:
    """A variable in the IR."""
    name: str
    vtype: VortexType
    is_argument: bool = False
    is_mutable: bool = True


@dataclass
class IRBinOp:
    """Binary operation: left op right."""
    left: str          # variable name or literal
    right: str
    op: str            # +, -, *, /, //, %, **, &, |, ^, <<, >>
    result: str        # target variable name
    left_type: VortexType = VortexType.UNKNOWN
    right_type: VortexType = VortexType.UNKNOWN


@dataclass
class IRUnaryOp:
    """Unary operation: op operand."""
    operand: str
    op: str            # -, +, not, ~
    result: str
    operand_type: VortexType = VortexType.UNKNOWN


@dataclass
class IRCompare:
    """Comparison operation: left op right."""
    left: str
    right: str
    ops: list[str]
    result: str
    left_type: VortexType = VortexType.UNKNOWN
    right_type: VortexType = VortexType.UNKNOWN


@dataclass
class IRAssign:
    """Simple assignment: target = value (variable or literal)."""
    target: str
    value: str
    target_type: VortexType = VortexType.UNKNOWN
    value_type: VortexType = VortexType.UNKNOWN


@dataclass
class IRReturn:
    """Return statement."""
    value: Optional[str]  # None for void returns
    return_type: VortexType = VortexType.VOID


@dataclass
class IRCall:
    """Function call: result = func(args...)."""
    target: str
    func_name: str
    args: list[str]
    arg_types: list[VortexType] = field(default_factory=list)
    result_type: VortexType = VortexType.UNKNOWN


@dataclass
class IRIfElse:
    """If-else conditional."""
    condition: str
    then_body: list = field(default_factory=list)
    else_body: list = field(default_factory=list)


@dataclass
class IRWhileLoop:
    """While loop."""
    condition: str
    condition_instrs: list = field(default_factory=list)  # IR instructions to re-evaluate condition
    body: list = field(default_factory=list)


@dataclass
class IRForLoop:
    """For loop (range-based)."""
    target: str
    start: str
    stop: str
    step: str
    body: list = field(default_factory=list)
    target_type: VortexType = VortexType.INT


@dataclass
class IRAugAssign:
    """Augmented assignment: target op= value."""
    target: str
    op: str
    value: str
    target_type: VortexType = VortexType.UNKNOWN
    value_type: VortexType = VortexType.UNKNOWN


@dataclass
class IRFunction:
    """A complete function in the IR."""
    name: str
    args: list[IRVariable]
    return_type: VortexType
    body: list = field(default_factory=list)
    local_vars: dict[str, VortexType] = field(default_factory=dict)
    is_entry: bool = False  # True for main()


@dataclass
class IRModule:
    """A complete compilation unit."""
    functions: list[IRFunction] = field(default_factory=list)
    globals: dict[str, VortexType] = field(default_factory=dict)
    source_file: str = ""


# ── Parser ───────────────────────────────────────────────────────────────

# Binary operators mapping
_BINOP_MAP = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
    ast.LShift: "<<",
    ast.RShift: ">>",
    ast.BitAnd: "&",
    ast.BitOr: "|",
    ast.BitXor: "^",
}

_COMPARE_MAP = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}

_AUGOP_MAP = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.BitAnd: "&",
    ast.BitOr: "|",
    ast.BitXor: "^",
    ast.LShift: "<<",
    ast.RShift: ">>",
}


class VortexParser:
    """
    Parses Python source into VortexPy IR.

    Supports:
      - Type-annotated function definitions
      - Integer and float arithmetic
      - Comparisons and boolean operations
      - If/elif/else statements
      - While and for-range loops
      - Variable assignments
      - Function calls (to other VortexPy functions)
      - return statements
      - Built-in functions: print, abs, min, max, len, range
    """

    # Built-in functions we support
    BUILTINS = {"print", "abs", "min", "max", "len", "range", "int", "float", "bool"}

    def __init__(self):
        self._type_env: dict[str, VortexType] = {}
        self._functions: dict[str, VortexFuncType] = {}
        self._var_counter = 0
        self._errors: list[str] = []

    def _fresh_var(self, prefix: str = "_t") -> str:
        """Generate a fresh temporary variable name."""
        self._var_counter += 1
        return f"{prefix}{self._var_counter}"

    def _infer_expr_type(self, node: ast.expr) -> VortexType:
        """Infer the type of an expression."""
        if isinstance(node, ast.Constant):
            return type_from_literal(node)
        elif isinstance(node, ast.Name):
            return self._type_env.get(node.id, VortexType.UNKNOWN)
        elif isinstance(node, ast.BinOp):
            left_t = self._infer_expr_type(node.left)
            right_t = self._infer_expr_type(node.right)
            return resolve_binop(left_t, right_t)
        elif isinstance(node, ast.UnaryOp):
            return self._infer_expr_type(node.operand)
        elif isinstance(node, ast.Compare):
            return VortexType.BOOL
        elif isinstance(node, ast.BoolOp):
            return VortexType.BOOL
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                fname = node.func.id
                if fname in self._functions:
                    return self._functions[fname].return_type
                # Built-in type constructors
                if fname == "int":
                    return VortexType.INT
                elif fname == "float":
                    return VortexType.FLOAT
                elif fname == "bool":
                    return VortexType.BOOL
                elif fname in ("abs", "min", "max"):
                    # These return the same type as their args
                    if node.args:
                        return self._infer_expr_type(node.args[0])
                    return VortexType.INT
                elif fname == "len":
                    return VortexType.INT
                elif fname == "print":
                    return VortexType.VOID
            return VortexType.UNKNOWN
        return VortexType.UNKNOWN

    def _get_name(self, node) -> str:
        """Get a simple name from an AST node — only works for names and literals."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return "True" if node.value else "False"
            return str(node.value)
        elif isinstance(node, ast.Subscript):
            return f"{self._get_name(node.value)}[{self._get_name(node.slice)}]"
        return repr(ast.dump(node))

    def _materialize_expr(self, node, func: IRFunction) -> tuple[str, list]:
        """
        Materialize an expression: if it's a complex expression (BinOp, Compare, Call, etc.),
        generate IR instructions and return the result variable name.
        If it's a simple name or literal, just return the name.
        
        Returns: (result_name, list_of_IR_instructions)
        """
        instructions = []

        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return ("True" if node.value else "False"), []
            return str(node.value), []

        if isinstance(node, ast.Name):
            return node.id, []

        if isinstance(node, ast.BinOp):
            left_name, left_instrs = self._materialize_expr(node.left, func)
            instructions.extend(left_instrs)
            right_name, right_instrs = self._materialize_expr(node.right, func)
            instructions.extend(right_instrs)

            result_name = self._fresh_var("_expr")
            op_type = _BINOP_MAP.get(type(node.op), "+")
            left_type = self._infer_expr_type(node.left)
            right_type = self._infer_expr_type(node.right)
            result_type = resolve_binop(left_type, right_type)

            self._type_env[result_name] = result_type
            func.local_vars[result_name] = result_type

            instructions.append(IRBinOp(
                left=left_name, right=right_name,
                op=op_type, result=result_name,
                left_type=left_type, right_type=right_type,
            ))
            return result_name, instructions

        if isinstance(node, ast.UnaryOp):
            operand_name, operand_instrs = self._materialize_expr(node.operand, func)
            instructions.extend(operand_instrs)

            result_name = self._fresh_var("_expr")
            op = "-"
            if isinstance(node.op, ast.USub):
                op = "-"
            elif isinstance(node.op, ast.UAdd):
                op = "+"
            elif isinstance(node.op, ast.Not):
                op = "not"
            elif isinstance(node.op, ast.Invert):
                op = "~"
            operand_type = self._infer_expr_type(node.operand)

            self._type_env[result_name] = operand_type
            func.local_vars[result_name] = operand_type

            instructions.append(IRUnaryOp(
                operand=operand_name, op=op, result=result_name,
                operand_type=operand_type,
            ))
            return result_name, instructions

        if isinstance(node, ast.Compare):
            left_name, left_instrs = self._materialize_expr(node.left, func)
            instructions.extend(left_instrs)
            right_name, right_instrs = self._materialize_expr(node.comparators[0], func)
            instructions.extend(right_instrs)

            result_name = self._fresh_var("_expr")
            left_type = self._infer_expr_type(node.left)
            right_type = self._infer_expr_type(node.comparators[0])
            ops = [_COMPARE_MAP.get(type(o), "==") for o in node.ops]

            self._type_env[result_name] = VortexType.BOOL
            func.local_vars[result_name] = VortexType.BOOL

            instructions.append(IRCompare(
                left=left_name, right=right_name,
                ops=ops, result=result_name,
                left_type=left_type, right_type=right_type,
            ))
            return result_name, instructions

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                fname = node.func.id
                arg_names = []
                for arg in node.args:
                    arg_name, arg_instrs = self._materialize_expr(arg, func)
                    instructions.extend(arg_instrs)
                    arg_names.append(arg_name)

                arg_types = [self._infer_expr_type(a) for a in node.args]
                result_type = self._infer_expr_type(node)
                if result_type == VortexType.UNKNOWN:
                    result_type = VortexType.INT

                result_name = self._fresh_var("_call")
                self._type_env[result_name] = result_type
                func.local_vars[result_name] = result_type

                instructions.append(IRCall(
                    target=result_name, func_name=fname,
                    args=arg_names, arg_types=arg_types,
                    result_type=result_type,
                ))
                return result_name, instructions

        # Fallback: return the string name
        return self._get_name(node), instructions

    def _parse_expr(self, node: ast.expr) -> str:
        """Parse an expression and return its string representation."""
        if isinstance(node, ast.Constant):
            return repr(node.value)
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.BinOp):
            left = self._parse_expr(node.left)
            right = self._parse_expr(node.right)
            return f"({left} {_BINOP_MAP.get(type(node.op), '?')} {right})"
        elif isinstance(node, ast.UnaryOp):
            operand = self._parse_expr(node.operand)
            if isinstance(node.op, ast.USub):
                return f"(-{operand})"
            elif isinstance(node.op, ast.UAdd):
                return f"(+{operand})"
            elif isinstance(node.op, ast.Not):
                return f"(not {operand})"
            elif isinstance(node.op, ast.Invert):
                return f"(~{operand})"
        elif isinstance(node, ast.Compare):
            left = self._parse_expr(node.left)
            parts = [left]
            for op, comp in zip(node.ops, node.comparators):
                parts.append(_COMPARE_MAP.get(type(op), "?"))
                parts.append(self._parse_expr(comp))
            return " ".join(parts)
        elif isinstance(node, ast.BoolOp):
            op = "and" if isinstance(node.op, ast.And) else "or"
            parts = [self._parse_expr(v) for v in node.values]
            return f" {op} ".join(parts)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                fname = node.func.id
                args = ", ".join(self._parse_expr(a) for a in node.args)
                return f"{fname}({args})"
        return repr(ast.dump(node))

    def _parse_stmt(self, node: ast.stmt, func: IRFunction) -> list:
        """Parse a statement and return a list of IR instructions."""
        instructions = []

        if isinstance(node, ast.Assign):
            # Simple assignment: use materialize_expr for complex values
            target = self._get_name(node.targets[0])
            value_expr = node.value

            # Materialize the expression - this handles all cases
            value_name, value_instrs = self._materialize_expr(value_expr, func)
            instructions.extend(value_instrs)

            value_type = self._infer_expr_type(value_expr)
            target_type = self._type_env.get(target, value_type)

            self._type_env[target] = target_type
            func.local_vars[target] = target_type

            if value_instrs:
                # The materialize_expr already created the proper instructions,
                # but the result is in a temp variable. We need to assign it to target.
                # Check if the last instruction already targets our variable
                last_instr = value_instrs[-1] if value_instrs else None
                if isinstance(last_instr, (IRBinOp, IRUnaryOp, IRCompare, IRCall)) and hasattr(last_instr, 'result') and last_instr.result == value_name:
                    # Redirect the result to our target variable
                    last_instr.result = target
                else:
                    instructions.append(IRAssign(
                        target=target, value=value_name,
                        target_type=target_type, value_type=value_type,
                    ))
            else:
                # Simple value (literal or variable)
                instructions.append(IRAssign(
                    target=target, value=value_name,
                    target_type=target_type, value_type=value_type,
                ))

        elif isinstance(node, ast.AugAssign):
            target = self._get_name(node.target)
            value_name, value_instrs = self._materialize_expr(node.value, func)
            instructions.extend(value_instrs)
            op = _AUGOP_MAP.get(type(node.op), "+")
            target_type = self._type_env.get(target, VortexType.UNKNOWN)
            value_type = self._infer_expr_type(node.value)

            instructions.append(IRAugAssign(
                target=target, op=op, value=value_name,
                target_type=target_type, value_type=value_type,
            ))

        elif isinstance(node, ast.Return):
            if node.value is not None:
                value_name, value_instrs = self._materialize_expr(node.value, func)
                instructions.extend(value_instrs)
                value_type = self._infer_expr_type(node.value)
                instructions.append(IRReturn(value=value_name, return_type=value_type))
            else:
                instructions.append(IRReturn(value=None, return_type=VortexType.VOID))

        elif isinstance(node, ast.If):
            cond_name, cond_instrs = self._materialize_expr(node.test, func)
            instructions.extend(cond_instrs)
            then_body = []
            for s in node.body:
                then_body.extend(self._parse_stmt(s, func))
            else_body = []
            for s in node.orelse:
                else_body.extend(self._parse_stmt(s, func))
            instructions.append(IRIfElse(
                condition=cond_name,
                then_body=then_body,
                else_body=else_body,
            ))

        elif isinstance(node, ast.While):
            cond_name, cond_instrs = self._materialize_expr(node.test, func)
            body = []
            for s in node.body:
                body.extend(self._parse_stmt(s, func))
            instructions.append(IRWhileLoop(
                condition=cond_name,
                condition_instrs=cond_instrs,
                body=body,
            ))

        elif isinstance(node, ast.For):
            target = self._get_name(node.target)
            self._type_env[target] = VortexType.INT
            func.local_vars[target] = VortexType.INT

            # Parse range() call or simple iterable
            start = "0"
            stop = "0"
            step = "1"
            if isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name):
                if node.iter.func.id == "range":
                    args = node.iter.args
                    if len(args) == 1:
                        stop_name, stop_instrs = self._materialize_expr(args[0], func)
                        instructions.extend(stop_instrs)
                        stop = stop_name
                    elif len(args) == 2:
                        start_name, start_instrs = self._materialize_expr(args[0], func)
                        instructions.extend(start_instrs)
                        stop_name, stop_instrs = self._materialize_expr(args[1], func)
                        instructions.extend(stop_instrs)
                        start = start_name
                        stop = stop_name
                    elif len(args) == 3:
                        start_name, start_instrs = self._materialize_expr(args[0], func)
                        instructions.extend(start_instrs)
                        stop_name, stop_instrs = self._materialize_expr(args[1], func)
                        instructions.extend(stop_instrs)
                        step_name, step_instrs = self._materialize_expr(args[2], func)
                        instructions.extend(step_instrs)
                        start = start_name
                        stop = stop_name
                        step = step_name

            body = []
            for s in node.body:
                body.extend(self._parse_stmt(s, func))

            instructions.append(IRForLoop(
                target=target, start=start, stop=stop, step=step,
                body=body, target_type=VortexType.INT,
            ))

        elif isinstance(node, ast.Expr):
            # Expression statement (e.g., function call)
            if isinstance(node.value, ast.Call):
                if isinstance(node.value.func, ast.Name):
                    fname = node.value.func.id
                    arg_names = []
                    for a in node.value.args:
                        arg_name, arg_instrs = self._materialize_expr(a, func)
                        instructions.extend(arg_instrs)
                        arg_names.append(arg_name)
                    arg_types = [self._infer_expr_type(a) for a in node.value.args]

                    # For print and void functions, no target
                    if fname == "print":
                        instructions.append(IRCall(
                            target="", func_name=fname,
                            args=arg_names, arg_types=arg_types,
                            result_type=VortexType.VOID,
                        ))
                    else:
                        result_type = self._infer_expr_type(node.value)
                        target = self._fresh_var()
                        self._type_env[target] = result_type
                        func.local_vars[target] = result_type
                        instructions.append(IRCall(
                            target=target, func_name=fname,
                            args=arg_names, arg_types=arg_types,
                            result_type=result_type,
                        ))

        elif isinstance(node, ast.AnnAssign):
            # Type-annotated assignment: x: int = x + y
            target = node.target.id if isinstance(node.target, ast.Name) else str(node.target)
            target_type = type_from_annotation(node.annotation)

            if node.value is not None:
                value_expr = node.value
                value_type = self._infer_expr_type(value_expr)

                # Use the annotated type if available
                if target_type == VortexType.UNKNOWN:
                    target_type = value_type

                self._type_env[target] = target_type
                func.local_vars[target] = target_type

                # Materialize the expression
                value_name, value_instrs = self._materialize_expr(value_expr, func)
                instructions.extend(value_instrs)

                if value_instrs:
                    last_instr = value_instrs[-1] if value_instrs else None
                    if isinstance(last_instr, (IRBinOp, IRUnaryOp, IRCompare, IRCall)) and hasattr(last_instr, 'result') and last_instr.result == value_name:
                        last_instr.result = target
                    else:
                        instructions.append(IRAssign(
                            target=target, value=value_name,
                            target_type=target_type, value_type=value_type,
                        ))
                else:
                    instructions.append(IRAssign(
                        target=target, value=value_name,
                        target_type=target_type, value_type=value_type,
                    ))
            else:
                # Just a declaration
                self._type_env[target] = target_type
                func.local_vars[target] = target_type

        return instructions

    def _parse_function(self, node: ast.FunctionDef) -> IRFunction:
        """Parse a function definition into IR."""
        # Parse arguments
        args = []
        for arg in node.args.args:
            arg_type = type_from_annotation(arg.annotation)
            if arg_type == VortexType.UNKNOWN:
                # Try to infer from default values or use int as default
                arg_type = VortexType.INT
            var = IRVariable(name=arg.arg, vtype=arg_type, is_argument=True)
            args.append(var)
            self._type_env[arg.arg] = arg_type

        # Parse return type
        return_type = type_from_annotation(node.returns)
        if return_type == VortexType.UNKNOWN:
            return_type = VortexType.INT  # default

        func = IRFunction(
            name=node.name,
            args=args,
            return_type=return_type,
            is_entry=(node.name == "main"),
        )

        # Register function type
        func_type = VortexFuncType(
            param_types=[a.vtype for a in args],
            return_type=return_type,
            name=node.name,
        )
        self._functions[node.name] = func_type

        # Parse body
        for stmt in node.body:
            func.body.extend(self._parse_stmt(stmt, func))

        return func

    def parse(self, source: str, filename: str = "<string>") -> IRModule:
        """Parse Python source code into a VortexPy IR module."""
        self._type_env = {}
        self._functions = {}
        self._var_counter = 0
        self._errors = []

        tree = ast.parse(source, filename=filename)
        module = IRModule(source_file=filename)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                func = self._parse_function(node)
                module.functions.append(func)
            elif isinstance(node, ast.AnnAssign):
                # Module-level annotated assignment
                name = node.target.id if isinstance(node.target, ast.Name) else ""
                vtype = type_from_annotation(node.annotation)
                if name:
                    module.globals[name] = vtype
            elif isinstance(node, ast.Assign):
                # Module-level assignment
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module.globals[target.id] = self._infer_expr_type(node.value)

        return module

    def parse_file(self, filepath: str) -> IRModule:
        """Parse a Python file into a VortexPy IR module."""
        with open(filepath, "r") as f:
            source = f.read()
        return self.parse(source, filename=filepath)

    @property
    def errors(self) -> list[str]:
        return self._errors
