# TREEQL Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give TREEQL a reader, so the language duckent prints is also a language duckent parses — and `tree_catalog.selector_languages.parser` stops being NULL for the `treeql` row.

**Architecture:** A pure-SQL macro parser in `sql/10_treeql.sql`, built bottom-up: a quote- and paren-aware splitter, then a clause reader, then a step reader, then IR assembly with canonical pre-order numbering, with groups unrolled to `tree_group_depth_limit()` exactly as the printer unrolls them. An independent, database-free Python reference parser in `test/` is bound to it by a differential. Both vocabularies — clause kinds and combinators — are read from the catalog, never restated.

**Tech Stack:** DuckDB 1.5.5 SQL macros; `test/run.py` sqllogictest-style runner; `test/run_mutants.py`; Python 3 for the reference parser.

**Spec:** `docs/superpowers/specs/2026-10-18-duckent-treeql-reader-design.md`

## Global Constraints

- **The printer is the specification.** Everything this parser accepts is defined by what `tree_selector_to_treeql` emits. Where the two could disagree, the printer is right and the parser is wrong.
- **Two theorems.** Exact on canonical IR: `parse(print(ir)) == ir`, node ids included. Normalising on everything else: `parse(print(ir))` is the canonical renumbering, and `print(parse(print(ir))) == print(ir)` byte for byte.
- **Tolerant input, canonical output.** Whitespace and keyword case are free; bare identifiers are accepted (D-N15); the printer's output is unchanged.
- **Both vocabularies come from the catalog.** `tree_catalog.clause_kinds` and `tree_catalog.combinators`. No list of kinds or combinator keywords may appear in any file this plan touches. `scripts/check_vocabulary_single_source.py` enforces this and its exemption table is not to be edited — if it fires, the site is wrong.
- **DuckDB 1.5.5.** Baseline `260d272`. **A subquery is illegal anywhere inside an expression that carries a lambda**, and macro inlining defeats indirection — so a macro that queries the catalog cannot be called from inside a `list_transform`. If you hit this, STOP and report; do not rewrite a core macro on your own initiative.
- **A macro parameter must not share a name with a column of a table the macro queries** (`kind` against `clause_kinds.kind` is a Binder Error; `macro_name.kind` is not an accepted spelling). Colliding parameters are named `want_*`.
- **`sql/00_types.sql` … `sql/08_traversal.sql` are embedded byte-identically by the extension.** `sql/10_treeql.sql` is a NEW embedded file: the extension's `extension_config.cmake` and embed step must learn it, which is Task 8's concern, not yours.
- **Groups unroll to `tree_group_depth_limit()` (2), never recurse.** Deeper nesting is refused, reusing the printer's wording. DuckDB macros cannot self-recurse.
- **Every gate must be shown to fail.** The step that adds a gate also breaks what it guards and records the observed failure. The slot engine shipped four gates that passed while covering less than they claimed; one was blind to exactly the inputs it policed.
- **Verification is three commands, not one.** `python3 test/run.py test/sql` AND `python3 test/run_mutants.py` AND `python3 scripts/check_vocabulary_single_source.py`. They are separate entry points; four times in the slot engine an edit broke one while the others stayed green. **This machine is short on memory: batch long runs, and never infer success from empty output — check exit status and that a summary line printed.**

---

### Task 1: The splitter

**Files:**
- Create: `sql/10_treeql.sql`
- Test: `test/sql/48_treeql_parse.test` (create)

**Interfaces:**
- Produces: `tree_treeql_split(s, sep) AS TABLE (ord INTEGER, part VARCHAR)` — splits `s` on `sep` at paren depth 0, outside single quotes, trimming each part.
- Consumes: nothing.

This is the one piece whose feasibility was in doubt, so it was spiked before the design was accepted. The code below is the spike, promoted and verified on `260d272` — use it as given.

- [ ] **Step 1: Write the failing test**

Create `test/sql/48_treeql_parse.test`:

