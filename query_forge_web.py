#!/usr/bin/env python3
"""Small local browser UI for Query Forge; uses only the Python standard library."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

from query_forge import analyze_query, load_schema


# Resolve next to this script so the browser UI uses the same editable schema
# file regardless of the directory from which the server was started.
SCHEMA = load_schema(str(Path(__file__).resolve().with_name("schema.json")))


PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Query Forge · Compiler Design Studio (24BCE0814)</title>
<style>
:root, :root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #090e13;
  --bg-alt: #0e161e;
  --panel: #13222d;
  --panel-header: #172733;
  --panel-subtle: #192b38;
  --line: #223746;
  --line-subtle: #182833;
  --text: #e6f1f5;
  --muted: #8ca0ad;
  --accent: #38bdf8;
  --accent-hover: #0284c7;
  --accent-subtle: rgba(56, 189, 248, 0.12);
  --accent-border: rgba(56, 189, 248, 0.35);
  --warn: #fbbf24;
  --warn-bg: rgba(251, 191, 36, 0.1);
  --warn-line: #f59e0b;
  --bad: #f87171;
  --bad-bg: rgba(248, 113, 113, 0.1);
  --bad-line: #ef4444;
  --good: #34d399;
  --good-bg: rgba(52, 211, 153, 0.1);
  --good-line: #10b981;
  --code-bg: #070d12;
  --table-header: #111c24;
  --token-bg: #16242f;
  --shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.45);
  --badge-kw: #818cf8;
  --badge-kw-bg: rgba(129, 140, 248, 0.15);
  --badge-ident: #38bdf8;
  --badge-ident-bg: rgba(56, 189, 248, 0.15);
  --badge-op: #fbbf24;
  --badge-op-bg: rgba(251, 191, 36, 0.15);
  --badge-lit: #34d399;
  --badge-lit-bg: rgba(52, 211, 153, 0.15);
  --badge-punct: #94a3b8;
  --badge-punct-bg: rgba(148, 163, 184, 0.15);
}
:root[data-theme="light"] {
  color-scheme: light;
  --bg: #f4f7fb;
  --bg-alt: #edf2f7;
  --panel: #ffffff;
  --panel-header: #f8fafc;
  --panel-subtle: #f1f5f9;
  --line: #cbd5e1;
  --line-subtle: #e2e8f0;
  --text: #0f172a;
  --muted: #475569;
  --accent: #0284c7;
  --accent-hover: #0369a1;
  --accent-subtle: rgba(2, 132, 199, 0.1);
  --accent-border: rgba(2, 132, 199, 0.35);
  --warn: #b45309;
  --warn-bg: #fffbeb;
  --warn-line: #f59e0b;
  --bad: #b91c1c;
  --bad-bg: #fef2f2;
  --bad-line: #ef4444;
  --good: #047857;
  --good-bg: #ecfdf5;
  --good-line: #10b981;
  --code-bg: #f8fafc;
  --table-header: #f1f5f9;
  --token-bg: #f1f5f9;
  --shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.08);
  --badge-kw: #4338ca;
  --badge-kw-bg: rgba(99, 102, 241, 0.12);
  --badge-ident: #0369a1;
  --badge-ident-bg: rgba(2, 132, 199, 0.12);
  --badge-op: #b45309;
  --badge-op-bg: rgba(245, 158, 11, 0.12);
  --badge-lit: #047857;
  --badge-lit-bg: rgba(16, 185, 129, 0.12);
  --badge-punct: #475569;
  --badge-punct-bg: rgba(100, 116, 139, 0.12);
}
*{box-sizing:border-box;transition:background-color 0.15s ease,border-color 0.15s ease,color 0.15s ease}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{background:var(--panel);border-bottom:1px solid var(--line);padding:18px max(24px,calc((100vw - 1180px)/2));display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;position:sticky;top:0;z-index:50}
.brand{display:flex;flex-direction:column;gap:3px}
.brand-title{margin:0;font-size:22px;font-weight:800;display:flex;align-items:center;gap:10px}
.brand-badge{font-size:11px;font-weight:700;letter-spacing:0.5px;padding:3px 8px;border-radius:6px;background:var(--accent-subtle);color:var(--accent);border:1px solid var(--accent-border);text-transform:uppercase}
header p{margin:0;color:var(--muted);font-size:13px}
.header-actions{display:flex;align-items:center;gap:10px}
.btn-theme{background:var(--panel-subtle);border:1px solid var(--line);color:var(--text);padding:8px 14px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:7px}
.btn-theme:hover{border-color:var(--accent);color:var(--accent)}
main{max-width:1180px;margin:22px auto 48px;padding:0 20px}
.editor,.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:var(--shadow);margin-bottom:20px}
.section-title{display:flex;justify-content:space-between;align-items:center;margin:0 0 14px;font-size:16px;font-weight:700}
.examples-bar{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px}
.chip{background:var(--panel-subtle);border:1px solid var(--line);color:var(--text);border-radius:6px;padding:6px 11px;font-size:12px;font-weight:600;cursor:pointer}
.chip:hover{background:var(--accent-subtle);border-color:var(--accent);color:var(--accent)}
textarea{width:100%;height:130px;resize:vertical;background:var(--code-bg);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:14px;font:14px/1.6 "Fira Code",ui-monospace,monospace;outline:none}
textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-subtle)}
.editor-controls{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-top:12px}
.btn-primary{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:10px 20px;font-weight:700;font-size:14px;cursor:pointer;display:inline-flex;align-items:center;gap:6px}
:root[data-theme="dark"] .btn-primary{color:#090e13;background:var(--accent)}
.btn-primary:hover{opacity:0.92}
#status{color:var(--muted);font-size:13px;font-weight:500}
.stepper{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;margin:18px 0;background:var(--panel);padding:10px;border-radius:10px;border:1px solid var(--line)}
.step-item{padding:8px 6px;border-radius:6px;background:var(--panel-subtle);border:1px solid var(--line-subtle);font-size:11.5px;font-weight:700;text-align:center;cursor:pointer;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.step-item:hover,.step-item.active{background:var(--accent-subtle);border-color:var(--accent);color:var(--accent)}
.step-item.step-error{border-color:var(--bad);color:var(--bad);background:var(--bad-bg)}
.phase-card{margin-bottom:20px;border-top:3px solid var(--accent)}
.phase-header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding-bottom:12px;margin-bottom:14px;border-bottom:1px solid var(--line-subtle)}
.phase-title{font-size:16px;font-weight:700;margin:0;display:flex;align-items:center;gap:8px}
.phase-num{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:var(--accent);color:#fff;font-size:12px;font-weight:800}
:root[data-theme="dark"] .phase-num{color:#090e13}
.phase-desc{color:var(--muted);font-size:13px;margin:0 0 14px}
.tokens-meta{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:99px;padding:3px 10px;font-size:12px;color:var(--muted);background:var(--panel-subtle)}
.pill b{color:var(--text)}
.filter-bar{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.filter-btn{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:6px;padding:4px 10px;font-size:11.5px;font-weight:600;cursor:pointer}
.filter-btn.active,.filter-btn:hover{background:var(--accent-subtle);border-color:var(--accent);color:var(--accent)}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;max-height:360px}
.token-table{width:100%;border-collapse:collapse;font-size:13px;text-align:left}
.token-table th{background:var(--table-header);padding:9px 12px;border-bottom:1px solid var(--line);font-size:11.5px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.4px;position:sticky;top:0;z-index:2}
.token-table td{padding:8px 12px;border-bottom:1px solid var(--line-subtle)}
.token-table tr:hover td{background:var(--panel-subtle)}
.token-badge{font-size:11px;font-weight:700;padding:2px 7px;border-radius:4px;display:inline-block;letter-spacing:0.3px}
.badge-kw{color:var(--badge-kw);background:var(--badge-kw-bg)}
.badge-ident{color:var(--badge-ident);background:var(--badge-ident-bg)}
.badge-op{color:var(--badge-op);background:var(--badge-op-bg)}
.badge-lit{color:var(--badge-lit);background:var(--badge-lit-bg)}
.badge-punct{color:var(--badge-punct);background:var(--badge-punct-bg)}
.token-code{font:12.5px/1.4 "Fira Code",ui-monospace,monospace;padding:2px 5px;background:var(--code-bg);border-radius:4px;border:1px solid var(--line-subtle);color:var(--text)}
.banner{padding:10px 14px;border-radius:8px;margin-bottom:14px;font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px}
.banner-good{background:var(--good-bg);color:var(--good);border:1px solid var(--good-line)}
.banner-bad{background:var(--bad-bg);color:var(--bad);border:1px solid var(--bad-line)}
.banner-warn{background:var(--warn-bg);color:var(--warn);border:1px solid var(--warn-line)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font:13px/1.6 "Fira Code",ui-monospace,monospace;background:var(--code-bg);border:1px solid var(--line);border-radius:8px;padding:14px;color:var(--text)}
.copy-row{display:flex;justify-content:flex-end;margin-bottom:8px}
.btn-copy{background:var(--panel-subtle);border:1px solid var(--line);color:var(--muted);border-radius:5px;padding:4px 9px;font-size:11.5px;font-weight:600;cursor:pointer}
.btn-copy:hover{color:var(--text);border-color:var(--accent)}
.score-box{display:flex;align-items:baseline;gap:12px;margin-bottom:6px}
.score{font-size:32px;font-weight:800;color:var(--accent)}
.score-label{font-size:14px;font-weight:700;text-transform:uppercase;padding:3px 8px;border-radius:5px;background:var(--accent-subtle);color:var(--accent)}
.issue{padding:10px 12px;border-left:4px solid var(--warn);background:var(--warn-bg);margin:8px 0;border-radius:0 6px 6px 0;font-size:13px}
.issue.error{border-left-color:var(--bad);background:var(--bad-bg)}
.complexity-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:14px}
.comp-card{background:var(--panel-subtle);border:1px solid var(--line-subtle);border-radius:8px;padding:10px;text-align:center}
.comp-val{font-size:18px;font-weight:800;color:var(--accent)}
.comp-lbl{font-size:11px;color:var(--muted);text-transform:uppercase;margin-top:2px}
@media(max-width:860px){.stepper{grid-template-columns:repeat(4,1fr)}}
@media(max-width:540px){.stepper{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<header>
  <div class="brand">
    <h1 class="brand-title">Query Forge <span class="brand-badge">Compiler Design · 24BCE0814</span></h1>
    <p>Comprehensive compiler pipeline: Lexical Token Breakdown, Syntax, Semantic, AST, Optimization, CodeGen & Static Review</p>
  </div>
  <div class="header-actions">
    <button id="theme_toggle" type="button" class="btn-theme" aria-label="Toggle theme">
      <span id="theme_icon">☀️</span> <span id="theme_label">Light Mode</span>
    </button>
  </div>
</header>

<main>
  <section class="editor">
    <div class="section-title">
      <span>SQL Query Input</span>
      <span id="stmt_badge" class="brand-badge">SELECT QUERY</span>
    </div>
    <div class="examples-bar">
      <button type="button" class="chip" data-sql="SELECT s.student_id, s.name, c.course_name FROM Student s JOIN Enrollment e ON s.student_id = e.student_id JOIN Course c ON e.course_id = c.course_id WHERE s.age >= 20;">📌 SELECT with JOIN</button>
      <button type="button" class="chip" data-sql="INSERT INTO Student (student_id, name, age, department_id) VALUES (105, 'John Doe', 21, 2);">📌 INSERT Query</button>
      <button type="button" class="chip" data-sql="UPDATE Student SET age = age + 1 WHERE department_id = 1 AND age > 20 AND age > 20;">📌 UPDATE Query (with Opt)</button>
      <button type="button" class="chip" data-sql="DELETE FROM Enrollment WHERE grade = 'F' AND student_id = 99;">📌 DELETE Query</button>
      <button type="button" class="chip" data-sql="CREATE TABLE IF NOT EXISTS Teachers (teacher_id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, salary FLOAT);">📌 CREATE TABLE</button>
      <button type="button" class="chip" data-sql="DROP TABLE IF EXISTS TempAuditLog;">📌 DROP TABLE</button>
    </div>
    <textarea id="sql" spellcheck="false">SELECT s.student_id, s.name, c.course_name FROM Student s JOIN Enrollment e ON s.student_id = e.student_id JOIN Course c ON e.course_id = c.course_id WHERE s.age >= 20;</textarea>
    <div class="editor-controls">
      <button id="run" class="btn-primary" type="button">⚡ Analyze Query</button>
      <span id="status"></span>
    </div>
  </section>

  <nav id="pipeline_stepper" class="stepper" aria-label="Compiler pipeline phases"></nav>

  <section id="results" hidden>
    <!-- Phase 1: Lexical Analysis -->
    <article id="phase1" class="card phase-card">
      <div class="phase-header">
        <h2 class="phase-title"><span class="phase-num">1</span> Phase 1: Lexical Analysis (Scanner & Token Breakdown)</h2>
        <span id="tokens_total_pill" class="pill"><b>0</b> Tokens Scanned</span>
      </div>
      <p class="phase-desc">Scans characters into discrete lexical tokens (lexemes) with assigned category, line, and column coordinates.</p>
      <div id="tokens_meta" class="tokens-meta"></div>
      <div id="token_filters" class="filter-bar"></div>
      <div class="table-wrap">
        <div id="tokens_container"></div>
      </div>
    </article>

    <!-- Phase 2: Syntax Analysis -->
    <article id="phase2" class="card phase-card">
      <div class="phase-header">
        <h2 class="phase-title"><span class="phase-num">2</span> Phase 2: Syntax Analysis (Parser & Parse Tree)</h2>
      </div>
      <p class="phase-desc">Validates stream of tokens against grammar production rules and constructs the concrete parse tree derivation.</p>
      <div id="syntax_status" class="banner banner-good"></div>
      <div class="copy-row">
        <button id="copy_tree" class="btn-copy" type="button">Copy Parse Tree</button>
      </div>
      <pre id="tree"></pre>
    </article>

    <!-- Phase 3: Semantic Analysis -->
    <article id="phase3" class="card phase-card">
      <div class="phase-header">
        <h2 class="phase-title"><span class="phase-num">3</span> Phase 3: Semantic Analysis & Symbol Verification</h2>
      </div>
      <p class="phase-desc">Resolves table/column identifiers against schema.json symbol definitions, validates ambiguities, and checks constraints.</p>
      <div id="semantic_status" class="banner banner-good"></div>
      <div id="diagnostics"></div>
    </article>

    <!-- Phase 4: Intermediate Representation (AST) -->
    <article id="phase4" class="card phase-card">
      <div class="phase-header">
        <h2 class="phase-title"><span class="phase-num">4</span> Phase 4: Intermediate Representation (Abstract Syntax Tree)</h2>
        <span id="ast_badge" class="brand-badge">AST</span>
      </div>
      <p class="phase-desc">Constructs the normalized Abstract Syntax Tree (AST) representing semantic operations without surface punctuation.</p>
      <div class="copy-row">
        <button id="copy_ast" class="btn-copy" type="button">Copy AST JSON</button>
      </div>
      <pre id="ast"></pre>
    </article>

    <!-- Phase 5: Code Optimization -->
    <article id="phase5" class="card phase-card">
      <div class="phase-header">
        <h2 class="phase-title"><span class="phase-num">5</span> Phase 5: Code Optimization (Target / Query Optimizer)</h2>
      </div>
      <p class="phase-desc">Applies rule-based algebraic simplifications (such as deduplication of deterministic WHERE conjuncts).</p>
      <div id="optimizations"></div>
      <pre id="optimized_sql" style="margin-top:10px"></pre>
    </article>

    <!-- Phase 6: Code Generation -->
    <article id="phase6" class="card phase-card">
      <div class="phase-header">
        <h2 class="phase-title"><span class="phase-num">6</span> Phase 6: Code Generation (Target SQL Synthesis)</h2>
      </div>
      <p class="phase-desc">Synthesizes standardized canonical target SQL with structured indentation and normalized keyword capitalization.</p>
      <div class="copy-row">
        <button id="copy_formatted" class="btn-copy" type="button">Copy SQL</button>
      </div>
      <pre id="formatted"></pre>
    </article>

    <!-- Phase 7: Static Quality Review & Metrics -->
    <article id="phase7" class="card phase-card">
      <div class="phase-header">
        <h2 class="phase-title"><span class="phase-num">7</span> Phase 7: Code Review, Quality Metrics & Complexity</h2>
      </div>
      <p class="phase-desc">Performs heuristic quality review, computes relational complexity metrics, and flags code smells.</p>
      <div class="score-box">
        <div id="score" class="score"></div>
        <div id="score_label" class="score-label"></div>
      </div>
      <div id="score_basis" class="muted" style="margin-bottom:12px;font-size:12.5px"></div>
      <div id="deductions" style="margin-bottom:14px"></div>
      <div id="complexity_metrics" class="complexity-grid"></div>
      <div id="smells"></div>
      <div class="section-title" style="margin-top:16px"><span>Detailed Review Report</span></div>
      <pre id="report"></pre>
    </article>
  </section>
</main>

<script>
const $ = id => document.getElementById(id);
const pretty = x => JSON.stringify(x, null, 2);

let CURRENT_TOKENS = [];
let CURRENT_TOKEN_FILTER = 'ALL';

function initTheme() {
  const saved = localStorage.getItem('query_forge_theme');
  const prefersLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
  const current = saved || (prefersLight ? 'light' : 'dark');
  applyTheme(current);
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('query_forge_theme', theme);
  const isLight = theme === 'light';
  $('theme_icon').textContent = isLight ? '🌙' : '☀️';
  $('theme_label').textContent = isLight ? 'Dark Mode' : 'Light Mode';
}

$('theme_toggle').addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(current === 'light' ? 'dark' : 'light');
});

document.querySelectorAll('.chip').forEach(btn => {
  btn.addEventListener('click', () => {
    $('sql').value = btn.getAttribute('data-sql') || '';
    analyze();
  });
});

function copyToClipboard(targetId, btnId) {
  const text = $(targetId).textContent;
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    const btn = $(btnId);
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  });
}
$('copy_ast').addEventListener('click', () => copyToClipboard('ast', 'copy_ast'));
$('copy_tree').addEventListener('click', () => copyToClipboard('tree', 'copy_tree'));
$('copy_formatted').addEventListener('click', () => copyToClipboard('formatted', 'copy_formatted'));

function getClassification(kind, value) {
  if (kind === 'KEYWORD') return { label: 'Keyword', cls: 'badge-kw', desc: 'SQL Reserved Keyword' };
  if (kind === 'IDENT') return { label: 'Identifier', cls: 'badge-ident', desc: 'Table or Column Identifier' };
  if (kind === 'OP') return { label: 'Operator', cls: 'badge-op', desc: 'Arithmetic / Comparison Operator' };
  if (kind === 'NUMBER') return { label: 'Number', cls: 'badge-lit', desc: 'Numeric Constant' };
  if (kind === 'STRING') return { label: 'String', cls: 'badge-lit', desc: 'String Literal' };
  if (kind === 'PUNCT') return { label: 'Punctuation', cls: 'badge-punct', desc: 'Syntactic Delimiter / Punctuation' };
  return { label: kind, cls: 'badge-punct', desc: 'Token' };
}

function renderTokenTable() {
  const container = $('tokens_container');
  container.textContent = '';
  const filtered = CURRENT_TOKENS.filter(t => {
    if (CURRENT_TOKEN_FILTER === 'ALL') return true;
    if (CURRENT_TOKEN_FILTER === 'KEYWORD') return t.kind === 'KEYWORD';
    if (CURRENT_TOKEN_FILTER === 'IDENT') return t.kind === 'IDENT';
    if (CURRENT_TOKEN_FILTER === 'OP') return t.kind === 'OP';
    if (CURRENT_TOKEN_FILTER === 'LITERAL') return t.kind === 'NUMBER' || t.kind === 'STRING';
    if (CURRENT_TOKEN_FILTER === 'PUNCT') return t.kind === 'PUNCT';
    return true;
  });

  const table = document.createElement('table');
  table.className = 'token-table';
  const thead = document.createElement('thead');
  const trH = document.createElement('tr');
  ['#', 'Token Kind', 'Lexeme / Value', 'Position', 'Classification'].forEach(h => {
    const th = document.createElement('th');
    th.textContent = h;
    trH.appendChild(th);
  });
  thead.appendChild(trH);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  filtered.forEach((t, i) => {
    const tr = document.createElement('tr');
    const tdIdx = document.createElement('td');
    tdIdx.className = 'muted';
    tdIdx.textContent = String(i + 1);
    tr.appendChild(tdIdx);

    const tdKind = document.createElement('td');
    const badge = document.createElement('span');
    const info = getClassification(t.kind, t.value);
    badge.className = 'token-badge ' + info.cls;
    badge.textContent = t.kind;
    tdKind.appendChild(badge);
    tr.appendChild(tdKind);

    const tdVal = document.createElement('td');
    const code = document.createElement('code');
    code.className = 'token-code';
    code.textContent = t.value;
    tdVal.appendChild(code);
    tr.appendChild(tdVal);

    const tdPos = document.createElement('td');
    tdPos.className = 'muted';
    tdPos.textContent = `L${t.line}:C${t.column}`;
    tr.appendChild(tdPos);

    const tdDesc = document.createElement('td');
    tdDesc.textContent = info.desc;
    tr.appendChild(tdDesc);

    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);
}

function renderTokenControls(tokens) {
  CURRENT_TOKENS = tokens || [];
  $('tokens_total_pill').textContent = `${CURRENT_TOKENS.length} Tokens Scanned`;

  const metaBox = $('tokens_meta');
  metaBox.textContent = '';
  const counts = {
    keywords: CURRENT_TOKENS.filter(t => t.kind === 'KEYWORD').length,
    idents: CURRENT_TOKENS.filter(t => t.kind === 'IDENT').length,
    ops: CURRENT_TOKENS.filter(t => t.kind === 'OP').length,
    lits: CURRENT_TOKENS.filter(t => t.kind === 'NUMBER' || t.kind === 'STRING').length,
    puncts: CURRENT_TOKENS.filter(t => t.kind === 'PUNCT').length,
  };

  const createPill = (label, count) => {
    const p = document.createElement('span');
    p.className = 'pill';
    const b = document.createElement('b');
    b.textContent = String(count);
    p.appendChild(b);
    p.appendChild(document.createTextNode(' ' + label));
    return p;
  };
  metaBox.appendChild(createPill('Keywords', counts.keywords));
  metaBox.appendChild(createPill('Identifiers', counts.idents));
  metaBox.appendChild(createPill('Operators', counts.ops));
  metaBox.appendChild(createPill('Literals', counts.lits));
  metaBox.appendChild(createPill('Punctuation', counts.puncts));

  const filterBar = $('token_filters');
  filterBar.textContent = '';
  const filters = [
    ['ALL', `All (${CURRENT_TOKENS.length})`],
    ['KEYWORD', `Keywords (${counts.keywords})`],
    ['IDENT', `Identifiers (${counts.idents})`],
    ['OP', `Operators (${counts.ops})`],
    ['LITERAL', `Literals (${counts.lits})`],
    ['PUNCT', `Punctuation (${counts.puncts})`]
  ];
  filters.forEach(([key, label]) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'filter-btn' + (CURRENT_TOKEN_FILTER === key ? ' active' : '');
    btn.textContent = label;
    btn.addEventListener('click', () => {
      CURRENT_TOKEN_FILTER = key;
      renderTokenControls(CURRENT_TOKENS);
    });
    filterBar.appendChild(btn);
  });

  renderTokenTable();
}

function renderStepper(d) {
  const stepper = $('pipeline_stepper');
  stepper.textContent = '';
  const hasSyntaxErr = d.diagnostics.some(x => x.phase === 'syntax');
  const hasSemanticErr = d.diagnostics.some(x => x.phase === 'semantic' && x.severity === 'error');

  const steps = [
    { id: 'phase1', num: '1', title: 'Lexical', status: d.tokens.length > 0 ? 'ok' : 'err' },
    { id: 'phase2', num: '2', title: 'Syntax', status: d.ast ? 'ok' : (hasSyntaxErr ? 'err' : 'ok') },
    { id: 'phase3', num: '3', title: 'Semantic', status: hasSemanticErr ? 'err' : 'ok' },
    { id: 'phase4', num: '4', title: 'AST', status: d.ast ? 'ok' : 'err' },
    { id: 'phase5', num: '5', title: 'Optimize', status: 'ok' },
    { id: 'phase6', num: '6', title: 'CodeGen', status: d.formatted_sql ? 'ok' : 'err' },
    { id: 'phase7', num: '7', title: 'Review', status: d.ok ? 'ok' : 'err' }
  ];

  steps.forEach(s => {
    const div = document.createElement('div');
    div.className = 'step-item' + (s.status === 'err' ? ' step-error' : '');
    div.textContent = `${s.num}. ${s.title}`;
    div.addEventListener('click', () => {
      const target = $(s.id);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    stepper.appendChild(div);
  });
}

function renderIssues(targetId, items, emptyText) {
  const container = $(targetId);
  container.textContent = '';
  if (!items || items.length === 0) {
    const span = document.createElement('span');
    span.className = 'muted';
    span.textContent = emptyText;
    container.appendChild(span);
    return;
  }
  for (const item of items) {
    const div = document.createElement('div');
    div.className = 'issue' + (item.severity === 'error' ? ' error' : '');
    const bold = document.createElement('b');
    bold.textContent = (item.severity || 'INFO').toUpperCase();
    div.appendChild(bold);
    div.appendChild(document.createTextNode(' ' + (item.message || '')));
    container.appendChild(div);
  }
}

function renderOptimizations(targetId, sqlTargetId, optimizations, optimizedSql) {
  const container = $(targetId);
  container.textContent = '';
  const sqlEl = $(sqlTargetId);
  if (!optimizations || optimizations.length === 0) {
    const span = document.createElement('span');
    span.className = 'muted';
    span.textContent = 'No applicable optimizations (WHERE predicates are already minimal or non-deterministic).';
    container.appendChild(span);
    sqlEl.textContent = 'No rewrite performed.';
    return;
  }
  for (const opt of optimizations) {
    const div = document.createElement('div');
    div.className = 'issue';
    const bold = document.createElement('b');
    bold.textContent = 'OPTIMIZATION';
    div.appendChild(bold);
    div.appendChild(document.createTextNode(' ' + opt));
    container.appendChild(div);
  }
  sqlEl.textContent = optimizedSql || '';
}

function renderComplexity(targetId, comp) {
  const container = $(targetId);
  container.textContent = '';
  if (!comp) return;

  const addCard = (label, val) => {
    const card = document.createElement('div');
    card.className = 'comp-card';
    const v = document.createElement('div');
    v.className = 'comp-val';
    v.textContent = String(val);
    const l = document.createElement('div');
    l.className = 'comp-lbl';
    l.textContent = label;
    card.appendChild(v);
    card.appendChild(l);
    container.appendChild(card);
  };

  addCard('Complexity Tier', (comp.level || 'LOW').toUpperCase());
  if (comp.statement) addCard('Query Type', comp.statement);
  if (comp.tables !== undefined) addCard('Tables', comp.tables);
  if (comp.joins !== undefined) addCard('Joins', comp.joins);
  if (comp.conditions !== undefined) addCard('Conditions', comp.conditions);
  if (comp.rows !== undefined) addCard('Rows', comp.rows);
  if (comp.columns !== undefined) addCard('Columns', comp.columns);
  if (comp.nested_queries !== undefined) addCard('Nested Queries', comp.nested_queries);
}

function renderDeductions(targetId, deductions) {
  const container = $(targetId);
  container.textContent = '';
  if (!deductions || deductions.length === 0) return;
  const title = document.createElement('div');
  title.style.fontWeight = '700';
  title.style.fontSize = '13px';
  title.style.marginBottom = '4px';
  title.textContent = 'Score Breakdown:';
  container.appendChild(title);
  deductions.forEach(d => {
    const line = document.createElement('div');
    line.className = 'muted';
    line.style.fontSize = '12.5px';
    line.textContent = '• ' + d;
    container.appendChild(line);
  });
}

async function analyze() {
  $('status').textContent = 'Analyzing…';
  try {
    const r = await fetch('/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql: $('sql').value })
    });
    const d = await r.json();
    $('results').hidden = false;

    const stmtType = d.statement_type || 'SQL';
    $('stmt_badge').textContent = stmtType + ' STATEMENT';
    $('ast_badge').textContent = stmtType + ' AST';

    // Phase 1: Tokens
    renderTokenControls(d.tokens);

    // Phase 2: Syntax
    const synEl = $('syntax_status');
    synEl.textContent = '';
    if (d.ast) {
      synEl.className = 'banner banner-good';
      synEl.textContent = `✓ Grammar Accepted: Valid ${stmtType} statement conforming to grammar rules.`;
    } else {
      synEl.className = 'banner banner-bad';
      const synErr = d.diagnostics.find(x => x.phase === 'syntax' || x.phase === 'lexical');
      synEl.textContent = `✗ Syntax Error: ${synErr ? synErr.message : 'Parser stopped on unexpected syntax'}.`;
    }
    $('tree').textContent = d.parse_tree ? pretty(d.parse_tree) : 'Parse tree unavailable: parsing halted on syntax error.';

    // Phase 3: Semantic
    const semEl = $('semantic_status');
    semEl.textContent = '';
    const semErrors = d.diagnostics.filter(x => x.phase === 'semantic' && x.severity === 'error');
    if (semErrors.length === 0 && d.ok) {
      semEl.className = 'banner banner-good';
      semEl.textContent = '✓ Schema Verification Passed: All table/column bindings resolved successfully against schema.json.';
    } else if (semErrors.length > 0) {
      semEl.className = 'banner banner-bad';
      semEl.textContent = `✗ Schema Validation Failed: ${semErrors.length} semantic error(s) detected.`;
    } else {
      semEl.className = 'banner banner-warn';
      semEl.textContent = '! Schema Verification: Analysis incomplete due to earlier phase errors.';
    }
    renderIssues('diagnostics', d.diagnostics, 'No diagnostic errors detected.');

    // Phase 4: AST
    $('ast').textContent = d.ast ? pretty(d.ast) : 'AST unavailable: an earlier phase reported an error.';

    // Phase 5: Optimization
    renderOptimizations('optimizations', 'optimized_sql', d.optimizations, d.optimized_sql);

    // Phase 6: CodeGen (Formatted)
    $('formatted').textContent = d.formatted_sql || 'Target SQL synthesis is unavailable until parsing succeeds.';

    // Phase 7: Review & Metrics
    $('score').textContent = `${d.quality_score.score}/100`;
    $('score_label').textContent = (d.quality_score.label || 'needs review').toUpperCase();
    $('score_basis').textContent = d.quality_score.basis || '';
    renderDeductions('deductions', d.quality_score.deductions);
    renderComplexity('complexity_metrics', d.complexity);
    renderIssues('smells', d.code_smells, 'No code smells detected.');
    $('report').textContent = d.report;

    // Pipeline Stepper
    renderStepper(d);

    $('status').textContent = d.ok ? 'Analysis complete (all phases successful)' : 'Analysis completed with diagnostics';
  } catch (e) {
    $('status').textContent = 'Could not reach the local analyzer.';
  }
}

$('run').addEventListener('click', analyze);
initTheme();
analyze();
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlparse(self.path).path != "/":
            self.send_error(404)
            return
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/analyze":
            self.send_error(404)
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 1_000_000)
            payload = json.loads(self.rfile.read(length))
            sql = payload.get("sql", "")
            if not isinstance(sql, str):
                raise ValueError("SQL must be a string.")
            report = analyze_query(sql, SCHEMA)
            body = json.dumps(report).encode()
            self.send_response(200)
        except (ValueError, json.JSONDecodeError) as exc:
            body = json.dumps({"error": str(exc)}).encode()
            self.send_response(400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("[Query Forge] " + fmt % args)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Query Forge running at http://127.0.0.1:8000 — press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
