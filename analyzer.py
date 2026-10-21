#!/usr/bin/env python3
"""
Source Code Metrics Analyzer
=============================
A compiler-front-end-based static analysis tool for Python source files.

Pipeline:
    Source Code -> Lexical Analysis (tokenize) -> Syntax Analysis (ast)
                 -> Semantic Analysis (symbol table + scope checks)
                 -> Metrics Computation (AST traversal)
                 -> Report Generation

Author: Buvan Mahendran (24BCE2716)
"""

import ast
import sys
import tokenize
import io
import json
from dataclasses import dataclass, field


# =====================================================================
# PHASE 1 — LEXICAL ANALYSIS
# =====================================================================
def lexical_analysis(source: str):
    """Tokenize the source using Python's tokenize module and
    classify tokens into compiler-style categories."""
    counts = {
        "KEYWORD": 0, "IDENTIFIER": 0, "OPERATOR": 0,
        "LITERAL": 0, "COMMENT": 0, "OTHER": 0,
    }
    token_stream = []
    KEYWORDS = {
        "False", "None", "True", "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del", "elif", "else", "except",
        "finally", "for", "from", "global", "if", "import", "in", "is",
        "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
        "while", "with", "yield",
    }

    readline = io.StringIO(source).readline
    for tok in tokenize.generate_tokens(readline):
        tok_type, tok_str, start, end, _ = tok
        tname = tokenize.tok_name[tok_type]

        if tname in ("ENCODING", "NEWLINE", "NL", "INDENT", "DEDENT", "ENDMARKER"):
            continue

        if tname == "NAME":
            category = "KEYWORD" if tok_str in KEYWORDS else "IDENTIFIER"
        elif tname in ("NUMBER", "STRING"):
            category = "LITERAL"
        elif tname == "OP":
            category = "OPERATOR"
        elif tname == "COMMENT":
            category = "COMMENT"
        else:
            category = "OTHER"

        counts[category] += 1
        token_stream.append((category, tok_str.strip(), start[0]))

    return {"counts": counts, "total_tokens": sum(counts.values()), "stream": token_stream}


# =====================================================================
# PHASE 2 — SYNTAX ANALYSIS
# =====================================================================
def syntax_analysis(source: str):
    """Parse source into an Abstract Syntax Tree. Raises SyntaxError on failure."""
    tree = ast.parse(source)
    return tree


# =====================================================================
# PHASE 3 — SEMANTIC ANALYSIS (Symbol Table + scope checks)
# =====================================================================
@dataclass
class Symbol:
    name: str
    kind: str      # 'function' | 'parameter' | 'variable'
    scope: str      # 'module' or function name
    line: int


class SymbolTableBuilder(ast.NodeVisitor):
    """Walks the AST building a symbol table and flagging simple
    semantic issues (use of a name before any assignment in scope)."""

    def __init__(self):
        self.symbols: list[Symbol] = []
        self.warnings: list[str] = []
        self._scope_stack = ["module"]
        self._defined_stack = [set()]

    def _current_scope(self):
        return self._scope_stack[-1]

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.symbols.append(Symbol(node.name, "function", self._current_scope(), node.lineno))
        self._defined_stack[-1].add(node.name)

        self._scope_stack.append(node.name)
        self._defined_stack.append(set())
        for arg in node.args.args:
            self.symbols.append(Symbol(arg.arg, "parameter", node.name, node.lineno))
            self._defined_stack[-1].add(arg.arg)

        for stmt in node.body:
            self.visit(stmt)

        self._scope_stack.pop()
        self._defined_stack.pop()

    def visit_For(self, node: ast.For):
        targets = node.target.elts if isinstance(node.target, ast.Tuple) else [node.target]
        for t in targets:
            if isinstance(t, ast.Name):
                self.symbols.append(Symbol(t.id, "variable", self._current_scope(), node.lineno))
                self._defined_stack[-1].add(t.id)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.symbols.append(Symbol(target.id, "variable", self._current_scope(), node.lineno))
                self._defined_stack[-1].add(target.id)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign):
        if isinstance(node.target, ast.Name):
            name = node.target.id
            if name not in self._defined_stack[-1] and name not in __builtins__.__dict__:
                self.warnings.append(
                    f"line {node.lineno}: '{name}' is used (augmented-assigned) "
                    f"before a prior assignment in scope '{self._current_scope()}'"
                )
            self._defined_stack[-1].add(name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load):
            name = node.id
            visible = any(name in scope for scope in self._defined_stack)
            if not visible and name not in dir(__builtins__):
                self.warnings.append(
                    f"line {node.lineno}: '{name}' referenced but not found in "
                    f"any enclosing scope's symbol table"
                )
        self.generic_visit(node)


