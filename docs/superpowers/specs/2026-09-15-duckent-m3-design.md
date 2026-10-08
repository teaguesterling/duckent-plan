# duckent M3 design: an honest, cheap O layer

*Status: built; see FINDINGS for deviations, and the dated amendments inline. Designed 2026-09-15, built 2026-09/10. Scope: milestone M3 as a macro prototype on DuckDB 1.5.5, on top of M2 (PR #2, merge `4bdd207`). Baseline documents: the core design (`2026-09-13-duckent-core-design.md`), the M2 design (`2026-09-14-duckent-m2-design.md`, amended to what was built), handover v21 §O and §M3. Where this document and an earlier one disagree, this document wins for M3 and the earlier one is amended at the end of the milestone.*

## 1. Decisions

| question | decision | why |
|---|---|---|
| when a declared O column is checked | at ingest, fail closed, wherever P13 runs for materialized trees; projection-mode trees on demand through `tree_check` | handover §O: a divergence is a corrupted encoding, surfaced at that severity |
| planner-side use of O, EXPLAIN benchmark | out of M3 in macros; they belong to the C++ port | the macro prototype has no planner; the compiled SQL already uses `_size` ranges and the O(1) sibling forms |
| what `_pre` holds | the dense rank of ORDER within ROOT: `row_number() OVER (PARTITION BY root ORDER BY order) - 1` | every O(1) form assumes a 0-based, gap-free position per root; ORDER may then be any orderable expression |
| what `_next` and `tree_siblings` mean | structural: the successor position `_pre + _size + 1`, and every row sharing a parent; the element-aware relations live in the fragments | cheap to verify, and what a declared NEXT must equal |
| how `_size` is derived | a level-expanded ASOF join, replacing the correlated scan | exact on every fixture; cost is rows × depth (§2.3): 19.7 s → 0.24 s on one 143k-row root, but 15 s on a 2k-deep spine beside 100k shallow rows, where SIZE should be declared |
| what R0°, R1 and R2 default to | ROOT: one forest; ORDER: frozen insertion order; LEVEL: 0. Several level-0 rows are anonymous trees; a table declaring none of the three is a plain SQL table | structure is something added to a table, not a precondition (§2.6) |
| how sibling and positional relations are computed | a window CTE over element rows (`lead`/`lag` per `(_root, _parent)`) and equality forms; no range `NOT EXISTS` | measured 262 s → 0.01 s (next element sibling, 10k siblings) and 14.9 s → 0.03 s (last child, 40k) |
| how an attribute literal compares | by its spelling: a quoted literal as text, an unquoted number as DOUBLE through `TRY_CAST`, identically for columns and ATTR MAP | one rule instead of three (§7.1 W1) |
| one projection per query | the compiled SQL and the traversal text open with a plain `WITH __proj AS (…)`; the engine decides whether to materialize | measured: same benefit as `MATERIALIZED` on projection-mode trees, no pushdown loss on stored trees |
| the MN3 / MN4 numbering | the M2 file named MN03 becomes MN04 (its edit is MN4's claim); MN03 is re-planted as the handover states it | permanent ids must mean what the handover says they mean |

Vocabulary stays the handover's. **R0°** ROOT partitions the relation into trees; **R1** is row order, significant per partition; **R2** is the structural basis, LEVEL or PARENT. `_pre` is R1 made canonical within R0°; `_level` is R2 and M3 does not change how it is derived.

## 2. Derived structure (`sql/02_projection.sql`)

**2.1 Position.** In the level basis, `_pre := row_number() OVER (PARTITION BY <root> ORDER BY <order>) - 1`, and the declared ORDER expression is carried as a hidden `__order` column that is excluded from the projection's output. The frozen-order branch (no ORDER declared) and the parent basis already number this way and do not change. For sources whose ORDER is already dense and 0-based per root (sitting_duck's `node_id`), `_pre` equals ORDER and nothing observable changes. ORDER is no longer required to be an integer.

Example, one root with a gapped ORDER:

| ORDER | LEVEL | `_level` | `_pre` before M3 | `_pre` after M3 |
|---|---|---|---|---|
| 7 | 0 | 0 | 7 | 0 |
| 10 | 1 | 1 | 10 | 1 |
| 13 | 2 | 2 | 13 | 2 |
| 16 | 1 | 1 | 16 | 3 |

Measured on 143k rows with a gapped, offset ORDER: the window costs 0.04 s and every root starts at 0.

**2.2 Declared PARENT and NEXT are values in ORDER space.** The projection translates them to positions with one join on `__order` within the root instead of casting them. A declared NEXT that names no row is kept as `_pre + _size + 1` in the column, and §3.1 counts it as a disagreement unless that position is past the end of the partition; a fallback that silently accepted it would hide a corrupted NEXT. In the parent basis NEXT is a value in KEY space and is translated through the key instead of `__order`. SIZE and CHILDREN are counts and pass through unchanged. Measured: a declared PARENT translated through the normalization equals the derived parent on 142,650 of 142,650 rows.

**2.3 Derived `_size`.** One fragment, `tree_sql_size_join()`, replaces `tree_sql_size_expr()` in both bases:

```sql
__mx AS (SELECT _root, max(_level) AS __ml, max(_pre) AS __mp FROM __p GROUP BY _root),
__cand AS (SELECT p._root, p._pre, unnest(range(p._level, m.__ml + 1)) AS __lvl
           FROM __p p JOIN __mx m USING (_root)),
__end AS (SELECT a._root, a._pre, c._pre AS __nx
          FROM __p a ASOF JOIN __cand c ON c._root = a._root AND c.__lvl = a._level AND c._pre > a._pre),
__s AS (SELECT a.*, COALESCE(e.__nx, m.__mp + 1) - a._pre - 1 AS _size
        FROM __p a JOIN __mx m USING (_root) LEFT JOIN __end e USING (_root, _pre))
```

Each row is a candidate subtree boundary for every level at or below its own depth, so the nearest later candidate at a row's own level is the first row after its subtree. The expansion is `Σ (max level of the root − level + 1)` rows: about 8× on the fixtures, `n²/2` on a pure chain, and worst when a deep spine shares a root with many shallow rows, each of which expands to the spine's depth. Measured on DuckDB 1.5.5: a 5,000-deep chain 0.83 s; a flat 200k-row root 0.04 s; a root with a 2,000-deep spine and 100k shallow rows 15.4 s. That last shape is the documented limit of the macro derivation: declare SIZE for it, and the C++ stack walk removes it. Measured against the declared `descendant_count`: 0 mismatches on `scripts` (14,265 rows), `py_variety` (3,272), and a 10× forest (142,650). Against the correlated scan on a single root: 0.21 s → 0.03 s at 14k rows, 19.7 s → 0.24 s at 143k.

**2.4 Derived `_children`** becomes a grouped count joined back (`count(*) … GROUP BY _root, _parent`) instead of a correlated subquery, so the conformance check and the projection share one shape.

**2.5 `_next` stays structural.** The column comment and the M2 spec's §4 say so: `_next` is the successor position, the element-aware next sibling is `tree_sql_next_sibling`, and `tree_siblings` is the structural sibling set the element-aware relations are built on.

**2.6 Defaults for R0°, R1 and R2** (amends handover v21 §R). Each block of R has a default, so structure is something added to a table:

- **R2**: LEVEL defaults to `0` when neither LEVEL nor PARENT is declared. `tree_ddl_create` stops refusing that shape (`declare LEVEL or PARENT (R2)`).
- **R1**: ORDER defaults to frozen insertion order, as today, and still refuses when `preserve_insertion_order` is off.
- **R0°**: ROOT defaults to one forest. It is required only when trees must be identifiable across ingests, for tree-granular DML and attachments, not whenever the relation holds more than one tree.

Several level-0 rows in one forest are anonymous trees, and relations between them hold: they are ordered siblings within `_root`, so `heading + table` relates two top-level blocks. A table that declares none of the three is every row a one-node tree, a plain SQL table; one with only an all-zero LEVEL is the same; adding rows at level > 0 after a level-0 row makes a materialized adjacency tree. No tree-identity column is added: matching never needs one (containment ends at `_size`, siblings compare within `_root`), and `count(*) FILTER (WHERE _level = 0) OVER (PARTITION BY _root ORDER BY _pre) - 1` numbers anonymous trees when a caller wants to. DML on a ROOT-less tree keeps treating its single forest as one partition, replaced whole.

Everything above stays inside the projection's SQL text, so `tree_compile_projection` remains a pure expression that `query()` accepts. ORDER ties are refused at ingest (§3), not here.

## 3. O conformance at ingest (`sql/04_dml.sql`, `sql/03_ddl.sql`)

**3.1 One compiler.** `tree_compile_o_conformance(shape, rel_sql, label, order_col, attr_text)` *(amended 2026-10-06: `order_col` carries the ORDER value into the message, and `attr_text` gates the arm added below, which can only read raw source columns when ATTR is open)* derives SIZE, PARENT, CHILDREN and NEXT from the `(_root, _pre, _level)` of the relation being ingested (the `__duckent_new` temp table at insert and replace, the fresh projection at create and alter), never by re-reading a possibly volatile source, joins the derived values to the declared ones on `(_root, _pre)`, compares each with `IS DISTINCT FROM`, and raises through `tree_err` on the first disagreement in `(_root, _pre)` order, naming the ORDER value as well as the position:

```
O conformance violated in tree main.t: SIZE disagrees with its derived default at root <key>, ORDER <value> (position <pre>): declared 8, derived 9 (a corrupted encoding, not a fast path)
```

Only declared slots are compared; a tree with no O override compiles to no statement. PARENT and NEXT are compared after the §2.2 translation. In the parent basis PARENT is R2, not an override, so only SIZE, CHILDREN and NEXT are compared there.

*(amended 2026-10-06)* **An override is a per-tree fact and does not survive composition.** The law reads "test-equals its derived default over every conforming source", and across a W1 splice that is false by construction: the parent's declared SIZE equals its derived size *in the parent tree*, not in the composite, which is larger by the spliced child. The override is not corrupt there, it is **scoped**. Two readings have to hold at once, and they are easy to run together — the *composite's* SIZE differs from the parent's along the ancestor path of the attachment point, while the parent's *stored* SIZE must not be touched, or P18 breaks: a purely within-parent descendant query would start spanning spliced rows and a single-tree answer would move. So composition produces a derived relation and never mutates a constituent. MN10 and MN11 are planted on the planner believing otherwise.

*(amended 2026-10-06)* **The law is what licenses planner substitution.** "Every override test-equals its default" is exactly the condition that makes O columns *interchangeable access paths*: if they are provably equal, a planner may pick any combination of declared and derived without changing an answer. Written as strictness the rule reads like pedantry and invites someone to relax it; it is in fact the thing that buys the plan freedom §9 defers to the port. A tree that declares nothing still has one path, so the freedom is only ever a widening.

*(amended 2026-10-06)* **SIZE determines NEXT; NEXT does not determine SIZE.** The two are inter-derivable only one way. `SIZE → NEXT` is total (`_pre + _size + 1`); `NEXT → SIZE` fails for a last child, which has no next sibling and so no value to subtract from. SIZE is therefore the more fundamental override, and a tree declaring one of the two should declare SIZE. In a tree that participates in composition, do not declare NEXT at all: maintaining the same fact twice across a splice invites exactly the divergence this section calls corruption.

*(amended 2026-10-06)* **A declared NEXT that names no row is compared too**, and was not. The projection's `COALESCE(nx._pre, a._pre + a._size + 1)` collapses an unresolvable NEXT to the derived default, so the comparison above was the default against itself: the tree was accepted and `tree_check` recorded `assert_o_next = ok` — a positive verdict for a declaration nothing had compared. Unresolved is not itself false: the conforming fixture `with_next` declares `node_id + descendant_count + 1`, and seven of its rows name no row (the root's last row and every ancestor whose subtree ends with it), all correctly. The violation is unresolved **and** the derivation naming a real row of the same root, which is falsified rather than merely unverifiable. Where neither names a row they agree and `ok` is honest, leaving a residue — the same residue the PARENT arm carries on ROOT rows, where the derived parent is NULL too. A declared NEXT of NULL is caught by the same predicate, consistent with SIZE and CHILDREN, which refuse a NULL override outright: a declared O column is total.

