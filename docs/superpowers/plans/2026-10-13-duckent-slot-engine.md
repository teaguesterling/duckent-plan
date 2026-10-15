# duckent slot engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Declare the clause-kind and combinator vocabularies once each, have every site read the declaration, and open the combinator set so a new structural relation is a row rather than a dozen edits.

**Architecture:** Two catalog tables. `tree_catalog.clause_kinds` is closed at six rows, one per S-block slot plus the host door. `tree_catalog.combinators` is open and its rows are *derived* from the existing relation macros by calling them with `{a}`/`{b}` placeholder aliases, so the macros remain the single source of the relation logic and there is no transcribed second copy. `tree_sql_comb` becomes a registry lookup plus `replace()`; `tree_sql_clause` keeps its `CASE` because the `attr` arm is not templatable.

**Tech Stack:** DuckDB 1.5.5 SQL macros; `test/run.py` sqllogictest-style runner; `test/run_mutants.py`; Python 3 for the lint and the cheatsheet generator.

**Spec:** `docs/superpowers/specs/2026-10-13-duckent-slot-engine-design.md`

## Global Constraints

- **The macros are the semantics.** No rule already stated by a macro may be restated anywhere. A registry row is *derived* from its macro, never transcribed.
- **DuckDB 1.5.5.** Baseline `73dfd47`.
- **`sql/00_types.sql` … `sql/08_traversal.sql` are embedded byte-identically by the `duckent` extension**, which fails CI on one byte of drift. `sql/09_css.sql` is NOT embedded. Anything these tasks add to `00`–`08` ships in the extension; nothing in them may reference `09_css.sql`.
- **Load order is numeric.** A statement in `01_catalog.sql` cannot *call* a macro defined in `07_match.sql`. Macro *bodies* resolve at call time, so a macro defined in `06` may read a table populated in `07`.
- **No C++ changes.** The door's kind checks live in the macros. If a task appears to need an executor change, stop and report it.
- **A macro parameter must not share a name with a column of a table the macro queries.** `op` against `combinators.op` is a `Binder Error`, and the qualified form `macro_name.op` is not supported. Parameters that collide are named `want_*`.
- **A registry lookup that misses returns NULL, not an error.** Every lookup that replaces a `tree_err` arm must wrap in `COALESCE(..., tree_err(...))` or the refusal silently becomes a NULL fragment.
- **Every gate must be shown to fail when its subject is removed.** A gate that passes today proves nothing; the step that adds a gate also deletes what it guards and records that it failed.
- `tree_sql_before` is **out of scope**: zero callers, therefore unverified. Do not register it.

---

### Task 1: The two registry tables, with rows derived from the macros

**Files:**
- Modify: `sql/01_catalog.sql` (add two `CREATE TABLE`s and the `clause_kinds` rows, beside the existing `selector_languages` table)
- Modify: `sql/07_match.sql` (insert the five core combinator rows, immediately after `tree_sql_next_sibling` / `tree_sql_prev_sibling` are defined — around line 118, before `tree_sql_comb`)
- Test: `test/sql/46_slot_registry.test` (create)

**Interfaces:**
- Produces: table `tree_catalog.clause_kinds(kind, keyword, slot, needs_semantic, step_field)`; table `tree_catalog.combinators(op, keyword, template, template_elem, requires_sibling_order)`; table macros `tree_catalog_clause_kinds()` and `tree_catalog_combinators()` mirroring the existing `tree_catalog_languages()` accessor style.
- Consumes: nothing. No existing macro changes in this task.

- [ ] **Step 1: Write the failing test**

Create `test/sql/46_slot_registry.test`:

```
# name: test/sql/46_slot_registry.test
# description: the clause-kind and combinator vocabularies, declared once and derived from the macros

# THE DERIVATION GATE. A row's template must be the macro's own output, not a copy of it. If
# someone hand-edits a template, substituting it stops matching the macro and this fails. That is
# the only thing standing between "derived" and "transcribed".
query I
SELECT count(*) FROM tree_catalog_combinators() c
WHERE replace(replace(c.template, '{a}', 's0'), '{b}', 's1') <> CASE c.op
  WHEN 'desc'  THEN tree_sql_subtree('s0','s1')
  WHEN 'child' THEN tree_sql_children('s0','s1')
  WHEN 'self'  THEN tree_sql_self('s0','s1')
  WHEN 'next'  THEN tree_sql_next_sibling('s0','s1', false)
  WHEN 'after' THEN tree_sql_after('s0','s1') END;
----
0

# the ELEMENT-aware arm, for the rows that have one
query I
SELECT count(*) FROM tree_catalog_combinators() c
WHERE c.template_elem IS NOT NULL
  AND replace(replace(c.template_elem, '{a}', 's0'), '{b}', 's1') <> CASE c.op
        WHEN 'next' THEN tree_sql_next_sibling('s0','s1', true) END;
----
0

# every op the compiler can be asked for has a row
query I rowsort
SELECT op FROM tree_catalog_combinators() ORDER BY op;
----
after
child
desc
next
self

# sibling relations declare that they need SIBLING_ORDER; the others do not
query II rowsort
SELECT op, requires_sibling_order FROM tree_catalog_combinators() ORDER BY op;
----
after	true
child	false
desc	false
next	true
self	false

# the clause-kind vocabulary: six rows, one per S-block slot plus the host door
query III rowsort
SELECT kind, slot, needs_semantic FROM tree_catalog_clause_kinds() ORDER BY kind;
----
attr	_attr	true
class	_tags	true
id	_key	true
pseudo	_predicate	true
type	_type	true
where	NULL	false

# the printed keyword for every kind and op, which the printer will read in Task 5
query II rowsort
SELECT kind, keyword FROM tree_catalog_clause_kinds() ORDER BY kind;
----
attr	ATTR
class	CLASS
id	ID
pseudo	PSEUDO
type	TYPE
where	WHERE
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: FAIL — `Catalog Error: Table Function with name tree_catalog_combinators does not exist!`

- [ ] **Step 3: Add the tables and the clause-kind rows**

In `sql/01_catalog.sql`, directly after the `selector_languages` table and its comment block, add:

```sql
-- THE CLAUSE-KIND VOCABULARY, declared once. Every clause kind is a predicate over exactly one
-- declared S-block slot, plus `where` as the host door -- so this table is the engine's answer to
-- "what may a step say about a row". It is CLOSED: the S block is fixed by the ROWS contract, so a
-- seventh kind is extensibility nothing has asked for, and `tree_sql_clause` keeps its CASE
-- because the `attr` arm (projected column vs ATTR MAP, TRY_CAST by literal type, the negation
-- prefix) is not expressible as a template.
--
-- What this table replaces is the SET being written out by hand: it was named at THIRTEEN sites
-- across four files -- eight that can read a declaration and five that cannot (see the agreement
-- gate below). One of the eight generates docs/cheatsheet.md, so a drifted copy there did not
-- fail, it published a false claim; and one, 07_match.sql:584, wrote the set with `where` left
-- out, so a search for the full set did not even find it.
--
-- step_field is the TREE_STEP_* field that builds the kind, and it exists for the agreement gate:
-- TREE_STEP_L0/L1/L2 are DuckDB STRUCT types whose field lists are fixed at definition and cannot
-- be generated from this table, so the duplication cannot be removed and is verified instead.
CREATE TABLE IF NOT EXISTS tree_catalog.clause_kinds(
  kind VARCHAR PRIMARY KEY, keyword VARCHAR, slot VARCHAR, needs_semantic BOOLEAN, step_field VARCHAR);