def semantic_analysis(tree: ast.AST):
    builder = SymbolTableBuilder()
    builder.visit(tree)
    return builder.symbols, builder.warnings


# =====================================================================
# PHASE 4 — METRICS COMPUTATION (AST traversal)
# =====================================================================
class ComplexityVisitor(ast.NodeVisitor):
    """Computes McCabe cyclomatic complexity: starts at 1, +1 per
    decision point (if/for/while/except/boolop-operand/ternary/assert)."""

    def __init__(self):
        self.complexity = 1

    def visit_If(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_IfExp(self, node):  # ternary
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.complexity += (len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self.complexity += len(node.ifs)
        self.generic_visit(node)


def _max_nesting_depth(node, depth=0):
    COMPOUND = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.FunctionDef, ast.ClassDef)
    best = depth
    for child in ast.iter_child_nodes(node):
        child_depth = depth + 1 if isinstance(child, COMPOUND) else depth
        best = max(best, _max_nesting_depth(child, child_depth))
    return best


def compute_metrics(source: str, tree: ast.AST, lex_result: dict):
    non_blank_lines = [l for l in source.splitlines() if l.strip() != ""]
    loc = len(non_blank_lines)

    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    function_count = len(functions)

    cv = ComplexityVisitor()
    cv.visit(tree)
    cyclomatic_complexity = cv.complexity

    # nesting depth measured from module body (depth 0), first compound stmt -> depth 1
    nesting_depth = _max_nesting_depth(tree, depth=0)

    comment_tokens = lex_result["counts"]["COMMENT"]
    comment_density = round((comment_tokens / loc) * 100, 1) if loc else 0.0

    return {
        "lines_of_code": loc,
        "cyclomatic_complexity": cyclomatic_complexity,
        "max_nesting_depth": nesting_depth,
        "function_count": function_count,
        "comment_density_pct": comment_density,
        "total_tokens": lex_result["total_tokens"],
    }


# =====================================================================
# PHASE 5 — REPORT GENERATION
# =====================================================================
def analyze_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    lex_result = lexical_analysis(source)
    tree = syntax_analysis(source)
    symbols, warnings = semantic_analysis(tree)
    metrics = compute_metrics(source, tree, lex_result)

    return {
        "file": path,
        "lexical": {
            "total_tokens": lex_result["total_tokens"],
            "token_counts": lex_result["counts"],
        },
        "symbol_table": [s.__dict__ for s in symbols],
        "semantic_warnings": warnings,
        "metrics": metrics,
    }


def print_report(result: dict):
    print("=" * 60)
    print(f"SOURCE CODE METRICS ANALYZER — REPORT")
    print(f"File: {result['file']}")
    print("=" * 60)

    print("\n[1] LEXICAL ANALYSIS")
    print(f"    Total tokens      : {result['lexical']['total_tokens']}")
    for cat, n in result["lexical"]["token_counts"].items():
        print(f"      {cat:<12}: {n}")

    print("\n[2] SYMBOL TABLE (semantic analysis)")
    print(f"    {'Name':<15}{'Kind':<12}{'Scope':<15}{'Line'}")
    for s in result["symbol_table"]:
        print(f"    {s['name']:<15}{s['kind']:<12}{s['scope']:<15}{s['line']}")

    print("\n[3] SEMANTIC WARNINGS")
    if result["semantic_warnings"]:
        for w in result["semantic_warnings"]:
            print(f"    ! {w}")
    else:
        print("    None — all referenced names resolve within scope.")

    print("\n[4] METRICS REPORT")
    m = result["metrics"]
    print(f"    Lines of Code (LOC)       : {m['lines_of_code']}")
    print(f"    Cyclomatic Complexity     : {m['cyclomatic_complexity']}")
    print(f"    Max Nesting Depth         : {m['max_nesting_depth']}")
    print(f"    Function Count            : {m['function_count']}")
    print(f"    Comment Density           : {m['comment_density_pct']}%")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python analyzer.py <source_file.py>")
        sys.exit(1)

    result = analyze_file(sys.argv[1])
    print_report(result)

    out_json = sys.argv[1] + ".metrics.json"
    with open(out_json, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nFull report written to {out_json}")