**3.2 ORDER is checked on its own**, whenever ORDER is declared, whatever else is: a separate compiled statement, `tree_compile_order_check(shape, source_sql, label)`, over the source's ROOT and ORDER expressions, refuses a NULL ORDER value (`ORDER is NULL in tree main.t at root <key>`) and a value repeated within a root (`ORDER is not a traversal in tree main.t: root <key> has <n> rows with ORDER value <v>`). It runs before P13, so a tie is not reported as a level jump, and it runs at create for projection-mode trees too, because a tie there makes `_pre` change between queries. This keeps the handover's rule that an unpartitioned, resetting ORDER column is rejected.

**3.3 Where it runs.** The ORDER check first, then P13, then conformance; conformance for materialized trees, in `tree_compile_create`, `tree_compile_alter`, `tree_compile_insert` and `tree_compile_replace`, inside the same transaction, so a refusal rolls the statement list back. Projection-mode trees are not checked at create (their source can change afterwards); P13 still is, as today.

**3.4 On demand.** `tree_check` accepts projection-mode trees for assertions (DML still refuses them), runs the ORDER check, P13 and conformance over the live projection, and records, never raises, one row per check (`ok` or `violated` with a detail naming the first disagreement) in `tree_state.assertions`: `assert_o_size`, `assert_o_parent`, `assert_o_children`, `assert_o_next`, beside `assert_p13`.