```
# name: test/sql/48_treeql_parse.test
# description: The TREEQL reader -- the text form of TREEQL, read back. parse(print(ir)) == ir on canonical IR.

# THE SEPARATORS OCCUR INSIDE CLAUSE BODIES, which is why this needs a tokenizer and not a split.
# ATTR and WHERE bodies are emitted unquoted and unescaped by the printer, so a clause list can
# contain ", " and ")" that are not structure. Each case below is one a naive split gets wrong.
query II
SELECT ord, part FROM tree_treeql_split('TYPE ''x'', WHERE name IN (''a'', ''b'')', ',') ORDER BY ord;
----
1	TYPE 'x'
2	WHERE name IN ('a', 'b')

query II
SELECT ord, part FROM tree_treeql_split('ATTR lang = ''p)y''', ',') ORDER BY ord;
----
1	ATTR lang = 'p)y'

# a comma-SPACE inside a quoted literal: the case that discriminates against a split on ', '
query II
SELECT ord, part FROM tree_treeql_split('TYPE ''a, b'', PSEUDO ''p''', ',') ORDER BY ord;
----
1	TYPE 'a, b'
2	PSEUDO 'p'

# the doubled-quote escape, which parity handles for free
query II
SELECT ord, part FROM tree_treeql_split('TYPE ''it''''s, ok'', PSEUDO ''p''', ',') ORDER BY ord;
----
1	TYPE 'it''s, ok'
2	PSEUDO 'p'

# a group is ONE part, however many commas it contains
query II
SELECT ord, part FROM tree_treeql_split('TYPE ''f'', HAS ( (TYPE ''b'', PSEUDO ''q'') )', ',') ORDER BY ord;
----
1	TYPE 'f'
2	HAS ( (TYPE 'b', PSEUDO 'q') )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 test/run.py test/sql/48_treeql_parse.test`
Expected: FAIL — `Catalog Error: Table Function with name tree_treeql_split does not exist!`

- [ ] **Step 3: Write `sql/10_treeql.sql` with the splitter**

```sql
-- sql/10_treeql.sql
--
-- The TREEQL reader. Reads the text form of TREEQL. The printer (sql/06_selector.sql) is the specification --
-- everything here accepts is defined by what tree_selector_to_treeql emits, and where the two
-- could disagree the printer is right.
--
-- WHY THIS FILE EXISTS. tree_catalog.selector_languages held ('treeql', NULL, ...) since M0: the
-- language the IR is named after could be printed and not read. Three things made that
-- structural rather than inconvenient -- doc 14 §2k made TREEQL the DEFAULT dialect, css's own
-- refusal directs authors to TREEQL text, and the slot engine added PARENT, ANCESTOR and
-- PRECEDING, which with the host door is four constructs reachable only through TREEQL.
--
-- WHY IT IS MACROS. The extension embeds sql/*.sql byte-identically and its global constraint is
-- that the C++ decides nothing about trees. A macro parser ships there with no C++.

-- A clause list split on `sep` at paren depth 0 and outside single quotes.
--
-- THE SEPARATORS OCCUR INSIDE THE BODIES. The printer emits ATTR and WHERE bodies unquoted and
-- unescaped, so `(TYPE 'x', WHERE name IN ('a', 'b'))` contains a ", " that is not a separator
-- and a ")" that is not the step's. A split on ', ' mis-parses it, and so do the other cases in
-- 48_treeql_parse.test.
--
-- "Inside a quote" is the PARITY of quote characters strictly before a position, which is what
-- makes the '' escape free: two quotes restore the parity. Paren depth is a second window over
-- the column the first produced, which needs its own CTE -- window functions do not nest.
CREATE OR REPLACE MACRO tree_treeql_split(s, sep) AS TABLE (
  WITH chars AS (SELECT i, s[i:i] AS c FROM generate_series(1, length(s)) t(i)),
  quoted AS (
    SELECT i, c,
           (COALESCE(sum(CASE WHEN c = '''' THEN 1 ELSE 0 END)
              OVER (ORDER BY i ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) % 2) = 1 AS inq
    FROM chars),
  depthed AS (
    SELECT i, c, inq,
           sum(CASE WHEN inq THEN 0 WHEN c = '(' THEN 1 WHEN c = ')' THEN -1 ELSE 0 END)
             OVER (ORDER BY i) AS depth
    FROM quoted),
  seps AS (SELECT i FROM depthed WHERE c = sep AND NOT inq AND depth = 0),
  bounds AS (SELECT 0 AS lo UNION ALL SELECT i FROM seps),
  spans AS (
    SELECT lo + 1 AS lo,
           COALESCE((SELECT min(i) FROM seps WHERE i > b.lo), length(s) + 1) - 1 AS hi
    FROM bounds b)
  SELECT row_number() OVER (ORDER BY lo) AS ord, trim(s[lo:hi]) AS part FROM spans ORDER BY lo);
```

