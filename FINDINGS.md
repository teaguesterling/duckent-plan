# FINDINGS

What first contact showed. Newest first. Every oracle divergence gets an entry with adjudication before any test changes.

**Reading the older entries, after the renames of 2026-10 (PRs #29, #48, #49).** Entries are dated
and are not rewritten, so one written before those PRs uses the vocabulary of its day and a grep
for a name it mentions can come back empty. The map, once, so it does not have to be repeated per
entry: catalog-side, `ID` → `KEY`, `CLASSES` → `TAGS`, `KEY` (the R slot) → `UNIQUE KEY`,
`PSEUDO`/`PSEUDO_ARGS` → `PREDICATE`/`PREDICATE_ARGS`, `tree_catalog.pseudo_classes` →
`tree_catalog.predicates`, the projection's `_id`/`_classes`/`_pseudo` → `_key`/`_tags`/
`_predicate`, and `tree_catalog_classes`/`tree_catalog_pseudo_classes` →
`tree_catalog_tags`/`tree_catalog_predicates`. Selector-side spellings did **not** move and are
correct wherever they appear: `.x`, `#x`, `[a=b]`, `:x`, the IR kinds `id`/`class`/`pseudo`/
`pseudo_unknown`, and TREEQL's `ID`/`CLASS`/`PSEUDO` clause keywords. `docs/cheatsheet.md` is
generated from a live catalog and CI-gated, so it is the authority for any name. Where a stale
*identifier* in an entry below would defeat a grep for live code it carries an inline note; stale
*prose* vocabulary is left as written, because the entry records what was true then.

## M4: predicate purity, and a cheatsheet that cannot rot (2026-10-08)

Two merged commits that left no entry here until now: `941e6ba` (predicate purity) and `399ed3c`
(the generated cheatsheet and its drift gate). Everything below was re-measured on DuckDB v1.5.5
for this entry rather than copied out of the commit messages.

### `duckdb_functions().stability` is authoritative for built-ins, and useless for macros

The whole verdict rests on DuckDB's own catalog rather than on a text scan of the body. For
built-ins it is exact — measured on a bare 1.5.5 connection, **16 `VOLATILE`**, **11
`CONSISTENT_WITHIN_QUERY`**, **2,614 `CONSISTENT`**, and 307 NULL (every macro, plus table
functions). Both impure classes are refused and for different reasons, which is worth keeping
distinct: `VOLATILE` (`random`, `uuid`, `nextval`) differs **within** one query, and
`CONSISTENT_WITHIN_QUERY` (`now`, `current_timestamp`) differs **between** them. A predicate that
moves between queries is the same defect as one that moves within a query — the same selector
would not answer the same twice, which is doctrine 2 — so the two are one refusal:

```
tree_ddl_create: PREDICATE p is not pure: its body reads a VOLATILE or
CONSISTENT_WITHIN_QUERY function, so the same selector would not answer the same twice
```

*(`941e6ba`'s message says 2,610 `CONSISTENT`; re-measured it is 2,614, the same in every slicing
tried — bare connection, with `json` loaded, scalar-only, non-table. The two counts that decide
anything, 16 and 11, are unchanged.)*

**And then the hole.** A macro reports `stability` NULL **whatever it calls** — measured, a macro
over `random()` and a macro over a constant are indistinguishable in `duckdb_functions()`. So the
catalog answers nothing about exactly the bodies a predicate is most likely to have, and
`tree_sql_purity` resolves one level through `macro_definition` and then stops. Measured verdicts:

| body | verdict |
|---|---|
| `descendant_count = 0` | `pure` |
| `contains(type, 'mod')` | `pure` (a CONSISTENT built-in) |
| `docs_pure_m(depth)`, a macro over CONSISTENT built-ins | `pure` |
| `docs_rand_m(depth)`, a macro over `random()` | `impure` — one level is enough to catch it |
| `docs_outer_m(depth)`, a macro calling a macro | `unknown` |
| `random() < 0.5`, `now() > TIMESTAMP '2020-01-01'` | `impure` |
| `descendant_count = )(` | `malformed` |

### The judgement call: `unknown` exists, and is accepted

This is the decision in the work worth recording, because it could have gone either way and the
losing option is the tempting one. `unknown` is **recorded and allowed**. Refusing it would refuse
a pure body on no evidence — a macro calling a macro is beyond one level of resolution, and since
DuckDB reports every macro's stability as NULL whatever it calls, *nothing can be proven either
way*. Claiming `pure` would be worse still: that is the false-positive verdict, the same shape of
wrong answer as #39's `assert_o_next = ok` for a declaration nothing had compared. So one honest
level of resolution, then an honest `unknown`, and only the two **decidable** failures are
refused. Transitive resolution is the obvious extension and would turn some of today's `unknown`
into `impure`; `36_pseudo` carries the case that would move.

Of the four verdicts `tree_sql_purity` returns, only two are ever stored: `impure` and `malformed`
are refused at declare time by `tree_sql_check_purity`, so `tree_catalog.predicates.purity` only
ever reads `pure` or `unknown`.

### `json_serialize_sql` does not raise on malformed input, which is why parse-ability is a separate question

The functions a body references come from DuckDB's own **parse tree**, via `json_serialize_sql`,
which parses **without binding** — so a body full of column names it cannot resolve still yields
its calls, and a *column* named `random` is not mistaken for the function. Measured before
building on it: a malformed body comes back as an error **object**, not an exception —
`json_serialize_sql('SELECT )(')` returns
`{"error":true,"error_type":"parser","error_message":"syntax error at or near \")\"",…}`. The
extractor therefore finds **no calls** in unparseable text, and "no calls found" looks exactly
like purity. Without asking parse-ability separately, `descendant_count = )(` would have been
recorded `pure`; it is refused with `tree_ddl_create: PREDICATE p does not parse`.

### Two implementation constraints that shaped the insert

- **The predicate insert is built over list *indices*, not `list_transform`.** `tree_sql_purity`
  is a subquery macro, and DuckDB refuses a subquery inside a `lambda` (the same 1.5.5 constraint
  recorded below for `tree_sql_predicate_map` and `tree_sql_chain`), so
  `tree_sql_pseudo_insert` iterates `generate_series(1, len(pseudo))` and indexes the list.
- **`ORDER BY i` matters.** `list_aggregate` gave list order for free; a hand-rolled
  `string_agg` does not. The expanded predicate list is **not name-ordered** — the shared tier is
  sorted, the local entries are in the order written — so ordering by name here would have
  silently reordered what the catalog records.

### The cheatsheet's drift gate: authored prose, measured names

`test/gen_cheatsheet.py` generates `docs/cheatsheet.md` out of a live database — the six
introspection views, `duckdb_functions()`, and the `TREE_SHAPE` / `TREE_SEMANTIC` types — and
`python3 test/gen_cheatsheet.py --check` runs in CI (`.github/workflows/tests.yml`). The division
is the point: **every name is measured, every gloss is authored**, and the generator checks the
prose against the catalog in both directions. A gloss naming something the catalog no longer has
is a hard error; a measured name with no gloss renders as `_(not described)_` rather than being
quietly dropped. Three coverage assertions make the fixture's job explicit rather than hopeful:
every shape slot must be exercised by some reference declaration, every body listed as refused
must actually be refused, and every body listed with a purity verdict must actually get one.

Four drift modes were verified to fail rather than assumed to: a hand-edited file, a stale gloss,
an unexercised slot, and an accepted declaration the file claims is refused. That is what makes
this different from a document: the renames in PRs #48 and #49 would have **failed this
generator** instead of rotting the doc, which is why `docs/cheatsheet.md` is the authority for a
name and this file is not.

Writing it measured three things no document carried before, each now in the generated file:
`tree_match` is absent from `duckdb_functions()` while `tree_explain` is present, because the
runner replaces the call with the query `tree_compile_match` returns; the shared predicate tier
binds **nothing** unless the tree declares `PREDICATE_ARGS`, since it has no other source of
arguments, so a tree without it gets zero shared predicates however many `sel_` macros exist; and
a macro already bound under one name is not bound again under another — with both a `pre_` binding
and a `sel_shallow` macro present, `shallow` is bound once, by the prefix. The first draft of the
fixture hit that last one by accident and lost its shared row to it.

An enumerated domain in the file is what the **reference declarations** produce, not what the code
can produce, and the file says so about itself: add a basis or a storage mode without adding a
reference declaration and the cheatsheet under-claims rather than lying (doctrine 5). `status` is
only ever `ok` there, and that is the point — the structural conditions a check would otherwise
record as violated are refused at declaration instead.

## DuckDB 1.5.5 constraints met in M2 (2026-09-15)

Each of these changed the shape of the code, not just a line of it. The design-phase section at
the foot of this file has the ones M0–M1½ met; these are new, and each is stated once.

- **`CREATE OR REPLACE MACRO` with a different arity DROPS the other overload** instead of adding
  to it. `tree_sql_root(root_csv, qual)` already existed when the fragment table wanted a
  one-argument root test, and creating `tree_sql_root(a)` would have silently unbound every
  projection compile. The fragment is named `tree_sql_is_root(a)`; the name is the whole fix, and
  the lesson is that overload sets are not additive here.
- Two constraints already stated in the design-phase section below are recorded here only for
  what M2 made of them, not restated: **a subquery or aggregate inside a lambda-bearing
  expression is refused after macro inlining** — which is why `tree_compile_match` carries its
  settings as joined CTEs rather than as subqueries; and **`recurring.<cte>` is illegal inside a
  correlated subquery** — which is why the bottom-up fold is a fixed number of unrolled passes
  and not `WITH RECURSIVE … USING KEY`. A group compiles to `[NOT] EXISTS (…)`, the exact shape
  1.5.5 refuses there. The unrolling is total rather than approximate because the IR has its own
  ceiling (`tree_group_depth_limit()` = 2).
- **Chained level-parameterized macro passes hit `INTERNAL Error: Failed to bind column
  reference: inequal types (INTEGER != BIGINT)`.** The printer in `sql/06_selector.sql` wanted
  one pass macro applied twice; it is kept as two unrolled passes for this reason, with the
  attempt recorded in a comment so the next person does not re-try it blind.
- **Table- and scalar-function NAMES bind at `CREATE MACRO` time.** A macro cannot name a
  function that does not exist yet, which is why `tree_parse_css` reaches sitting_duck's
  `parse_ast_list_table` through core `query()` rather than by calling it. The consequence for
  callers: the argument must be constant-foldable.
- **`error(NULL)` does not raise — it evaluates to NULL.** This is the nastiest of them,
  because it turns a refusal into a wrong answer: a message built by concatenation goes NULL if
  any operand is NULL, `error()` then returns NULL, and the NULL propagates — a NULL SQL fragment
  makes the whole compiled query NULL, a NULL context struct makes every statement built from it
  NULL and `list_filter` drops them, so a verb that should have refused runs `BEGIN … COMMIT` over
  nothing. Found in `sql/09_css.sql` (55 of 187 probe inputs returned a NULL selector instead of
  refusing) and answered there with `tree_css_err`. The M2 audit extended it: `tree_err(msg)` in
  `sql/00_types.sql` is the backstop, every refusal in the macro files goes through it, and the
  operands that can actually be NULL are `COALESCE`d to `'<NULL>'` so the message still names
  what was wrong. See the audit entry below for the sites.
- **A guard can be optimized out of existence.** `tree_compile_delete` and `tree_compile_check`
  build every statement by string concatenation over the identity, so with a NULL identity each
  statement constant-folds to NULL *before* anything reads the DML context — and the planner then
  prunes the column that holds it, so the refusal inside `tree_dml_context` was never evaluated
  at all. `CALL tree_check('main', NULL)` reached the executor as `[BEGIN, NULL, NULL, COMMIT]`
  and died on an `INTERNAL Error: Attempted to dereference shared_ptr that is NULL`.
  `tree_compile_insert` and `_replace` escaped it only by accident: they also call
  `tree_compile_projection(x.shape, …)`, which forces the context. Both now read the context in a
  predicate that cannot fold. **A refusal placed where the planner can prune it is not a
  refusal**, and "it raises when I test it" is not evidence that it raises in every plan.
- **`unnest(…) AS p` in a scalar context flattens the struct's fields** rather than binding the
  struct to `p`, so `p.name` afterwards is not a field access. Use `list_filter` /
  `list_transform` with a lambda instead. (The related parenthesization rule for struct access
  inside macro bodies is in the design-phase section below.)

## The `error(NULL)` audit (2026-09-15)

Task 13 grepped every `error(` in `sql/*.sql` whose message is a concatenation with a
possibly-NULL operand, and probed each one live. Seven sites leaked a NULL instead of raising,
in three shapes:

| site | reachable with | what happened instead of a refusal |
|---|---|---|
| `tree_sql_comb` unknown combinator | a hand-built IR step with a NULL `op` | NULL fragment → NULL compiled query |
| `tree_sql_clause` unknown clause kind | a hand-built IR node with a NULL `kind` | same |
| `tree_sql_clause` attribute not served | an `attr` node with a NULL `value` | same |
| `tree_compile_match` tree not found | `tree_match(NULL, 'app', …)` | compiler returned NULL; the runner then failed on the Python side |
| `tree_compile_alter` tree not found | `tree_ddl_alter(NULL, 'app', …)` | same (F11 closed the other route to this) |
| `tree_dml_context` tree not found | `tree_insert(NULL, 'app', …)` | context NULL → every statement NULL → `BEGIN … COMMIT` over nothing |
| `tree_compile_delete` / `_check` | `tree_check('main', NULL)` | the refusal was *pruned out of the plan* (see above) |

Fixes: `tree_err(msg)` = `error(COALESCE(msg, 'duckent: internal: refusal with a NULL message …'))`
in `sql/00_types.sql`, with every refusal in `sql/00_types.sql`, `03_ddl.sql`, `04_dml.sql`,
`06_selector.sql` and `07_match.sql` routed through it; `COALESCE(x, '<NULL>')` on the operands
above so the message stays specific rather than falling back to the internal one; and the two
pruned guards rewritten to read the context in a predicate. `sql/09_css.sql` keeps its own
`tree_css_err`, whose fallback names the css parse. Twelve test records cover the seven rows —
`31_match.test` (6, including `tree_err`'s own backstop), `12_dml.test` (4) and `13_alter.test`
(2) — and every one of them failed first.

What generalizes past this table: **a refusal is code, and untested code does not work.** Each of
these sites had a correctly worded message and no record asserting that it is ever raised. The
audit was a grep for a pattern (`error(` over a concatenation with a possibly-NULL operand) and a
probe of every hit; the pattern found all seven, and the probe is what told the difference
between a hazard and a shape that cannot occur.

## Element rows: which spelling (D-N18)

The element predicate can be written as a regexp over the node type or as `is_construct(flags)`,
and **the two disagree on keyword tokens**. `(flags & 1) = 0` reproduces `is_construct` on all
three fixtures and is what the corpus trees declare, through the `is_element` column
`test/gen_fixtures.py` derives at fixture time. The regexp spelling is not equivalent and should
not be used as if it were.

## D-N17 list-space spike

`test/spike_listspace.py` (2026-09-15, DuckDB 1.5.5, one machine, best of three runs after a
warm-up). Two forms of the flagship pair `.fn:has(string)` and `.fn:not(:has(string))`: (a) what
`tree_compile_match` emits today, `[NOT] EXISTS (SELECT 1 FROM P h1 WHERE <subtree> AND …)`,
compiled through the real compiler on a tree declared exactly like the corpus trees and executed;
(b) a hand-written list-space form — `list(_pre)` of each node's subtree materialized by a
self-join and `GROUP BY`, tested with `list_has_any` against the root's list of `string` nodes.
Inputs: `scripts.parquet` (14,265 rows, 15 roots) and ten copies of it with distinct roots
(`file_path || '#' || i`; 142,650 rows, 150 roots). Both trees declare `SIZE`.

| input | selector | EXISTS | list-space | EXISTS ÷ list | same answer |
|---|---|---|---|---|---|
| scripts | `.fn:has(string)` | 0.004 s | 0.059 s | 0.08× | yes (38 rows) |
| scripts | `.fn:not(:has(string))` | 0.004 s | 0.061 s | 0.07× | yes (1 row) |
| scripts10 | `.fn:has(string)` | 0.010 s | 0.530 s | 0.02× | yes (380 rows) |
| scripts10 | `.fn:not(:has(string))` | 0.008 s | 0.510 s | 0.02× | yes (10 rows) |

Row counts and key hashes (`md5` over the sorted `file_path:node_id` list) are equal in every
cell, so the two forms are the same query, not two different questions.

**The most generous reading, measured** (2026-09-15, `test/spike_listspace.py --materialized`).
The timings above charge list-space for building its lists on every query, which is the honest
per-query cost but not the strongest form of the proposal. With both lists — every node's subtree
and the per-root string-node list — **pre-materialized as temp tables**, a one-time 0.529 s on
the 10× input, the list-space query still runs **about 4.6× slower than `EXISTS`** there
(0.035–0.037 s against 0.008 s), on the same 380 and 10 rows with the same key hash. On the
14k-row input it is 1.3–1.5× slower (0.006–0.007 s against 0.004–0.005 s). So the decision holds
under the reading most favourable to list-space, and that reading is already unfair to `EXISTS`:
those tables are stale the moment a row is inserted, so a real implementation would owe their
maintenance on top. (The Task 13 reviewer measured the same thing independently and got 0.52 s,
0.035 s and 0.007 s — about 5×.)

**Decision: keep `EXISTS`. D-N17 is closed against list-space.** The rule set in advance was
"adopt unless list-space wins by 3× on the larger input"; it loses by 50× to 60× there, and the
gap *widens* with size (0.08× at 14k rows, 0.02× at 143k). The reason is structural, not a
tuning detail: DuckDB turns `EXISTS` into a semi-join, which stops at the first match and
materializes nothing, while the list-space form must build every node's subtree list first —
a self-join whose output is the sum of all subtree sizes, which is O(n · depth) rows for a tree
that `EXISTS` never has to visit. The list form pays for all subtrees to answer about a few.

Two things the spike settled along the way, both worth carrying:

- **The brief's sketch of the list-space form is cross-root-unsound.** Taking the string-node
  list as `(SELECT list(_pre) FROM P WHERE _type = 'string')` is sitting_duck #130 in list form:
  `_pre` is unique only within a root, so a global list answers `:has(string)` with a string in
  another file. The measured form groups both lists by `_root`, because any honest list-space
  implementation has to.
- **Derived `_size` did not dominate these timings, and the reason matters for M3.** The
  quadratic is *within a root*, and `scripts10` multiplies the number of roots, not their size,
  so it never reaches the quadratic term:

  | input | rows | rows/root | declared SIZE | derived `_size` | ratio |
  |---|---|---|---|---|---|
  | scripts | 14,265 | ~951 | 0.045 s | 0.167 s | 3.7× |
  | scripts10 | 142,650 | ~951 | 0.306 s | 0.793 s | 2.6× |
  | scripts_deep | 142,650 | ~9,510 | 0.280 s | 3.644 s | 13.0× |

  `scripts_deep` is the same 142,650 rows under the original 15 roots (a cost probe, not a
  well-formed forest — it is never created as a tree, only its projection text is timed). Ten
  times the rows *per root* costs 4.6× the derived time while the declared time is flat. That
  is the M3 case in one line: the O(n²) derivation is invisible on a forest of small files and
  is the whole cost on one big one, which is exactly the shape a whole-repository parse has.
  No timeout guard fired; nothing had to be skipped.

## M3 derivation cost

`test/spike_listspace.py --sizes` (2026-09-15, DuckDB 1.5.5, one machine, best of three after a
warm-up). M3 Task 6 replaced the derived `_size` — a correlated `min` over the projection, O(n²)
within a root — with a **level-expanded ASOF join**: every row is a candidate boundary for each
level from its own down to its root's deepest, and one ASOF join per row takes the nearest later
candidate at the row's own level. `_children` became a grouped count joined back, instead of a
correlated `count(*)`.

Four shapes, each a relation whose `descendant_count` is computed in SQL from the generated rows
(by aggregates over them, never by the boundary rule being measured), so "sizes agree" is an
independent check. Both sides go through the real compiler; only the shape differs.

| shape | rows | declared | derived, before | derived, after | before | after |
|---|---|---|---|---|---|---|
| chain depth 5000 | 5,000 | 0.013 s | 0.044 s | 0.908 s | 1.0× | **72×** |
| flat 200k | 200,000 | 0.102 s | 76.529 s | 0.164 s | 435× | **1.6×** |
| 2k spine + 100k shallow | 102,001 | 0.066 s | 21.501 s | 21.033 s | 254× | **316×** |
| scripts ×10 as one root | 142,651 | 0.227 s | 26.923 s | 0.281 s | 167× | **1.2×** |

(The "before" column was measured by running the same shapes against HEAD's `02_projection.sql`
in a scratch copy; declared times differ by a few ms between the two runs and are quoted from the
"after" run. Derived and declared sums agree in every cell, in both versions.)

**The case that matters got 96× faster and the pathological case did not move.** `scripts ×10 as
one root` is the realistic target — a whole-repository parse, 142,651 rows under ONE root — and it
goes from 26.9 s to 0.28 s, which is 1.2× a declared SIZE rather than 167×. `flat 200k` is 467×
faster. Neither is a surprise: the quadratic was in the number of rows per root, and both shapes
are shallow, so the candidate expansion is 2 levels deep.

Two results are worth carrying, because they are the honest cost of the change:

- **A pure deep chain got 21× SLOWER** (0.044 s → 0.908 s). The expansion is
  Σ(max level − level + 1), which on a 5000-level chain is n²/2 ≈ 12.5M candidate rows — the
  quadratic moved from the correlated subquery into the candidate relation. The old form was fast
  here only because DuckDB optimizes a correlated `min` over a strictly-increasing level well.
- **The deep-spine-beside-shallow-rows shape did not improve at all** (21.5 s → 21.0 s). This is
  the shape spec §2.3 names as the worst case and it remains the worst case: 100k shallow rows
  each expand over the spine's full 2000 levels, so the candidate relation is ~200M rows. The
  comment on `tree_sql_size_join()` says so and says what to do about it — **declare SIZE** on a
  source of that shape. A C++ port replaces the whole thing with a single stack walk, which is
  O(n) on every shape here; until then the derivation is a convenience, not a guarantee.

So the change is a large win on the shapes real sources have and a regression on one synthetic
shape, with the known-bad shape unchanged. It is not a substitute for declaring SIZE when the
source has one.

## M3 sibling relations

`test/spike_listspace.py --siblings` (2026-09-21, DuckDB 1.5.5, one machine, best of three after a
warm-up; the scanning form in a child process bounded to 6 GB of memory and 24 GB of spill). M3
Task 8 replaced the element-aware sibling and positional relations — which asked "is there a nearer
element sibling?" as a `NOT EXISTS` correlated to each candidate — with a single window pass, the
`__sib` CTE carrying each row's nearest element neighbour on either side.

One flat root, every third row a non-element, so every relation is answered within one parent's
child list and the width of that list is the variable. `independent` is a third implementation —
plain `lead()` / `row_number()` over the element rows, written from the definitions and from
neither form — and every completed cell has all three agreeing.

| children | relation | scanning | window | speedup |
|---|---|---|---|---|
| 300 | `next` | 0.030 s | 0.006 s | 5× |
| 600 | `next` | 0.231 s | 0.016 s | 14× |
| 1,200 | `next` | 3.457 s | 0.045 s | 76× |
| 2,400 | `next` | 87.630 s | 0.153 s | **574×** |
| 3,000 | `next` | **does not finish** | 0.189 s | — |
| 3,000 | `first-child` | 0.098 s | 0.020 s | 5× |
| 3,000 | `last-child` | 0.109 s | 0.016 s | 7× |

**The pair relations were the problem and the positional ones never were.** `next` grows worse than
quadratically — doubling the width from 1,200 to 2,400 costs 25× — and at 3,000 it does not finish
at all: it exhausts 6 GB of memory and 24 GB of spill, and unbounded it was OOM-killed at 19.5 GB
resident. The window form is linear across the same range. But `first-child` and `last-child` asked
their question of ONE row, which DuckDB plans as an anti-join, and they were never quadratic: the
window wins them by 5–7×, and at 300–600 rows the two forms are within noise of each other (both
under 20 ms). The rewrite is a large win on one relation and a tidy-up on the other two.

**A claim was corrected rather than carried.** The task's own comments said the 3,000-child record
"took 3m24s" on the scanning form. That number is not reproducible and the evidence contradicts it:
at 3,000 the scanning form does not complete under any budget tried, in either join shape (the
comma-join the probe hand-writes and the `JOIN … ON` the compiler emitted were measured separately
and both exhaust the same 22.3 GiB). The comments in `sql/07_match.sql` and
`test/sql/33_navigation.test` now quote the measured curve instead, and the 2,400 row is there
because it is the widest one that yields a time at all.

**Two defects in the probe harness, found by running it.** Both are fixed in this task:

- **A child that dies without posting hung the parent forever.** `sib_old_timed` joined with a
  timeout, then called `q.get()` — and an OOM-killed child posts nothing, so `pr.is_alive()` was
  already false and the timeout branch never fired. The first attempt at this table sat on that
  `get` for two hours. `derived_cost` (from Task 6) had the identical bug and had simply never had
  a child die early; both now go through one `run_child` helper that distinguishes *still running*
  from *exited without a result* from *posted*. The M3 derivation cost table above was taken before
  this fix, and is unaffected — every cell there either timed out while alive or completed.
- **The probe built its tree from a generating subquery, not a table.** The scanning form names the
  projection relation three times, so with a `range(n)` subquery as the source every correlated
  probe re-ran the generator through the projection — a cost the compiled form never had. Measured
  that way the 3,000-row cell was OOM-killed, which would have been recorded as a fact about the
  scanning form when it was a fact about the harness. `sib_setup` now materializes its source, as
  the `33_navigation` record and every real source do.

**"One projection per query" was checked in the plan, not assumed.** A three-step selector plans as
three `CTE_SCAN`s of one CTE index rather than three scans of the source. The `__sib` window costs
nothing when unused: a selector with no sibling relation plans with zero `WINDOW` operators even on
a tree that declares ELEMENT, and exactly one when `next` is asked for.

**That was checked for SELECTORS only, and it was false for traversal** — see the review section
below. `sql/08_traversal.sql`'s `tree_nav` put its two aliases on `__proj` as well, which cost it
the pushdown of its own one-row anchor predicate. The sentence that used to stand here, "so the
CTEs are not a tax paid by every query", was true of the compiler and untrue of the five traversal
macros that never read `__sib`. Fixed below.

A C++ port keeps the shape of this: `__sib` is one ordered pass over a partition, which is what a
node cursor does anyway. What it removes is the compiler's need to spell the projection into every
fragment — the fragments name a relation, and binding decides what that relation is.

## M3 Task 8 review (2026-09-29)

Task 8 was merged in PR #14 without the review round tasks 1–7 each had. The round was run
afterwards. It found **three defects and one coverage hole, none of them a wrong answer on a
well-formed selector**, and every one was reproduced independently before being accepted — the
reviewer's Task 3 claim that proved false is why that is the standing rule here.

### R1: a user alias in the `__` namespace shadows the compiler's own probes

`__` is the namespace the compiler gives its own relations (`__proj`, `__sib`) and the probe
aliases inside them (`__s`, `__x`). A user alias there did not collide loudly the way `s<N>` does —
it shadowed the probe, whose `WHERE` then compared the shadowing row to itself. Measured on a
4-row fixture, with a harmless alias as the control:

| selector | alias `q` | the generated name |
|---|---|---|
| non-ELEMENT `:last-child` | 2 rows | **4 rows** (silently wrong) |
| ELEMENT `:first-child` | 2 rows | `Invalid Input Error: More than one row returned by a subquery` |

Both names are Task 8's. The `s<N>` refusal has three producers (`tree_steps`, the css front-end,
and the compiler as the convergence point every front-end's IR arrives at), so the new guard has
the same three, with its own message: `alias __x is reserved for the compiler's own relations`.
Refusing the whole `__` prefix rather than enumerating four names is deliberate — it is the
namespace, and `:__cap_` was already reserved in css on the same reasoning. Records in suites 30,
31, 37 and 38, each confirmed to fail before the guard existed, with a positive control (`a__b` is
a fine alias) so the guard cannot be passing by refusing everything.

### R2: `tree_nav` paid for a CTE it did not need

Putting `tree_nav`'s two aliases on `__proj` materializes the whole projection and stops its
anchor predicate (`a._root = <lit> AND a._pre = <n>`, which selects ONE row) from reaching the base
scan. Isolated on a 500k-row materialized tree with three hand-built variants of the same one-row
query, so only the relation text differed:

| variant | best |
|---|---|
| pre-Task-8: both aliases on the projection text, no CTEs | 1.9 ms |
| as committed: both aliases on `__proj` | **16.0 ms** |
| `__sib` over the projection, aliases on the projection text | 2.5 ms |

So it is `__proj` that costs, not `__sib`. Through the real macros on the same tree:

| macro | as committed | fixed |
|---|---|---|
| `tree_parent` | 19.4 ms | 14.7 ms |
| `tree_children` | 17.7 ms | 13.6 ms |
| `tree_next_sibling` | 112.8 ms | 66.3 ms |

`tree_sql_nav_ctes` splits into `tree_sql_sib_body(rel)` (the window, spelled once) plus two
callers: the compiler still opens with `__proj` and `__sib`, and traversal opens with
`tree_sql_sib_cte`, the window alone read straight from the projection. The compiler's pinned SQL
in suite 31 is byte-identical, which is what says this moved traversal and not matching. Safe
because `tree_nav` always passes `elem := true`, so the one `__proj`-referencing branch
(`tree_sql_last_child`'s ELSE) is never reached from there. Naming `__sib` for the five traversal
macros that never read it is free: DuckDB prunes an unreferenced CTE.

### R3: the rewritten `last_child` depends on an operator no test covered

Task 8 changed the non-ELEMENT `last_child` from a scan to a keyed lookup, which introduced a
parent comparison the scan never made. Level-0 rows carry a NULL `_parent`, so under plain `=` the
comparison is NULL, the `NOT EXISTS` finds nothing, and **every root of a partition reads as a last
child** — F7 of the 2026-09-14 review, reappearing in a new place.

The rewrite is correct. What was missing is any record that says so: changing that one operator to
`=` in a scratch copy left **all 24 suites passing**. By this project's third doctrine a suite no
mutant can fail tests nothing, so the operator was load-bearing and unguarded.

Equivalence was checked first, old form against new, on `app.parquet`, `scripts.parquet` (14,265
rows), a 10-root partition and a deep chain — no disagreement — and the differential was shown to
have power by perturbing the new form three ways (size off by one, dropped parent check, `=` for
`IS NOT DISTINCT FROM`), each of which it caught. Suite 33 now carries a record: 10 roots in one
partition, `:last-child` pinned to 11, counted from the definitions rather than read off the
implementation. It FAILS on the mutated copy (`got ['20'], want ['11']`) and passes on clean.

Reachability was checked rather than assumed: `CALL tree_ddl_create` is emulated by `test/run.py`
over the same compile path the DDL uses, and a partition with several level-0 rows is *accepted* by
it, so this is not an unreachable shape. No mutant id is claimed — ids are permanent and
handover-assigned — so this is the `also_kills` candidate the MN02 note describes.

### Carried, not fixed

For **projection-storage** trees the source can change after create and O conformance is not
re-checked per query, so a drifted `_size` now makes `:last-child` silently wrong where before it
was right (the old form read no `_size`). Materialized trees are unaffected, and conformance
refuses a bad `_size` at ingest for both. Recorded here rather than fixed: re-checking per query
is a cost decision the O layer's design should make, not a review follow-up.

## Inbound: duck_block_utils v3.5.0 and Task 13's document shape (2026-10-03)

*(2026-10-03, same day: **the three "not started / cannot be written / left open" judgements in
this entry are closed.** `test/sql/45_duck_blocks.test` exists (commit `41599ee`), it decides for
the explicit `document` root, and it needed no extension update to do it. The closure is at the
foot of the entry; the measurement table below still holds exactly as written.)*

Reported by the duck_block_utils build (a peer session, second-hand — recorded as an input to be
decided, not as a settled ruling), and relevant to **Task 13**, which is not started:

- `duck_block_type_names()` now enumerates `document` (44 names). It did not for two weeks: the
  type was declared, validated, repair-exempted and writer-dropped, but absent from the
  enumeration, so a consumer building a type-to-node-type map by reading that function got a map
  with no root in it.
- **Level 0 is an optional explicit document root** (`kind='block'`, `element_type='document'`),
  several roots are permitted in one relation, and a root carries no content. The reported ruling
  is that the 1-based `level` is *intentional* and that prepending a level-0 root is the supported
  way to conform — **rather than declaring `level - 1`**.
- `ATTR_ID = "id"` is the document fragment locator, unique within its document and semantic in
  location and value. `ATTR_NAME = "name"` is provenance, not an address. If duckent grows an
  `#id` selector, `attributes['id']` is what it should resolve against.
- `SPEC_VERSION` is unchanged at 1.4, so nothing forces a re-vendor.

### What is verified here, and what is not

| claim | checked | result |
|---|---|---|
| `duck_block_type_names()` returns 44 including `document` | yes | **no — 43 names, no `document`** |
| the fixture's levels are 1-based | yes | yes, 1–4 over 172 rows |
| the fixture carries a `document` root | yes | **no** |
| the level-0-root ruling is Teague's | no | second-hand, needs confirming |

**The installed extension predates `e00db698`.** `LOAD duck_block_utils` succeeds and returns 43
type names without `document`, so this machine has the older build and Task 13 cannot be written
against a `document` root until it is updated. `test/data/readme_blocks.parquet` was generated from
that build (`read_markdown_blocks('README.md')`) and has no root row.

### The decision Task 13 now needs

The plan's Task 13 takes the other road, explicitly: it declares `level := 'level - 1'`, says "No
ROOT: one document is one forest, and its top-level blocks are anonymous trees that are ordered
siblings of each other", and Task 4's offset-hint message was written to *recommend* `level - 1`
("if the source's levels are 1-based, declare LEVEL as 'level - 1'"). Those are two different
shapes, not two spellings of one:

- **`level - 1`** — a document is a FOREST of anonymous top-level trees. Works against the current
  fixture today. No ROOT slot.
- **explicit `document` root** — a document is ONE tree with one root. Needs the newer extension,
  a regenerated fixture, and changes what the suite's sibling records mean, because the top-level
  blocks become children of a root rather than roots themselves.

The second also interacts with R0: a relation holding several rooted documents needs ROOT to tell
them apart, where the forest reading needs none. Left open deliberately — it is a design call, and
the plan's text and the hint message both point the other way, so it should not be changed by
inference from a relayed message.

### Closed the same day, by `test/sql/45_duck_blocks.test` (commit `41599ee`)

The measurements above stand — the installed extension really does return 43 type names with no
`document`, and `readme_blocks.parquet` really has no level-0 row (`min(level) = 1` over 172 rows,
which suite 45 now asserts as a premise rather than assuming). Three conclusions drawn from them
do not:

- **"Task 13 is not started."** It is written. Suite 45 declares the fixture as a tree and pins
  `h2` → 9 rows, `document > table` → `[69, 132, 150]`, `h2 + table` → `[132, 150]`, and
  `section h2 + table` → 0 rows. Expected answers were computed independently in Python from the
  parquet (nearest-preceding-lower-level parent, then adjacent siblings) *before* being run
  through duckent, and the two agreed.
- **"Task 13 cannot be written against a `document` root until the extension is updated."** It
  can, and was, with the extension exactly as measured above. The level-0 row is synthesized in
  the declaration's own source SQL — `SELECT 'block' AS kind, 'document' AS element_type, …, 0 AS
  level, …, -1 AS element_order UNION ALL BY NAME SELECT * FROM readme_blocks.parquet`. The
  blocker was read as "the extension must emit the root"; the actual requirement is only that the
  *relation handed to duckent* have one, and a relation is something you can write. This is the
  lesson worth carrying out of the entry: an inbound report's blocker is a claim about the
  upstream, not about what you can declare over it.
- **"Left open deliberately" — the design call is made, for the explicit `document` root.** Suite
  45's own header states the reasoning and rejects the `level - 1` road in writing: shifting the
  levels "also happens to pass today, but only because P13 then sees every top-level block as its
  own level-0 root; that is issue #9's territory, not a second valid encoding". The prepend is
  also what makes `document > table` expressible at all — without the root row those three tables
  have no parent and the selector has nothing to anchor to, which is the positive case for the
  root rather than an argument against the alternative.

So the "second-hand, needs confirming" row in the table above is settled, and by the right route:
not by accepting the relayed ruling, but by building both shapes far enough to see that only one
of them is an encoding. The verification doctrine worked — the ruling was held as unconfirmed
until something in this repository could decide it.

One thing the suite adds that this entry did not anticipate: the fixture's provenance now moves.
`gen_readme()` returns the markdown extension version *and* a sha256 of `README.md`, because
unlike the two astcss-eval fixtures pinned to external commits, this one drifts whenever the
README is edited — which it had been doing with nothing recording it. `test/data/FIXTURES.md`
carries both as `unrecorded` rather than values filled in by hand, and says why: the committed
parquet predates the provenance, and regenerating just to populate the fields would rewrite it
from today's README and move the row counts other suites assert.

## M2 differential adjudications

The corpus import (`test/import_astcss_eval.py`) runs all 108 accepted astcss-eval pairs against
their frozen references. References are never edited: where we disagree, the row is adjudicated
here, and only a row adjudicated **against** upstream loses its assertion (it is tagged
`divergent:<reason>` in `test/corpus/astcss_eval.jsonl` and `41_differential_sitting_duck.test`
emits it as a commented no-op naming the reason). 107 of 108 references are asserted and pass.

- **`lambda` on `repo-small-py` (t1-p21) — 2 rows here, 3 in the reference; the reference is
  wrong. Tagged `divergent:sd-type-prefix-match`.** The reference's extra node is
  `update_test_names.py:247`, whose `type` is `lambda_parameters`, not `lambda`. Reproduced live
  against the installed sitting_duck on the same fixture: `ast_select_from(rs, 'lambda')` returns
  3 rows, `ast_select_from(rs, 'lambda_parameters')` returns exactly that node, and the probe
  `ast_select_from(rs, 'lambd')` returns **both** types — so sitting_duck's bare type selector is
  a *prefix* match, not equality. (`with` likewise selects `with_item`, `with_statement`, `with`
  and `with_clause`; `while` selects `while` and `while_statement`.) A css type selector is
  equality on the node type — `lambda` cannot silently mean `lambda*` — so duckent's 2 rows are
  right. This is not one of the tracked issues (#127, #128, #130, #133, #134, #141); it is a new
  upstream bug, and the reason the corpus's other bare-type rows (`with_statement`,
  `while_statement`, `decorated_definition`, `continue_statement`) pass is only that no other
  type in those fixtures shares their prefix. *(2026-09-15, PR #2 fix wave: **filed upstream as
  sitting_duck #151** — https://github.com/teaguesterling/sitting_duck/issues/151. The corpus tag
  stays `divergent:sd-type-prefix-match`; the M2 design's §5.1 footgun table carries the row.)*

- **`.import` and issue #139, an inheritance note rather than a divergence.** sitting_duck #139
  says a `.class` selector matches the sub-nodes of the construct it names and misses the
  construct itself. duckent's `CLASSES` is **declared data**, so nothing here decides that — but
  our fixtures' `css_classes` column was generated *from sitting_duck* at fixture time
  (`test/gen_fixtures.py`), so it reproduces sitting_duck's alias test as it stood. The corpus
  rows that use `.import` (t1-p06, t3-p10, t3-p11, t3-p22) therefore **inherit #139's semantics
  by construction**, and their frozen references agree with us for that reason and not because
  the semantics are right. Recorded so that regenerating the fixtures against a fixed upstream
  reads as a change to the DATA, not as a break in the matcher.

- **Embedding multiplicity, not a divergence: `.import ~ .class` (t3-p11, 9 rows vs 3),
  `.import ~ .fn` (t3-p22, 126 vs 27), `.fn ~ .class` (t3-p38, 6 vs 5), `.loop .call#print`
  (t3-p39, 20 vs 19).** The node *sets* are identical in all four; only the row counts differ.
  duckent's match is a join and its contract is "one output row per full-pattern embedding"
  (core design §6.3) — that is what makes a `@capture` a joinable relation alias — so a node with
  three preceding `.import` siblings is three rows here and one row in sitting_duck, which emits
  the subject set. The M2 design already specifies the sitting_duck differential as *identical
  `(file_path, node_id)` sets, checked by `EXCEPT` in both directions* (§8), so
  `41_differential_sitting_duck.test` aggregates its keys from `SELECT DISTINCT file_path,
  node_id`. That is a projection of our bag to its set, not a relaxation of the reference: the
  key list and the sha256 are still compared against the reference verbatim.

- **Scoping note for `41b_live_sitting_duck.test`: the installed sitting_duck has regressed on
  issue #127.** All 31 corpus rows whose chain has a combinator (`.loop .call`, `.mod > .fn`,
  `.import + .import`, …) return **0 rows** from today's `ast_select_from`, while their frozen
  references — captured on the `sd-20260914-1835` build, which had #127 fixed — carry 21, 26 and
  16 nodes. duckent matches the *frozen* references on all 31 (modulo the multiplicity above), so
  41 keeps them; 41b covers the 76 single-compound rows the installed engine still answers, and
  lists the skipped rows with their reason at the foot of the file. When upstream is fixed again,
  deleting the `top_level_combinator` skip in the importer and regenerating restores full live
  coverage.

## Mutant kill map corrections

The M2 design's §9 mutant table names a killing suite per mutant. Planting the nine remaining
mutants (task 12) showed six of those rows are wrong or incomplete. Every line below was
established by running `python3 test/run.py <suite> --mutant test/mutants/<file>` on the suite in
question, in both directions where a suite was expected to fail and did not. The manifest
(`test/mutants/manifest.yaml`) is the live record; this is the reasoning behind it, and the M2
design's §9 table now carries the corrected rows *(done 2026-09-15)*.

*(2026-09-15, M3 Task 6: the MN03 row below is HISTORY. That mutant was retired when the `__s`
stage it edited was restructured into `tree_sql_size_join()` — its edit was textual and no longer
had text to plant. The id is not reused for the same claim: M3 Task 9 re-plants MN03 as a
different mutant in `sql/07_match.sql`. Its CLAIM is carried from M3 Task 7 by **MN04**, which
plants the same edit on the restructured line; the mutant count is 18. The reasoning in the
MN03 paragraph below is kept because it is about 40 and 41's blindness to a symmetric change,
which is a fact about those suites rather than about the retired mutant.)*

*(2026-10-05, M3 Task 9: MN03 is now PLANTED, as the module-boundary mutant M3's gate names, and
the count is 20. The edit is one line of `tree_compile_match`: `has_element` -- the flag that picks
between the element-scan sibling form and the O(1) `_pre + _size + 1` form -- gains a disjunct
asking `tree_catalog.slots` whether SIZE is DECLARED. The compiler then chooses its compiled form
by which O columns happen to be declared rather than by what the S group says. It is not a wrong
answer; it is a wrong DEPENDENCY. The matcher reads the PROJECTION, which supplies `_size`,
`_parent` and `_children` whether they were declared or derived, so it has nothing to consult.*

*No result differential can see it, by construction: the two forms agree on a conforming tree,
because `_element` is true on every row of a tree that declares no ELEMENT, so "the nearest element
sibling" and "the row at `_pre + _size + 1`" are the same row. Only the compiled TEXT moves -- and
only for an ELEMENT-less tree, because with ELEMENT declared both trees already take the
element-aware path and there is nothing to differ. That is why 42 carries a THIRD and FOURTH tree,
`app_declared_plain` and `app_derived_plain`: the existing pair declares ELEMENT, so the O(1)
sibling and positional fragments are never compiled in it at all. Measured on `main` before the
pair existed: the next-sibling fragment on `app_declared` matches `_element` and does NOT match
`_size + 1`.*

*Measured, not asserted, after the F14/MN21 precedent recorded below: under the mutant 42 is the
only file that fails and 23 pass, and within 42 exactly THREE records fail -- three of the four
ELEMENT-less plan records, not four. The `.fn:has(string)` one does not move, because the
descendant relation does not branch on the element flag at all. That record is a guard against
other mutations of the plan rather than a discriminator for this one, and the manifest keeps it on
that footing instead of counting it as part of the kill.*

*A note on how this landed, because the manifest is supposed to record what a mutant does rather
than what one hopes it does, and the same applies to how it got there. MN03 was implemented twice.
The version above is the earlier one (2026-10-01), which sat unmerged on a local branch. A second
implementation was written and merged first (#24) without that branch being checked: it planted an
arithmetically inert `+ 0` respelling of the subtree arithmetic and compared compiled text across
the ELEMENT-declaring pair only. It was killed by its own record, but it could not have seen a
boundary violation in the sibling or positional fragments, which is where one is most likely --
those are the fragments that legitimately branch. #26 replaced it with this one. One id, one
meaning.)*

| mutant | §9 says | actually killed by | why the difference |
|---|---|---|---|
| MN03 *(retired, M3 Task 6)* | 42 | **42 only** | 40 and 41 PASS, although both declare SIZE — see below |
| MN04 *(M3 Task 7, carries MN03's claim)* | — | **11_ddl, 12_dml, 42**, and 31, 32, 33, 34, 37, 38, 40, 41, 41b, 43, 44 | O conformance refuses a declared SIZE at CREATE, so every suite that builds a SIZE tree now fails — the exact reverse of MN03's near-invisibility |
| MN05 | 40/41 | **40, 41, 34_groups** | table is right; 34 is a third witness |
| MN07 | 40 | **40, 37, 31, 34, 36** | only after corpus row c17 was added; 41 PASSES |
| MN08 | 44 | **44, 37** | — |
| MN12 | 40 | **36_pseudo only** | no corpus tree declares a pseudo a `sel_*` could shadow |
| MN13 | 40 | **35_attr_map** | the `'9'` vs `'10'` row moved to 35 before this task |
| MN22 | 40 | **44_parsers** | 40 never reaches the SQL lowering |
| MN24 | 40 | **34_groups, 38_css_lower** | 40 cannot see a symmetric printer mutation |
| MN25 | 43 | **43** | only after `rep_class_none` was added; the promotion records alone cannot discriminate |

Three of these are the same lesson, and it is worth stating once: **a differential suite cannot see
a mutation that moves both of its sides.** 40_corpus compares two SPELLINGS of one selector against
each other on ONE tree.

- **MN22** (the css lowering reads `tree_state`) is invisible to 40 because 40's
  `language := 'css'` selectors are rewritten by `test/run.py`'s `rewrite_selectors`, which calls
  the RUNNER's parser (`test/css_parser.py`). No record in 40 reaches `tree_css_lower` at all. The
  suite that runs the SQL front-end is 44_parsers, which is where the bait row lives.
- **MN24** (the printer omits NOT groups) is invisible to 40 because its printed-TREEQL records
  compare `tree_selector_to_treeql(<ir>)` with `tree_explain(...).treeql` — both sides go through
  the same printer, so a symmetric mutation cancels. Only a record comparing the print against a
  FROZEN literal catches it: 34_groups and 38_css_lower have those.
- **MN03** (a declared SIZE compiles one short of a derived one) is invisible to 40 for the same
  reason — both spellings run against the same tree, so a shortened `_size` moves both key lists
  identically. It is invisible to 41 for a different reason: a range one short drops only a
  subtree's LAST descendant, and on these fixtures that row is almost always an anonymous token no
  selector can name. That is the same fact that made 42 write `SIZE_WITNESS` (`attribute
  identifier`) by hand rather than rely on the corpus. 42 is the only suite that sees MN03, and it
  sees it twice: on the record comparing the two projections column for column, and on
  SIZE_WITNESS. (This entry exists because the first version of MN03's manifest row claimed 40 and
  41 as `also_kills` without running them. They pass. F14/MN21 precedent: a manifest states what a
  mutant does, not what one hopes it does.)

Two mutants had nothing in the suite that could kill them, so the corpora gained bait, each
commented in place with the mutant it serves:

- **MN07** — no corpus row carried an unknown pseudo-class (the 108 astcss rows use only `:has` and
  `:not`). Hand-corpus row **c17**, `.fn:not(:nope)`, was added. The unknown name sits inside a
  `:not()` because a compound carrying one directly matches no row, and 40's records are written so
  that an empty match FAILS rather than passing vacuously.
- **MN25** — 43's two promotion records cannot discriminate: on `rep_class` every `def` row already
  has a non-empty CLASSES list, so a fallback that fires only on an empty one never fires. Tree
  `rep_class_none` (binds `def` as a PSEUDO, declares `classes := '[]::VARCHAR[]'` — the live
  declaration in `test/sql/43_representation.test` reads `tags := '[]::VARCHAR[]'` since the
  rename) was added, with
  a record asserting `.def` selects nothing there while `:def` still selects every def.

And one mechanism: **MN08** mutates the runner's css parser, which is Python, not a macro, so no
`CREATE OR REPLACE MACRO` override can express it. `test/mutants/manifest.yaml` rows may now carry
an optional `env:` map that `test/run_mutants.py` adds to each subprocess environment; the mutant's
SQL file is comment-only, so every mutant is still one id, one file, one row.

Two mutants are also shaped differently from the §9 table's sentence — three, counting MN13 below
— for reasons the spec text now carries *(done 2026-09-15)*:

- **MN3** as §9 words it ("the compiler reads `_size` through a fragment that consults
  declared-versus-derived status") would die trivially: a fragment that reads the catalog cannot be
  spliced into `query()`, which is where the projection text goes. The planted mutant is instead a
  copy of `tree_compile_projection` whose DECLARED size branch is `CAST(a.__size_raw AS BIGINT) - 1`
  — the smallest edit that makes a declared O column diverge from its derived default.
- **MN22** is a one-fragment override of `tree_css_path` (the fragment stage 9 of the lowering calls
  for every emitted row) rather than a copy of the whole 365-line `tree_css_lower`, which §9's last
  paragraph anticipates. The state read still happens where the lowering decides where a row goes.
- **MN13** drops the typed cast by casting the LITERAL to VARCHAR rather than by removing
  `TRY_CAST` outright. Removing it outright is a *binder* error in 1.5.5 ("Cannot compare values of
  type VARCHAR and type INTEGER_LITERAL"), which would make MN13 a loud mutant that any suite
  comparing a map against a number kills. Casting the literal instead is the plausible wrong
  implementation: it binds, it runs, and it answers that `'10'` is not greater than `9`.

## M3 Task 7: O conformance at ingest, and the one thing it cannot see

O conformance (spec §3.1) compares each declared O column against the value the derivation would
have produced, RAISES on the first disagreement at ingest, and RECORDS the same comparison as a
`tree_state.assertions` row from `tree_check`. Both halves read one fragment,
`tree_sql_o_bad_cte`, so the verb that refuses and the verb that reports cannot come to disagree
about what a disagreement is.

### The ORDER value is named only when the projection carries it

The refusal names `ORDER <v>` by reading the ORDER column off the projection, which is possible
only when ORDER is a plain column *and* ATTR is open (`*`). A computed ORDER (`node_id + 1`) or a
closed ATTR list leaves nothing to read, and the message then gives the position alone
(`tree_sql_o_order_col`). That is the one place this refusal says less than §3.1 asks for; the
position identifies the row unambiguously either way.

### A declared NEXT that names no row is invisible to conformance — deliberately

*(2026-10-06: **this entry's decision was reversed.** Commit `6a53d37` (#44, closing #39) makes
such a NEXT a violation. The measurement and the three options below are kept as the record of
what was true and what was considered — the closure, and the one option that turned out to be
reachable after all, are at the foot of the entry.)*

`sql/02_projection.sql` compiles a declared NEXT as `COALESCE(nx._pre, a._pre + a._size + 1)`.
When the declared value names no row, the COALESCE substitutes the structural successor — which
is exactly what a *conforming* NEXT produces — so the two are indistinguishable in the
projection's OUTPUT, and conformance sees only the output (ingest is handed
`'(' || proj_sql || ')'`, and the raw `__next_raw` is EXCLUDEd). No comparison over that relation
can tell them apart. The options, and why each was rejected:

- **Publish `__next_raw`, or a `_next_matched` flag.** Both add a column to every projection and
  therefore to every materialized tree's stored table. That is the cost that stands, and it is
  enough on its own. *(An earlier version of this note also claimed both break 10_projection's
  record that no `__%` column reaches the output. That is true of `__next_raw`, which is
  double-underscored, but NOT of a single-underscore `_next_matched`, which the record's
  `LIKE '\_\_%'` does not match. Corrected in fix round 1.)*
- **Compare against the source relation.** Not reachable: ingest passes the projection as
  `rel_sql`, so this needs a signature change at every call site.
- **Drop the COALESCE fallback**, so an unmatched NEXT is NULL and `IS DISTINCT FROM` catches it.
  That is a §2.2 semantic change ("one that names no row keeps the structural successor") pinned
  by three 10_projection records — out of scope for this task, and a spec question rather than an
  implementation one.

**Decision: left open.** The cost of closing it is permanent and paid by every tree; the benefit
is a diagnostic for a case that cannot produce a wrong answer. A declared NEXT naming no row
yields the *correct* structural successor, so unlike a wrong SIZE, PARENT or CHILDREN it degrades
to the derived tree rather than to a corrupted one — a declaration typo, not the corrupted
encoding §3.1 is about. `sql/02_projection.sql` previously claimed "§3.1 then counts as a
disagreement"; that was false and could not be made true without one of the above. The comment now
says what actually happens.

**Closed 2026-10-06, commit `6a53d37` (#44, closing #39): it IS a violation, and the route taken
is the one rejected above as "not reachable".** The second option — compare against the source
relation — was rejected here on the grounds that "ingest passes the projection as `rel_sql`, so
this needs a signature change at every call site". That reasoning confused two things: the
comparison does not need the *source*, it needs the source **columns**, and the projection carries
them whenever ATTR is open. So a second NEXT arm reads the raw declared value straight off
`rel_sql`, with no signature change, no new projection column, and `tree_canonical_columns()`
untouched. The commit message quotes this entry's sentence to argue against it, which is the
honest way to reverse a finding.

**What the cost argument got wrong** was not the cost but the claim that there was nothing to buy:
"a diagnostic for a case that cannot produce a wrong answer" is true of the *projection output*
and false of `tree_state.assertions`. `tree_check` was recording `assert_o_next = 'ok'`,
`'0 disagreeing rows'` for a declaration nothing had compared — a positive verdict published to a
table whose whole purpose is to be read back. That is a wrong answer, in the only place the user
sees one.

**The discriminator is structural, and it is why "refuse an unresolvable NEXT" would have been
wrong.** Unresolved is not itself false: `with_next`, the suite's own *conforming* declared-NEXT
fixture, declares `node_id + descendant_count + 1`, and seven of its rows name no row — the root's
last row and every ancestor whose subtree ends with it — all correctly. The violation is
unresolved **and** the derivation naming a real row of the same root (`__dnext <= the root's max
_pre`): the declaration says nothing follows while the structure says row N does. Measured, an
all-`999` `next_id` on the 4-row reference tree:

```
O conformance violated in tree docs.n999: NEXT disagrees with its derived default at root
{'file_path': f.py}, ORDER 2 (position 1): declared names no row (999), derived 3
(a corrupted encoding, not a fast path)
```

**The residue this does not close, and it is the right answer rather than a gap.** Where neither
the declared nor the derived NEXT names a row, the two agree and `ok` is honest — the last row of
a root has no successor to disagree about. The same residue `assert_o_parent` carries on ROOT
rows, where the derived parent is NULL too. So no third assertion status: once the derived default
is in the comparison the harmful case is verifiable and *false*, which `violated` already says,
and a third status would advertise a gap that no longer exists.

Two gates, both narrowing rather than weakening: the arm runs only when ATTR is open and the NEXT
and key expressions are plain identifiers (`tree_sql_o_next_readable`), exactly as
`tree_sql_o_order_col` already gates naming the ORDER value — a level-basis tree with no ORDER
resolves against `__seq`, which is not a source column. No declared-NEXT tree in the suite has a
closed ATTR, so the gate costs nothing today; where it is off the arm simply does not run. And it
is **strict on NULL**, consistent with SIZE and CHILDREN, which refuse a NULL override outright: a
declared O column is total.

### Plan defect found and corrected

The brief's `__bad` CTE aliased only its FIRST arm (`SIZE`) — `AS slot, AS k, AS pos, …` — and
left the PARENT, CHILDREN and NEXT arms positional. A `UNION ALL` takes its column names from its
LEADING branch, and which branch leads depends on which slots the shape declares, so any shape
declaring CHILDREN or NEXT *without* a SIZE built a `__bad` whose columns were named `'CHILDREN'`
or `'NEXT'`, and `ORDER BY k, pos` died with a Binder Error. Every arm now carries the full alias
list; 11_ddl's `with_children` and `with_next` records are the shapes that have no SIZE, and they
are what catch it.

### `assert_order` is reachable and tested as of this task

`tree_dml_context` refused projection-mode trees for every verb, so `tree_compile_check`'s ORDER
assertion could not be run by anything — dead scaffolding since Task 4. The refusal now applies
only when `verb <> 'tree_check'`, and the context carries a `rel:` field (the table for
materialized trees, the projection macro call for projection-mode ones) so a read-only check never
reaches for a table that does not exist. `assert_p13` reads `rel` rather than `tbl` for the same
reason: lifting the refusal without that change turns dormant scaffolding into a live
`Catalog Error: Table with name t_… does not exist`. 12_dml's `scripts_pm` record covers all
three artifacts.

## Spec deviations in this milestone

Where the prototype knowingly differs from `docs/superpowers/specs/2026-09-13-duckent-core-design.md`. Each is a deviation to carry forward or close in M2, not an accident. *(2026-09-15: both specs were amended at the close of M2 and now carry the surviving items in place, marked "(amended 2026-09-15, M2 build)". This list stays as the record of what moved and why — a spec that has been corrected no longer shows where it was wrong.)*

- `tree_state.partitions.root_key` is `VARCHAR` (the ROOT struct cast to text), not the STRUCT §2.2 describes; one column type serves every tree's ROOT shape. Tests compare against `{...}::VARCHAR` renderings.
- `tree_catalog.compiled` records only the `projection` artifact. `encoder`, `ingest`, `assert_p13` and `assert_o_<slot>` rows are not written. *(2026-10-08: **two** artifacts are written, not one — `attribute_columns` has been written beside `projection` since M2 added it (M2 design §10), and `SELECT DISTINCT artifact FROM tree_catalog.compiled` after one create returns both. The four §2.1 artifacts named above are still not written, which is what this deviation is about. The M3 design §7.9 listed correcting this line as done; it was not, until now.)*
- `tree_compile_encoder`, `tree_compile_ingest` and `tree_compile_assertions` do not exist as separate compilers: the encoder is a branch of `tree_compile_projection`, ingest is `tree_compile_insert`/`_replace`, and the P13 assertion is `tree_compile_p13` called from create, the DML compilers and `tree_compile_check`.
- ~~`tree_explain` and `tree_compile_match` take no `language` parameter; `_match_language` is the constant `'treeql'`.~~ Closed in M2: both take `language :=`, and `_match_language` is `COALESCE(language, 'treeql')`. The compiler does not read `tree_catalog.settings` for it -- that row governs how a front-end parses selector *text*, and a selector handed over as IR was never parsed.
- The levels fixtures §7 names (`levels_*.csv`) are an inline `walks` table in `test/sql/20_derivations.test` instead of generated CSVs.
- `coa.csv` and `ledger.csv` are committed for M2 and unused by this milestone's suite.
- ~~The match compiler is a linear chain over `lag(alias)`, not the `WITH RECURSIVE … USING KEY` bottom-up fold of §6.1.~~ Closed in M2: it is a bottom-up fold over the IR, but unrolled to `tree_group_depth_limit()` group levels rather than run as a `USING KEY` recursion — the readiness test that shape needs is a `recurring.<cte>` reference inside a correlated `NOT EXISTS`, which 1.5.5 refuses (see the design-phase findings). The number of levels is fixed by the IR's own ceiling, so the unrolling is total, and `sql/06_selector.sql`'s printer is unrolled the same way for the same reason.
- `tree_ddl_alter` refuses outright when a materialized tree holds partitions ingested after create (C1 below), which §4 does not mention.
- ~~An unknown attribute name in a match refuses through DuckDB's binder, not through a compile-time check against `_attr_map`.~~ Closed in M2: `tree_sql_clause` resolves an attribute against the `attribute_columns` artifact first, then against `ATTR MAP` with a cast implied by the comparison literal, and refuses at compile time naming the attribute when neither serves it. Note the limit of "neither serves the name": a map's keys are data, so on a tree that declares `ATTR MAP` every name is servable and an absent key reads as no match. §6.1's compile-time refusal can only ever mean "no projected column and no map".
- Coverage note (M2 task 11, `test/sql/42_second_differential.test`): a wrong SIZE or CHILDREN is all but invisible through selectors. `_children` is read by no fragment in `sql/07_match.sql` or `sql/08_traversal.sql` (it appears only in `tree_canonical_columns()`), and `_size` is read by `tree_sql_subtree` plus the O(1) sibling/positional forms — which a tree that declares ELEMENT never uses, because those fragments then scan for the nearest *element* neighbour instead. On `app.parquet` that leaves exactly one selector whose answer moves when SIZE is perturbed by one (`attribute identifier`: app.py:50 is the last descendant of its `attribute`). 42 therefore compares the declared and derived *projections* column for column as well as running the corpus selectors; a suite that only ran selectors would not have caught a broken derivation of either column. **Updated by M3 Task 8:** `tree_sql_last_child`'s non-ELEMENT branch used to scan for a later sibling and read no `_size`; it now asks whether the row at `_pre + _size + 1` is a sibling, so `:last-child` on a tree that declares no ELEMENT is size-sensitive where it was not before. That widens selector visibility of a wrong SIZE slightly — the count of app.parquet selectors whose answer moves under a one-off perturbation was measured before this change and is no longer known to be one. It does not weaken the reason 42 compares projections column for column.
- Mutant coverage: the derived parent join's `a._root = b._root` scoping is now covered by a test in `test/sql/10_projection.test` over `scripts.parquet`, but no mutant id is reserved for it (MN22–MN25 are already assigned by the handover). It is recorded as `also_kills` under MN02 in `test/mutants/manifest.yaml`; if the convention later allows a new id, that is the mutant to plant. *(2026-10-08: the parenthetical names the wrong source. **The handover's mutant catalogue stops at MN21** — `docs/11-duckent-handover-v21.md` lists MN1 through MN21 and no further id. MN22, MN24 and MN25 are assigned by the **M2 design §9**; MN26 was assigned by M3 on 2026-10-03. So the "if the convention later allows a new id" has since been answered yes — MN26 is one — and the derived-parent root scoping is still the candidate it names.)*

## 2026-09-14 review of PR #1

Sixteen defects, each confirmed by live reproduction before the fix and covered by a test that failed first.

- **F1 `tree_ancestors` aborted the process on a projection-mode level-basis tree.** The recursive CTE inlined the projection macro, whose derived-parent ASOF join 1.5.5 refuses inside a recursive CTE ("AsOf joins are not supported in recursive CTEs yet"), and the process then died with a corrupted heap; ancestors are now the rows whose `(_pre, _size)` range contains the node, with no recursion at all (`sql/08_traversal.sql`).
- **F2 positional `INSERT` misfiled reordered attribute columns.** `tree_insert`/`tree_replace` wrote `INSERT INTO <tbl> SELECT * FROM __duckent_new`, so a source listing the same columns in another order silently swapped same-typed values (857 of 857 rows in the covering test); both use `INSERT ... BY NAME` now (`sql/04_dml.sql`).
- **F3 the canonical-prefix guard missed implicit and quoted aliases.** The regex only sees an explicit `AS _x`, so `CAST(depth AS BIGINT) _size` walked straight through; create, alter, insert and replace now also DESCRIBE the compiled relation and refuse when DuckDB has renamed a displaced canonical duplicate to `_size_1` (`tree_sql_shadow_check` in `sql/00_types.sql`).
- **F4 generated object names collided.** `('a_b','c')` and `('a','b_c')` both compiled to `proj_a_b_c`, so the second create replaced the first's macro and either drop took out both; `tree_sql_object_name(kind, sch, nm)` length-prefixes the schema — `proj_<len(sch)>_<sch>_<nm>` — which is injective (`sql/00_types.sql`, used everywhere). Doubling the underscores, the first attempt, was not: `('a_','c')` and `('a','_c')` both double to `a__c`, and the re-review caught it.
- **F5 a NULL `abstract` or a NULL pseudo body silently dropped required statements.** Both compiled an interpolated statement to NULL, which `list_filter` then removed, leaving a catalog row with no table or a table with no catalog row; both refuse now, and the create statement list fails closed if BEGIN, the trees INSERT, the slots INSERT or COMMIT is NULL (`sql/00_types.sql`, `sql/03_ddl.sql`).
- **F6 `tree_ddl_alter` rebuilt storage from `source_sql` whatever the data had done.** Alter changes S only, so any drift between the source and `tree_state.partitions` — a root the source gained, a root whose row count changed — now refuses naming the drifted roots, alongside the existing C1 refusal, and alter emits the P13 and shadow checks create emits (`sql/03_ddl.sql`).
- **F7 `next`/`after` compared `b._parent = a._parent`.** That is NULL for every level-0 row, so the root rows of a partition were never each other's siblings; both use `IS NOT DISTINCT FROM`, as `tree_next_sibling` already did, and §6.1 of the spec now says so (`sql/07_match.sql`).
- **F8 ingest ignored the frozen-order guard.** Create refuses `order_source = 'frozen'` while `preserve_insertion_order` is off, but `tree_insert`/`tree_replace` would happily freeze an arbitrary scan order into `_pre`; they emit the same refusal now (`tree_sql_frozen_guard`, `sql/04_dml.sql`).
- **F9 a LIKE child's `has_semantic` was read off the parent's TYPE slot.** A parent declaring only ID produced a child whose every S clause refused with "has no SEMANTIC group"; the child now inherits the parent's own `has_semantic` (`sql/03_ddl.sql`).
- **F10 the `§` placeholder rewrote user text.** The clause compiler emitted `§` and the caller replaced it with the step alias, so a WHERE or an ID containing `§` was silently rewritten to `s1`; the alias is a parameter of `tree_sql_clause` now (`sql/07_match.sql`, MN19 follows).
- **F11 `tree_compile_alter` on a nonexistent tree returned NULL.** The existence check lived inside `FROM c WHERE ok`, which has no rows when the tree is missing, so the executor got nothing to run instead of a refusal; the check is evaluated outside the FROM (`sql/03_ddl.sql`).
- **F12 `tree_compile_match` returned NULL for an empty selector or an empty overlay, and ignored an overlay's ATTR.** All three refuse: "selector has no steps", "semantic overlay is empty", and a per-query overlay cannot add attribute columns (`sql/07_match.sql`).
- **F13 a user alias `s<N>` collided with the generated step aliases.** `tree_steps` refuses an `as` matching `^s[0-9]+$` (`sql/06_selector.sql`).
- **F14 MN02's manifest claim was false for `20_derivations.test`, and `tree_encode` qualified only the first sibling_order column.** `tree_derive_parent` held its own copy of the parent-join text, out of the mutant's reach; it now builds the join from `tree_sql_parent_join()` and MN02 is killed by both listed tests. `tree_encode` qualifies every sibling key column, so a second column no longer binds to the walk relation (`sql/05_derivations.sql`).
- **F15 a `semantic :=` pseudo overlay replaced the whole `_pseudo` map.** Every catalog pseudo-class was orphaned for that query; the overlay is `map_concat(_pseudo, <overlay>)`, which keeps the catalog's bindings and lets the overlay win on a shared name (`sql/07_match.sql`). *(The column is now `_predicate`, so the live fragment reads `map_concat(_predicate, <overlay>)`.)*
- **F16 DML verbs on an abstract tree failed with a raw catalog error.** An abstract tree records `storage = materialized` but owns no table; `tree_dml_context` refuses first, naming SHAPE ONLY (`sql/04_dml.sql`).

Deferred cleanups the review named, not addressed here:

- `tree_sql_size_expr` is O(n²) — the review measured 0.64s at 20k rows and 2.52s at 40k. The M3 replacement is a per-level ASOF form (and the C++ port's stack walk).
- Create and alter run the compiled projection more than once: once per guard plus the materialization. This wave made it worse on purpose (the shadow check and, on alter, the drift check each re-run it); the guards are cheap to fold together once a compiled artifact is materialized first and the checks run over it.
- `tree_shape_from_catalog` is called three times per LIKE create (merge, missing-check, and the S inheritance read).
- MN21's manifest also claimed `test/sql/31_match.test`, which it never failed (the R-only match test there uses WHERE clauses only, so the lost TYPE default never shows); the claim was corrected to `test/sql/11_ddl.test` alone in this wave. A manifest states what a mutant does, not what one hopes it does.

## 2026-09-13 final-review fix wave

- `tree_ddl_alter` on a materialized tree rebuilds the projection from `trees.source_sql` alone, so every partition added afterwards by `tree_insert`/`tree_replace` would be dropped by the `CREATE OR REPLACE TABLE`. The wave's ruling is to refuse, naming the count of partitions "ingested after create". Lifting the refusal needs per-partition ingest provenance (the source text, or at least the relation, recorded per `tree_state.partitions` row) so alter can re-derive each partition from what produced it; that is M2 work and stays an **open decision** until the partitions table carries it.

## 2026-09-13 design-phase findings (DuckDB 1.5.5)

- `query()` refuses text produced by a macro containing any subquery ("Table function cannot contain subqueries"), so a macro that reads the catalog cannot feed `query()`. Consequence: in the macro phase the runner executes compiled `tree_match` and DDL; pure string-building compilers (projection, derivations) still run through `query()`.
- Inside a recursive CTE with several `UNION ALL` branches, everything but the last branch is the base case. The recursive term must be one SELECT, and `recurring.<cte>` is legal only in FROM-clause position, never inside a correlated EXISTS.
- sitting_duck's `depth` is UINTEGER; `depth - 1` overflows. All canonical `_pre` and `_level` are cast to BIGINT.
- Derived `_parent` by ASOF join and derived `_size` by nearest-following-shallower-row match sitting_duck's native `parent_id` and `descendant_count` on every row of `app.py` (54/54).
- Partial struct casts to a custom type fill NULLs and silently drop unknown fields; the named-parameter constructors exist to catch typos.
- `MAP[...]` bracket access returns the value directly (NULL when missing); `SELECT alias FROM ...` yields the row as a STRUCT; `* REPLACE` and `* EXCLUDE` are available. The arrow lambda is deprecated in favor of `lambda x: ...`.
- Shipped `ast_select` accepts only a type, `#id`, or `.class` inside `:has(...)`; `.fn:not(:has(:docblock))` is unsupported there, so the shared corpus for M2 uses `.fn:not(:has(string))` on the sitting_duck side.
- `query()` refuses text from a macro whose body contains any SELECT, even `(SELECT 'x')` with no FROM; only pure expression macros (CASE, COALESCE, string concatenation, list functions) can feed it. `tree_compile_projection` is written that way for this reason; `tree_compile_match` and the DDL compilers read the catalog and are executed by the runner instead.
- `row_number() OVER (PARTITION BY x)` with no ORDER BY does not preserve scan order on 1.5.5; `row_number() OVER ()` does. Frozen order therefore computes `__seq` with the empty window first and orders the partitioned row_number by it.
- Inside macro bodies, struct field access must be parenthesized: `(shape).level`, not `shape.level`, or the binder may resolve it as table.column; inside lambdas an unparenthesized `p.name` was observed to yield the literal string 'p.name'.
- A subquery anywhere inside an expression that carries a lambda is refused ("Binder Error: subqueries in lambda expressions are not supported"), and macro inlining puts an argument's text inside the lambda. So a macro whose body uses `list_transform`/`list_filter`/`list_aggregate` (`tree_sql_pseudo_map`, since renamed `tree_sql_predicate_map`; `tree_sql_chain`) may not be handed `(SELECT ... FROM cte)` — nor an aggregate. `tree_compile_match` therefore carries its one-row settings as CTEs joined in (`cfg`, `ovp`) and aggregates a group's inner chain into a list column one CTE before rendering it.
- Declared O columns (parent, size, children, next) must be carried through the projection stages under hidden aliases (`__size_raw` etc.) because a closed or explicit ATTR list otherwise drops the source column before the stage that reads it.
- A runner-level lesson: a stub macro in a smoke test must be CREATE OR REPLACE because the real macro of the same name exists once the suite matures.
- Mutant lessons: a fragment macro can be shadowed by an earlier guard (MN17's delete predicate was already ROOT-restricted by the gone-partition computation), so the mutant had to override the whole compiler; and a mutant with no test surface survives silently (MN14 needed a multi-root match test).

## Open after M2

The triage list for the final review. None of these is a wrong answer today; each is a place the
code and the contract have not been made to agree, and each is written so the next reader can
decide rather than re-discover.

*(2026-09-15, final fix wave: the six items this list carried that the whole-branch review
promoted to Critical or Important are struck through below with what closed them. The rest stand,
and the wave added a few of its own.)*

**Element rows (D-N18), the half that was not finished.**

- The projection's `_next` column is **element-blind** — it is the raw structural next sibling
  (`_pre + _size + 1`) — while `tree_next_sibling` and the `next` combinator are element-aware.
  Nothing in the matcher reads `_next`, so nothing is wrong today; but the column and the
  relation of the same name mean different things, which needs either a comment saying so or a
  decision to make `_next` element-aware and pay for it.
- `tree_siblings` is unfiltered by element, while `tree_next_sibling`, `tree_prev_sibling`,
  `tree_first_child` and `tree_last_child` are. The same inconsistency, in the traversal surface
  rather than the projection. *(2026-09-15: still open as a decision, but no longer undocumented —
  the M2 design §4 sentence now names siblings as the exception and says why (the sibling set is
  the structural base the element-aware relations are built on), and `33_navigation.test` pins the
  current answer on the `elem` tree, so changing it means changing a record on purpose.)*

**Refusals that are narrower than they read.**

- ~~`tree_compile_alter` sets `has_semantic = true` unconditionally, so an alter that changes only
  ATTR marks an S-less tree as S-ful.~~ **Closed** in the final fix wave (I4): alter computes the
  flag from a per-slot expression (type / id / classes / attr_map / element / pseudo /
  pseudo_args declared, or the flag already there), never from the presence of a `semantic`
  argument and never from ATTR. ~~Create was not symmetric with it: its expression led with
  `(spec).shape.semantic IS NOT NULL`, so `tree_ddl_create(..., semantic := tree_semantic(attr :=
  'x'))` marked an S-less tree S-ful by the other road.~~ **Also closed**, in the same wave:
  create reads exactly the expression alter reads, and `11_ddl` and `13_alter` carry the twin
  records.
- ~~"semantic overlay is empty" ignores a `pseudo_args`-only overlay: such an overlay *would* bind
  the shared tier, so refusing it as empty is wrong, if harmlessly so.~~ **Closed** in the PR #2
  fix wave (R11): the question "does this SEMANTIC declare an S slot?" is one predicate,
  `tree_semantic_declares`, read by create, by alter and by the compiler's overlay check — the
  three hand-copied expressions had already drifted, and the compiler's was the one that had
  dropped `PSEUDO_ARGS`. Record in 36_pseudo.
- ~~The compiler does not police `SELF`'s position.~~ **Closed** in the final fix wave (I5): the
  compiler refuses a `SELF` that is not the lowest-id step under a `has`/`not` node, wherever the
  IR came from.
- `tree_steps_group`'s `self` guard covers only top-level inner steps. *(2026-09-15: unchanged,
  but no longer the last line of defence — `tree_compile_match` refuses the misplaced `SELF` the
  splice would let through, so the hole is a worse message rather than a wrong match.)*
- ~~An unknown-kind node that is **not under a step** (under the root, or under a group) is
  dropped by the compiler rather than refused.~~ **Closed** in the final fix wave (I5), together
  with three more shapes the fold reached through no link: a NULL kind anywhere, an orphan step or
  group, and the misplaced `SELF` above. One structural rule in `chk` says what may hang off what.
- ~~The printer's own unknown-kind check reads `min(kind)`, which is NULL when the offending
  node's `kind` is NULL.~~ **Closed** in the final fix wave (I5): the COALESCE is inside the
  aggregate and the node is named `<NULL>`.
- The shadow check (`tree_sql_shadow_check`) enumerates thirteen canonical columns in its regex
  and **only `_size` is exercised by a test** (11_ddl, 12_dml, 13_alter all use it). `_element` in
  particular was added in M2 and its arm has never fired in a test; a typo in that alternative
  would reopen the back door F3 closed, silently.

**Language and front-end.**

- ~~LIKE patterns are not `%`-escaped in either css front-end, so `[attr^=50%]` means more than it
  says. v0, in both, deliberately.~~ **Closed** in the PR #2 fix wave (R5): both front-ends escape
  `\`, `%` and `_` in the value and emit the pattern with `ESCAPE '\'` inside the clause's `arg`.
  It was not harmless after all — `[name$="_t"]` matched `greet` — and it took hand corpus row
  c11's TREEQL twin with it, which now spells the escape explicitly.

**Tests and mutants.**

- `44_parsers.test` FREEZES the runner parser's IR as a literal and compares `tree_parse_css` to
  it, rather than comparing the two front-ends live on each row. The two are equivalent today
  because `test/import_astcss_eval.py` generates the literal by calling `test/css_parser.py` — but
  they stop being equivalent the moment the fixture is regenerated from a changed parser, because
  then both sides of the "IR" record move together and only the second record of each pair (which
  does re-parse live) is still watching. It is worth one live-versus-live record, or a note in the
  generator that regeneration is what makes the freeze meaningless.
- **File size.** The Task 4 review noted `sql/06_selector.sql` at ~200 lines and suggested
  splitting the printer out in Task 5; it was not done, and the file is ~340 lines now.
  `sql/09_css.sql` is ~500 and `test/import_astcss_eval.py` ~620. *(2026-10-08, `wc -l`: all
  three have grown past those figures — `sql/06_selector.sql` **378**, `sql/09_css.sql` **561**,
  `test/import_astcss_eval.py` **737**. The argument is unchanged and the case for splitting the
  printer out is slightly stronger than the numbers said.)* None of them is confusing yet —
  each is one subject — but the printer really is a separate subject from the constructor, and
  the split gets more expensive the longer it waits.

**Fixtures and cost.**

- `test/gen_fixtures.py` is not byte-reproducible for `scripts.parquet` and `py_variety.parquet`:
  the row *order* moves between runs although the content is equal. Regenerating them produces a
  diff that is not a change.
- ~~Derived `_size` is O(n²) **within a root**, and `test/spike_listspace.py` says where that
  starts to matter: 13× the declared cost on a 142,650-row input whose roots hold ~9,510 rows
  each, and only 2.6× on the same rows spread over ten times as many roots. The M3 replacement is
  the per-level ASOF form (and the C++ port's stack walk).~~ **Closed by M3 Task 6**, which
  shipped exactly that form (`tree_sql_size_join()`): the realistic shape — 142,651 rows under
  ONE root, which is what a whole-repository parse looks like — goes from **26.9 s to 0.28 s**,
  i.e. **1.2×** a declared SIZE rather than 167×, and `flat 200k` is 467× faster. The numbers are
  in "M3 derivation cost" above. **Two costs are carried out of the change, not closed by it**,
  and they are the honest price of it: a pure deep chain got **21× slower** (0.044 s → 0.908 s on
  5,000 levels, because the candidate expansion is Σ(max level − level + 1) ≈ n²/2 — the quadratic
  moved from the correlated subquery into the candidate relation), and the **deep-spine-beside-
  shallow-rows shape did not improve at all** (21.5 s → 21.0 s, still 316× declared, because 100k
  shallow rows each expand over the spine's 2,000 levels for ~200M candidate rows). That second
  shape is the one the core design §2.3 already names as the worst case, and it remains the worst
  case; `tree_sql_size_join()`'s comment says what to do about it — **declare SIZE** — and the
  C++ stack walk is O(n) on every shape here. So the derivation is a convenience, not a
  guarantee.
- Create and alter still run the compiled projection more than once (once per guard, plus the
  materialization). Named in the PR #1 review and still open.
- ~~The projection macro is spliced once **per step alias**, so an n-step selector inlines it n
  times; a `WITH __p AS MATERIALIZED` would compute it once. Measured as roughly linear in the
  number of references, so it is a cost item rather than a correctness one.~~ **Closed by M3
  Task 7, by exactly that mechanism.** `sql/07_match.sql` opens every compiled match with
  `WITH __proj AS (SELECT * FROM <projection macro call>)` (`tree_sql_nav_ctes`), and the
  relation text handed to every fragment is `__proj`: step aliases, HAS/NOT subqueries and
  element scans all read the one CTE, and `tree_nav` builds its `query()` text the same way. A
  per-query `semantic` overlay moved inside the CTE as a `SELECT * REPLACE (…)` instead of being
  repeated at each reference. Two refinements on the bullet's own proposal, both measured on
  1.5.5: it is a **plain** CTE, not `MATERIALIZED`, because a CTE referenced more than once is
  materialized without being asked — 0.34 s through repeated macro references, 0.16 s plain,
  0.15 s `MATERIALIZED`, 0.33 s `NOT MATERIALIZED` on a projection-mode `scripts` tree, and
  0.00–0.03 s for every form on a 285k-row stored tree, so a plain CTE neither helps nor hurts
  there and does not block scan pushdown. And it bought a second CTE the bullet did not
  anticipate: `__sib`, a `lead`/`lag` window over element rows per `(_root, _parent)`, read from
  `__proj` rather than from the projection a second time, which is what turned the sibling and
  positional relations from range scans into equality lookups (262 s → 0.01 s for the next
  element sibling at 10k siblings; 14.9 s → 0.03 s for last child at 40k). **What stays open is
  the other half of the cost**, and the M3 design §8 is its record: the suites are slow because
  DuckDB *binds* very large macro expansions, not because of the joins — 67–107 ms per
  40_corpus record in `tree_compile_match`, 29–59 ms in the printer, 2–10 ms executing the
  match — and there is no per-query prune to be had, because the projection is one stored macro
  per tree, identical for every query. Narrowing the `__proj` CTE and the `EXCLUDE` list
  together leaves the plan and the time unchanged (DuckDB does not push column pruning through
  the macro body's ASOF joins), and removing an unused CTE changes nothing either. For
  projection-mode trees the available win is the declaration, not the compiler: declaring all
  three O columns takes a TYPE-only selector on `app.parquet` from 17.65 ms to 6.78 ms, 2.6×.
- `test/run_mutants.py --verify` re-runs a full baseline per control (~246 s each). The baseline
  for a given suite is the same for every control that copies the same macro, so memoizing it per
  suite would cut the harness roughly in half. (`suite_passes` already memoizes per
  (test, overlay); what is missing is sharing across overlays that are no-ops.)
- `tree_css_ppath(lvl, i0, a0, i1, a1)` is exactly `tree_css_path(lvl, i0, a0, i1, a1, 0, 0)`;
  aliasing one to the other would remove a second copy of the level→slot mapping.

**Raised by the PR #2 review as PLAUSIBLE, and left as written.** Each is a real seam; none is a
wrong answer today, and each is recorded so the next reader decides rather than re-discovers.

- `explicit_sel_prefix` (sql/03_ddl.sql) is computed from the tree's own unexpanded `PSEUDO`, and
  a LIKE child whose parent declared `{prefix: 'sel_'}` is labelled by the parent's marker rather
  than by its own declaration. The label is provenance (`origin`), not behaviour.
- A tree whose `attribute_columns` row is missing — deleted by hand, or a catalog written by
  something other than the DDL compilers — resolves every attribute name to `ATTR MAP` or refuses
  it; there is no `DESCRIBE` fallback. The artifact is written inside create's transaction, so
  this is a hand-edited catalog, not a state the compilers produce.
- `test/mutants/regen.py`'s macro extractor tracks `'` and `"` quoting but not `$$`
  dollar-quoting. No macro in `sql/` uses `$$`; one that did could be cut short at a `;` inside
  it, and the mistake would be visible as a mutant body that does not parse.
