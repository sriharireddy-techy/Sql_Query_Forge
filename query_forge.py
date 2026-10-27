#!/usr/bin/env python3
    

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


KEYWORDS = {
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "IS", "NULL",
    "LIKE", "BETWEEN", "AS", "DISTINCT", "JOIN", "INNER", "LEFT", "RIGHT",
    "FULL", "OUTER", "CROSS", "ON", "GROUP", "BY", "HAVING", "ORDER",
    "ASC", "DESC", "LIMIT", "OFFSET", "TRUE", "FALSE",
    "INSERT", "INTO", "VALUES",
    "UPDATE", "SET",
    "DELETE",
    "CREATE", "DROP", "TABLE", "IF", "EXISTS", "PRIMARY", "KEY", "DEFAULT",
}
TOKEN_RE = re.compile(
    r"(?P<SPACE>\s+)"
    r"|(?P<COMMENT>--[^\n]*|/\*[\s\S]*?\*/)"
    r"|(?P<STRING>'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")"
    r"|(?P<NUMBER>\d+(?:\.\d+)?)"
    r"|(?P<OP><=|>=|<>|!=|=|<|>|\+|-|\*|/|%)"
    r"|(?P<PUNCT>[(),.;])"
    r"|(?P<IDENT>[A-Za-z_][A-Za-z0-9_$]*)"
    r"|(?P<INVALID>.)"
)


@dataclass
class Token:
    kind: str
    value: str
    line: int
    column: int


@dataclass
class Diagnostic:
    phase: str
    severity: str
    message: str
    line: int | None = None
    column: int | None = None


@dataclass
class Expr:
    kind: str
    value: Any = None
    children: list["Expr"] = field(default_factory=list)


@dataclass
class SelectItem:
    expression: Expr
    alias: str | None = None


@dataclass
class TableRef:
    name: str
    alias: str | None = None


@dataclass
class Join:
    join_type: str
    table: TableRef
    condition: Expr | None = None


@dataclass
class OrderItem:
    expression: Expr
    direction: str = "ASC"


@dataclass
class SelectStatement:
    distinct: bool
    columns: list[SelectItem]
    from_table: TableRef
    joins: list[Join] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderItem] = field(default_factory=list)
    limit: int | None = None


@dataclass
class ColumnDef:
    name: str
    data_type: str
    is_primary_key: bool = False
    is_not_null: bool = False
    default_value: str | None = None


@dataclass
class CreateTableStatement:
    table: TableRef
    if_not_exists: bool
    columns: list[ColumnDef]


@dataclass
class DropTableStatement:
    table: TableRef
    if_exists: bool


@dataclass
class InsertStatement:
    table: TableRef
    columns: list[str]
    values: list[list[Expr]]


@dataclass
class UpdateAssignment:
    column: str
    value: Expr


@dataclass
class UpdateStatement:
    table: TableRef
    assignments: list[UpdateAssignment]
    where: Expr | None = None


@dataclass
class DeleteStatement:
    table: TableRef
    where: Expr | None = None


Statement = (
    SelectStatement
    | CreateTableStatement
    | DropTableStatement
    | InsertStatement
    | UpdateStatement
    | DeleteStatement
)


class QueryError(Exception):
    def __init__(self, message: str, token: Token | None = None, phase: str = "syntax"):
        super().__init__(message)
        self.token = token
        self.phase = phase


class Lexer:
    def __init__(self, sql: str):
        self.sql = sql

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        line = column = 1
        for match in TOKEN_RE.finditer(self.sql):
            value = match.group()
            kind = match.lastgroup or "INVALID"
            start_line, start_column = line, column
            line += value.count("\n")
            column = (len(value.rsplit("\n", 1)[-1]) + 1) if "\n" in value else column + len(value)
            if kind in {"SPACE", "COMMENT"}:
                continue
            if kind == "INVALID":
                raise QueryError(f"Unexpected character {value!r}.", Token(kind, value, start_line, start_column), "lexical")
            if kind == "IDENT" and value.upper() in KEYWORDS:
                kind = "KEYWORD"
                value = value.upper()
            tokens.append(Token(kind, value, start_line, start_column))
        tokens.append(Token("EOF", "", line, column))
        return tokens


