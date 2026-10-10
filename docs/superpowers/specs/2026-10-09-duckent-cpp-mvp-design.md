# duckent C++ extension — MVP design (the TREEQL slot matcher)

Status: **designed, not built.** Supersedes nothing; this is the first spec of the C++ phase and
the first increment of core design §9 (repository plan) and §10 (what the port replaces).

| in | out | why |
|---|---|---|
| extension skeleton, embedded macros, the seven CALL verbs, `tree_match` over IR selectors | every selector front-end, including css | a front-end is its own extension that registers with duckent, not a milestone of it |
| the 16 suites that pass IR selectors — a floor of 495 assertions | the 9 suites that pass selector TEXT | those 9 test a front-end; the MVP has none |
| the macro layer as the semantics, unchanged | any C++ reimplementation of semantics | the corpus is the acceptance gate, so the semantics must not move while the substrate does |
| the language registry as the dispatch seam | planner-side use of O, W, the 2.0 grammar | later increments, each with its own spec |

## 1. What the MVP is

**The TREEQL slot matcher.** An extension that loads duckent's macros, provides the executors the
macro phase emulated in Python, and matches selectors handed over as IR. No parser, no front-end,
no `require`, and no sitting_duck dependency.

The semantics stay in the macros throughout. That is the point: a corpus failure during this
increment is a substrate or executor bug, never a semantics one, because the semantics are the
same bytes running in a different host.

### The gate, measured

```
16 file(s): 16 ran, 0 skipped, 495 assertion(s), 0 failure(s)
```

*(amended 2026-10-10)* The count is a **floor**, asserted with `>=`, not an equality. It was 487
when this spec was written and 497 a day later, because PR #59 added ten attribute-operator
records to `31_match.test`; it is 495 now because two css-registration records moved out of
`36_pseudo.test` to `38_css_lower.test`. A silent skip REDUCES the count, so a floor still
catches the failure the gate exists for, while an equality check fails on correct work — and a
gate that cries wolf is a gate people stop trusting.

00_smoke, 01_types, 02_catalog, 03_fixtures, 10_projection, 11_ddl, 12_dml, 13_alter,
20_derivations, 30_selector, 31_match, 32_traversal, 33_navigation, 34_groups, 35_attr_map,
36_pseudo.

The split falls on a seam rather than a judgement: those 16 contain **zero** text selectors and
**zero** `require` lines. The other nine (37, 38, 40, 41, 41b, 42, 43, 44, 45) each exercise a
front-end — eight through text selectors, and 38 through the SQL css lowering directly.

Covered by the gate: declarations and both bases, the projection compiler, forest DML with P13 on
ingest, O conformance, the frozen-order guard, the per-root unique-key check, traversal,
navigation, nested HAS/NOT groups, attribute maps, element rows, and the predicate registry with
its purity lint.

## 2. Repository and build layout

A new repository from `duckdb/extension-template`, with `duckdb/` and `extension-ci-tools/` as
root submodules — the layout sitting_duck uses. Named `duckent-ext` until the gate is green; at
that point it becomes `duckent` and the present repository becomes `duckent-plan`, completing §9.
The rename is deferred deliberately so that it renames a proven thing rather than an intention.

`sql/*.sql` are **copied** to `src/sql_macros/`, and `scripts/embed_sql_macros.py` — sitting_duck's
script, reused — compiles them into `src/include/embedded_sql_macros.hpp` as raw string literals.
Measured: 263 KB across 10 files, 7 of them above the 14 KB chunking threshold the script applies
for MSVC's 16380-byte string-literal limit, so the chunking is required rather than theoretical.
The macros execute at extension load in filename order, which is already a dependency order.
Nothing reads SQL from disk at runtime.

**The MVP embeds 00 through 08 and omits `09_css.sql`.** Measured, both configurations load clean:

| build | registry | default selector language |
|---|---|---|
| core only, 00–08 | `treeql` (parser NULL) | `treeql` |
| full, 00–09 | `css`, `treeql` | `css` |

### The drift gate

Embedding the macros puts the same semantics in two repositories, which is a fork waiting to
happen. The answer is the idiom this project already uses for generated artifacts — `regen.py
--check`, `gen_cheatsheet.py --check` — applied to the copy: **a CI check that every file in
`src/sql_macros/` is byte-identical to the plan repo's `sql/`**, failing the build on divergence.

This is byte-identity rather than identity-with-exceptions because of the registry move
(`7320ed2`): with css registering itself inside `09_css.sql`, the extension's only difference is
*which files it embeds*. A gate with an exception list is a gate that accumulates exceptions.

## 3. The executor layer

### 3.1 The seven CALL verbs

`tree_ddl_create`, `tree_ddl_drop`, `tree_ddl_alter`, `tree_insert`, `tree_replace`,
`tree_delete`, `tree_check`.

