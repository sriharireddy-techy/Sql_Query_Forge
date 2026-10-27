#!/usr/bin/env python3
"""Regression test suite for Query Forge covering essential features and changes."""

import unittest
from query_forge import (
    DEFAULT_SCHEMA,
    Lexer,
    Parser,
    _ast_dict,
    analyze_query,
    format_sql,
    load_schema,
    optimize_query,
)
from query_forge_web import PAGE


class TestQueryForge(unittest.TestCase):

    def test_1_valid_select_query(self):
        sql = "SELECT student_id, name, age FROM Student WHERE age > 20;"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertIsNotNone(res["ast"])
        self.assertIsNotNone(res["formatted_sql"])
        self.assertIn("WHERE age > 20;", res["formatted_sql"])

    def test_2_syntax_error(self):
        sql = "SELECT FROM Student;"
        res = analyze_query(sql)
        self.assertFalse(res["ok"])
        syntax_errors = [d for d in res["diagnostics"] if d["phase"] == "syntax"]
        self.assertTrue(len(syntax_errors) > 0)
        self.assertEqual(res["quality_score"]["score"], 0)

    def test_3_unknown_table(self):
        sql = "SELECT * FROM NonExistentTable;"
        res = analyze_query(sql)
        self.assertFalse(res["ok"])
        self.assertTrue(any("Unknown table" in d["message"] for d in res["diagnostics"]))

    def test_4_unknown_column(self):
        sql = "SELECT nonexistent_col FROM Student;"
        res = analyze_query(sql)
        self.assertFalse(res["ok"])
        self.assertTrue(any("Unknown column" in d["message"] for d in res["diagnostics"]))

    def test_5_ambiguous_unqualified_column_in_join(self):
        sql = "SELECT student_id FROM Student JOIN Enrollment ON Student.student_id = Enrollment.student_id;"
        res = analyze_query(sql)
        self.assertFalse(res["ok"])
        self.assertTrue(any("Ambiguous column 'student_id'" in d["message"] for d in res["diagnostics"]))

    def test_6_properly_qualified_join_columns(self):
        sql = "SELECT s.student_id, e.grade FROM Student s JOIN Enrollment e ON s.student_id = e.student_id;"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        errors = [d for d in res["diagnostics"] if d["severity"] == "error"]
        self.assertEqual(len(errors), 0)

    def test_7_mixed_and_or_formatting_preserves_grouping(self):
        sql = "SELECT * FROM Student WHERE (age > 20 OR name = 'Alice') AND department_id = 1;"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        formatted = res["formatted_sql"]
        self.assertIn("(age > 20 OR name = 'Alice') AND department_id = 1", formatted)

        # Verify that re-parsing formatted SQL yields the exact same AST structure
        stmt_orig = Parser(Lexer(sql).tokenize()).parse()
        stmt_re = Parser(Lexer(formatted).tokenize()).parse()
        self.assertEqual(_ast_dict(stmt_orig), _ast_dict(stmt_re))

    def test_8_duplicate_predicate_optimization(self):
        sql = "SELECT salary FROM employees WHERE salary > 50000 AND salary > 50000;"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertIsNotNone(res["optimized_sql"])
        self.assertTrue(res["optimized_sql"].strip().endswith("WHERE salary > 50000;"))
        self.assertEqual(len(res["optimizations"]), 1)
        self.assertIn("salary > 50000", res["optimizations"][0])

    def test_9_queries_without_duplicate_predicates_unchanged(self):
        sql = "SELECT salary FROM employees WHERE salary > 50000 AND department = 'Engineering';"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertIsNone(res["optimized_sql"])
        self.assertEqual(res["optimizations"], [])

    def test_10_original_sql_and_ast_not_modified_by_optimization(self):
        sql = "SELECT salary FROM employees WHERE salary > 50000 AND salary > 50000;"
        stmt = Parser(Lexer(sql).tokenize()).parse()
        ast_before = _ast_dict(stmt)
        opt_stmt, msgs = optimize_query(stmt)
        ast_after = _ast_dict(stmt)
        self.assertEqual(ast_before, ast_after)
        self.assertIsNot(stmt, opt_stmt)
        self.assertNotEqual(format_sql(stmt), format_sql(opt_stmt))

    def test_11_function_call_predicates_not_removed_unsafely(self):
        sql = "SELECT salary FROM employees WHERE COALESCE(salary, 0) > 1000 AND COALESCE(salary, 0) > 1000;"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertIsNone(res["optimized_sql"])
        self.assertEqual(res["optimizations"], [])

    def test_12_browser_diagnostics_render_text_safely(self):
        self.assertNotIn("innerHTML", PAGE)
        self.assertIn("textContent", PAGE)
        self.assertIn("createElement", PAGE)

    def test_13_valid_insert_query(self):
        sql = "INSERT INTO Student (student_id, name, age, department_id) VALUES (101, 'Charlie', 22, 1);"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertEqual(res["statement_type"], "INSERT")
        self.assertIn("INSERT INTO Student", res["formatted_sql"])

    def test_14_insert_column_count_mismatch(self):
        sql = "INSERT INTO Student (student_id, name) VALUES (102, 'David', 23);"
        res = analyze_query(sql)
        self.assertFalse(res["ok"])
        self.assertTrue(any("specified" in d["message"] or "value" in d["message"] for d in res["diagnostics"]))

    def test_15_valid_update_query_with_optimization(self):
        sql = "UPDATE Student SET age = age + 1 WHERE age > 20 AND age > 20;"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertEqual(res["statement_type"], "UPDATE")
        self.assertIsNotNone(res["optimized_sql"])
        self.assertEqual(len(res["optimizations"]), 1)

    def test_16_unbounded_update_warning(self):
        sql = "UPDATE Student SET age = 25;"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertTrue(any(s["code"] == "UNBOUNDED_UPDATE" for s in res["code_smells"]))

    def test_17_valid_delete_query(self):
        sql = "DELETE FROM Enrollment WHERE grade = 'F';"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertEqual(res["statement_type"], "DELETE")

    def test_18_create_table_query(self):
        sql = "CREATE TABLE IF NOT EXISTS Teachers (teacher_id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, salary FLOAT);"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertEqual(res["statement_type"], "CREATE TABLE")
        self.assertEqual(len(res["ast"]["columns"]), 3)

    def test_19_drop_table_query(self):
        sql = "DROP TABLE IF EXISTS TempTable;"
        res = analyze_query(sql)
        self.assertTrue(res["ok"])
        self.assertEqual(res["statement_type"], "DROP TABLE")

    def test_20_drop_unknown_table_without_if_exists(self):
        sql = "DROP TABLE NonExistentTable;"
        res = analyze_query(sql)
        self.assertFalse(res["ok"])
        self.assertTrue(any("Unknown table" in d["message"] for d in res["diagnostics"]))


if __name__ == "__main__":
    unittest.main()