class Parser:
    """Recursive-descent parser for a practical SELECT query subset."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        token = self.current
        if token.kind != "EOF":
            self.pos += 1
        return token

    def accept(self, value: str) -> Token | None:
        if self.current.value.upper() == value.upper():
            return self.advance()
        return None

    def expect(self, value: str) -> Token:
        token = self.accept(value)
        if token is None:
            raise QueryError(f"Expected {value!r}, found {self.current.value or 'end of input'!r}.", self.current)
        return token

    def expect_identifier(self) -> Token:
        if self.current.kind != "IDENT":
            raise QueryError(f"Expected an identifier, found {self.current.value or 'end of input'!r}.", self.current)
        return self.advance()

    def parse(self) -> Statement:
        val = self.current.value.upper()
        if val == "SELECT":
            stmt = self.parse_select()
        elif val == "INSERT":
            stmt = self.parse_insert()
        elif val == "UPDATE":
            stmt = self.parse_update()
        elif val == "DELETE":
            stmt = self.parse_delete()
        elif val == "CREATE":
            stmt = self.parse_create()
        elif val == "DROP":
            stmt = self.parse_drop()
        else:
            raise QueryError(
                f"Expected SQL statement (SELECT, INSERT, UPDATE, DELETE, CREATE, DROP), found {self.current.value or 'end of input'!r}.",
                self.current,
            )
        self.accept(";")
        if self.current.kind != "EOF":
            raise QueryError(f"Unexpected token {self.current.value!r} after the query.", self.current)
        return stmt

    def parse_select(self) -> SelectStatement:
        self.expect("SELECT")
        distinct = bool(self.accept("DISTINCT"))
        columns = [self.select_item()]
        while self.accept(","):
            columns.append(self.select_item())
        self.expect("FROM")
        from_table = self.table_ref()
        joins: list[Join] = []
        while self.current.value.upper() in {"JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS"}:
            join_type = "INNER"
            if self.current.value.upper() in {"INNER", "LEFT", "RIGHT", "FULL", "CROSS"}:
                join_type = self.advance().value.upper()
                self.accept("OUTER")
            self.expect("JOIN")
            table = self.table_ref()
            condition = None if join_type == "CROSS" else None
            if self.accept("ON"):
                condition = self.expression()
            elif join_type != "CROSS":
                raise QueryError("Expected ON after this JOIN.", self.current)
            joins.append(Join(join_type, table, condition))
        where = self.expression() if self.accept("WHERE") else None
        group_by: list[Expr] = []
        if self.accept("GROUP"):
            self.expect("BY")
            group_by = self.expression_list()
        having = self.expression() if self.accept("HAVING") else None
        order_by: list[OrderItem] = []
        if self.accept("ORDER"):
            self.expect("BY")
            while True:
                expr = self.expression()
                direction = "DESC" if self.accept("DESC") else "ASC"
                if direction == "ASC":
                    self.accept("ASC")
                order_by.append(OrderItem(expr, direction))
                if not self.accept(","):
                    break
        limit = None
        if self.accept("LIMIT"):
            if self.current.kind != "NUMBER" or "." in self.current.value:
                raise QueryError("LIMIT must be a non-negative integer.", self.current)
            limit = int(self.advance().value)
            if self.accept("OFFSET"):
                if self.current.kind != "NUMBER" or "." in self.current.value:
                    raise QueryError("OFFSET must be a non-negative integer.", self.current)
                self.advance()
        return SelectStatement(distinct, columns, from_table, joins, where, group_by, having, order_by, limit)

    def parse_insert(self) -> InsertStatement:
        self.expect("INSERT")
        self.accept("INTO")
        table = self.table_ref()
        columns: list[str] = []
        if self.accept("("):
            while True:
                columns.append(self.expect_identifier().value)
                if not self.accept(","):
                    break
            self.expect(")")
        self.expect("VALUES")
        values: list[list[Expr]] = []
        while True:
            self.expect("(")
            row = self.expression_list()
            self.expect(")")
            values.append(row)
            if not self.accept(","):
                break
        return InsertStatement(table, columns, values)

    def parse_update(self) -> UpdateStatement:
        self.expect("UPDATE")
        table = self.table_ref()
        self.expect("SET")
        assignments: list[UpdateAssignment] = []
        while True:
            col = self.expect_identifier().value
            self.expect("=")
            val = self.expression()
            assignments.append(UpdateAssignment(col, val))
            if not self.accept(","):
                break
        where = self.expression() if self.accept("WHERE") else None
        return UpdateStatement(table, assignments, where)

    def parse_delete(self) -> DeleteStatement:
        self.expect("DELETE")
        self.accept("FROM")
        table = self.table_ref()
        where = self.expression() if self.accept("WHERE") else None
        return DeleteStatement(table, where)

    def parse_create(self) -> CreateTableStatement:
        self.expect("CREATE")
        self.expect("TABLE")
        if_not_exists = False
        if self.accept("IF"):
            self.expect("NOT")
            self.expect("EXISTS")
            if_not_exists = True
        table = self.table_ref()
        self.expect("(")
        columns: list[ColumnDef] = []
        while True:
            if self.current.value.upper() == "PRIMARY":
                self.advance()
                self.expect("KEY")
                self.expect("(")
                pk_col = self.expect_identifier().value
                self.expect(")")
                for c in columns:
                    if c.name.lower() == pk_col.lower():
                        c.is_primary_key = True
            else:
                col_name = self.expect_identifier().value
                dt_token = self.current
                if dt_token.kind not in {"IDENT", "KEYWORD"}:
                    raise QueryError(f"Expected data type for column {col_name!r}, found {dt_token.value!r}.", dt_token)
                self.advance()
                data_type = dt_token.value.upper()
                if self.accept("("):
                    args: list[str] = []
                    while True:
                        args.append(self.current.value)
                        self.advance()
                        if not self.accept(","):
                            break
                    self.expect(")")
                    data_type += f"({', '.join(args)})"

                is_pk = False
                is_nn = False
                default_val = None
                while True:
                    if self.current.value.upper() == "PRIMARY":
                        self.advance()
                        self.expect("KEY")
                        is_pk = True
                    elif self.current.value.upper() == "NOT":
                        self.advance()
                        self.expect("NULL")
                        is_nn = True
                    elif self.current.value.upper() == "NULL":
                        self.advance()
                    elif self.current.value.upper() == "DEFAULT":
                        self.advance()
                        default_val = self.current.value
                        self.advance()
                    else:
                        break
                columns.append(ColumnDef(col_name, data_type, is_pk, is_nn, default_val))
            if not self.accept(","):
                break
        self.expect(")")
        return CreateTableStatement(table, if_not_exists, columns)

    def parse_drop(self) -> DropTableStatement:
        self.expect("DROP")
        self.expect("TABLE")
        if_exists = False
        if self.accept("IF"):
            self.expect("EXISTS")
            if_exists = True
        table = self.table_ref()
        return DropTableStatement(table, if_exists)

    def select_item(self) -> SelectItem:
        expr = self.expression()
        alias = None
        if self.accept("AS"):
            alias = self.expect_identifier().value
        elif self.current.kind == "IDENT":
            alias = self.advance().value
        return SelectItem(expr, alias)

    def table_ref(self) -> TableRef:
        name = self.expect_identifier().value
        if self.accept("."):
            name += "." + self.expect_identifier().value
        alias = None
        if self.accept("AS"):
            alias = self.expect_identifier().value
        elif self.current.kind == "IDENT":
            alias = self.advance().value
        return TableRef(name, alias)

    def expression_list(self) -> list[Expr]:
        result = [self.expression()]
        while self.accept(","):
            result.append(self.expression())
        return result

    # Pratt expression parser. Precedence increases from OR to arithmetic.
    PRECEDENCE = {"OR": 1, "AND": 2, "=": 3, "<>": 3, "!=": 3, "<": 3, ">": 3,
                  "<=": 3, ">=": 3, "LIKE": 3, "IN": 3, "IS": 3, "BETWEEN": 3,
                  "+": 4, "-": 4, "*": 5, "/": 5, "%": 5}

    def expression(self, min_precedence: int = 1) -> Expr:
        left = self.prefix()
        while True:
            op = self.current.value.upper()
            if op == "NOT" and self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1].value.upper() in {"IN", "LIKE", "BETWEEN"}:
                op = "NOT " + self.tokens[self.pos + 1].value.upper()
            base_op = op.removeprefix("NOT ")
            precedence = self.PRECEDENCE.get(base_op, 0)
            if precedence < min_precedence:
                break
            if op.startswith("NOT "):
                self.advance()
            self.advance()
            if base_op == "IS":
                negated = bool(self.accept("NOT"))
                right = self.prefix()
                left = Expr("binary", "IS NOT" if negated else "IS", [left, right])
            elif base_op == "IN":
                self.expect("(")
                values = self.expression_list()
                self.expect(")")
                left = Expr("binary", "NOT IN" if op.startswith("NOT ") else "IN", [left, Expr("list", children=values)])
            elif base_op == "BETWEEN":
                low = self.expression(precedence + 1)
                self.expect("AND")
                high = self.expression(precedence + 1)
                left = Expr("binary", "NOT BETWEEN" if op.startswith("NOT ") else "BETWEEN", [left, Expr("range", children=[low, high])])
            else:
                right = self.expression(precedence + 1)
                left = Expr("binary", "NOT LIKE" if op.startswith("NOT ") else base_op, [left, right])
        return left

    def prefix(self) -> Expr:
        token = self.current
        if self.accept("NOT"):
            return Expr("unary", "NOT", [self.expression(3)])
        if token.value in {"+", "-"}:
            self.advance()
            return Expr("unary", token.value, [self.expression(6)])
        if self.accept("("):
            expr = self.expression()
            self.expect(")")
            return expr
        if token.kind == "NUMBER":
            self.advance()
            return Expr("number", token.value)
        if token.kind == "STRING":
            self.advance()
            return Expr("string", token.value)
        if token.value.upper() in {"NULL", "TRUE", "FALSE"}:
            self.advance()
            return Expr("keyword", token.value.upper())
        if token.kind == "IDENT":
            name = self.advance().value
            if self.accept("("):
                args = [] if self.accept(")") else self.expression_list()
                if args and self.accept(")") is None:
                    raise QueryError("Expected ')' after function arguments.", self.current)
                return Expr("call", name, args)
            if self.accept("."):
                if self.accept("*"):
                    return Expr("column", name + ".*")
                return Expr("column", name + "." + self.expect_identifier().value)
            return Expr("column", name)
        if self.accept("*"):
            return Expr("star", "*")
        raise QueryError(f"Expected an expression, found {token.value or 'end of input'!r}.", token)


def expr_dict(expr: Expr) -> dict[str, Any]:
    return {"type": expr.kind, "value": expr.value, "children": [expr_dict(child) for child in expr.children]}


def _name_key(name: str) -> str:
    return name.rsplit(".", 1)[-1].strip('"`[]').lower()


class SemanticAnalyzer:
    def __init__(self, schema: dict[str, list[str]]):
        self.schema: dict[str, set[str]] = {}
        for table, columns in schema.items():
            self.schema[_name_key(table)] = {col.lower() for col in columns}
            self.schema[table.lower()] = {col.lower() for col in columns}
        self.diagnostics: list[Diagnostic] = []

    def analyze(self, stmt: Statement) -> list[Diagnostic]:
        if isinstance(stmt, SelectStatement):
            return self._analyze_select(stmt)
        if isinstance(stmt, InsertStatement):
            return self._analyze_insert(stmt)
        if isinstance(stmt, UpdateStatement):
            return self._analyze_update(stmt)
        if isinstance(stmt, DeleteStatement):
            return self._analyze_delete(stmt)
        if isinstance(stmt, CreateTableStatement):
            return self._analyze_create_table(stmt)
        if isinstance(stmt, DropTableStatement):
            return self._analyze_drop_table(stmt)
        return self.diagnostics

    def _analyze_select(self, stmt: SelectStatement) -> list[Diagnostic]:
        refs = [stmt.from_table] + [join.table for join in stmt.joins]
        tables: dict[str, str] = {}
        for ref in refs:
            table_key = _name_key(ref.name)
            if table_key not in self.schema and ref.name.lower() in self.schema:
                table_key = ref.name.lower()
            if table_key not in self.schema:
                self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown table {ref.name!r}."))
                continue
            qualifier = (ref.alias or ref.name.rsplit(".", 1)[-1]).lower()
            if qualifier in tables:
                self.diagnostics.append(Diagnostic("semantic", "error", f"Duplicate table alias {qualifier!r}."))
            tables[qualifier] = table_key
        expressions: list[Expr] = []
        for item in stmt.columns:
            expressions.append(item.expression)
        expressions += [expr for join in stmt.joins if join.condition for expr in [join.condition]]
        expressions += [expr for expr in (stmt.where, stmt.having) if expr]
        expressions += stmt.group_by + [item.expression for item in stmt.order_by]
        for expr in expressions:
            self._check_expr(expr, tables)
        return self.diagnostics

    def _analyze_insert(self, stmt: InsertStatement) -> list[Diagnostic]:
        table_key = _name_key(stmt.table.name)
        if table_key not in self.schema and stmt.table.name.lower() in self.schema:
            table_key = stmt.table.name.lower()
        if table_key not in self.schema:
            self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown table {stmt.table.name!r}."))
            return self.diagnostics
        known_columns = self.schema[table_key]
        if stmt.columns:
            for col in stmt.columns:
                if col.lower() not in known_columns:
                    self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown column {col!r} on {stmt.table.name!r}."))
            expected_count = len(stmt.columns)
            for i, row in enumerate(stmt.values):
                if len(row) != expected_count:
                    self.diagnostics.append(
                        Diagnostic("semantic", "error", f"Row {i+1} has {len(row)} value(s), but {expected_count} column(s) were specified.")
                    )
        else:
            expected_count = len(known_columns)
            for i, row in enumerate(stmt.values):
                if len(row) != expected_count:
                    self.diagnostics.append(
                        Diagnostic("semantic", "error", f"Row {i+1} has {len(row)} value(s), but table {stmt.table.name!r} expects {expected_count} column(s).")
                    )
        return self.diagnostics

    def _analyze_update(self, stmt: UpdateStatement) -> list[Diagnostic]:
        table_key = _name_key(stmt.table.name)
        if table_key not in self.schema and stmt.table.name.lower() in self.schema:
            table_key = stmt.table.name.lower()
        if table_key not in self.schema:
            self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown table {stmt.table.name!r}."))
            return self.diagnostics
        qualifier = (stmt.table.alias or stmt.table.name.rsplit(".", 1)[-1]).lower()
        tables = {qualifier: table_key}
        known_columns = self.schema[table_key]
        for assign in stmt.assignments:
            if assign.column.lower() not in known_columns:
                self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown column {assign.column!r} on {stmt.table.name!r}."))
            self._check_expr(assign.value, tables)
        if stmt.where:
            self._check_expr(stmt.where, tables)
        return self.diagnostics

    def _analyze_delete(self, stmt: DeleteStatement) -> list[Diagnostic]:
        table_key = _name_key(stmt.table.name)
        if table_key not in self.schema and stmt.table.name.lower() in self.schema:
            table_key = stmt.table.name.lower()
        if table_key not in self.schema:
            self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown table {stmt.table.name!r}."))
            return self.diagnostics
        qualifier = (stmt.table.alias or stmt.table.name.rsplit(".", 1)[-1]).lower()
        tables = {qualifier: table_key}
        if stmt.where:
            self._check_expr(stmt.where, tables)
        return self.diagnostics

    def _analyze_create_table(self, stmt: CreateTableStatement) -> list[Diagnostic]:
        table_key = _name_key(stmt.table.name)
        if table_key in self.schema or stmt.table.name.lower() in self.schema:
            if not stmt.if_not_exists:
                self.diagnostics.append(Diagnostic("semantic", "error", f"Table {stmt.table.name!r} already exists in schema."))
            else:
                self.diagnostics.append(Diagnostic("semantic", "info", f"Table {stmt.table.name!r} already exists; creation skipped by IF NOT EXISTS."))
        seen_cols: set[str] = set()
        for col in stmt.columns:
            if col.name.lower() in seen_cols:
                self.diagnostics.append(Diagnostic("semantic", "error", f"Duplicate column name {col.name!r} in CREATE TABLE."))
            seen_cols.add(col.name.lower())
        return self.diagnostics

    def _analyze_drop_table(self, stmt: DropTableStatement) -> list[Diagnostic]:
        table_key = _name_key(stmt.table.name)
        if table_key not in self.schema and stmt.table.name.lower() not in self.schema:
            if not stmt.if_exists:
                self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown table {stmt.table.name!r} in DROP TABLE."))
            else:
                self.diagnostics.append(Diagnostic("semantic", "info", f"Table {stmt.table.name!r} does not exist; drop skipped by IF EXISTS."))
        return self.diagnostics

    def _check_expr(self, expr: Expr, tables: dict[str, str]) -> None:
        if expr.kind == "column":
            parts = expr.value.split(".", 1)
            if len(parts) == 2:
                qualifier, column = parts[0].lower(), parts[1].lower()
                if qualifier not in tables:
                    self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown table or alias {parts[0]!r} in column reference."))
                elif column != "*" and column not in self.schema.get(tables[qualifier], set()):
                    self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown column {parts[1]!r} on {parts[0]!r}."))
            else:
                col_name = expr.value.lower()
                if col_name != "*":
                    matching_qualifiers = [q for q, t in tables.items() if col_name in self.schema.get(t, set())]
                    if not matching_qualifiers:
                        self.diagnostics.append(Diagnostic("semantic", "error", f"Unknown column {expr.value!r}."))
                    elif len(matching_qualifiers) > 1:
                        self.diagnostics.append(
                            Diagnostic(
                                "semantic",
                                "error",
                                f"Ambiguous column {expr.value!r}; present in multiple tables ({', '.join(sorted(matching_qualifiers))}).",
                            )
                        )
        for child in expr.children:
            self._check_expr(child, tables)


OP_PRECEDENCE: dict[str, float] = {
    "OR": 1,
    "AND": 2,
    "=": 3, "<>": 3, "!=": 3, "<": 3, ">": 3,
    "<=": 3, ">=": 3, "LIKE": 3, "NOT LIKE": 3,
    "IN": 3, "NOT IN": 3, "IS": 3, "IS NOT": 3,
    "BETWEEN": 3, "NOT BETWEEN": 3,
    "+": 4, "-": 4,
    "*": 5, "/": 5, "%": 5,
}


def _expr_precedence(expr: Expr) -> float:
    if expr.kind == "binary":
        op = str(expr.value).upper()
        return OP_PRECEDENCE.get(op, OP_PRECEDENCE.get(op.removeprefix("NOT "), 3.0))
    if expr.kind == "unary":
        if str(expr.value).upper() == "NOT":
            return 3.0
        if expr.value in {"+", "-"}:
            return 6.0
    return 100.0


def format_expr(expr: Expr) -> str:
    if expr.kind in {"column", "number", "string", "keyword", "star"}:
        return str(expr.value)
    if expr.kind == "call":
        return f"{expr.value.upper()}({', '.join(format_expr(c) for c in expr.children)})"
    if expr.kind == "list":
        return f"({', '.join(format_expr(c) for c in expr.children)})"
    if expr.kind == "range":
        return f"{format_expr(expr.children[0])} AND {format_expr(expr.children[1])}"
    if expr.kind == "unary":
        child = expr.children[0]
        child_prec = _expr_precedence(child)
        my_prec = _expr_precedence(expr)
        needs_parens = child_prec <= my_prec
        child_str = f"({format_expr(child)})" if needs_parens else format_expr(child)
        return f"{expr.value} {child_str}" if expr.value == "NOT" else f"{expr.value}{child_str}"
    if expr.kind == "binary":
        op = str(expr.value).upper()
        my_prec = _expr_precedence(expr)
        left = expr.children[0]
        right = expr.children[1]

        if op in {"IN", "NOT IN"}:
            left_prec = _expr_precedence(left)
            left_str = f"({format_expr(left)})" if left_prec < my_prec else format_expr(left)
            if right.kind == "list":
                right_str = f"({', '.join(format_expr(c) for c in right.children)})"
            else:
                right_str = format_expr(right)
            return f"{left_str} {expr.value} {right_str}"

        if op in {"BETWEEN", "NOT BETWEEN"}:
            left_prec = _expr_precedence(left)
            left_str = f"({format_expr(left)})" if left_prec < my_prec else format_expr(left)
            return f"{left_str} {expr.value} {format_expr(right)}"

        left_prec = _expr_precedence(left)
        right_prec = _expr_precedence(right)

        left_parens = left_prec < my_prec
        left_str = f"({format_expr(left)})" if left_parens else format_expr(left)

        if right_prec < my_prec:
            right_parens = True
        elif right_prec == my_prec:
            if op in {"AND", "OR", "+", "*"} and right.kind == "binary" and right.value.upper() == op:
                right_parens = False
            else:
                right_parens = True
        else:
            right_parens = False

        right_str = f"({format_expr(right)})" if right_parens else format_expr(right)
        return f"{left_str} {expr.value} {right_str}"

    return str(expr.value or "")


def format_sql(stmt: Statement) -> str:
    if isinstance(stmt, SelectStatement):
        lines = ["SELECT" + (" DISTINCT" if stmt.distinct else "")]
        lines.extend("    " + format_expr(item.expression) + (f" AS {item.alias}" if item.alias else "") + ("," if i < len(stmt.columns) - 1 else "") for i, item in enumerate(stmt.columns))
        base = "FROM " + stmt.from_table.name + (f" AS {stmt.from_table.alias}" if stmt.from_table.alias else "")
        lines.append(base)
        for join in stmt.joins:
            part = f"{join.join_type} JOIN {join.table.name}"
            if join.table.alias:
                part += f" AS {join.table.alias}"
            if join.condition:
                part += " ON " + format_expr(join.condition)
            lines.append(part)
        if stmt.where:
            lines.append("WHERE " + format_expr(stmt.where))
        if stmt.group_by:
            lines.append("GROUP BY " + ", ".join(map(format_expr, stmt.group_by)))
        if stmt.having:
            lines.append("HAVING " + format_expr(stmt.having))
        if stmt.order_by:
            lines.append("ORDER BY " + ", ".join(format_expr(i.expression) + (" DESC" if i.direction == "DESC" else "") for i in stmt.order_by))
        if stmt.limit is not None:
            lines.append(f"LIMIT {stmt.limit}")
        return "\n".join(lines) + ";"

    if isinstance(stmt, InsertStatement):
        lines = ["INSERT INTO " + stmt.table.name]
        if stmt.columns:
            lines[0] += f" ({', '.join(stmt.columns)})"
        lines.append("VALUES")
        val_rows = [f"    ({', '.join(format_expr(e) for e in row)})" for row in stmt.values]
        lines.append(",\n".join(val_rows))
        return "\n".join(lines) + ";"

    if isinstance(stmt, UpdateStatement):
        lines = ["UPDATE " + stmt.table.name]
        lines.append("SET")
        assign_lines = [f"    {a.column} = {format_expr(a.value)}" + ("," if i < len(stmt.assignments) - 1 else "") for i, a in enumerate(stmt.assignments)]
        lines.extend(assign_lines)
        if stmt.where:
            lines.append("WHERE " + format_expr(stmt.where))
        return "\n".join(lines) + ";"

    if isinstance(stmt, DeleteStatement):
        lines = ["DELETE FROM " + stmt.table.name]
        if stmt.where:
            lines.append("WHERE " + format_expr(stmt.where))
        return "\n".join(lines) + ";"

    if isinstance(stmt, CreateTableStatement):
        head = "CREATE TABLE "
        if stmt.if_not_exists:
            head += "IF NOT EXISTS "
        head += stmt.table.name + " ("
        lines = [head]
        for i, col in enumerate(stmt.columns):
            c_str = f"    {col.name} {col.data_type}"
            if col.is_primary_key:
                c_str += " PRIMARY KEY"
            if col.is_not_null:
                c_str += " NOT NULL"
            if col.default_value is not None:
                c_str += f" DEFAULT {col.default_value}"
            if i < len(stmt.columns) - 1:
                c_str += ","
            lines.append(c_str)
        lines.append(");")
        return "\n".join(lines)

    if isinstance(stmt, DropTableStatement):
        return f"DROP TABLE {'IF EXISTS ' if stmt.if_exists else ''}{stmt.table.name};"

    return ""


AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


def walk_expr(expr: Expr) -> Iterable[Expr]:
    yield expr
    for child in expr.children:
        yield from walk_expr(child)


def _is_deterministic_predicate(expr: Expr) -> bool:
    """Check if a predicate expression is deterministic and safe for deduplication.

    A predicate is deterministic if it contains only supported literals, columns,
    and standard binary/unary operators, and contains NO function calls or uncertain kinds.
    """
    for node in walk_expr(expr):
        if node.kind == "call":
            return False
        if node.kind not in {"column", "number", "string", "keyword", "binary", "unary", "list", "range"}:
            return False
    return True


def _expr_equal(a: Expr, b: Expr) -> bool:
    """Check if two expressions are structurally identical."""
    if a.kind != b.kind:
        return False
    if a.kind == "string":
        if a.value != b.value:
            return False
    elif a.kind in {"column", "keyword", "binary", "unary"}:
        if str(a.value).upper() != str(b.value).upper():
            return False
    else:
        if a.value != b.value:
            return False
    if len(a.children) != len(b.children):
        return False
    return all(_expr_equal(c1, c2) for c1, c2 in zip(a.children, b.children))


def _flatten_and_predicates(expr: Expr) -> list[Expr]:
    """Flatten top-level AND-connected predicates in a WHERE clause."""
    if expr.kind == "binary" and str(expr.value).upper() == "AND":
        return _flatten_and_predicates(expr.children[0]) + _flatten_and_predicates(expr.children[1])
    return [expr]


def _build_and_tree(predicates: list[Expr]) -> Expr:
    """Rebuild a left-associative AND tree from a list of predicates."""
    if not predicates:
        raise ValueError("Cannot construct AND tree from empty predicates")
    result = predicates[0]
    for p in predicates[1:]:
        result = Expr("binary", "AND", [result, p])
    return result


def optimize_query(stmt: Statement) -> tuple[Statement | None, list[str]]:
    """Conservative AST optimization pass:

    Removes structurally identical, deterministic predicates connected by AND in
    the WHERE clause.

    Preserves the original input AST (does not mutate stmt).
    Does NOT rewrite OR expressions, JOIN conditions, or HAVING conditions.
    Does NOT remove predicates containing function calls.
    Returns (optimized_stmt, messages). If no optimization is applicable,
    returns (None, []).
    """
    if isinstance(stmt, (SelectStatement, UpdateStatement, DeleteStatement)):
        if stmt.where is None:
            return None, []

        conjuncts = _flatten_and_predicates(stmt.where)
        if len(conjuncts) <= 1:
            return None, []

        kept: list[Expr] = []
        removed: list[Expr] = []

        for pred in conjuncts:
            if _is_deterministic_predicate(pred):
                if any(_expr_equal(pred, prior) for prior in kept):
                    removed.append(pred)
                    continue
            kept.append(pred)

        if not removed:
            return None, []

        optimized_stmt = copy.deepcopy(stmt)
        optimized_stmt.where = _build_and_tree(kept)
        messages = [
            f"Removed duplicate WHERE predicate: {format_expr(r)} (rule-based simplification; does not guarantee runtime performance improvement)."
            for r in removed
        ]
        return optimized_stmt, messages
    return None, []


def analyze_query(sql: str, schema: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Analyze SQL and return a JSON-serializable review report."""
    schema = schema or load_schema(None)
    diagnostics: list[Diagnostic] = []
    tokens: list[Token] = []
    try:
        tokens = Lexer(sql).tokenize()
    except QueryError as error:
        token = error.token
        diagnostics.append(Diagnostic(error.phase, "error", str(error), token.line if token else None, token.column if token else None))
        return _error_report(sql, tokens, diagnostics)
    try:
        stmt = Parser(tokens).parse()
    except QueryError as error:
        token = error.token
        diagnostics.append(Diagnostic(error.phase, "error", str(error), token.line if token else None, token.column if token else None))
        return _error_report(sql, tokens, diagnostics)

    diagnostics.extend(SemanticAnalyzer(schema).analyze(stmt))
    smells: list[dict[str, str]] = []
    recommendations: list[dict[str, str]] = []

    statement_type = "SELECT"
    if isinstance(stmt, InsertStatement):
        statement_type = "INSERT"
    elif isinstance(stmt, UpdateStatement):
        statement_type = "UPDATE"
    elif isinstance(stmt, DeleteStatement):
        statement_type = "DELETE"
    elif isinstance(stmt, CreateTableStatement):
        statement_type = "CREATE TABLE"
    elif isinstance(stmt, DropTableStatement):
        statement_type = "DROP TABLE"

    if isinstance(stmt, SelectStatement):
        if any(item.expression.kind == "star" or (item.expression.kind == "column" and item.expression.value.endswith(".*")) for item in stmt.columns):
            smells.append({"code": "SELECT_STAR", "severity": "warning", "message": "SELECT * can make results fragile and fetch unnecessary columns."})
            recommendations.append({"rule": "explicit_columns", "message": "List only the columns the caller needs; the analyzer cannot infer that list."})
        if not stmt.where:
            smells.append({"code": "NO_FILTER", "severity": "info", "message": "The query has no WHERE clause; confirm that reading every matching row is intended."})
        if len(stmt.joins) >= 4:
            smells.append({"code": "MANY_JOINS", "severity": "warning", "message": f"The query contains {len(stmt.joins)} joins; review whether each join is needed."})
        if stmt.where:
            for node in walk_expr(stmt.where):
                if node.kind == "binary" and node.value == "OR":
                    smells.append({"code": "OR_PREDICATE", "severity": "info", "message": "Review OR predicates for clarity and database-specific index behavior."})
                    break
        all_exprs = [item.expression for item in stmt.columns] + stmt.group_by + [item.expression for item in stmt.order_by]
        all_exprs += [expr for expr in (stmt.where, stmt.having) if expr]
        all_exprs += [j.condition for j in stmt.joins if j.condition]
        tables = [stmt.from_table] + [j.table for j in stmt.joins]
        join_count = len(stmt.joins)
        conditions = sum(1 for expr in ([stmt.where, stmt.having] + [j.condition for j in stmt.joins]) if expr for node in walk_expr(expr) if node.kind == "binary" and node.value in {"=", "<>", "!=", "<", ">", "<=", ">=", "LIKE", "IN", "NOT IN", "IS", "IS NOT", "BETWEEN", "NOT BETWEEN"})
        nested = sum(1 for token in tokens if token.value.upper() == "SELECT") - 1
        complexity = {"statement": "SELECT", "tables": len(tables), "joins": join_count, "conditions": conditions, "nested_queries": max(0, nested), "expression_nodes": sum(1 for expr in all_exprs for _ in walk_expr(expr)), "level": "low"}
        complexity["level"] = "high" if join_count >= 4 or conditions >= 8 or nested else "medium" if join_count >= 2 or conditions >= 4 else "low"
    elif isinstance(stmt, InsertStatement):
        if not stmt.columns:
            smells.append({"code": "IMPLICIT_COLUMNS", "severity": "warning", "message": "INSERT without explicit column list makes query brittle to schema changes."})
            recommendations.append({"rule": "explicit_insert_columns", "message": "Specify target column names explicitly: INSERT INTO table (col1, col2) VALUES (...)."})
        num_rows = len(stmt.values)
        num_cols = len(stmt.columns) if stmt.columns else (len(stmt.values[0]) if stmt.values else 0)
        complexity = {"statement": "INSERT", "tables": 1, "rows": num_rows, "columns": num_cols, "level": "low"}
    elif isinstance(stmt, UpdateStatement):
        if not stmt.where:
            smells.append({"code": "UNBOUNDED_UPDATE", "severity": "warning", "message": "UPDATE statement has no WHERE clause; this will update all rows in the table."})
            recommendations.append({"rule": "safeguard_update", "message": "Add a WHERE clause specifying the target rows, or confirm whole-table update is intentional."})
        else:
            for node in walk_expr(stmt.where):
                if node.kind == "binary" and node.value == "OR":
                    smells.append({"code": "OR_PREDICATE", "severity": "info", "message": "Review OR predicates for clarity and database index behavior."})
                    break
        conditions = sum(1 for node in walk_expr(stmt.where) if node.kind == "binary" and node.value in {"=", "<>", "!=", "<", ">", "<=", ">=", "LIKE", "IN", "NOT IN", "IS", "IS NOT", "BETWEEN", "NOT BETWEEN"}) if stmt.where else 0
        complexity = {"statement": "UPDATE", "tables": 1, "assignments": len(stmt.assignments), "conditions": conditions, "level": "medium" if conditions >= 4 else "low"}
    elif isinstance(stmt, DeleteStatement):
        if not stmt.where:
            smells.append({"code": "UNBOUNDED_DELETE", "severity": "warning", "message": "DELETE statement has no WHERE clause; this will delete all rows from the table."})
            recommendations.append({"rule": "safeguard_delete", "message": "Add a WHERE clause to target specific records, or use TRUNCATE if clearing table."})
        else:
            for node in walk_expr(stmt.where):
                if node.kind == "binary" and node.value == "OR":
                    smells.append({"code": "OR_PREDICATE", "severity": "info", "message": "Review OR predicates for clarity and database index behavior."})
                    break
        conditions = sum(1 for node in walk_expr(stmt.where) if node.kind == "binary" and node.value in {"=", "<>", "!=", "<", ">", "<=", ">=", "LIKE", "IN", "NOT IN", "IS", "IS NOT", "BETWEEN", "NOT BETWEEN"}) if stmt.where else 0
        complexity = {"statement": "DELETE", "tables": 1, "conditions": conditions, "level": "medium" if conditions >= 4 else "low"}
    elif isinstance(stmt, CreateTableStatement):
        if not any(c.is_primary_key for c in stmt.columns):
            smells.append({"code": "NO_PRIMARY_KEY", "severity": "info", "message": "Table definition does not designate a PRIMARY KEY."})
            recommendations.append({"rule": "define_primary_key", "message": "Designate a PRIMARY KEY for row uniqueness and efficient indexing."})
        if not stmt.if_not_exists:
            smells.append({"code": "NO_IF_NOT_EXISTS", "severity": "info", "message": "CREATE TABLE without IF NOT EXISTS will raise an error if table already exists."})
            recommendations.append({"rule": "idempotent_ddl", "message": "Use CREATE TABLE IF NOT EXISTS for safe repeated executions."})
        complexity = {"statement": "CREATE TABLE", "tables": 1, "columns": len(stmt.columns), "level": "low"}
    elif isinstance(stmt, DropTableStatement):
        if not stmt.if_exists:
            smells.append({"code": "NO_IF_EXISTS", "severity": "warning", "message": "DROP TABLE without IF EXISTS will fail with an error if table does not exist."})
            recommendations.append({"rule": "safe_drop_table", "message": "Use DROP TABLE IF EXISTS for robust idempotent migration scripts."})
        complexity = {"statement": "DROP TABLE", "tables": 1, "level": "low"}
    else:
        complexity = {"statement": "UNKNOWN", "tables": 1, "level": "low"}

    deductions: list[str] = []
    errors = [d for d in diagnostics if d.severity == "error"]
    if errors:
        score = 0
        deductions.append("Score set to 0 due to validation errors.")
    else:
        score = 100
        if isinstance(stmt, SelectStatement):
            if any(s["code"] == "SELECT_STAR" for s in smells):
                score -= 20
                deductions.append("-20: Using SELECT * instead of specifying explicit column names.")
            if any(s["code"] == "NO_FILTER" for s in smells):
                score -= 10
                deductions.append("-10: Query has no WHERE clause filter (reads all rows).")
            join_deduction = min(complexity.get("joins", 0) * 4, 16)
            if join_deduction > 0:
                score -= join_deduction
                deductions.append(f"-{join_deduction}: Join complexity ({complexity['joins']} join(s), -4 each, capped at -16).")
            cond_deduction = min(max(0, complexity.get("conditions", 0) - 3) * 2, 12)
            if cond_deduction > 0:
                score -= cond_deduction
                deductions.append(f"-{cond_deduction}: Filter condition complexity ({complexity['conditions']} conditions, exceeding threshold of 3, -2 each, capped at -12).")
        elif isinstance(stmt, UpdateStatement):
            if any(s["code"] == "UNBOUNDED_UPDATE" for s in smells):
                score -= 30
                deductions.append("-30: Unbounded UPDATE without WHERE clause modifies all rows.")
            cond_deduction = min(max(0, complexity.get("conditions", 0) - 3) * 2, 12)
            if cond_deduction > 0:
                score -= cond_deduction
                deductions.append(f"-{cond_deduction}: Filter condition complexity ({complexity['conditions']} conditions, exceeding threshold of 3).")
        elif isinstance(stmt, DeleteStatement):
            if any(s["code"] == "UNBOUNDED_DELETE" for s in smells):
                score -= 35
                deductions.append("-35: Unbounded DELETE without WHERE clause purges all rows.")
            cond_deduction = min(max(0, complexity.get("conditions", 0) - 3) * 2, 12)
            if cond_deduction > 0:
                score -= cond_deduction
                deductions.append(f"-{cond_deduction}: Filter condition complexity ({complexity['conditions']} conditions, exceeding threshold of 3).")
        elif isinstance(stmt, InsertStatement):
            if any(s["code"] == "IMPLICIT_COLUMNS" for s in smells):
                score -= 15
                deductions.append("-15: Implicit column list in INSERT (brittle to future schema alterations).")
        elif isinstance(stmt, CreateTableStatement):
            if any(s["code"] == "NO_PRIMARY_KEY" for s in smells):
                score -= 10
                deductions.append("-10: Table schema does not define a primary key.")
            if any(s["code"] == "NO_IF_NOT_EXISTS" for s in smells):
                score -= 5
                deductions.append("-5: Missing IF NOT EXISTS clause for idempotent creation.")
        elif isinstance(stmt, DropTableStatement):
            if any(s["code"] == "NO_IF_EXISTS" for s in smells):
                score -= 20
                deductions.append("-20: Missing IF EXISTS clause on DROP TABLE (non-idempotent migration).")

        score = max(0, score)
        if not deductions:
            deductions.append("No deductions applied (baseline 100/100).")

    tree = _parse_tree(stmt)

    # Conservative duplicate-predicate optimization pass
    optimized_stmt, opt_messages = optimize_query(stmt)
    optimized_sql = format_sql(optimized_stmt) if optimized_stmt else None

    return {
        "ok": not errors,
        "statement_type": statement_type,
        "input_sql": sql,
        "tokens": [asdict(t) for t in tokens if t.kind != "EOF"],
        "parse_tree": tree,
        "ast": _ast_dict(stmt),
        "formatted_sql": format_sql(stmt),
        "optimized_sql": optimized_sql,
        "optimizations": opt_messages,
        "diagnostics": [asdict(d) for d in diagnostics],
        "code_smells": smells,
        "recommendations": recommendations,
        "quality_score": {
            "score": score,
            "label": _score_label(score),
            "basis": "Rule-based educational heuristic; this is a static code-quality indicator, not a runtime performance measurement or execution-time prediction.",
            "deductions": deductions,
        },
        "complexity": complexity,
        "report": _report_text(diagnostics, smells, score, deductions, complexity, recommendations, opt_messages),
    }