**3.5 The module boundary.** Matching never reads `tree_state` or the O slot rows of `tree_catalog.slots`; MN03 (§6) proves it.

*(amended 2026-10-06)* And that is not hygiene — it is the precondition for §3.1's plan freedom. Because matching cannot observe *which* O columns are declared, every combination a planner might choose is semantics-preserving by construction. If matching could branch on an O declaration, as MN03 makes it, then each plan choice would be a semantics change and cost-based O selection would be unsound. The record that kills MN03 compares the compiled TEXT of a declared tree against a derived one, because results cannot carry the claim: a compiler that branched and emitted an equivalent form would move no row. 42 carries an ELEMENT-less pair for it, since with ELEMENT declared both trees take the element-scan path and the O(1) forms are never compiled.

## 4. One projection per query (`sql/07_match.sql`, `sql/08_traversal.sql`)

**4.1** The compiled SQL opens with `WITH __proj AS (SELECT * FROM <projection macro call>)`, and the projection text the compiler passes to every fragment is `__proj`: step aliases, HAS/NOT subqueries, and element scans all read it. A per-query `semantic` overlay moves inside the CTE (`SELECT * REPLACE (…) FROM <projection macro call>`) instead of being repeated at each reference. `tree_nav` builds its `query()` text the same way.

**4.1b Sibling and positional relations read a window.** When a selector uses `next`, `after`, a positional built-in, or their traversal counterparts, the compiled query adds `__sib AS (SELECT _root, _pre, lead(_pre) OVER w AS __next_el, lag(_pre) OVER w AS __prev_el FROM __proj WHERE _element WINDOW w AS (PARTITION BY _root, _parent ORDER BY _pre))`, and the element-aware fragments become equality lookups against it: next element sibling is `b._pre = s.__next_el`, first child is `s.__prev_el IS NULL`, last child `s.__next_el IS NULL`, `after`/`before` compare `_pre` within the same `(_root, _parent)` of element rows. Without ELEMENT the O(1) forms stay, and last child becomes the equality `NOT EXISTS (… x._pre = a._pre + a._size + 1 AND x._level = a._level)`. No fragment keeps a range `NOT EXISTS`. Measured on one flat root: next element sibling 262 s → 0.01 s at 10k siblings; last child 14.9 s → 0.03 s at 40k.