Add `sql/10_treeql.sql` to whatever loads `sql/*.sql` — `test/run.py` globs the directory, so nothing to do there; confirm by running the test.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 test/run.py test/sql/48_treeql_parse.test`
Expected: PASS, 5 assertions.

- [ ] **Step 5: Prove the cases discriminate**

In a scratch Python session, run each of the five inputs through a naive `string_split(s, ', ')` and record which produce the wrong answer. At least three must. A case a naive split also gets right proves nothing about the tokenizer and should be replaced with one that does. Record the per-case result in your report.

- [ ] **Step 6: Run the suite and the other two gates**

Run, batched: `python3 test/run.py test/sql`; then `python3 test/run_mutants.py`; then `python3 scripts/check_vocabulary_single_source.py`.
Expected: all green. A new file under `sql/` is new input to the lint and to the macro-identity story; if the lint fires on `10_treeql.sql`, the file names a vocabulary it should be reading.

- [ ] **Step 7: Commit**

```bash
git add sql/10_treeql.sql test/sql/48_treeql_parse.test
git commit -m "feat(mlang): a quote- and paren-aware splitter, because the separators are inside the bodies"
```

---

### Task 2: The clause reader

**Files:**
- Modify: `sql/10_treeql.sql`
- Test: `test/sql/48_treeql_parse.test` (append)

**Interfaces:**
- Produces: `tree_treeql_unlit(v)` — strips the printer's single quotes and undoubles `''`; passes a bare identifier through unchanged. `tree_treeql_clause_parse(txt)` — one clause's text to `{kind, value, op, arg}`, or NULL when no registered keyword matches.
- Consumes: `tree_catalog.clause_kinds` (Task 1 of the slot engine).

The code below is verified on `260d272`. Note what it does NOT contain: any list of clause kinds. The keyword and the kind both come from the registry, and only the *body's* shape is per-kind — which mirrors `tree_treeql_clause` in the printer, where the keyword is a registry lookup and the body's rendering is a `CASE`.

- [ ] **Step 1: Write the failing test**

Append to `test/sql/48_treeql_parse.test`:

```
# One clause's text to its IR fields. The KEYWORD is matched from tree_catalog.clause_kinds, so
# this reader learns a new clause kind the day one is registered -- there is no list of kinds here.
query I
SELECT tree_treeql_clause_parse('TYPE ''fn''').kind;
----
type

query I
SELECT tree_treeql_clause_parse('TYPE ''fn''').value;
----
fn

# TOLERANT INPUT: keyword case is free and a bare identifier is accepted (D-N15), while the
# printer goes on emitting the quoted form.
query I
SELECT tree_treeql_clause_parse('type fn').value;
----
fn

# the printer's doubled-quote escape, undone
query I
SELECT tree_treeql_clause_parse('TYPE ''it''''s''').value;
----
it's

# ATTR is the one clause with three fields, and its body is emitted UNQUOTED
query III
SELECT (c).value, (c).op, (c).arg FROM (SELECT tree_treeql_clause_parse('ATTR lang = ''py''') AS c);
----
lang	=	'py'

query III
SELECT (c).value, (c).op, (c).arg FROM (SELECT tree_treeql_clause_parse('ATTR name LIKE ''a%''') AS c);
----
name	LIKE	'a%'

# WHERE is the host door: its body is raw SQL and is carried verbatim
query I
SELECT tree_treeql_clause_parse('WHERE length(name) > 3').value;
----
length(name) > 3