def _ast_dict(stmt: Statement) -> dict[str, Any]:
    if isinstance(stmt, SelectStatement):
        return {
            "type": "SelectStatement",
            "distinct": stmt.distinct,
            "columns": [{"expression": expr_dict(i.expression), "alias": i.alias} for i in stmt.columns],
            "from": asdict(stmt.from_table),
            "joins": [{"join_type": j.join_type, "table": asdict(j.table), "condition": expr_dict(j.condition) if j.condition else None} for j in stmt.joins],
            "where": expr_dict(stmt.where) if stmt.where else None,
            "group_by": [expr_dict(e) for e in stmt.group_by],
            "having": expr_dict(stmt.having) if stmt.having else None,
            "order_by": [{"expression": expr_dict(i.expression), "direction": i.direction} for i in stmt.order_by],
            "limit": stmt.limit,
        }
    if isinstance(stmt, InsertStatement):
        return {
            "type": "InsertStatement",
            "table": asdict(stmt.table),
            "columns": stmt.columns,
            "values": [[expr_dict(e) for e in row] for row in stmt.values],
        }
    if isinstance(stmt, UpdateStatement):
        return {
            "type": "UpdateStatement",
            "table": asdict(stmt.table),
            "assignments": [{"column": a.column, "value": expr_dict(a.value)} for a in stmt.assignments],
            "where": expr_dict(stmt.where) if stmt.where else None,
        }
    if isinstance(stmt, DeleteStatement):
        return {
            "type": "DeleteStatement",
            "table": asdict(stmt.table),
            "where": expr_dict(stmt.where) if stmt.where else None,
        }
    if isinstance(stmt, CreateTableStatement):
        return {
            "type": "CreateTableStatement",
            "table": asdict(stmt.table),
            "if_not_exists": stmt.if_not_exists,
            "columns": [asdict(c) for c in stmt.columns],
        }
    if isinstance(stmt, DropTableStatement):
        return {
            "type": "DropTableStatement",
            "table": asdict(stmt.table),
            "if_exists": stmt.if_exists,
        }
    return {}


