# Solution — Translation Tool (TT)

## What the TT does

The TT is a TypeScript -> Python translator built as a classical compiler
pipeline in pure Python (standard library only). Given a TS source file and
a Python "stub" file that exposes the same class interface, it produces a
Python file where as many methods as possible are translated from the TS,
while methods the pipeline cannot (yet) handle keep the stub's original
implementation.

Pipeline (per TS file):

1. **Preprocess** (`tt/preprocess.py`) — strip TS-only syntax (type
   annotations, generics, `interface`/`type` decls, access modifiers, `as`
   casts, `!` non-null assertions) so the parser only has to handle ES2020.
2. **Lex** (`tt/lexer.py`) — hand-rolled tokenizer producing `Token(kind,
   value, pos)`: numbers, strings, template literals, identifiers, keywords,
   punctuation, operators.
3. **Parse** (`tt/parser.py`, `tt/ast_nodes.py`) — recursive-descent parser
   that builds typed AST nodes. Unknown constructs fail softly: the affected
   method is recorded as "untranslatable" instead of aborting the whole run.
4. **Emit** (`tt/emitter.py`) — visits AST nodes and produces Python source
   for one method at a time, already indented for a class body. Emission
   consults the scaffold-specific `tt_import_map.json` to rewrite
   JS-library calls (`big.js`, `date-fns`, `lodash`) into calls against
   pure-Python shim modules.
5. **Merge** (`tt/merger.py`) — parses the stub with Python's own `ast`
   module, locates each translated method by name, and splices the
   translated source into the stub file. Untouched methods keep their
   original bytes; imports emitted during translation are deduplicated and
   inserted after the `from __future__` line.

An overlay step (`tt/runner.py`) drops project-specific support modules
("shims": e.g. `bigjs`, `datefns`, `lodashish`) into
`<output>/app/implementation/_support/` before emission.

## Why this design

- **Generic core + project-specific scaffold.** The code in `tt/tt/*.py`
  contains no project strings (class names, library identifiers, etc.).
  All project knowledge lives in `tt/tt/scaffold/<scaffold_name>/` —
  `tt_import_map.json`, `sources.json` and the `shims/` directory. The
  scaffold is discovered automatically when exactly one exists, so the CLI
  works without flags. This cleanly satisfies the competition rule
  prohibiting project-specific logic in the TT core.
- **AST-based, not regex-based.** Regex translation bottoms out very
  quickly for real code. A proper AST gives us accurate scope tracking,
  per-method isolation, and a principled place to hang the library-mapping
  rules.
- **Stub fallback.** The merger never deletes a stub method it cannot
  replace. If parsing fails, the emitter errors, or merging encounters a
  problem, the output file remains a valid, importable stub. This is the
  baseline-guarantee the hackathon scoring model rewards: we cannot
  regress, only improve.
- **No external deps.** Pure-Python stdlib only — no `tree-sitter`, no
  `node`, no LLMs. Dev tooling keeps `pytest`.

## What it handles / what it doesn't

Handled:
- `export class X extends Y { … }` class shapes, methods, constructors,
  fields with initializers.
- Statements: blocks, `if`/`else`, `for (… of …)`, C-style `for`, `while`,
  `return`, `throw`, `try/catch`, variable decls, expression statements.
- Expressions: binary/unary/assignment ops, calls, member/index access,
  `new`, arrow functions, conditionals, template literals, array and
  object literals, simple destructuring, spread.
- Automatic rewrites via `tt_import_map.json`:
  - `new Big(x)`  -> `Big(x)`  (shim-backed by `decimal.Decimal`)
  - `a.plus(b)`   -> `a + b`   (method -> operator rules)
  - `sortBy(arr, k)` -> `sorted(arr, key=k)`
  - `format(d, 'yyyy-MM-dd')` -> `_date_format(d, 'yyyy-MM-dd')`
  - `null`/`undefined`/`true`/`false` -> `None`/`None`/`True`/`False`
- Import rewrites (e.g. `from big.js import Big` ->
  `from app.implementation._support.bigjs import Big`).

Not handled (left as stub or logged as "failed"):
- Decorators, namespaces, module augmentation.
- Generators, `async`/`await` (parser flags these; emitter bails).
- Complex destructuring with defaults and nested patterns.
- Dynamic imports.
- Any method whose parse throws — isolation keeps it from breaking peers.

## How to run

```sh
make evaluate_tt_ghostfolio               # translate + test + score
make translate-and-test-ghostfolio_pytx   # faster loop
make detect_rule_breaches                 # verify rule compliance
make scoring_codequality                  # pyscn health score
make publish_results                      # submit to the live dashboard
```

Directly:

```sh
python -m tt translate
```

The CLI auto-detects the scaffold. Override with
`python -m tt translate --scaffold <name>` if multiple scaffolds exist.

## Repository layout (relevant subset)

```
tt/tt/
  cli.py             # argparse entrypoint, scaffold auto-detect
  runner.py          # pipeline orchestration, stub overlay, shim copy
  preprocess.py      # strip TS-only syntax
  lexer.py           # tokenizer
  parser.py          # recursive-descent -> AST
  ast_nodes.py       # AST dataclasses
  emitter.py         # AST -> Python source + collected imports
  merger.py          # splice translated methods into stub file
  translator.py      # backwards-compat shim (delegates to runner)
  scaffold/
    <scaffold_name>/
      tt_import_map.json
      sources.json
      shims/*.py
```