INSERT INTO tree_catalog.clause_kinds VALUES
  ('type',   'TYPE',   '_type',       true,  'type'),
  ('id',     'ID',     '_key',        true,  'id'),
  ('class',  'CLASS',  '_tags',       true,  'class'),
  ('attr',   'ATTR',   '_attr',       true,  'attr'),
  ('pseudo', 'PSEUDO', '_predicate',  true,  'pseudo'),
  -- the host door reads no S slot, so it is available on a tree with no SEMANTIC group
  ('where',  'WHERE',  NULL,          false, 'where')
ON CONFLICT DO NOTHING;

-- THE COMBINATOR VOCABULARY. Unlike clause kinds this is OPEN: a front-end registers a row from
-- its own .sql file exactly as 09_css.sql registers its selector language, because the
-- registration API is SQL and not C++.
--
-- template carries the join condition with {a} and {b} standing for the two step aliases, and the
-- rows are DERIVED by calling the relation macro with those placeholders rather than transcribed
-- -- so the logic and the reasoning recorded around it (the root COALESCE, the IS NOT DISTINCT
-- FROM that makes level-0 rows siblings of each other) stay in sql/07_match.sql and there is no
-- second copy to drift. The rows are inserted THERE, because load order is numeric and those
-- macros do not exist yet at this point in the file.
--
-- requires_sibling_order is a CAPABILITY, and it is the reason this table is correctness rather
-- than tidiness. The sibling-free refusal used to hardcode `op IN ('next','after')`; a relation
-- registered without being added to that list compiled against a _pre no SIBLING_ORDER governs
-- and answered with whatever rows happened to land there.
CREATE TABLE IF NOT EXISTS tree_catalog.combinators(
  op VARCHAR PRIMARY KEY, keyword VARCHAR, template VARCHAR, template_elem VARCHAR,
  requires_sibling_order BOOLEAN);
```

and beside the existing `tree_catalog_*()` accessors near the bottom of the same file:

```sql
CREATE OR REPLACE MACRO tree_catalog_clause_kinds() AS TABLE SELECT * FROM tree_catalog.clause_kinds;
CREATE OR REPLACE MACRO tree_catalog_combinators() AS TABLE SELECT * FROM tree_catalog.combinators;
```

- [ ] **Step 4: Insert the derived combinator rows**

In `sql/07_match.sql`, immediately after the `tree_sql_prev_sibling` definition and before the
`tree_sql_comb` comment block, add:

```sql
-- The five relations the engine exposes, registered by DERIVATION: each template is the macro
-- above called with placeholder aliases, so this INSERT cannot disagree with the macro it names.
-- test/sql/46_slot_registry.test substitutes every template back and compares it against the
-- macro's direct output, which is what keeps that true.
INSERT INTO tree_catalog.combinators VALUES
  ('desc',  'DESCENDANT', tree_sql_subtree('{a}','{b}'),  NULL, false),
  ('child', 'CHILD',      tree_sql_children('{a}','{b}'), NULL, false),
  ('self',  'SELF',       tree_sql_self('{a}','{b}'),     NULL, false),
  ('next',  'SIBLING',    tree_sql_next_sibling('{a}','{b}', false),
                          tree_sql_next_sibling('{a}','{b}', true),  true),
  ('after', 'FOLLOWING',  tree_sql_after('{a}','{b}'),    NULL, true)
ON CONFLICT DO NOTHING;
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: PASS, all assertions.

- [ ] **Step 6: Prove the derivation gate has teeth**

Temporarily hand-edit one template in `sql/07_match.sql` — change `tree_sql_children('{a}','{b}')`
to the literal `'{b}}._root = {a}._root AND {b}._parent = {a}._pre'` (one extra brace).
Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: FAIL on the first assertion (count 1, not 0).
Revert the edit, re-run, confirm PASS. Record both outcomes in the task report.

- [ ] **Step 7: Confirm nothing else moved**

Run: `python3 test/run.py test/sql`
Expected: the whole suite passes. This task adds tables and rows and changes no consumer, so any
failure here is a load-order or name-collision problem, not a semantics change.

- [ ] **Step 8: Commit**

```bash
git add sql/01_catalog.sql sql/07_match.sql test/sql/46_slot_registry.test
git commit -m "feat(engine): declare the clause-kind and combinator vocabularies once"
```

---

### Task 2: `tree_sql_comb` and the printer read the combinator registry

**Files:**
- Modify: `sql/07_match.sql` (`tree_sql_comb`, around line 148)
- Modify: `sql/06_selector.sql` (`tree_treeql_comb`, around line 299; add a `bad_comb` guard to `tree_selector_to_treeql`, around line 338)
- Test: `test/sql/46_slot_registry.test` (append)