def _parse_tree(stmt: Statement) -> dict[str, Any]:
    if isinstance(stmt, SelectStatement):
        ast = _ast_dict(stmt)
        return {
            "node": "Query (SELECT)",
            "children": [
                {"node": "SELECT", "children": ast["columns"]},
                {"node": "FROM", "children": [ast["from"]]},
                {"node": "JOIN", "children": ast["joins"]},
                *([{"node": "WHERE", "children": [ast["where"]]}] if ast["where"] else []),
                *([{"node": "GROUP BY", "children": ast["group_by"]}] if ast["group_by"] else []),
                *([{"node": "HAVING", "children": [ast["having"]]}] if ast["having"] else []),
                *([{"node": "ORDER BY", "children": ast["order_by"]}] if ast["order_by"] else []),
                *([{"node": "LIMIT", "children": [stmt.limit]}] if stmt.limit is not None else []),
            ],
        }
    if isinstance(stmt, InsertStatement):
        return {
            "node": "Statement (INSERT)",
            "children": [
                {"node": "TABLE", "children": [stmt.table.name]},
                {"node": "COLUMNS", "children": stmt.columns if stmt.columns else ["* (implicit)"]},
                {"node": "ROWS", "children": [f"Row {i+1}: {len(row)} value(s)" for i, row in enumerate(stmt.values)]},
            ],
        }
    if isinstance(stmt, UpdateStatement):
        return {
            "node": "Statement (UPDATE)",
            "children": [
                {"node": "TABLE", "children": [stmt.table.name]},
                {"node": "SET", "children": [f"{a.column} = {format_expr(a.value)}" for a in stmt.assignments]},
                *([{"node": "WHERE", "children": [format_expr(stmt.where)]}] if stmt.where else []),
            ],
        }
    if isinstance(stmt, DeleteStatement):
        return {
            "node": "Statement (DELETE)",
            "children": [
                {"node": "TABLE", "children": [stmt.table.name]},
                *([{"node": "WHERE", "children": [format_expr(stmt.where)]}] if stmt.where else []),
            ],
        }
    if isinstance(stmt, CreateTableStatement):
        return {
            "node": "Statement (CREATE TABLE)",
            "children": [
                {"node": "TABLE", "children": [stmt.table.name + (" (IF NOT EXISTS)" if stmt.if_not_exists else "")]},
                {"node": "COLUMNS", "children": [f"{c.name} {c.data_type}" + (" PRIMARY KEY" if c.is_primary_key else "") for c in stmt.columns]},
            ],
        }
    if isinstance(stmt, DropTableStatement):
        return {
            "node": "Statement (DROP TABLE)",
            "children": [
                {"node": "TABLE", "children": [stmt.table.name + (" (IF EXISTS)" if stmt.if_exists else "")]},
            ],
        }
    return {"node": "Statement", "children": []}