**4.2 No forced materialization.** Observed on DuckDB 1.5.5: a CTE referenced more than once is materialized without being asked. Measured on a projection-mode `scripts` tree, three-reference selectors: 0.34 s through repeated macro references, 0.16 s with a plain CTE, 0.15 s with `MATERIALIZED`, 0.33 s with `NOT MATERIALIZED`. On a 285k-row stored tree every form costs 0.00–0.03 s, so a plain CTE neither helps nor hurts there and does not block scan pushdown.

**4.3** Output columns, captures and provenance do not change; the compiled SQL text that `tree_explain(...).sql` shows does. The byte-for-byte linear SQL pin in `31_match.test` moves once, deliberately, and the MN06 copy is regenerated.

## 5. Parked M2 items closed

- **Provenance has one mechanism.** The runner's `language :=` splice (`test/run.py`) retires; the selector root-row stamp (M2, R10) is the only source of `_match_language`. The `37_css_parser.test` records on the default-language path are re-pinned against the stamp, and the Open-after-M2 bullet closes.
- **The first-root O(1) form** (`COALESCE(a._pre = a._parent + 1, a._pre = 0)`) is correct for every declared ORDER once §2.1 lands. The M2 spec's "in both forms" sentence stands, backed by a gapped-ORDER record comparing an ELEMENT tree with a plain one.
- **`_next` and `tree_siblings`**: documented per §2.5; no code.

## 6. Mutants and evidence

| id | wrong implementation | killed by |
|---|---|---|
| MN03 (re-planted) | a semantics-path function reads an O accessor: the compiler looks up whether SIZE is declared in `tree_catalog.slots` and emits a different descendant form when it is not | 42's new boundary record: for every app corpus selector, the compiled SQL for `app_declared` and `app_derived` is identical apart from the projection name and the `_match_tree` literal |
| MN04 (the M2 file formerly named MN03) | the declared SIZE path of the projection returns `size + 1` | conformance at create (11_ddl, 12_dml records that create or insert a declared-SIZE tree) and 42 |