**Interfaces:**
- Consumes: `tree_catalog.combinators` from Task 1.
- Produces: `tree_sql_comb(want_op, a, b, elem)` — note the **renamed first parameter**; callers pass positionally so no call site changes. `tree_treeql_comb(want_op)` likewise.

- [ ] **Step 1: Write the failing tests**

Append to `test/sql/46_slot_registry.test`:

```
# The compiled join condition must be identical whether it came from the macro or the registry.
# This is the assertion that lets the registry replace the CASE at all.
query I
SELECT count(*) FROM (VALUES ('desc'), ('child'), ('self'), ('next'), ('after')) v(op)
WHERE tree_sql_comb(v.op, 's0', 's1', false) IS NULL;
----
0

# AN UNKNOWN COMBINATOR MUST REFUSE, NOT RETURN NULL. A registry lookup that misses yields NULL,
# and a NULL concatenated into the join text makes the whole fragment NULL -- a guard that does not
# fire, the same family as the error(NULL) audit. The CASE this replaces ended in tree_err; the
# lookup has to keep that.
statement error
SELECT tree_sql_comb('sideways', 's0', 's1', false);
----
tree_match: unknown combinator sideways

statement error
SELECT tree_sql_comb(NULL, 's0', 's1', false);
----
tree_match: unknown combinator <NULL>

# THE PRINTER'S SILENT DROP. tree_treeql_comb ended in ELSE NULL, and tree_treeql_step wraps it in
# COALESCE(... || ' ', '') -- so an op the printer did not know rendered as NOTHING and the
# combinator vanished from the printed text. The printer already refuses an unknown clause KIND
# for exactly this reason ("a kind this printer does not know refuses rather than rendering as
# nothing"); combinators had no equivalent. Now they do.
statement error
SELECT tree_selector_to_treeql([
  {node_id: 0, parent_id: NULL, kind: 'selector', value: 'treeql', op: NULL, arg: NULL, alias: NULL},
  {node_id: 1, parent_id: 0, kind: 'step', value: NULL, op: 'sideways', arg: NULL, alias: NULL},
  {node_id: 2, parent_id: 1, kind: 'type', value: 'x', op: NULL, arg: NULL, alias: NULL}]::TREE_SELECTOR);
----
tree_selector_to_treeql: unknown combinator sideways

# and the keyword for every registered op still prints
query I
SELECT string_agg(tree_treeql_comb(op), ',' ORDER BY op) FROM tree_catalog_combinators();
----
FOLLOWING,CHILD,DESCENDANT,SIBLING,SELF
```

- [ ] **Step 2: Run to verify the new assertions fail**

Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: FAIL. The two `tree_sql_comb` refusals already pass (the current `CASE` has the
`tree_err`), the printer refusal FAILS (it renders `(TYPE 'x')` with the combinator dropped), and
the keyword aggregate FAILS only if a keyword is wrong. Record which assertions failed and why —
the printer one is the live defect this task fixes.

- [ ] **Step 3: Replace `tree_sql_comb` with the registry lookup**

In `sql/07_match.sql`, replace the whole `tree_sql_comb` macro. Keep the existing comment block
above it and add the two paragraphs noted:

```sql
-- Combinator between the previous step alias a and this step alias b. MN14 mutates
-- tree_sql_subtree/tree_sql_children to drop the root equality.
-- 'self' only ever arrives here as a group's first inner step, which sql/06_selector.sql
-- enforces when the IR is built; nothing else in the compiler treats it specially.
--
-- The relation is looked up rather than branched on, so a front-end that registers a combinator
-- is compiled without editing this macro. The templates are DERIVED from the relation macros
-- above (sql/01_catalog.sql says why), so this is a lookup over their own output.
--
-- COALESCE around the lookup is load-bearing, not defensive: a miss returns NULL, and a NULL
-- concatenated into the join text would make the whole FROM fragment NULL -- the refusal silently
-- becoming no refusal at all. The parameter is `want_op` and not `op` because a parameter sharing
-- a name with a column of the table it queries is a Binder Error, and `tree_sql_comb.op` is not a
-- spelling DuckDB accepts.
CREATE OR REPLACE MACRO tree_sql_comb(want_op, a, b, elem) AS COALESCE(
  (SELECT replace(replace(
            CASE WHEN elem AND c.template_elem IS NOT NULL THEN c.template_elem ELSE c.template END,
            '{a}', a), '{b}', b)
   FROM tree_catalog.combinators c WHERE c.op = want_op),
  tree_err('tree_match: unknown combinator ' || COALESCE(want_op, '<NULL>')));
```

- [ ] **Step 4: Make the printer read the registry and refuse an unknown op**

In `sql/06_selector.sql`, replace `tree_treeql_comb`:

```sql
-- The keyword for a combinator, from the registry rather than a second copy of the set. Returns
-- NULL for an unregistered op, which tree_selector_to_treeql's bad_comb arm refuses -- see the
-- note there; it must not reach tree_treeql_step, which would render it as nothing.
CREATE OR REPLACE MACRO tree_treeql_comb(want_op) AS
  (SELECT c.keyword FROM tree_catalog.combinators c WHERE c.op = want_op);
```

and in `tree_selector_to_treeql`, add a `bad_comb` CTE beside the existing `bad_kind` and
`bad_dup`, and an arm in the final `CASE` before the `bad_dup` arm:

```sql
  -- A step whose op is not registered has no keyword, and tree_treeql_step wraps the keyword in
  -- COALESCE(... || ' ', '') -- so it used to render as NOTHING and the combinator vanished from
  -- the printed text. Refused for the same reason bad_kind is refused: a printer that silently
  -- drops part of a selector is worse than one that stops.
  bad_comb AS (
    SELECT min(op) AS o FROM n
    WHERE kind = 'step' AND op IS NOT NULL
      AND op NOT IN (SELECT c.op FROM tree_catalog.combinators c)),
```