def _score_label(score: int) -> str:
    return "excellent" if score >= 90 else "good" if score >= 75 else "fair" if score >= 50 else "needs review"


def _report_text(
    diagnostics: list[Diagnostic],
    smells: list[dict[str, str]],
    score: int,
    deductions: list[str],
    complexity: dict[str, Any] | None,
    recommendations: list[dict[str, str]],
    optimizations: list[str] | None = None,
) -> str:
    lines = [f"Query Forge Review - score {score}/100 ({_score_label(score)})"]
    lines.append("Quality Score Note: Rule-based static heuristic only; not a measurement or prediction of execution time.")
    if complexity:
        stmt_name = complexity.get("statement", "QUERY")
        comp_details = f"Complexity: {complexity.get('level', 'low')} | statement: {stmt_name} | tables: {complexity.get('tables', 1)}"
        if "joins" in complexity:
            comp_details += f" | joins: {complexity['joins']}"
        if "conditions" in complexity:
            comp_details += f" | conditions: {complexity['conditions']}"
        if "nested_queries" in complexity:
            comp_details += f" | nested queries: {complexity['nested_queries']}"
        if "rows" in complexity:
            comp_details += f" | rows: {complexity['rows']}"
        if "columns" in complexity:
            comp_details += f" | columns: {complexity['columns']}"
        lines.append(comp_details)
    if deductions:
        lines.append("Score deductions:")
        for d in deductions:
            lines.append(f"  - {d}")
    if diagnostics:
        lines.extend(f"{d.severity.upper()} [{d.phase}]: {d.message}" for d in diagnostics)
    if smells:
        lines.extend(f"{s['severity'].upper()} [{s['code']}]: {s['message']}" for s in smells)
    if recommendations:
        lines.extend(f"SUGGESTION [{r['rule']}]: {r['message']}" for r in recommendations)
    if optimizations:
        lines.append("Rule-Based Optimizations:")
        for opt in optimizations:
            lines.append(f"  - {opt}")
    if not diagnostics and not smells and not recommendations:
        lines.append("No issues found by the configured checks.")
    lines.append("Rule-based analysis only; validate performance with your database and execution plan.")
    return "\n".join(lines)