# an unregistered keyword yields NULL, which the refusal arm in Task 5 turns into a message
query I
SELECT tree_treeql_clause_parse('FROBNICATE ''x''') IS NULL;
----
true
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 test/run.py test/sql/48_treeql_parse.test`
Expected: FAIL — `tree_treeql_clause_parse does not exist`.

- [ ] **Step 3: Add the clause reader**

Append to `sql/10_treeql.sql`:

```sql
-- The printer's literal form, undone: '...' with '' for an embedded quote. A bare identifier
-- (D-N15, decided 2026-10-15: accepted on input, never emitted) has no quotes to strip and
-- passes through, which is why the test is on the delimiters and not on the content.
CREATE OR REPLACE MACRO tree_treeql_unlit(v) AS
  CASE WHEN v LIKE '''%''' THEN replace(v[2:length(v)-1], '''''', '''') ELSE v END;

-- One clause's text to its IR fields, or NULL when no registered keyword matches.
--
-- THE KEYWORD AND THE KIND COME FROM tree_catalog.clause_kinds, so this reader gains a clause
-- kind the day one is registered and there is no list of kinds in this file. Only the BODY's
-- shape is per-kind, exactly as tree_treeql_clause renders it: TYPE/ID/CLASS/PSEUDO carry a
-- quoted literal, ATTR carries `name op arg` unquoted, WHERE carries raw host SQL.
--
-- The match is on `upper(keyword) || ' %'` rather than on a prefix, so a keyword is only
-- recognised when followed by a body -- a bare `TYPE` with no operand falls through to NULL and
-- is refused by name in Task 5 rather than parsing to a clause with no value.
CREATE OR REPLACE MACRO tree_treeql_clause_parse(txt) AS (
  WITH t AS (SELECT trim(txt) AS s),
  kw AS (SELECT k.kind, k.keyword,
                trim((SELECT s FROM t)[length(k.keyword) + 2 : ]) AS body
         FROM tree_catalog.clause_kinds k
         WHERE upper((SELECT s FROM t)) LIKE upper(k.keyword) || ' %')
  SELECT CASE
    WHEN (SELECT count(*) FROM kw) = 0 THEN NULL
    ELSE (SELECT {kind: kind,
                  value: CASE kind WHEN 'where' THEN body
                                   WHEN 'attr'  THEN regexp_extract(body, '^([A-Za-z_][A-Za-z0-9_]*)', 1)
                                   ELSE tree_treeql_unlit(body) END,
                  op:    CASE kind WHEN 'attr' THEN trim(regexp_extract(body, '^[A-Za-z_][A-Za-z0-9_]*\s*(=|!=|<>|<=|>=|<|>|LIKE|ILIKE|NOT LIKE)', 1)) END,
                  arg:   CASE kind WHEN 'attr' THEN trim(regexp_extract(body, '^[A-Za-z_][A-Za-z0-9_]*\s*(?:=|!=|<>|<=|>=|<|>|LIKE|ILIKE|NOT LIKE)\s*(.+)$', 1)) END}
          FROM kw) END);
```

- [ ] **Step 4: Run the test, then the three gates**

Run: `python3 test/run.py test/sql/48_treeql_parse.test` — expect PASS.
Then the suite, `run_mutants.py` and the lint, batched.

- [ ] **Step 5: Prove the registry is read, not mirrored**

In a scratch session: load `sql/*.sql`, `DELETE FROM tree_catalog.clause_kinds WHERE kind = 'pseudo'`, then `SELECT tree_treeql_clause_parse('PSEUDO ''def''')`. It must return NULL — the reader no longer knows that keyword. Then register a probe kind and confirm the reader accepts it with no edit to this file. Record both. A reader that still parsed `PSEUDO` after the row was deleted is carrying a private copy.

- [ ] **Step 6: Commit**

```bash
git add sql/10_treeql.sql test/sql/48_treeql_parse.test
git commit -m "feat(mlang): read one clause, with the keyword and kind from the registry"
```

---

### Task 3: The step reader

**Files:**
- Modify: `sql/10_treeql.sql`
- Test: `test/sql/48_treeql_parse.test` (append)

**Interfaces:**
- Produces: `tree_treeql_reserved()` — the reserved-word set as a list, from the catalog. `tree_treeql_step_parse(txt)` — one step's text to `{op, body, alias}`, where `op` is the IR op for the leading combinator keyword (NULL when absent), `body` is the text inside the step's parentheses (NULL when the step has none), and `alias` is the `AS` capture.
- Consumes: `tree_catalog.combinators`, `tree_catalog.clause_kinds`, `tree_sql_is_ident`.

**Contract, from the printer** (`tree_treeql_step`): a step is `rtrim(comb? '(' clauses ')'? (' AS ' alias)?)`. So all three parts are optional, a combinator may appear with no clause list at all (`CHILD` prints bare), and the alias is last.

- [ ] **Step 1: Write the failing test**

Append to `test/sql/48_treeql_parse.test`. Cover, at minimum: a bare clause list; a combinator plus clause list; a combinator alone (which the printer emits); an alias; a combinator with alias and clauses together; keyword case and extra whitespace; the eight registered combinator keywords resolving to their ops; and `tree_treeql_reserved()` returning exactly `clause_kinds.keyword ∪ combinators.keyword ∪ {AS, HAS, NOT}` — **asserted against the registry, not against a literal list**, so the assertion cannot go stale when a combinator is registered.

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Write the step reader**

Requirements the implementer must satisfy, each with its reason:

1. **The combinator keyword is looked up in `tree_catalog.combinators`**, matching `keyword` case-insensitively and yielding `op`. No list of combinator keywords in this file: `PARENT`, `ANCESTOR` and `PRECEDING` were added to the engine as rows with no macro changed, and this reader inherits them the same way.
2. **A combinator keyword the registry does not define is left for Task 5's refusal**, not silently treated as part of the clause list.
3. **The alias is split off before the parentheses are read**, because `AS` may follow `)` and an alias is an identifier — validate it with `tree_sql_is_ident`, the rule `tree_steps` already applies, rather than restating it.
4. **A step with no parentheses is legal** and yields `body = NULL`.
5. **`tree_treeql_reserved()` derives the set** from both registries plus the three structural words. It is the only place that set appears.
6. **The step's clause-list parentheses are OPTIONAL on input** (decided 2026-10-18). `CLASS fn` and `CHILD TYPE block` must parse as `(CLASS 'fn')` and `CHILD (TYPE 'block')` do. With bare identifiers from D-N15, this is what makes TREEQL hand-writable — the reason it is getting a reader at all. The printer is unchanged; this widens the accepted set only.
7. **A GROUP's parentheses are NOT optional.** A group's inner chain is space-separated and the enclosing clause list continues after it, so `HAS CHILD TYPE 'b' PSEUDO 'p'` cannot say whether `PSEUDO 'p'` is the inner step's or the outer's. Refuse a group with no parentheses; do not attempt to infer the boundary.
8. **Within a group, a parenless step is distinguishable only because a clause keyword never begins a step and a combinator keyword always does** — and that holds because the printer emits a combinator for every inner step, even one the constructor omitted (`tree_steps([{type:'f', has:[{type:'b'}]}])` prints `HAS ( DESCENDANT (TYPE 'b') )`). **That invariant is the constructor's, not the grammar's**, and hand-built IR through the host door is not bound by it — so Task 5 adds the refusal that keeps this tolerance resting on the grammar. Do not rely on the invariant without that refusal.

- [ ] **Step 4: Run the test and the three gates**

- [ ] **Step 5: Prove a registered combinator extends the grammar with no edit**

Register a probe combinator with a new keyword, then parse a step using that keyword and confirm it resolves to the probe's op — with this file unchanged. Delete the row and confirm the same text stops resolving. Record both outcomes. This is the gate that would otherwise pass vacuously, so it must assert a *behaviour change* when the row is added.

- [ ] **Step 6: Commit**

---

### Task 4: IR assembly, groups, and canonical numbering

**Files:**
- Modify: `sql/10_treeql.sql`
- Test: `test/sql/48_treeql_parse.test` (append)

**Interfaces:**
- Produces: `tree_parse_treeql(txt) -> TREE_SELECTOR`. The selector row stamps `value = 'treeql'`.
- Consumes: Tasks 1–3, `tree_group_depth_limit()`, `tree_selector_group_depth`.

**This is the task that makes the exact theorem true**, and the whole design rests on one property: canonical IR is dense, 0-based and pre-order — a step, then its clauses in slot order, then its groups — and the printer orders both steps and parts by `node_id`. So **textual order is node_id order**, and a counter incremented as parts are encountered reproduces the ids.

Groups **unroll** to `tree_group_depth_limit()` (2), never recurse: DuckDB macros cannot self-recurse, and the printer unrolls to the same depth for the same reason. Deeper nesting is refused, reusing the printer's wording — the alternative is silently losing the innermost groups.

- [ ] **Step 1: Write the failing test — the exact theorem first**

Append assertions that, for each of a spread of `tree_steps` selectors, `tree_parse_treeql(tree_selector_to_treeql(sel)) = sel` compares equal **as a whole value**, so node ids are included rather than merely the shape. Cover: a single clause; two steps with a combinator; a capture; multiple clauses on one step; a `HAS` group; a `NOT` group; nested groups at the depth limit; `ATTR`; `WHERE`; each of the eight combinators. Then the normalising half: a hand-built selector with sparse ids, asserting `print(parse(print(ir))) = print(ir)`.

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Write the assembly**

Requirements:

1. **Split the selector on newline** into top-level steps, using `tree_treeql_split(txt, chr(10))` so a newline inside a quoted value cannot split a step.
2. **Number pre-order**: selector 0, then for each step its own row, then its clauses in textual order, then its groups and each group's inner chain.
3. **Stamp `value = 'treeql'`** on the selector row. This is the provenance mechanism `tree_selector_language` reads back; canonical IR already carries it, so the exact theorem is undisturbed.
4. **A group's first inner step defaults to `desc`**, matching `tree_steps_group`. Do not restate the rule — the printer emits the explicit keyword, so the parser reads what is there; this requirement exists so that a group whose inner chain *omits* a combinator still lands on `desc`.
5. **Refuse nesting past the limit** by measuring the assembled selector with `tree_selector_group_depth` against `tree_group_depth_limit()`, which is what the printer and `tree_steps_group` both do.

- [ ] **Step 4: Run the test, then the whole suite and the other two gates**

The exact theorem over the corpus is the real gate here. Expect this task to surface disagreements between parser and printer; each one is either a parser bug or a printer behaviour the spec failed to describe — say which, in your report, for every one you find.

- [ ] **Step 5: Prove the numbering is checked, not assumed**

Perturb one expected node id in one assertion and confirm the test fails. A round-trip test that compared only the shape would pass that perturbation, and the exact theorem would be worthless.

- [ ] **Step 6: Commit**

---

### Task 5: Refusals, and the one documented limit

**Files:**
- Modify: `sql/10_treeql.sql`
- Test: `test/sql/48_treeql_parse.test` (append)

**Interfaces:** no new names; `tree_parse_treeql` gains its refusal arms.

- [ ] **Step 1: Write the failing test**

One assertion per refusal, each pinning the message by its distinguishing words:

| input | refused with |
|---|---|
| a clause keyword nothing defines | `tree_parse_treeql: unknown clause keyword FROBNICATE` |
| a combinator keyword nothing defines | `tree_parse_treeql: unknown combinator SIDEWAYS` |
| an unterminated quoted value | `tree_parse_treeql: unterminated quoted value` |
| unbalanced parentheses | `tree_parse_treeql: unbalanced parentheses` |
| empty input, or no steps | `tree_parse_treeql: selector has no steps` |
| nesting past the limit | the printer's wording, reused verbatim |
| a parenless inner step with no combinator | `tree_parse_treeql: a step inside HAS/NOT needs a combinator or parentheses, so its clauses can be told from the next step's` |
| a group with no parentheses | `tree_parse_treeql: HAS/NOT needs parentheses around its chain` |