```sql
    WHEN (SELECT o FROM bad_comb) IS NOT NULL
      THEN tree_err('tree_selector_to_treeql: unknown combinator ' || (SELECT o FROM bad_comb))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: PASS.

- [ ] **Step 6: Run the whole suite — this is the real gate for this task**

Run: `python3 test/run.py test/sql`
Expected: every existing suite passes unchanged. `tree_sql_comb` is on the hot path of every
compiled match, so the existing corpus is what proves the lookup produces byte-identical SQL.

- [ ] **Step 7: Prove the registry is actually read**

Delete the `child` row (`DELETE FROM tree_catalog.combinators WHERE op = 'child'`) in a scratch
session after loading `sql/*.sql`, then compile any selector using `CHILD`.
Expected: `tree_match: unknown combinator child`, not a NULL fragment and not a silent pass.
Record the observed message in the task report. Do not commit the deletion.

- [ ] **Step 8: Commit**

```bash
git add sql/06_selector.sql sql/07_match.sql test/sql/46_slot_registry.test
git commit -m "feat(engine): compile and print combinators from the registry, and stop dropping unknown ones"
```

---

### Task 3: the sibling-free refusal reads `requires_sibling_order`

**Files:**
- Modify: `sql/07_match.sql` (the `sibling_free` arm, around line 592)
- Test: `test/sql/46_slot_registry.test` (append)

**Interfaces:**
- Consumes: `tree_catalog.combinators.requires_sibling_order`.
- Produces: no new names. The refusal's message is now generated from the registry's keywords.

- [ ] **Step 1: Write the failing test**

Append to `test/sql/46_slot_registry.test`. This is the capability gate, and it asserts a
**behaviour change when the column flips** — a gate that merely read the column without acting on
it could not fake this:

```
# A tree with no SIBLING_ORDER. Sibling relations are unavailable on it, and the refusal must name
# them from the registry rather than from a string literal listing four spellings by hand.
statement ok
CALL tree_ddl_create('main', 'nosib', tree_spec(
  tree_shape(root := 'file_path', level := 'depth', size := 'descendant_count',
             semantic := tree_semantic(type := 'type', key := 'name')),
  source := 'read_parquet(''test/data/app.parquet'')'));

statement error
FROM tree_match('main', 'nosib', tree_steps([{type: 'a'}, {comb: 'next', type: 'b'}]));
----
is sibling-free

# A relation that does NOT require sibling order is still available on the same tree -- so the
# refusal is reading the capability, not refusing every combinator.
query I
SELECT count(*) >= 0 FROM tree_match('main', 'nosib', tree_steps([{type: 'module'}, {comb: 'child', type: 'function_definition'}]));
----
true

# THE GATE WITH TEETH: register a probe relation that declares it needs sibling order, and it must
# be refused on this tree WITHOUT any edit to the refusal. Then flip the column and the refusal
# must stop firing. A hardcoded op list cannot pass both halves.
statement ok
INSERT INTO tree_catalog.combinators VALUES
  ('probe_sib', 'PROBE', tree_sql_children('{a}','{b}'), NULL, true);

statement error
FROM tree_match('main', 'nosib', tree_steps([{type: 'a'}, {comb: 'probe_sib', type: 'b'}]));
----
is sibling-free

statement ok
UPDATE tree_catalog.combinators SET requires_sibling_order = false WHERE op = 'probe_sib';

query I
SELECT count(*) >= 0 FROM tree_match('main', 'nosib', tree_steps([{type: 'module'}, {comb: 'probe_sib', type: 'function_definition'}]));
----
true

statement ok
DELETE FROM tree_catalog.combinators WHERE op = 'probe_sib';
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: FAIL at the first `probe_sib` assertion — the hardcoded `IN ('next','after')` does not
know the probe op, so the match is NOT refused and compiles against an ungoverned `_pre`. That
failure is the bug the spec describes; record the observed behaviour.

- [ ] **Step 3: Replace the hardcoded op list**

In `sql/07_match.sql`, in the `sibling_free` arm, replace
`(ir.kind = 'step' AND ir.op IN ('next', 'after'))` with a registry read, and build the message
from the registry:

```sql
              -- The op list is the registry's, not a literal: a relation registered by a
              -- front-end declares requires_sibling_order and is refused here BECAUSE it said so.
              -- When this was `IN ('next','after')`, a newly registered sibling relation compiled
              -- against a _pre no SIBLING_ORDER governs and answered with whatever rows happened
              -- to land there -- the one thing this profile exists to prevent. The message is
              -- generated for the same reason: it used to name four spellings by hand and would
              -- have gone stale on the first registration.
              WHEN (SELECT profile FROM t) = 'sibling_free'
                   AND ((ir.kind = 'step'
                         AND ir.op IN (SELECT c.op FROM tree_catalog.combinators c
                                       WHERE c.requires_sibling_order))
                        OR (ir.kind = 'pseudo' AND list_contains(tree_builtin_predicates(), ir.value)))
              THEN tree_err('tree_match: tree ' || sch || '.' || nm
                   || ' is sibling-free (no SIBLING_ORDER declared); '
                   || (SELECT string_agg(c.keyword, ', ' ORDER BY c.keyword)
                       FROM tree_catalog.combinators c WHERE c.requires_sibling_order)
                   || ', :first-child and :last-child are unavailable')
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: PASS, both halves of the probe.

- [ ] **Step 5: Run the suites that assert the old message text**

Run: `python3 test/run.py test/sql`
Expected: a failure anywhere that pinned the literal string `SIBLING, FOLLOWING, :first-child and
:last-child`. The generated message orders keywords alphabetically, so `FOLLOWING, SIBLING` is the
new text. Update those expectations — the message is now derived, and that is the point. Record
which files changed.

- [ ] **Step 6: Commit**

```bash
git add sql/07_match.sql test/sql/46_slot_registry.test test/sql/*.test
git commit -m "fix(engine): the sibling-free refusal read a hardcoded op list, so a registered relation bypassed it"
```

---

### Task 4: three relations the engine already computes get spellings

**Files:**
- Modify: `sql/07_match.sql` (append three rows to the `INSERT` from Task 1)
- Test: `test/sql/47_new_combinators.test` (create)

**Interfaces:**
- Consumes: Tasks 1–3. **No macro changes.** If this task needs to edit a macro, the registry did
  not achieve what it claimed and that must be reported rather than worked around.

- [ ] **Step 1: Write the failing test**

Create `test/sql/47_new_combinators.test`:

```
# name: test/sql/47_new_combinators.test
# description: PARENT, ANCESTOR and PRECEDING -- relations the engine already computed with no spelling

statement ok
CALL tree_ddl_create('main', 'app', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', level := 'depth', size := 'descendant_count',
             semantic := tree_semantic(type := 'type', key := 'name')),
  source := 'read_parquet(''test/data/app.parquet'')'));

# PARENT is the inverse of CHILD, so the pair must agree on the same fixture: every (parent, child)
# the CHILD chain finds must be the (child, parent) the PARENT chain finds. Asserted as a set
# difference in both directions, which a one-sided count would not catch.
query I
SELECT count(*) FROM (
  SELECT p.name AS up, c.name AS down FROM tree_match('main', 'app', tree_steps([{type: 'module', "as": 'p'}, {comb: 'child'}])) c
  EXCEPT
  SELECT c2.name, p2.name FROM tree_match('main', 'app', tree_steps([{type: 'module', "as": 'c2'}, {comb: 'parent'}])) p2
);
----
0

# ANCESTOR is DESCENDANT read backwards -- tree_sql_ancestors is literally tree_sql_subtree(b, a) --
# so the same inverse property holds and is the cheapest check that the template was derived from
# the right macro rather than from tree_sql_subtree directly.
query I
SELECT count(*) FROM (
  SELECT a.name AS up, d.name AS down FROM tree_match('main', 'app', tree_steps([{type: 'module', "as": 'a'}, {comb: 'desc'}])) d
  EXCEPT
  SELECT d2.name, a2.name FROM tree_match('main', 'app', tree_steps([{type: 'module', "as": 'd2'}, {comb: 'ancestor'}])) a2
);
----
0

# PRECEDING is the inverse of SIBLING on a tree that HAS sibling order
query I
SELECT count(*) FROM (
  SELECT x.name AS l, y.name AS r FROM tree_match('main', 'app', tree_steps([{type: 'function_definition', "as": 'x'}, {comb: 'next'}])) y
  EXCEPT
  SELECT y2.name, x2.name FROM tree_match('main', 'app', tree_steps([{type: 'function_definition', "as": 'y2'}, {comb: 'prev'}])) x2
);
----
0

# the three new ops print, and round-trip through the printer
query I
SELECT tree_selector_to_treeql(tree_steps([{type: 'a'}, {comb: 'parent', type: 'b'}]));
----
(TYPE 'a')
PARENT (TYPE 'b')

query I
SELECT tree_selector_to_treeql(tree_steps([{type: 'a'}, {comb: 'ancestor', type: 'b'}]));
----
(TYPE 'a')
ANCESTOR (TYPE 'b')

query I
SELECT tree_selector_to_treeql(tree_steps([{type: 'a'}, {comb: 'prev', type: 'b'}]));
----
(TYPE 'a')
PRECEDING (TYPE 'b')

# PRECEDING declares it needs sibling order, so it is refused on a sibling-free tree -- by the
# capability column, with no edit to the refusal. This is Task 3's gate holding for a real row.
# The fixture must be PARENT basis. sql/03_ddl.sql sets
#   level_basis = (level IS NOT NULL OR parent IS NULL)
#   profile     = CASE WHEN NOT level_basis AND sibling_order IS NULL THEN 'sibling_free' ELSE 'full' END
# so ANY tree declaring `level` is 'full' and can never reach the sibling-free arm. An earlier
# draft of this plan used the app.parquet shape here and would have asserted a refusal that
# cannot fire. PARENT basis also requires UNIQUE KEY.
statement ok
CALL tree_ddl_create('main', 'nosib2', tree_spec(
  tree_shape(unique_key := 'email', parent := 'manager_email',
             semantic := tree_semantic(type := 'role', key := 'email')),
  source := 'read_csv(''test/data/employees.csv'')'));

# Pin the fixture's own property, so this gate cannot go vacuous if the shape rules move.
query II
SELECT basis, profile FROM tree_catalog_trees() WHERE tree_name = 'nosib2';
----
parent	sibling_free

statement error
FROM tree_match('main', 'nosib2', tree_steps([{type: 'manager'}, {comb: 'prev', type: 'engineer'}]));
----
is sibling-free

# PARENT and ANCESTOR do NOT need sibling order, so they stay available there
query I
SELECT count(*) >= 0 FROM tree_match('main', 'nosib2', tree_steps([{type: 'manager'}, {comb: 'parent'}]));
----
true
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 test/run.py test/sql/47_new_combinators.test`
Expected: FAIL — `tree_match: unknown combinator parent`.

- [ ] **Step 3: Add the three rows, and nothing else**

Append to the `INSERT INTO tree_catalog.combinators` in `sql/07_match.sql`:

```sql
  -- Three relations sql/07_match.sql already computed and TREEQL could not name:
  -- tree_sql_parent had five callers, tree_sql_prev_sibling and tree_sql_ancestors one each, all
  -- reached through tree_nav/tree_ancestors. They need no new logic, which is the claim this
  -- registry makes -- a new relation is a row.
  --
  -- tree_sql_ancestors is defined as tree_sql_subtree(b, a), so its template is derived from a
  -- macro that is itself derived, and the derivation gate covers it with no special case.
  --
  -- PRECEDING is the previous SIBLING, hence requires_sibling_order -- the first row to exercise
  -- the capability column against a relation the old hardcoded IN ('next','after') never knew.
  --
  -- tree_sql_before is deliberately absent: it has zero callers anywhere, so nothing has ever
  -- executed it. It earns tests before it earns a spelling.
  ('parent',   'PARENT',    tree_sql_parent('{a}','{b}'),    NULL, false),
  ('ancestor', 'ANCESTOR',  tree_sql_ancestors('{a}','{b}'), NULL, false),
  ('prev',     'PRECEDING', tree_sql_prev_sibling('{a}','{b}', false),
                            tree_sql_prev_sibling('{a}','{b}', true), true)
```

- [ ] **Step 4: Extend the derivation gate to cover them**

In `test/sql/46_slot_registry.test`, add the three arms to both `CASE`s in the derivation
assertions and the three ops to the `SELECT op` and `requires_sibling_order` expectations.
Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: PASS. A new row that the derivation gate does not cover is a row nothing checks.

- [ ] **Step 5: Run both and then the suite**

Run: `python3 test/run.py test/sql/47_new_combinators.test test/sql/46_slot_registry.test`
Expected: PASS.
Run: `python3 test/run.py test/sql`
Expected: PASS.

- [ ] **Step 6: Record whether any macro had to change**

In the task report, state explicitly whether Step 3 was the only source edit. If any macro needed
touching, name it — that is evidence against the design's central claim and the controller needs it.

- [ ] **Step 7: Commit**

```bash
git add sql/07_match.sql test/sql/46_slot_registry.test test/sql/47_new_combinators.test
git commit -m "feat(engine): PARENT, ANCESTOR and PRECEDING, as rows over relations that already existed"
```

---

### Task 5: the eight clause-kind consumers read the registry, and the irreducible surface is gated

**Files:**
- Modify: `sql/06_selector.sql` (lines 153, 338, 345 and `tree_treeql_clause` around line 301)
- Modify: `sql/07_match.sql` (lines 418, 457, 467, and 584 — the partial-copy site, Step 3b)
- Test: `test/sql/46_slot_registry.test` (append)

**Interfaces:**
- Consumes: `tree_catalog.clause_kinds`.
- Produces: `tree_ir_kinds()` — the full node-kind list, structural kinds plus clause kinds. The
  structural kinds (`selector`, `step`, `has`, `not`) are **not** registry-driven: they are the
  IR's own shape, not a vocabulary a front-end extends.

- [ ] **Step 1: Write the failing tests**

Append to `test/sql/46_slot_registry.test`:

```
# the node-kind list the IR allows: the four structural kinds plus every registered clause kind
query I
SELECT list_sort(tree_ir_kinds()) = list_sort(['selector','step','has','not'] ||
       (SELECT list(kind) FROM tree_catalog_clause_kinds()));
----
true

# THE AGREEMENT GATE. TREE_STEP_L0/L1/L2 are STRUCT types whose field lists are fixed at
# definition and cannot be generated from the registry, so this duplication cannot be removed --
# it is verified instead. Both directions, because each fails differently: a registry row with no
# struct field cannot be BUILT by tree_steps, and a struct field with no row is accepted by the
# constructor and then refused by the compiler.
query I
SELECT count(*) FROM tree_catalog_clause_kinds() k
WHERE k.step_field NOT IN (SELECT column_name FROM (DESCRIBE SELECT unnest(NULL::TREE_STEP_L0)));
----
0

query I
SELECT count(*) FROM (DESCRIBE SELECT unnest(NULL::TREE_STEP_L0)) d
WHERE d.column_name NOT IN ('comb', 'as', 'has', 'not')
  AND d.column_name NOT IN (SELECT k.step_field FROM tree_catalog_clause_kinds() k);
----
0

# the printer's clause keyword comes from the registry
query I
SELECT tree_treeql_clause('type', 'x', NULL, NULL);
----
TYPE 'x'

# and an unregistered kind still refuses at the printer, as it did before
statement error
SELECT tree_selector_to_treeql([
  {node_id: 0, parent_id: NULL, kind: 'selector', value: 'treeql', op: NULL, arg: NULL, alias: NULL},
  {node_id: 1, parent_id: 0, kind: 'step', value: NULL, op: NULL, arg: NULL, alias: NULL},
  {node_id: 2, parent_id: 1, kind: 'frobnicate', value: 'x', op: NULL, arg: NULL, alias: NULL}]::TREE_SELECTOR);
----
unknown node kind frobnicate
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: FAIL — `tree_ir_kinds does not exist`.

- [ ] **Step 3: Add `tree_ir_kinds()` and replace the seven literals**

In `sql/01_catalog.sql`, beside the accessors:

```sql
-- Every node kind the IR allows: the four STRUCTURAL kinds, which are the IR's own shape and not a
-- vocabulary anything extends, plus every registered clause kind. Read by the constructor, the
-- printer and the compiler, so the set is stated here once instead of at six sites.
CREATE OR REPLACE MACRO tree_ir_kinds() AS
  ['selector', 'step', 'has', 'not'] || (SELECT list(kind) FROM tree_catalog.clause_kinds);
CREATE OR REPLACE MACRO tree_clause_kinds() AS (SELECT list(kind) FROM tree_catalog.clause_kinds);
```

Then replace each site. `sql/06_selector.sql:153` — the constructor's unknown-field check, whose
set is the struct's fields rather than the IR's kinds:

```sql
    WHERE k NOT IN (SELECT unnest(['comb', 'as', 'has', 'not'] ||
                                  (SELECT list(step_field) FROM tree_catalog.clause_kinds)))),
```

`sql/06_selector.sql:338`:

```sql
       OR NOT list_contains(tree_ir_kinds(), kind)),
```

`sql/06_selector.sql:345` and `sql/07_match.sql:418`:

```sql
    FROM n c WHERE list_contains(tree_clause_kinds(), c.kind)),
```

`sql/07_match.sql:457`:

```sql
     OR (NOT list_contains(tree_ir_kinds(), c.kind)
```

`sql/07_match.sql:467`:

```sql
  WHERE c.kind = 'step' OR c.kind IN ('has', 'not') OR list_contains(tree_clause_kinds(), c.kind)
```

And `tree_treeql_clause` takes its keyword from the registry while keeping its per-kind rendering,
which is not uniform — `ATTR` and `WHERE` print unquoted bodies, the other four print a literal.
Note the parameter is `want_kind`, per the Global Constraint: a parameter named `kind` would
collide with `clause_kinds.kind`, and the qualified form `tree_treeql_clause.kind` is a Binder
Error rather than a disambiguation:

```sql
-- The keyword is the registry's; the BODY's rendering is not uniform and stays here. TYPE, ID,
-- CLASS and PSEUDO print a quoted literal; ATTR prints `name op arg` and WHERE prints raw host
-- SQL, both unquoted -- which is why the TREEQL text form needs a quote- and paren-aware reader
-- and why this cannot collapse into one concatenation.
CREATE OR REPLACE MACRO tree_treeql_clause(want_kind, value, op, arg) AS
  (SELECT k.keyword FROM tree_catalog.clause_kinds k WHERE k.kind = want_kind) || ' ' ||
  CASE want_kind WHEN 'attr'  THEN value || ' ' || op || ' ' || arg
                 WHEN 'where' THEN value
                 ELSE tree_sql_lit(value) END;
```

Call sites pass positionally (`tree_treeql_clause(c.kind, c.value, c.op, c.arg)`), so the rename
reaches no caller.

- [ ] **Step 3b: The S-less refusal reads `needs_semantic`**

`sql/07_match.sql:584` is the eighth site, and it writes the set as a **five-member** list — `where`
omitted, because the host door needs no `SEMANTIC` group. That omission *is* the `needs_semantic`
rule, stated nowhere. Replace it so the column is actually read; otherwise `needs_semantic` is a
declaration nothing consumes, which is the defect this whole plan removes:

```sql
         -- needs_semantic comes from the registry. This used to be a FIVE-member list with
         -- `where` left out, so the rule "the host door reads no S slot" was encoded as an
         -- omission that nothing stated -- and a search for the clause-kind set did not even find
         -- this site. The built-in positional predicates stay exempt on the VALUE, not the kind:
         -- they compile through the navigation fragments, read no S slot and bind nothing.
         CASE WHEN ir.kind IN (SELECT k.kind FROM tree_catalog.clause_kinds k WHERE k.needs_semantic)
                   AND NOT (SELECT has_semantic FROM t)
                   AND NOT (ir.kind = 'pseudo' AND list_contains(tree_builtin_predicates(), ir.value))
              THEN tree_err('tree_match: tree ' || sch || '.' || nm || ' has no SEMANTIC group; only combinators and WHERE are available. Add one with tree_ddl_alter or pass semantic :=')
```

and add to `test/sql/46_slot_registry.test`:

```
# A tree with no SEMANTIC group: the five slot kinds refuse, WHERE does not. The refusal must come
# from needs_semantic, so flipping the column changes behaviour -- which a site reading the column
# without acting on it cannot fake.
statement ok
CALL tree_ddl_create('main', 'nosem', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', level := 'depth', size := 'descendant_count'),
  source := 'read_parquet(''test/data/app.parquet'')'));

statement error
FROM tree_match('main', 'nosem', tree_steps([{type: 'module'}]));
----
has no SEMANTIC group

# WHERE is the host door and needs no S slot, so it stays available
query I
SELECT count(*) >= 0 FROM tree_match('main', 'nosem', tree_steps([{"where": '_level = 0'}]));
----
true

statement ok
UPDATE tree_catalog.clause_kinds SET needs_semantic = false WHERE kind = 'type';

query I
SELECT count(*) >= 0 FROM tree_match('main', 'nosem', tree_steps([{type: 'module'}]));
----
true

statement ok
UPDATE tree_catalog.clause_kinds SET needs_semantic = true WHERE kind = 'type';
```

- [ ] **Step 4: Run the test, then the suite**

Run: `python3 test/run.py test/sql/46_slot_registry.test`
Expected: PASS.
Run: `python3 test/run.py test/sql`
Expected: PASS. Every refusal message must be unchanged — this task moves where a set is read, not
what it contains.

- [ ] **Step 5: Prove each site reads the registry**

For each of `type`, `id`, `class`, `attr`, `pseudo`, `where`: in a scratch session, delete that row
and confirm that (a) `tree_steps` refuses the corresponding field, (b) the printer refuses the
kind, (c) the compiler refuses it at the door. Six rows × three consumers. Record the matrix in the
task report; a cell that *passes* after deletion is a site still carrying a private copy.

- [ ] **Step 6: Commit**

```bash
git add sql/01_catalog.sql sql/06_selector.sql sql/07_match.sql test/sql/46_slot_registry.test
git commit -m "feat(engine): eight copies of the clause-kind set become one declaration"
```

---

### Task 6: the lint, and the cheatsheet generator reads the registry

**Files:**
- Create: `scripts/check_vocabulary_single_source.py`
- Modify: `test/gen_cheatsheet.py` (`SELECTOR_KINDS`, line 220)
- Modify: `docs/cheatsheet.md` (regenerated)
- Modify: `.github/workflows/tests.yml` (add the lint as a gate)

**Interfaces:**
- Consumes: `tree_catalog.clause_kinds`, `tree_catalog.combinators`.
- Produces: `scripts/check_vocabulary_single_source.py`, exit non-zero when a written-out
  vocabulary reappears.

- [ ] **Step 1: Write the lint, and a self-test that proves it can fail**

Create `scripts/check_vocabulary_single_source.py`. It scans `sql/*.sql` and `test/*.py` for the
written-out sets and fails on any occurrence outside the declaration itself and the irreducible
struct surface. Follow `scripts/check_test_skips.py`'s shape: a module-level
`SELF_TEST_CASES` of strings that must be flagged and strings that must not, counted in the
summary rather than asserted as a magic number.

```python
#!/usr/bin/env python3
"""The clause-kind and combinator vocabularies must be declared once.

WHY A LINT AND NOT A TEST. The sets were written out at thirteen sites, and the failure mode of a
drifted copy is silence: the printer renders a clause as nothing, or the door accepts a kind the
compiler then refuses. A SQL test can prove the registry is read where it is read; only a scan can
prove no site quietly grew its own copy again.

WHAT IS ALLOWED, and why each exemption exists:
  sql/00_types.sql        TREE_STEP_L0/L1/L2 -- DuckDB STRUCT field lists are fixed at definition
                          and cannot be generated. test/sql/46_slot_registry.test gates agreement.
  sql/06_selector.sql     the extraction mirroring those structs, once per nesting level
  sql/01_catalog.sql      the declaration itself
  sql/07_match.sql        the derived INSERT, and tree_sql_clause's CASE -- the COMPILATION of each
                          kind, which is not a vocabulary copy
"""
import re, sys, pathlib

KIND_SET = ("type", "id", "class", "attr", "pseudo", "where")
COMB_SET = ("desc", "child", "next", "after", "self")

SELF_TEST_CASES = [
    ("WHERE k NOT IN ('comb', 'type', 'id', 'class', 'attr', 'pseudo', 'where')", True),
    ("kind NOT IN ('selector', 'step', 'has', 'not', 'type', 'id', 'class', 'attr')", True),
    ("SELECTOR_KINDS = [\"type\", \"id\", \"class\", \"attr\", \"pseudo\", \"where\"]", True),
    ("WHERE list_contains(tree_clause_kinds(), c.kind)", False),
    ("WHEN 'type' THEN alias || '._type = '", False),
]
```

The detector: a line is flagged when it contains three or more members of either set as quoted
strings and is not in an exempt (file, reason) pair.

- [ ] **Step 2: Run the self-test to verify the detector discriminates**

Run: `python3 scripts/check_vocabulary_single_source.py --self-test`
Expected: PASS, and the summary reports how many cases were checked.
Then break the detector (lower the threshold to one member) and confirm a `False` case is flagged.
Record both.

- [ ] **Step 3: Run it on the tree**

Run: `python3 scripts/check_vocabulary_single_source.py`
Expected: exit 0. If it flags a real site Task 5 missed, fix the site — not the exemption list.

- [ ] **Step 4: Point the cheatsheet generator at the registry**

In `test/gen_cheatsheet.py`, replace the `SELECTOR_KINDS` literal with a query against
`tree_catalog_clause_kinds()` plus the four structural kinds, and add a *Combinators* section
generated from `tree_catalog_combinators()` with columns keyword, op and whether it requires
sibling order.

This matters more than its size: this generator writes `docs/cheatsheet.md`, so a drifted copy
here did not fail, it published a false claim. The generated section is also how `PARENT`,
`ANCESTOR` and `PRECEDING` become documented at all.

- [ ] **Step 5: Regenerate and inspect the diff**

Run: `python3 test/gen_cheatsheet.py > docs/cheatsheet.md`
Expected: the diff adds the three new combinators and the combinator section, and changes nothing
else. Read the whole diff; an unexpected change means the generator was reading something else.

- [ ] **Step 6: Add the lint to CI**

In `.github/workflows/tests.yml`, add a step running the lint, gated the way the existing gate
steps are.

- [ ] **Step 7: Commit**

```bash
git add scripts/check_vocabulary_single_source.py test/gen_cheatsheet.py docs/cheatsheet.md .github/workflows/tests.yml
git commit -m "test(engine): lint the vocabularies back to one declaration, and generate the cheatsheet from it"
```

---

### Task 7: mutants

**Files:**
- Create: `test/mutants/MN30_comb_template.sql`, `test/mutants/MN31_capability_ignored.sql`
  (MN24 and MN25 are ALREADY TAKEN. The manifest carries MN01-08, MN12-15, MN17-19, MN21-22,
  MN24-29, and its first line is "id is permanent". The gaps MN09/10/11/16 are W's deferred
  mutants, MN20 is retired-but-reserved, MN23 is reserved for M-LANG — none of them is free.)
- Modify: `test/mutants/manifest.yaml`

**Interfaces:**
- Consumes: everything above.
- Produces: two planted defects with declared `expect_fail` lists.

- [ ] **Step 1: Read the manifest's own rules first**

Read the header of `test/mutants/manifest.yaml`. It records that most mutants are copy-and-edit of
a whole macro, that a kill says nothing about the planted edit if the copy has drifted from the
macro, and which two checks hold that claim up. Both mutants below must satisfy those checks.

- [ ] **Step 2: MN30 — a combinator template that is subtly wrong**

`test/mutants/MN30_comb_template.sql`: re-register `child` with the root equality dropped from its
template — the same defect MN14 plants in `tree_sql_children` itself, but reached through the
registry. It proves the template is what the compiler uses:

```sql
-- MN30: the registry's child template loses the root equality. MN14 plants the same defect in
-- tree_sql_children; this one plants it in the ROW, so a kill proves the compiler reads the
-- template rather than the macro.
UPDATE tree_catalog.combinators
   SET template = '{b}._parent = {a}._pre'
 WHERE op = 'child';
```

- [ ] **Step 3: MN31 — the capability column read but not acted on**

`test/mutants/MN31_capability_ignored.sql`: restore the sibling-free arm to a hardcoded
`IN ('next','after')`. This is the exact pre-Task-3 behaviour, and the mutant exists because that
behaviour *passed every test in the repo* before Task 3 added its probe. It must now be killed by
`46_slot_registry.test` and `47_new_combinators.test`.

- [ ] **Step 4: Declare both in the manifest with their `expect_fail` lists**

```yaml
- id: MN30
  file: MN30_comb_template.sql
  expect_fail: [test/sql/47_new_combinators.test, test/sql/31_match.test]
- id: MN31
  file: MN31_capability_ignored.sql
  expect_fail: [test/sql/46_slot_registry.test, test/sql/47_new_combinators.test]
```

- [ ] **Step 5: Run the mutant harness**

Run: `python3 test/run_mutants.py`
Expected: MN30 and MN31 both KILLED, every control passing, and every pre-existing mutant's status
unchanged. A mutant reported killed by a file not in its `expect_fail` list is a mis-declared
mutant, not a pass.

- [ ] **Step 6: Commit**

```bash
git add test/mutants/MN30_comb_template.sql test/mutants/MN31_capability_ignored.sql test/mutants/manifest.yaml
git commit -m "test(mutants): plant a wrong template and an ignored capability column"
```

---

## Verification, whole-branch

- [ ] `python3 test/run.py test/sql` — full suite green
- [ ] `python3 test/run_mutants.py` — all mutants killed, controls pass, no status regressions
- [ ] `python3 scripts/check_vocabulary_single_source.py` — exit 0
- [ ] `python3 test/gen_cheatsheet.py | diff - docs/cheatsheet.md` — generated docs committed and current
- [ ] The deletion matrices from Task 2 Step 7 and Task 5 Step 5 are recorded, with no cell passing
- [ ] Task 4's report states whether any macro needed editing to add a combinator
- [ ] In the `duckent` extension checkout: re-embed `sql/*.sql` and run
      `python3 scripts/check_macro_identity.py --plan-repo <this repo>` — byte-identical, and the
      extension's own suite green with no C++ change