def _error_report(sql: str, tokens: list[Token], diagnostics: list[Diagnostic]) -> dict[str, Any]:
    deductions = ["Score set to 0 due to an earlier phase error."]
    return {
        "ok": False,
        "statement_type": "UNKNOWN",
        "input_sql": sql,
        "tokens": [asdict(t) for t in tokens if t.kind != "EOF"],
        "parse_tree": None,
        "ast": None,
        "formatted_sql": None,
        "optimized_sql": None,
        "optimizations": [],
        "diagnostics": [asdict(d) for d in diagnostics],
        "code_smells": [],
        "recommendations": [],
        "quality_score": {
            "score": 0,
            "label": "needs review",
            "basis": "Analysis stopped after an earlier phase error; heuristic quality score set to 0.",
            "deductions": deductions,
        },
        "complexity": None,
        "report": _report_text(diagnostics, [], 0, deductions, None, []),
    }


DEFAULT_SCHEMA: dict[str, list[str]] = {
    "Student": ["student_id", "name", "age", "department_id"],
    "Department": ["department_id", "department_name"],
    "Enrollment": ["student_id", "course_id", "grade"],
    "Course": ["course_id", "course_name", "credits"],
    "employees": ["id", "first_name", "salary", "department"],
    "projects": ["project_name", "employee_id"],
}