The first of those two new rows is what makes the parenless step form safe rather than lucky. Inside a group, steps are space-separated, and a parenless step is unambiguous only because every inner step carries a combinator — an invariant `tree_steps_group` maintains by coalescing to `desc`, which hand-built IR arriving through the host door is under no obligation to honour. Without this refusal the bare form would be unambiguous only for input the printer happened to produce, which is a property of the producer rather than of the grammar. Assert it against hand-built IR, not against printer output, or the test cannot reach the case.

Plus **the documented limit**, which is the point of this task: a `WHERE` body with a **top-level** comma — `(TYPE 'x', WHERE a = 1, PSEUDO 'p')` — is read as three clauses, because the separator and the body's comma are indistinguishable at depth 0 ~~and the text is therefore genuinely ambiguous~~. **"GENUINELY AMBIGUOUS" IS FALSE, measured in the final-review fix round under duckdb 1.5.5:** `pseudo` is slot 5 and `where` slot 6, so `tree_steps([{type: 'x', "where": 'a = 1', pseudo: 'p'}])` prints `(TYPE 'x', PSEUDO 'p', WHERE a = 1)` — different bytes — and the text's only constructor-accepted preimage is the one-clause WHERE body. A reader *can* choose here, so the three-clause reading is a wrong parse and not one horn of an ambiguity. It stays a limit because its fix needs the clause kinds' **slot order** and `tree_catalog` has no order column: declared as `k13` beside k01–k07 in `test/sweep_treeql.py`'s `KNOWN_EXACT_FAILURES`. ~~No valid boolean predicate has a bare top-level comma, so this is unreachable from valid input.~~ **THAT PREMISE IS FALSE, measured during Task 5 fix round 3 and confirmed on BASE `3384ede`.** The clause-list splitter counts `(` and `)` and nothing else -- it is blind to `[` `]` and to `{` `}` -- so a comma inside a bracket OR brace pair sits at paren depth 0 and is read as a clause separator. Both of these are printer output from the ordinary constructor and both are REFUSED: `tree_steps([{"where": '[1, 2] = [1, 2]'}])` prints `(WHERE [1, 2] = [1, 2])` and refuses `cannot read 2]`; the brace form refuses `cannot read b: 2}`. The limit is therefore reachable from valid input, and reaching it refuses printer output, which the Global Constraints make a defect rather than a gate. Task 7's differential generator owns the fix; Task 5 pins the behaviour as records. Assert what actually happens, with a comment saying it is a limit rather than a bug, so the claim "unreachable" is tested instead of argued.