The M2 file's rename is recorded in FINDINGS: the number MN3 was used for MN4's claim in M2, corrected here so a permanent id keeps the handover's meaning. MN01, MN02 and MN14 touch the fragments §2 and §4 rewrite and are regenerated with `test/mutants/regen.py`; MN14 stops overriding `tree_sql_size_expr`, which §2.3 removes.

Records (all in existing suites unless named):

- a source with one corrupted `descendant_count` refuses at create and at insert, naming SIZE, the root and the row;
- a source with a corrupted `parent_id` refuses naming PARENT;
- an ORDER tie refuses; an unpartitioned resetting ORDER refuses;
- a gapped, offset ORDER tree (`node_id * 3 + 7`) returns the same `file_path:node_id` sets as its dense twin for every app corpus selector, and the same first-child and last-child totals with and without ELEMENT;
- `tree_check` on a projection-mode tree records `assert_o_*` rows;
- the derived size equals the declared one on all three fixtures (projection-level record in 42, extended to `py_variety`).

The single-root timing lives in `test/spike_listspace.py` (a new `--sizes` mode) and FINDINGS, not in a timed test.

**Harness.** `test/run_mutants.py --verify` stops re-running a full-suite baseline per control file: the green suite run already proves the baseline, so each control needs only its own `expect_fail` suites.

## 7. Well-formedness and the duck_block_utils review

A review from the duck_block_utils side (2026-09-15, all suites and mutants green on DuckDB 1.5.5 with sitting_duck loaded) found defects none of the M2 reviews did. M3 absorbs all of them, because §2 and §3 rewrite most of the code they live in. Items marked *verified* were reproduced by the reviewer against test files.

**7.1 Wrong results.**

| # | defect | rule |
|---|---|---|
| W1 | a numeric literal compared through `TRY_CAST(… AS BIGINT)` rounds: `[n=2]` matches `'1.5'` and `'2.4'` (*verified*); a quoted literal against a numeric column aborts the query (`Could not convert string 'x' to INT32`); a number against a VARCHAR column compares as text, so `'10' > '5'` is false while ATTR MAP says true | the literal's spelling decides the domain, the same for projected columns and ATTR MAP: a quoted literal compares `CAST(<value> AS VARCHAR) <op> '<text>'`; an unquoted number compares `TRY_CAST(<value> AS DOUBLE) <op> <number>`; a boolean literal compares `TRY_CAST(<value> AS BOOLEAN)`. Nothing rounds and nothing aborts |
| W2 | an empty affix value (`[a^=""]`, `$=""`, `*=""`) lowers to `LIKE '%'`-style patterns and matches every row (*verified*) | in CSS an empty affix value matches nothing; both front-ends lower it to an `attr` clause with `op = 'LIKE'` and `arg = 'NULL'`, which the clause's `COALESCE(…, false)` makes false; the printer shows `ATTR a LIKE NULL` |
| W3 | `:first-child` wrong on a gapped or offset ORDER (*verified*) | closed by §2.1 |
| W4 | a capture named `@__c` collides with the compiler's own `__c` subquery alias and turns `+` into `~` | aliases beginning `__` are reserved like `s<N>`: refused by `tree_steps`, `tree_steps_group`, both css front-ends and the compiler's `bad_alias` (`alias __c is reserved: names beginning with __ belong to the compiler`) |
| W5 | the SQL `@name` rewrite splits on `"` first, so a `"` inside a single-quoted value corrupts the text | `tree_css_capture_markers` tokenizes quoted strings with one pattern (`'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|[^'"]+`) and rewrites only the unquoted tokens |
| W6 | `b:not(:nope)` matches every `b`: the unknown pseudo-class compiles to `false` inside a NOT, which widens the step | "unknowns match nothing" holds for the whole step: a HAS or NOT group containing an unknown pseudo-class at any depth compiles to `false`, so its step matches nothing; `_match_unknown_pseudos` still counts it |