def load_schema(path: str | None = None) -> dict[str, list[str]]:
    """Load schema mapping table names to arrays of column names.

    If path is provided, reads that file and raises on error.
    If path is None, looks for schema.json next to this script or in the
    current working directory. If found, returns its contents.
    Otherwise, returns DEFAULT_SCHEMA.
    """
    if path:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict) or any(not isinstance(cols, list) for cols in raw.values()):
            raise ValueError("Schema JSON must map table names to arrays of column names.")
        return raw

    candidates = [
        Path(__file__).resolve().with_name("schema.json"),
        Path("schema.json"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                with open(candidate, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict) and all(isinstance(cols, list) for cols in raw.values()):
                    return raw
            except Exception:
                pass
    return DEFAULT_SCHEMA


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="Analyze a SELECT query with Query Forge.")
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument("--sql", help="SQL query to analyze")
    source.add_argument("--file", help="Read SQL from a file (use - for stdin)")
    cli.add_argument("--schema", help="JSON object mapping table names to column arrays")
    cli.add_argument("--json", action="store_true", help="Print the complete machine-readable report")
    args = cli.parse_args(argv)
    try:
        sql = args.sql if args.sql is not None else (sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read())
        result = analyze_query(sql, load_schema(args.schema))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Query Forge: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["report"])
        if result["formatted_sql"]:
            print("\nFormatted SQL:\n" + result["formatted_sql"])
        if result.get("optimized_sql"):
            print("\nOptimized SQL (rule-based simplification):\n" + result["optimized_sql"])
            for opt in result.get("optimizations", []):
                print(f"  - {opt}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