- [ ] **Step 2: Run to verify each assertion fails for the right reason**

Record, per assertion, what the parser does *before* the refusal exists. Some will already fail with a NULL or a wrong parse rather than a message — note which, because "fails" and "refuses legibly" are different and this task is about the second.

- [ ] **Step 3: Add the refusal arms**

Route every rule that already exists through its existing holder: `tree_sql_is_ident` for aliases, `tree_selector_group_depth` against `tree_group_depth_limit()` for nesting, the two registries for vocabularies. Restating a rule the macros already state is the pattern the slot engine removed thirteen copies of.

Use `tree_err`, and make sure every concatenated piece is `COALESCE`d: a NULL anywhere in a refusal message makes the whole message NULL, which `tree_err` reports as "refusal with a NULL message" — losing the one sentence the caller needed. That is a real defect this repo has shipped twice.

- [ ] **Step 4: Run the test and the three gates**

- [ ] **Step 5: Commit**

---

### Task 6: Registration and dispatch — the end-to-end path

**Files:**
- Modify: `sql/10_treeql.sql` (the registration)
- Modify: `test/run.py` (`rewrite_selectors`)
- Test: `test/sql/48_treeql_parse.test` (append)

**Interfaces:**
- Produces: `tree_catalog.selector_languages.parser = 'tree_parse_treeql'` for the `treeql` row; a registry-driven dispatch in the runner.
- Consumes: Tasks 1–5.