**7.2 Data loss.** Tree names that differ only in case share generated objects, because DuckDB identifiers are case-insensitive: creating `App` overwrote `app`'s table, and `tree_ddl_drop` of a tree that does not exist runs its `DROP … IF EXISTS` statements anyway, so dropping a mistyped `App` destroys `app`'s storage while `app`'s catalog rows stay (*verified*). Rules: `tree_compile_create` refuses when a tree exists whose schema and name match case-insensitively (`tree_ddl_create: tree main.App collides with existing tree main.app (names are case-insensitive)`); `tree_compile_drop` refuses a tree that does not exist, matched exactly (`tree_ddl_drop: tree main.App not found`). Identity stays case-sensitive in the catalog; uniqueness is case-insensitive.

**7.3 Well-formedness at ingest (P13 and the bases).** P13 today checks only level jumps and the first row's level. Wherever P13 runs, the following refuse, each with its own message naming the tree and root:

- a NULL or negative `_level`;
- a NULL ORDER value, or two rows of one root with the same ORDER value (§3.2), checked against the source's ORDER expression before normalization, since `row_number()` would otherwise number NULLs and ties arbitrarily;
- a partition whose first row starts above level 0: the message now says `rows start at level <n>; if the source's levels are <n>-based, declare LEVEL as '<level> - <n>'`, and keeps the ROOT hint only for the case it describes (an undeclared ROOT whose levels reset).

A ROOT partition with several level-0 rows is **not** refused. The handover allows it ("multiple roots legal — R2 permits level returning to 0"): ROOT delimits independent trees for DML and attachments, it does not require one root row. The reviewer read it as a defect; FINDINGS records the adjudication.

**7.4 The parent basis respects ROOT.** The DFS walk joins a child to its parent by key alone, so a valid forest whose keys repeat per root is refused, orphans vanish, and a duplicate key duplicates rows or never terminates (*verified*). Rules: the walk's recursive join also requires the child's ROOT to equal the walker's; before the walk, ingest refuses a key that repeats within a root (`KEY <k> appears <n> times in root <r>`) and any row the walk cannot reach from a NULL parent within its root (`<n> rows are not reachable from a root in root <r>: orphans or a cycle, e.g. key <k>`). Those two checks are emitted before any statement that evaluates the projection.

**7.5 Smaller items.** A ROOT declaration splits on every comma, so an expression containing one cannot be declared: `tree_sql_list` splits on top-level commas only, honoring one level of parentheses and quotes, and a deeper nesting refuses with a hint to project a column. Selectors that reach a raw DuckDB error instead of a duckent refusal, and inputs the two css front-ends treat differently, are found by one sweep (`test/sweep_selectors.py`, reusing the Task 9 differential generator) over `app`, and each class found gets a fix and a record.

**7.6 The harness.**

- A mutant that fails to load is counted as a kill. `test/run.py --mutant` exits `3` with `MUTANT DID NOT LOAD` when applying the overlay raises, and `run_mutants.py` counts only exit `1` with at least one `FAIL <file>:<line>` record as a kill; exit `3` fails the run.
- MN08 has no control but the summary says every kill was verified. The manifest marks it `control: manual`, and the summary reads `<k> of <n> kills verified against a control; manual: MN08`.
- A file with no assertions passes, and a `require` that cannot load returns `[]`, discarding earlier failures. `run.py` fails a file that executes no `query` and no `statement error` record; `require` is legal only before the first record; `DUCKENT_NO_SKIP=1` turns a skip into a failure (CI sets it).
- Expected error text matches by substring against DuckDB's message *including* its echoed SQL (`LINE n: …`), so `01_types.test:34` passes only because `levl` appears in the echo (*verified*). The runner compares against the message with everything from `\nLINE ` onward removed, and the one record that relied on the echo asserts the real message.
- Suite 38 compares against a frozen snapshot of the runner parser's IR, not a live parser: its header and the README say so, and suite 44 is named as the live parser differential.

**7.7 duck_block_utils.** The README's claim that duck_block_utils documents "conform by construction" is false: duck_blocks puts top-level blocks at level 1, so P13 refuses the repo's own markdown fixture, and its hint says to declare ROOT (*verified*). Rules: the README says documents conform with one declaration, `level := 'level - 1'`; its `section h2 + table` example is marked as needing a section projection duckent does not build; a new suite `45_duck_blocks.test` declares `test/data/readme_blocks.parquet` as a tree (ORDER `element_order`, LEVEL `level - 1`, TYPE `element_type`) and pins `heading + table` against a result computed independently in SQL; `test/data/FIXTURES.md` records the markdown extension version the fixture was generated with (community `2ba1321`). duckent has no notion of a block's body, so spec-1.4 metadata and value subtrees are ordinary nodes to it: recorded as **D-N22**, not built.

