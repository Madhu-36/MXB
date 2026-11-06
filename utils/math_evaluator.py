import ast
import operator
import re
from utils.logger import log

class SafeMathEvaluator:
    """
    AST-based Safe Arithmetic Expression Evaluator for MXB Voice Engine.
    Evaluates spoken mathematical queries without LLM roundtrips (<0.2ms).
    """

    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    PHRASE_NORMALIZERS = [
        (r'\bmultiplied by\b', '*'),
        (r'\btimes\b', '*'),
        (r'\bdivided by\b', '/'),
        (r'\bover\b', '/'),
        (r'\bplus\b', '+'),
        (r'\badded to\b', '+'),
        (r'\bminus\b', '-'),
        (r'\bsubtracted by\b', '-'),
        (r'(\d+(?:\.\d+)?)\s*(?:percent|%)\s+of\s+(\d+(?:\.\d+)?)', r'(\1 * 0.01 * \2)'),
        (r'\bto the power of\b', '**'),
        (r'\bpower of\b', '**'),
        (r'(\d+(?:\.\d+)?)\s+squared\b', r'(\1 ** 2)'),
        (r'(\d+(?:\.\d+)?)\s+cubed\b', r'(\1 ** 3)'),
        (r'\bx\b', '*'),
    ]

    MATH_PREFIX_RE = re.compile(
        r'^(?:what\s+is|what\'s|calculate|compute|how\s+much\s+is|evaluate|solve)\s+',
        re.IGNORECASE
    )

    @classmethod
    def _eval_node(cls, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant type: {type(node.value)}")
        elif isinstance(node, ast.BinOp):
            left = cls._eval_node(node.left)
            right = cls._eval_node(node.right)
            op_type = type(node.op)
            if op_type in cls.OPERATORS:
                if op_type == ast.Div and right == 0:
                    raise ZeroDivisionError("division by zero")
                if op_type == ast.Pow and (abs(left) > 1000 or abs(right) > 100):
                    raise OverflowError("Exponent too large")
                return cls.OPERATORS[op_type](left, right)
            raise ValueError(f"Unsupported operator: {op_type}")
        elif isinstance(node, ast.UnaryOp):
            operand = cls._eval_node(node.operand)
            op_type = type(node.op)
            if op_type in cls.OPERATORS:
                return cls.OPERATORS[op_type](operand)
            raise ValueError(f"Unsupported unary operator: {op_type}")
        else:
            raise ValueError(f"Unsupported AST node: {type(node)}")

    @classmethod
    def evaluate(cls, expression: str) -> float | int | None:
        """Parses and safely evaluates a mathematical expression string."""
        if not expression or not expression.strip():
            return None
        try:
            tree = ast.parse(expression.strip(), mode='eval')
            return cls._eval_node(tree.body)
        except Exception:
            return None

    @classmethod
    def try_solve(cls, text: str) -> str | None:
        """
        Detects if input is a spoken math query and returns formatted speech reply, or None.
        e.g., 'what is 25 times 4' -> '25 * 4 is 100'
        """
        raw = text.strip().rstrip('?').strip()
        clean = cls.MATH_PREFIX_RE.sub('', raw).strip()

        # Check if the query has arithmetic intent
        normalized = clean.lower()
        for pattern, repl in cls.PHRASE_NORMALIZERS:
            normalized = re.sub(pattern, repl, normalized)

        # Must contain at least one digit and one arithmetic operator
        if not re.search(r'\d', normalized) or not re.search(r'[\+\-\*\/\%]', normalized):
            return None

        # Clean up unwanted non-math characters
        allowed_chars = set("0123456789.+-*/%() ")
        if not all(c in allowed_chars for c in normalized):
            return None

        try:
            val = cls.evaluate(normalized)
            if val is not None:
                if isinstance(val, float):
                    if val.is_integer():
                        val_str = str(int(val))
                    else:
                        val_str = f"{val:.4f}".rstrip('0').rstrip('.')
                else:
                    val_str = str(val)
                log.info(f"SafeMathEvaluator: Solved '{text}' -> {val_str}")
                return f"{clean} is {val_str}"
        except ZeroDivisionError:
            return "That would be division by zero, which is undefined."
        except OverflowError:
            return "The resulting number is too large to compute."
        except Exception as e:
            log.debug(f"SafeMathEvaluator skipped: {e}")
        return None
