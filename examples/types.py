"""
Type system and type inference for VortexPy.

Supports static type inference over a subset of Python:
  - int (i64)
  - float (f64)
  - bool (i1)
  - void
  - lists of homogeneous type
  - functions with typed signatures
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class VortexType(Enum):
    """Primitive types in VortexPy's type system."""
    INT = auto()
    FLOAT = auto()
    BOOL = auto()
    VOID = auto()
    LIST = auto()
    STRING = auto()
    UNKNOWN = auto()


@dataclass
class VortexFuncType:
    """Represents a function type with parameter and return types."""
    param_types: list[VortexType]
    return_type: VortexType
    name: str = ""


# Mapping Python AST operator results to types
_BINOP_RESULT = {
    (VortexType.INT, VortexType.INT): VortexType.INT,
    (VortexType.FLOAT, VortexType.FLOAT): VortexType.FLOAT,
    (VortexType.INT, VortexType.FLOAT): VortexType.FLOAT,
    (VortexType.FLOAT, VortexType.INT): VortexType.FLOAT,
    (VortexType.BOOL, VortexType.BOOL): VortexType.INT,  # bool ops produce int
}

_COMPARE_RESULT = VortexType.BOOL

# Which types support which operations
_COMPATIBLE_ARITH = {
    (VortexType.INT, VortexType.INT),
    (VortexType.FLOAT, VortexType.FLOAT),
    (VortexType.INT, VortexType.FLOAT),
    (VortexType.FLOAT, VortexType.INT),
}


def resolve_binop(left: VortexType, right: VortexType) -> VortexType:
    """Resolve the result type of a binary operation."""
    key = (left, right)
    if key in _BINOP_RESULT:
        return _BINOP_RESULT[key]
    # Fallback: promote to float if mixed, else int
    if VortexType.FLOAT in key:
        return VortexType.FLOAT
    return VortexType.INT


def is_comparable(left: VortexType, right: VortexType) -> bool:
    """Check if two types can be compared."""
    return (left, right) in _COMPATIBLE_ARITH or left == right


def promote_type(left: VortexType, right: VortexType) -> VortexType:
    """Promote two types to a common type (e.g., int+float -> float)."""
    if VortexType.FLOAT in (left, right):
        return VortexType.FLOAT
    if VortexType.INT in (left, right):
        return VortexType.INT
    return left


def type_from_annotation(annotation) -> VortexType:
    """Convert a Python AST annotation node to a VortexType."""
    import ast

    if annotation is None:
        return VortexType.UNKNOWN

    if isinstance(annotation, ast.Constant):
        # Handle string annotations like "int"
        name = annotation.value
    elif isinstance(annotation, ast.Name):
        name = annotation.id
    elif isinstance(annotation, ast.Attribute):
        # Handle typing module references (e.g., typing.List)
        return VortexType.UNKNOWN
    else:
        return VortexType.UNKNOWN

    mapping = {
        "int": VortexType.INT,
        "float": VortexType.FLOAT,
        "bool": VortexType.BOOL,
        "void": VortexType.VOID,
        "str": VortexType.STRING,
        "list": VortexType.LIST,
    }
    return mapping.get(name, VortexType.UNKNOWN)


def type_from_literal(node) -> VortexType:
    """Infer type from a literal value in the AST."""
    import ast

    if isinstance(node, ast.Constant):
        if isinstance(node.value, int):
            # Check if it's a bool (Python bools are ints)
            if isinstance(node.value, bool):
                return VortexType.BOOL
            return VortexType.INT
        elif isinstance(node.value, float):
            return VortexType.FLOAT
        elif isinstance(node.value, bool):
            return VortexType.BOOL
        elif isinstance(node.value, str):
            return VortexType.STRING
    return VortexType.UNKNOWN


def type_name(vtype: VortexType) -> str:
    """Human-readable type name."""
    names = {
        VortexType.INT: "int",
        VortexType.FLOAT: "float",
        VortexType.BOOL: "bool",
        VortexType.VOID: "void",
        VortexType.LIST: "list",
        VortexType.STRING: "str",
        VortexType.UNKNOWN: "unknown",
    }
    return names.get(vtype, "unknown")