**7.8 Mutants.** The review's harness findings change what a kill means (§7.6) but plant no new ids. W2, W4, W6, 7.2 and 7.4 each get a record that fails under a hand-reverted fix during implementation; none is promoted to a permanent mutant id.

**7.9 The second review** (panduck, 2026-09-15, at `242acdc`) confirmed W3, W4, 7.3, 7.4 and 7.6 independently and added:

- **Refusals missing from the printer and compiler.** A capture inside a group and an empty group are refused only by the constructors: the printer drops an empty group (`'HAS ( ' || NULL`), and the compiler silently discards an inner alias. A duplicate user alias compiles and then fails in DuckDB's binder. Rule: all three are refused by `tree_steps`, `tree_steps_group`, the printer and the compiler, with the same messages.
- **Corpus independence.** 216 of 40_corpus's 252 records compare the Python parser with itself, because the frozen `treeql_ir` came from `css_parser`. Rule: the importer freezes the IR from `tree_parse_css` (the SQL lowering, run under sitting_duck at import time), so 40 compares two front-ends while still running without sitting_duck.
- **What a kill needs.** `run_mutants.py` counts a kill when any listed suite fails, while the manifest says every listed file must. Rule: every suite in `expect_fail` must fail with at least one record; suites that only sometimes see a mutant move to `also_kills`.
- **41b** passes when both engines return zero rows, which is exactly sitting_duck #127's symptom, and its combinator skip ignores combinators inside `:has`/`:not`. Rule: each live record also requires the reference count to be nonzero, and the skip covers nested combinators.
- **Mutant hygiene.** `regen.py --check` never looks at the hand-written MN01, MN02, MN14 and MN15; it now checks that every macro they override exists in `sql/`. `run_mutants.py` runs its subprocesses with `cwd` set to the repository root, refuses an unknown `--only` id, and the manifest's MN22 note counts 252 records, not 250.
- **Evidence behind claims.** The 3,444-selector front-end differential and the §7.5 sweep are committed as `test/sweep_selectors.py`, so the number has a script behind it.
- **Doc drift**, corrected in the core and M2 specs and FINDINGS: ATTR MAP is `MAP(VARCHAR, VARCHAR)` only, not "compiled by its type"; a local and a prefix pseudo-class with the same name refuse (S-coherence), which is what the code does; selector-bodied pseudo-classes are not built and are listed as carried; the M2 footgun table's citations point at rows that exist (refusals live in 37 and 38, #141 is `c12` on `py_variety`, no corpus row uses a capture); FINDINGS' description of `tree_catalog.compiled` and its `_match_language` formula; deferred mutant ids are listed in the manifest as the core spec says.

## 8. What M3 does not fix: compile cost

Profiled on the corpus suites (2026-09-15): a 40_corpus record spends 67–107 ms in `tree_compile_match`, 29–59 ms in the printer and 2–10 ms executing the match; a `tree_steps` literal costs 28 ms. The suites are slow because DuckDB binds very large macro expansions, not because of the derivation or the joins. The C++ port removes this cost; M3 records the numbers and does not chase them (no compiled-selector cache: it would be state consulted by matching).

*(amended 2026-10-07)* **In projection mode, declaring O is the optimisation, and it is worth 2.6×.** A projection-mode tree derives its O columns on every query, whether or not the selector reads one — a TYPE-only selector costs the same as a descendant selector, because the derivation runs either way. Measured on app.parquet, warmed, median of 13:

| declared | projection body | TYPE-only |
|---|---|---|
| nothing (derive all) | 1656 chars | **17.65 ms** |
| PARENT | 1679 | 12.99 ms |
| SIZE | 1199 | 11.23 ms |
| PARENT + SIZE | 1222 | 8.60 ms |
| all three | 1088 | **6.78 ms** |
| *(materialized, derive all)* | — | *0.95 ms* |

Derive-parent ≈ 4.7 ms, derive-size ≈ 6.4 ms, derive-children ≈ 1.8 ms, and the overhead is near-constant in row count (22.1 ms on 54 rows, 31.1 ms on 14,265) — it is bind cost, as above. Note PARENT makes the body *longer* while being faster, so cost tracks the ASOF and window machinery rather than expansion size.

There is no per-query prune to be had: the projection is a stored per-tree macro, identical for every query, and the match references it by name. Measured twice — narrowing the `__proj` CTE and the `EXCLUDE` list together leaves the plan and the time unchanged, because DuckDB does not push column pruning through the macro body's ASOF joins; and removing an unused CTE changes nothing either, because DuckDB already eliminates unreferenced CTEs. Pruning per query would mean two stored bodies per tree (full and lean, the match picking by name), which is the only route that works and is held until a tree that *cannot* declare O actually hurts.