`CALL` invokes a table function. Arguments arrive already evaluated: `tree_spec(tree_shape(...),
source := '…')` is a scalar macro over literals, so it constant-folds to a STRUCT `Value`. Each
verb binds those Values into `SELECT tree_compile_<verb>(?, …)`, receives a `VARCHAR[]`, and
executes the statements in order.

This is `test/run.py`'s `Session.execute` CALL branch — about twenty lines of Python — in C++.

**Side effects belong in the scan, not in `bind`.** Bind runs during `EXPLAIN` and during prepare,
where a verb must not fire.

### 3.2 No transactions in the compiled list

Settled, and already implemented in the macro phase (`a21d889`): the compile macros emit semantics
only. Atomicity is the executor's, which is what core design §4 says ("every mutating operation is
a pure compiler plus a thin executor").

This was a blocking defect in the port, not a tidiness fix. A `CALL` verb is a table function and
runs *inside* a query, where `BEGIN TRANSACTION` is not legal — so a compiler emitting transaction
control could not be executed by the extension at all. In the extension the enclosing single
statement supplies the atomicity the explicit transaction used to.

It also retires a spike this design would otherwise have carried: there is no longer a question
about whether DDL side effects inside a table function share the outer transaction, because there
are no transaction statements to be illegal.

### 3.3 `tree_match`, and what needs no C++ at all

`tree_explain` is already a macro and ports as a macro. Only `tree_match` needs C++.

`tree_match` binds, compiles via `tree_compile_match`, and streams the resulting query: `query()`
without the literal-only restriction, which is what §10 means by "a bound table function; lifts
the literal-only restriction on selectors." Bind runs the compile and determines the schema;
execution streams rows.

### 3.4 Where a selector's language is decided

One branch in `tree_match`'s bind:

- the selector argument is **IR** → pass through, provenance `treeql`, because IR was never parsed
  and the default's name is not its to claim;
- the selector argument is **text** → resolve the language (the `language :=` argument if given,
  else `tree_catalog.settings`), look the language up in the registry, and call the parser it
  names.

The macro-phase comment on `rewrite_selectors` is emphatic that the parse and the provenance are
one decision made by whoever made it. This keeps that property by keeping it in one place.

In the MVP the registry holds `treeql` alone, with a NULL parser — so **every text selector is
refused by a lookup that finds no parser**, naming the registry and what is registered. That
replaces the runner's hardcoded "TREEQL text parsing arrives with M-LANG; pass `tree_steps(...)`".

## 4. The front-end seam

`tree_catalog.selector_languages(language, parser, printer, bare_safe)` becomes the dispatch
mechanism it was written to be. Before `7320ed2` it was a record that nothing consumed — written
by the catalog bootstrap, exposed by `tree_catalog_languages()`, and read by no code; the runner
read the *default* from settings and hardcoded its own parser. The test audit had independently
flagged `bare_safe` as written-but-never-read.

A front-end is its own extension. It registers by inserting its row and naming its own parser
function, so **the registration API is SQL, not C++** — which is why `09_css.sql` can perform its
own registration today and why an external css extension can do exactly the same thing later.

This settles **D-N10** (language registration API).

A `tree_register_language(language, parser, printer, bare_safe)` helper is worth adding when the
first external front-end arrives, so that a parser named at registration time can be verified to
exist then rather than at first use. It is out of the MVP: with one row and a NULL parser there is
nothing to validate.

## 5. Error handling

The refusals are the product. duckent has 83 `tree_err` call sites, and the corpus pins many of
their messages by substring — the macro phase treats an illegible refusal as a defect in its own right
(see `81fe805`, where a refusal that named neither the tree nor the predicate was the whole
finding).

Three requirements follow:

1. **Refusal text is contract.** Every message the 16 suites pin must survive verbatim. They come
   from the macros, so they survive by construction — unless the C++ layer wraps or reformats
   them, which it must not.
2. **The executor adds no refusals of its own** beyond the registry lookup of §3.4 and
   argument-marshalling failures, and those name duckent rather than DuckDB internals.
3. **No raw engine error where a duckent refusal is owed.** This is the defect class the hardening
   pass closed twice: `Map keys must be unique.` reaching a user who declared two predicates with
   one name, and `Table Function with name proj_4_main_abs1 does not exist!` reaching a user who
   queried an abstract tree. The second is still open and belongs to a later increment, but the
   executor must not add new instances.

A specific hazard: error text matching. duckent's runner trims DuckDB messages at `\nLINE ` so
that an expected error can only match what the error *says*, never the statement echoed back.
DuckDB's sqllogictest may compare differently. Where it does, the record moves and the diff is
enumerated — so "the `.test` files move unchanged" becomes "move unchanged except for an
enumerated list", which is the honest form of that claim.

## 6. Testing

### 6.1 The gate

The 16 suites run under DuckDB's own sqllogictest via `extension-ci-tools`. No `require`, no
sitting_duck, no fixture staging — the MVP's CI is a plain extension build and test, where
duckent's present CI carries about thirty lines of fixture staging from two pinned sitting_duck
commits.

