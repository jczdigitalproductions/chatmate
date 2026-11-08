"""Capability-free interpreter for a small, explicitly bounded Python subset.

Never eval/exec/import submitted code. This is not a general Python sandbox.
Only integer functions with assignments, branches and selected expressions work.
"""
import ast
import operator

ENGINE_VERSION = "chatmate-integer-v1"
LIMIT = 10**18


class Unsupported(ValueError):
    pass


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
       ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
BUILTINS = {"abs": abs, "min": min, "max": max}
ALLOWED = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
           ast.If, ast.Assign, ast.Name, ast.Load, ast.Store, ast.Constant,
           ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call,
           ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.UAdd, ast.USub,
           ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
           ast.GtE)


def bounded(value):
    if type(value) not in (int, bool) or abs(value) > LIMIT:
        raise Unsupported("Only bounded integer/boolean values are supported.")
    return value


class Program:
    def __init__(self, source, function, parameters):
        if not isinstance(source, str) or not 1 <= len(source) <= 50_000:
            raise Unsupported("Source must contain 1–50000 characters.")
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise Unsupported(f"Invalid source: {exc}") from None
        nodes = list(ast.walk(tree))
        if len(nodes) > 1000:
            raise Unsupported("Source exceeds the 1000-node limit.")
        for node in nodes:
            if not isinstance(node, ALLOWED):
                raise Unsupported(f"Unsupported syntax: {type(node).__name__} at line {getattr(node, 'lineno', '?')}.")
            if isinstance(node, ast.Constant):
                bounded(node.value)
            if isinstance(node, ast.Name) and (node.id.startswith("_") or "__" in node.id):
                raise Unsupported("Private/dunder names are not supported.")
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name) or node.targets[0].id in BUILTINS:
                    raise Unsupported("Assignments must target one non-reserved local name.")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in BUILTINS or node.keywords:
                    raise Unsupported("Only abs/min/max positional calls are supported.")
                count = len(node.args)
                if (node.func.id == "abs" and count != 1) or (node.func.id != "abs" and not 2 <= count <= 6):
                    raise Unsupported("Invalid bounded builtin call.")
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
            raise Unsupported("Submit exactly one function, with no module-level statements.")
        self.function = tree.body[0]
        args = self.function.args
        if self.function.name != function or [a.arg for a in args.args] != parameters:
            raise Unsupported("Function name and parameter names must match the frozen contract.")
        if (args.defaults or args.kw_defaults or args.kwonlyargs or args.posonlyargs or args.vararg
                or args.kwarg or self.function.decorator_list or self.function.returns
                or getattr(self.function, "type_params", []) or any(a.annotation for a in args.args)):
            raise Unsupported("Defaults, decorators, annotations and variadic arguments are unsupported.")
        if sum(isinstance(n, ast.FunctionDef) for n in nodes) != 1:
            raise Unsupported("Nested functions are unsupported.")
        self.parameters = parameters

    def run(self, arguments):
        if len(arguments) != len(self.parameters):
            raise Unsupported("Argument count mismatch.")
        self.steps = 0
        env = dict(zip(self.parameters, map(bounded, arguments)))
        returned, value = self.statements(self.function.body, env)
        if not returned:
            raise Unsupported("Function did not return an integer/boolean.")
        return value

    def tick(self):
        self.steps += 1
        if self.steps > 2000:
            raise Unsupported("Evaluation budget exceeded.")

    def statements(self, statements, env):
        for node in statements:
            self.tick()
            if isinstance(node, ast.Return):
                return True, self.expression(node.value, env)
            if isinstance(node, ast.Assign):
                env[node.targets[0].id] = self.expression(node.value, env)
            elif isinstance(node, ast.If):
                returned, value = self.statements(node.body if self.expression(node.test, env) else node.orelse, env)
                if returned:
                    return True, value
        return False, None

    def expression(self, node, env):
        self.tick()
        if isinstance(node, ast.Constant):
            return bounded(node.value)
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise Unsupported(f"Unknown variable: {node.id}.")
            return env[node.id]
        if isinstance(node, ast.BinOp):
            return bounded(OPS[type(node.op)](self.expression(node.left, env), self.expression(node.right, env)))
        if isinstance(node, ast.UnaryOp):
            value = self.expression(node.operand, env)
            return bounded(-value if isinstance(node.op, ast.USub) else +value if isinstance(node.op, ast.UAdd) else not value)
        if isinstance(node, ast.Compare):
            left = self.expression(node.left, env)
            for op, right in zip(node.ops, node.comparators):
                value = self.expression(right, env)
                if not CMP[type(op)](left, value):
                    return False
                left = value
            return True
        if isinstance(node, ast.BoolOp):
            for item in node.values:
                value = self.expression(item, env)
                if isinstance(node.op, ast.And) and not value or isinstance(node.op, ast.Or) and value:
                    return value
            return value
        if isinstance(node, ast.IfExp):
            return self.expression(node.body if self.expression(node.test, env) else node.orelse, env)
        if isinstance(node, ast.Call):
            return bounded(BUILTINS[node.func.id](*(self.expression(a, env) for a in node.args)))
        raise Unsupported("Unsupported expression.")
