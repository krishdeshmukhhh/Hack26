"""Bounded, exact polynomial algebra. No eval, sampling, or model verdicts."""

import ast
from fractions import Fraction


class Unsupported(ValueError):
    pass


def add(a, b):
    result = dict(a)
    for power, value in b.items():
        result[power] = result.get(power, Fraction(0)) + value
    return {p: c for p, c in result.items() if c}


def multiply(a, b):
    result = {}
    for p, c in a.items():
        for q, d in b.items():
            if p + q > 32:
                raise Unsupported("Degree exceeds 32")
            result = add(result, {p + q: c * d})
    return result


def derivative(a):
    return {p - 1: p * c for p, c in a.items() if p}


def compose(a, b):
    result = {}
    for p, c in a.items():
        term = {0: c}
        for _ in range(p):
            term = multiply(term, b)
        result = add(result, term)
    return result


def polynomial(text, variable="x"):
    if len(text) > 256:
        raise Unsupported("Expression exceeds 256 characters")
    try:
        tree = ast.parse(text.strip().replace("^", "**"), mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise Unsupported("Use explicit multiplication, e.g. 2*x") from exc
    if len(list(ast.walk(tree))) > 100:
        raise Unsupported("Expression is too complex")

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            if abs(node.value) > 10**9:
                raise Unsupported("Integer is too large")
            return {0: Fraction(node.value)} if node.value else {}
        if isinstance(node, ast.Name) and node.id == variable:
            return {1: Fraction(1)}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return multiply({0: -1 if isinstance(node.op, ast.USub) else 1}, visit(node.operand))
        if isinstance(node, ast.BinOp):
            a = visit(node.left)
            if isinstance(node.op, ast.Pow):
                if not isinstance(node.right, ast.Constant) or type(node.right.value) is not int:
                    raise Unsupported("Use integer powers from 0 to 12")
                n = node.right.value
                if not 0 <= n <= 12:
                    raise Unsupported("Use integer powers from 0 to 12")
                result = {0: Fraction(1)}
                for _ in range(n):
                    result = multiply(result, a)
                return result
            b = visit(node.right)
            if isinstance(node.op, ast.Add):
                return add(a, b)
            if isinstance(node.op, ast.Sub):
                return add(a, multiply({0: -1}, b))
            if isinstance(node.op, ast.Mult):
                return multiply(a, b)
            if isinstance(node.op, ast.Div) and set(b) == {0}:
                return multiply(a, {0: 1 / b[0]})
        raise Unsupported("Supported: rational polynomials in one variable; use * explicitly")

    return visit(tree.body)


def format_polynomial(poly, variable="x"):
    return (
        " + ".join(
            f"({c})" + (f"*{variable}^{p}" if p else "")
            for p, c in sorted(poly.items(), reverse=True)
        )
        or "0"
    )


def antiderivative(text, variable="x", *, checker=polynomial):
    """Return the variable polynomial and whether a free additive C remains.

    C may appear anywhere in an affine expression, including scaled or negated.
    Products coupling C to the variable are outside this representation.
    """
    if len(text) > 256:
        raise Unsupported("Expression exceeds 256 characters")
    try:
        tree = ast.parse(text.strip().replace("^", "**"), mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise Unsupported("Use explicit polynomial notation") from exc
    if len(list(ast.walk(tree))) > 100:
        raise Unsupported("Expression is too complex")

    def visit(node):
        contains_c = any(isinstance(n, ast.Name) and n.id == "C" for n in ast.walk(node))
        if not contains_c:
            return checker(ast.unparse(node), variable), Fraction(0)
        if isinstance(node, ast.Name) and node.id == "C":
            return {}, Fraction(1)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value, constant = visit(node.operand)
            sign = -1 if isinstance(node.op, ast.USub) else 1
            return multiply({0: sign}, value), sign * constant
        if isinstance(node, ast.BinOp):
            a, ac = visit(node.left)
            b, bc = visit(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                sign = -1 if isinstance(node.op, ast.Sub) else 1
                return add(a, multiply({0: sign}, b)), ac + sign * bc
            if isinstance(node.op, ast.Mult):
                if (ac and (bc or any(b))) or (bc and any(a)):
                    raise Unsupported("C must be an additive constant independent of the variable")
                return multiply(a, b), ac * b.get(0, 0) + bc * a.get(0, 0)
            if isinstance(node.op, ast.Div) and not bc and set(b) == {0}:
                return multiply(a, {0: 1 / b[0]}), ac / b[0]
        raise Unsupported("Use a free additive constant C, optionally scaled or negated")

    value, constant = visit(tree.body)
    return value, bool(constant)