### 6.2 Replacing `DUCKENT_NO_SKIP`

duckent's runner turns a skip into a failure. That mechanism is why an incident of 17 vacuous
assertions was caught once, and DuckDB's `require` merely skips.

*(amended 2026-10-10)* The original reasoning here was "the MVP has no `require` lines, so nothing
can skip". That premise is false: measured, a statically linked extension still needs resolving
for the harness, and without it a suite's assertions fail outright. What makes the suites need no
`require` is a committed `test/test_config.json` naming `statically_loaded_extensions`, passed to
the unittest binary via `--test-config` from the extension's own Makefile. The conclusion stands
and the mechanism is now stated, so nobody re-derives it: **CI checks that 16 files ran and that the assertion count is at least 495.** A suite dropping out of the glob must be a failure, not a smaller green
number.

### 6.3 The mutant harness ports nearly unchanged

`run_mutants.py` applies a mutant as a `CREATE OR REPLACE MACRO` override and re-runs the suites it
expects to fail. The extension's macros are real macros, overridable at runtime, so the mechanism
survives the port.

Measured against the MVP gate:

| | mutants |
|---|---|
| every `expect_fail` suite inside the gate | 15 — MN01, MN02, MN06, MN12, MN13, MN14, MN15, MN17, MN18, MN19, MN21, MN26, MN27, MN28, MN29 |
| mixed, still detected but not fully verified | 2 — MN04, MN24 |
| front-end only | 6 — MN03, MN05, MN07, MN08, MN22, MN25 |

So the MVP carries roughly three-quarters of the mutation guard, and the quarter it cannot run is
exactly the part it does not implement.

**The manifest must mark which increment each mutant belongs to**, so that "not run because out of
scope" is distinguishable from "not run because broken". This is the absence-assertions lesson
applied before it bites: a mutant silently not running looks identical to a mutant that passed.
MN04's and MN24's entries need their `expect_fail` lists split along the same boundary.

### 6.4 The differential the corpus cannot provide

The corpus cannot detect an executor bug that changes only *how* statements run, because both
implementations execute the same macros. What catches that class is a direct comparison:

**For each of the seven verbs, compile the statement list in the plan repo (through `run.py`)
and in the extension (through the C++ verb), and assert the two texts are identical.** Both call the same `tree_compile_*` macro, so any divergence is an
argument-marshalling bug in the C++ layer — which is precisely the bug class this increment can
introduce and the only one the corpus is blind to.

This is the same discipline as the two-front-end differential in 41/41b: compare two independent
implementations rather than one implementation against transcribed expectations.

## 7. Sequence after the MVP

Each gets its own spec. Ordering reflects dependencies, not priority.

| | increment | notes |
|---|---|---|
| 2 | the O(n) stack walk replacing derived `_parent`/`_size`/`_children`/`_next` and P13 | §10's named replacement; the performance win |
| 3 | `tree_encode` as a hash-based in-memory DFS | §10 |
| 4 | the css front-end as its own extension, registering per §4 | brings back the 9 suites and the 6 front-end mutants |
| 5 | planner-side use of O | explicitly deferred out of M3 "to the C++ port" |
| 6 | W: attachments and the tri-state frontier | D-N4 and D-N5 put the slots in core; issue #33 proves it cannot be fixtured in macros |
| 7 | the 2.0 grammar via `GrammarExtension` | preview API; §8's transformers carry no semantics |

## 8. Decisions

**Settled by this design**

- D-N10 — language registration API: a row in `tree_catalog.selector_languages` naming the
  parser function. Registration is SQL, so a front-end extension needs no C++ hook.
- Atomicity belongs to the executor, not the compiler (implemented, `a21d889`).
- A front-end's registration lives in the front-end's own file, so the file boundary is the
  extension boundary (implemented, `7320ed2`).

**Carried into later increments**

- D-N25 — the two ATTR tiers disagree about coercion. The MVP inherits the macros' behaviour
  unchanged, so it is unaffected; the increment that reimplements comparison in C++ must choose a
  rule rather than inherit an accident.
- Querying an abstract tree leaks the projection compiler's internal object name
  (`Table Function with name proj_4_main_abs1 does not exist!`) where the DDL reference promises a
  bind-time refusal. Not an MVP regression, but it is a Doctrine 4 gap that the executor layer is
  the natural place to close.

## 9. Risks

| risk | handling |
|---|---|
| sqllogictest error-matching differs from duckent's runner | enumerate the records that move; do not silently rewrite expectations |
| extension-load cost of executing 263 KB of DDL | measure once the skeleton loads; the macros are catalog-level, so the cost is per database, not per connection, and sitting_duck already does this |
| the two repositories' macros fork | the byte-identity `--check` of §2, in CI, from the first commit |
| `CALL` argument marshalling of STRUCT Values | the per-verb compile differential of §6.4 is the test for exactly this |
| doing verb work in `bind` | stated as a rule in §3.1; a verb firing under `EXPLAIN` is the symptom to test for |