- [ ] **Step 1: Write the failing test**

The assertion this whole increment exists for — a TREEQL text selector reaching `tree_match`:

```
query I
FROM tree_match('main', 'app', '(TYPE ''function_definition'')') SELECT count(*) > 0;
----
true
```

Plus: the same selector as text and as `tree_steps` IR returning identical rows; `tree_selector_language` reporting `treeql` for a text selector; and the registry showing a non-NULL parser for the first time.

- [ ] **Step 2: Run to verify it fails**

Expected: the runner raises `tree_match: TREEQL text parsing arrives with M-LANG; pass tree_steps(...)` — an error message that names this increment. Quote it in your report; it is about to be deleted.

- [ ] **Step 3: Register the parser from this file**

```sql
-- The registry's parser column for treeql stops being NULL, and this is the line that does it.
-- It lives HERE, not in sql/01_catalog.sql, for the same reason 09_css.sql registers css: the
-- extension's difference is WHICH FILES it embeds, not what they say. A core-only build that does
-- not embed this file still finds parser IS NULL and still refuses text -- by a registry lookup
-- rather than a hardcoded branch, which is what sql/01_catalog.sql asks for in as many words.
UPDATE tree_catalog.selector_languages SET parser = 'tree_parse_treeql' WHERE language = 'treeql';
```

- [ ] **Step 4: Make the runner dispatch through the registry**

`test/run.py`'s `rewrite_selectors` currently hardcodes:

```python
if lang != "css":
    raise RuntimeError("tree_match: TREEQL text parsing arrives with M-LANG; pass tree_steps(...)")
args[2] = " " + css_parser.to_sql(css_parser.parse(text))
```

Replace it with a lookup of `selector_languages.parser` for the resolved language, refusing with the registry's own reason when the column is NULL.

**For `treeql`, dispatch to the MACRO**, not to a Python parser. This is deliberate and it differs from how css is handled: the runner sends css to `css_parser.py` while the extension will send it to `tree_css_lower`, so the two repos exercise different artifacts bound only by a differential. For treeql, pointing the runner at the macro means plan-repo tests exercise the artifact the extension actually ships.

- [ ] **Step 5: Run the test, the whole suite, and the other two gates**

Expect fallout: any test that asserted the old refusal must change, and `02_catalog.test` or `38_css_lower.test` may pin the registry's contents. List every file you touch.

- [ ] **Step 6: Commit**

---

### Task 7: The independent reading, and the differential

**Files:**
- Create: `test/treeql_parser.py`
- Test: `test/sql/48_treeql_parse.test` (append) and/or a sweep script

**Interfaces:**
- Produces: `treeql_parser.parse(text)` and `treeql_parser.to_sql(rows)`, mirroring `css_parser.py`'s shape.
- Consumes: nothing. **This module must have zero database access.**

A differential between two readings is evidence only if the readings are independent. `test/css_parser.py` has zero duckdb references for exactly this reason, and `sql/09_css.sql` states what the alternative is worth: "Two independent readings of one grammar is the point; agreeing by construction would prove nothing."

So this module carries its own copy of the reserved set and the slot order, and that copy is bound by the differential rather than by the registry. **That duplication is deliberate and must not be "fixed"** — the slot-engine review confirmed the arrangement works, because `38_css_lower.test` compares IR structs including `node_id`.

- [ ] **Step 1: Write the differential first, against a generator**