So the guidance is simply: **a projection-mode tree should declare the O columns its source has.** That is O doing exactly what this contract says it is for — cost only, never results — and for such a tree the derivation cost is the price of not declaring them.

## 9. Scope

**In:** §2–§7. **Out:** planner-side use of O and the EXPLAIN-shape benchmark (C++ port); attachments and loaders (W); M-LANG (TREEQL text, D-N20 parameterized pseudo-classes); compile-cost caching; **an O5° `previous_sibling` override** *(added 2026-10-07)*.

*(2026-10-07)* **On O5°.** The cost asymmetry between the two sibling directions is real and is recorded here rather than acted on. `tree_sql_next_sibling` is arithmetic on the subject's own row — `b._pre = a._pre + a._size + 1`, O(1), no lookup — while `tree_sql_prev_sibling` is keyed on the *candidate's* size, `a._pre = b._pre + b._size + 1`, which the subject cannot compute because it does not know how large the row before it is. So of the two, O4 `next_sibling` earns an override least and a `previous_sibling` would earn one most, which inverts how the slots are currently spent. The mechanism exists already: under a declared ELEMENT the projection computes `__prev_el`, and an O5° would let a vocabulary supply what that computes.

It is deferred rather than added because adding a contract slot now would create a declared surface no vocabulary supplies and no fixture exercises — the defect class closed on 2026-10-06, where five declarations were recorded in the catalog and never verified. It belongs with the planner-side O work this section already defers, and with the composable vocabularies (filesystem, directory services) that would actually carry a previous pointer. Note the asymmetry is conditional on dense ranking: under a sparse key with stored interval bounds, `pre + size + 1` stops being the next sibling and both directions become lookups.

## 10. Open decisions carried

*(2026-10-07)* **D-N24, how a W1 attachment composes two trees.** Recorded now because the measurements are in hand, with nothing to implement until attachments exist. The composite is a DERIVED relation: the child's LEVEL is offset by `level(d) + 1` and the composite's PRE is a re-rank over the union, with the constituents untouched — required by P18, since mutating a parent's stored SIZE would move a within-parent answer. Per column the composite differs on all of C for LEVEL, on `d` and its ancestors for SIZE, on `d` alone for CHILDREN, and on all of C plus every parent row after d's subtree for PRE.

**Dense ranking is kept.** An earlier draft proposed a sparse or fractional key with stored interval bounds to avoid the PRE shift; that trade is worse. Counting rows overstates the cost — shifting PRE is one BIGINT column, one vectorized add over a contiguous range, no other column touched — while a sparse key costs the gap-free guarantee every O(1) form rests on and turns NEXT into a lookup. Projection-mode composition is free in the sense that PRE is already a per-query window (`02_projection.sql`), so composing is a union before the window; materialized trees pay the shift. Two DDL-time checks fall out and are specified but unbuilt, having nothing to guard yet: `order_source = 'frozen'` and splice participation are contradictory, since a frozen order cannot be re-ranked; and attaching must re-run O conformance on the parent, because an attachment changes what *conforming* means for it.

D-N9, D-N10, D-N13, D-N15, D-N16, D-N19, D-N20 unchanged. New: **D-N21** whether projection-mode trees should run conformance at create as P13 does (M3 runs their ORDER check and P13 at create and conformance on demand only; the asymmetry is deliberate and one line to change). **D-N22** whether duckent models a block's body (duck_blocks spec-1.4 metadata and value subtrees) or leaves it to the vocabulary. **D-N23** whether materialized trees carry a `UNIQUE INDEX` on `(_root, _pre)`. Measured on 1.5.5: `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE` is unimplemented, and both storage paths are CTAS (`03_ddl.sql:230`, `:359`), which cannot declare constraints — but `CREATE UNIQUE INDEX` works after the table is built and does enforce (`Duplicate key "a: 0, b: 0" violates unique constraint`), so it costs one extra statement per materialized tree. It would not replace the ingest checks: `tree_compile_key_check` and `tree_compile_order_check` run over the SOURCE before the walk, because that is where rows multiply or collapse, and by insert time the damage is renumbered and reads as a well-formed tree. What an index adds is the guarantee no ingest check gives — protection against later direct `INSERT`/`UPDATE` into a tree's own table — at the cost of an ART index per tree and a generic constraint message in place of duckent's named diagnostics.