Generate selectors by printing `tree_steps` IR across a spread of shapes, then assert for each that the SQL parser and the Python parser produce identical rows — node ids included — and refuse the same inputs with the same distinguishing words. Follow `test/sweep_selectors.py`, which does this for the css pair.

- [ ] **Step 2: Run it to verify it fails** (no `treeql_parser` yet)

- [ ] **Step 3: Write the Python reference parser**

Recursive descent over the text, database-free, producing the same `(node_id, parent_id, kind, value, op, arg, alias)` rows. Where it must know a vocabulary, write it out with a comment naming the differential as what keeps the copy honest.

- [ ] **Step 4: Run the differential and the three gates**

- [ ] **Step 5: Prove the differential discriminates**

Plant a divergence in the Python reading — one wrong slot ordinal is enough — and confirm the differential fails and names the selector. Revert and confirm green. Two readings that agree prove nothing unless disagreement is detectable.

- [ ] **Step 6: Commit**

---

### Task 8: Mutants, and the extension's embed

**Files:**
- Create: two mutants under `test/mutants/` with controls
- Modify: `test/mutants/manifest.yaml`, `test/mutants/regen.py`
- Modify (extension repo, separate commit): `extension_config.cmake`, the embed list, the mirror

**Interfaces:** consumes everything above.

- [ ] **Step 1: Read the manifest's header and `regen.py` before writing anything**

"id is permanent", and a kill says nothing about the planted edit once the copy has drifted from the macro it copies. **Check the manifest for the next free ids** — the slot engine's plan named two that were already taken, and the gaps are reserved rather than free. Report which ids you chose and why they are free.

- [ ] **Step 2: Plant a wrong tokenizer**

Mutate `tree_treeql_split` so it splits on `sep` without tracking quote state. This must be killed by the separator assertions from Task 1. If it is not, those assertions do not actually cover the tokenizer and that is a finding about them, not about the mutant.

- [ ] **Step 3: Plant a wrong numbering**

Mutate the assembly so clauses are numbered after groups rather than before. The *shape* is unchanged, so only the exact round-trip theorem can see it — which is precisely what that theorem is for. Confirm the kill is attributable to that assertion and not to an incidental error.

- [ ] **Step 4: Declare both in the manifest with measured `expect_fail` lists**

Verify each listed suite genuinely fails under the mutant, individually, with `python3 test/run.py test/sql/<file> --mutant test/mutants/<file>.sql`. **A mutant is KILLED only when ALL its `expect_fail` suites fail** — `run_mutants.py` uses `all(v == "fail" ...)` — so a suite that does not fail makes the row report SURVIVED. Do not guess the list.

If a mutant needs no `regen.py` SPEC entry because it mutates catalog data rather than copying a macro, say so: the extension's harness refuses an in-scope mutant with no SPEC entry unless it is named in `DATA_MUTANTS`.

- [ ] **Step 5: Run everything**

`python3 test/run_mutants.py` — all killed, controls passing, no pre-existing status changed. Then the suite and the lint.

- [ ] **Step 6: The extension's embed — report, do not do it**

`sql/10_treeql.sql` is a NEW embedded file. The extension needs `extension_config.cmake` and its embed step to learn it, the new suite and mutants mirrored, and the **front-end dispatch** that `RefuseTextSelector`'s middle arm anticipates — it currently throws `NotImplementedException` when a parser is registered but no dispatch exists, and registering the parser makes that arm reachable for the first time.

**This is cross-repo work and out of scope for a dispatch told to work in this worktree.** Record it as a follow-up with the file list, as the slot engine's Task 7 did. Do not edit the other repository.

- [ ] **Step 7: Commit**

---

## Verification, whole-branch

- [ ] `python3 test/run.py test/sql` — full suite green (batch it)
- [ ] `python3 test/run_mutants.py` — all killed, controls pass, no status regressions
- [ ] `python3 scripts/check_vocabulary_single_source.py` and `--self-test`
- [ ] `python3 test/mutants/regen.py --check`
- [ ] `python3 test/gen_cheatsheet.py` — exits 0; the cheatsheet's "Handing over a pre-parsed selector" section says TREEQL text "has no parser yet", which is about to be false. Regenerate and read the diff.
- [ ] `tree_catalog_languages()` shows a non-NULL parser for `treeql` — the first time that column has been populated for it
- [ ] The deletion/registration probes from Tasks 2, 3 and 7 are recorded, with no cell passing that should fail
- [ ] The cross-repo follow-up from Task 8 Step 6 is written down, not done
