# SHAPE Syntax Exploration — semantics without CREATE, applied ad hoc
*Method: enumerate the design space, then execute it — all candidate ingredients tested against DuckDB 1.x tonight (log in §4). Status: **settled reference** — §2e–§2j amended §1–§2d and **§2k (2026-10-15) supersedes §2b**, and the sketches below are kept current with them; the appended sections carry the rationale. Every apply-slot and MATCH example below is written in the §2k grammar.*

*Slot names here are the catalog's, as [`cheatsheet.md`](cheatsheet.md) measures them: `TYPE`, `KEY`, `TAGS`, `ATTR`, `ATTR_MAP`, `PREDICATE`. Selector spellings stay CSS's — `.x`, `#x`, `[a=b]`, `:x` — per the one naming rule. The clause spellings in this document are the proposed 2.0 surface; the shipped macro spellings are the cheatsheet's.*

## 1. The decomposition
The ask splits into two orthogonal objects, and naming that split is most of the design:
- **SHAPE** = the ROWS slot bundle *without data*: basis, TYPE/KEY/TAGS, ATTR tiers, PREDICATE bindings, O declarations. Pure semantics, catalog-resident, reusable.
- **TREE** = SHAPE × source (× lifetime). `CREATE TREE` stops being primitive and becomes composition: *register a shaped source*.

```sql
CREATE TREE ast (                                    -- abstract: §2c
  SHAPE ONLY,
  ROOT  (file_path),                                 -- required iff >1 tree (§2d)
  ORDER node_id,  LEVEL depth,
  TYPE  semantic_type_to_string(semantic_type),      -- optional: S0°, defaults 'node' (§2h)
  ATTR  (name := name, start_line := start_line),    -- named/typed tier
  ATTR  (COLUMNS('attr_(.*)') AS '\\1'),              -- bulk-bind: verified ✓
  ATTR_MAP extra,                                     -- catch-all tier
  PREDICATE (docblock := has_docblock(file_path, node_id),
             leaf     := descendant_count = 0),       -- row-scope expressions (§2j)
  SIZE descendant_count OPTIMIZE                      -- O overrides (§2i: CHILDREN/NEXT provisional)
);
```

## 2. Ad hoc application — candidates & verdicts
| # | Syntax | Verdict |
|---|---|---|
| A | `FROM 'code.parquet' USING TREE SHAPE ast MATCH WITH css '.fn'` (keyword order: §2b, superseded by §2k) | **Recommended.** Postfix modifier chain on a FROM item — exact precedent: `USING SAMPLE` (verified ✓). Reads as the pipeline it is: *source → semantics → query*. FROM-first native; each modifier a TableRef-suffix PEG rule (small extension surface); MATCH on an unshaped source is a bind-time error with the missing slot named. Anonymous form: `USING TREE SHAPE (LEVEL depth)` — TYPE optional since §2h, noun per §2k. |
| B | `TREE 'code.parquet' SHAPE ast` | **Accepted as sugar** — statement-level shorthand mirroring `TABLE src` (verified ✓). Whole-statement brevity for exploration; desugars to A. |
| C | `TREE ast FROM 'code.parquet'` (proposed) | **Ranked down.** Semantics-before-source reverses the read order every other construct in the house teaches (FROM-first, pipes, modifier chains: data first, meaning second, question third). Also statement-initial `TREE` collides with B and crowds future `CREATE TREE`. |
| D | `FROM TREE 'code.parquet' (SHAPE ast …)` (proposed) | **Ranked down.** The parenthesized clause mid-FROM fights the modifier-chain pattern and reads as a function call that isn't one; everything it does, A does with less grammar. |
| E | `FROM tree('code.parquet', shape := 'ast')` | **Kept as the compatibility spelling** — a real table function, no new grammar, works pre-2.0; the PEG form A desugars to it. |

### 2b. Keyword order within the modifier (decided this pass; **SUPERSEDED by §2k, 2026-10-15**)
Candidates: `USING SHAPE ast` · `USING TREE SHAPE ast` · `USING TREE ast` · `USING ast TREE SHAPE` (rejected instantly: SQL keywords introduce, names follow — cf. `USING SAMPLE 10`).
**Decision: `USING TREE <shape-name | (rules)>`.** *— superseded by §2k, which takes `USING <KIND> SHAPE <name>`; rationale (3) below is the cost §2k deliberately accepts, and (1) and (2) survive. Read §2k before citing this paragraph.* Rationale: (1) PEG hygiene — composable grammars want one unambiguous head token per extension's modifiers; ordered choice fails fast on `TREE`, and duckent doesn't squat on a generic word. (2) Collision avoidance — to the duckdb-spatial audience, `USING SHAPE` reads *shapefile*. (3) Brevity — `USING TREE SHAPE ast` spends two keywords where one carries the meaning. SHAPE survives only as the `SHAPE ONLY` marker inside CREATE TREE (§2c superseded the separate catalog kind).
**Disclosed wrinkle:** the modifier keyword says TREE while its argument names a shape. Unambiguous (raw sources can't take tree names in that slot; shapes and trees are separate catalogs) and read naturally as "under the tree-semantics named ast" — but stated in the spec so it reads as a decision, not an oversight.
### 2c. Supersession: LIKE instead of a SHAPE catalog kind (decided this pass, Teague's design)
Shapes are not a second catalog kind; they are **abstract trees**. One kind, existing keywords:
```sql
CREATE TREE sitting_duck_ast ( SHAPE ONLY, LEVEL depth, TYPE …, PREDICATE … );  -- abstract
CREATE TREE t LIKE sitting_duck_ast AS FROM 'code.parquet';                    -- instantiate
CREATE TREE py_ast LIKE sitting_duck_ast ( SHAPE ONLY, PREDICATE (docstring := …) ); -- refine, still abstract
FROM 'code.parquet' USING TREE SHAPE sitting_duck_ast MATCH WITH css '.fn:not(:has(:docblock))';
FROM 'code.parquet' USING TREE SHAPE (LEVEL depth) MATCH WITH css '.fn';       -- anonymous; TYPE defaults 'node'
FROM code MATCH .fn:not(:has(:docblock)) SELECT name;                          -- bare MATCH in the pipeline (§2g)
FROM code MATCH $( .fn[WHERE name IN (SELECT f FROM flagged)] ) SELECT *;      -- host escape ⇒ $( ) required (§2f–g)
```
Rules: **LIKE copies semantics, never source** (the universal LIKE contract: structure, never data). **SHAPE ONLY is required when no AS clause is present** — sourceless-by-omission would surface as confusion three queries later; the marker makes abstractness declared intent (house legibility doctrine). `FROM <shape-only tree>` errors at bind with "SHAPE ONLY; no source bound." Postgres's `INCLUDING/EXCLUDING` option family is reserved future syntax over the blocks (`LIKE ast EXCLUDING O`). **This dissolves §2b's disclosed wrinkle**: `USING TREE SHAPE` (§2k) now takes a tree name, uniformly — abstract or concrete — and the footnote defending the mismatch deletes itself, which is how you know the second design won.

### 2d. Forest key & tree-granular DML (decided this pass, Teague's requirement)
Multi-tree sources need the column(s) that delimit independent trees declared — the slot every window in this project has been quietly using:
```sql
CREATE TREE sitting_duck_ast (
  SHAPE ONLY,
  ROOT (file_path),                -- the forest key: delimits, identifies, and attaches
  LEVEL depth, TYPE …, PREDICATE … );

INSERT INTO t FROM read_ast('new.py');            -- append trees (new key values)
DELETE FROM t WHERE file_path = 'old.py';          -- drop a tree
INSERT OR REPLACE INTO t FROM read_ast('mod.py');  -- re-derive that tree, by key
```
Semantics: the entire R block is **scoped by the forest key** — order, the level invariant, basis derivations, O defaults, and P13 all hold per partition; cross-partition adjacency is *ill-typed* (the old cross-file LEAD guard graduates from verify-list caution to law). DML is **tree-granular**: appending and dropping whole partitions is safe and P13-checked on ingest; within-tree mutation is re-derivation (epoch bump), never row surgery — the forest key is a primary key at tree granularity, `INSERT OR REPLACE` is re-derivation spelled in shipped syntax, and renumbering never crosses a partition you didn't wholly replace. **Spelling decided (this pass): `ROOT (col, …)`** over PARTITION BY (names only the delimiting role; storage connotations) and IDENTIFIED BY (Oracle auth smell). ROOT names all three roles the key plays — delimit / identify / attach — with the semantics: *ROOT columns are the tree's identity, constant on every row.* Two dividends: (1) **W1's root-restriction becomes structural** — the only cross-tree reference a row can express is its ROOT value, identical across the tree, so interior-node FKs are impossible by schema shape, not forbidden by review; (2) **ATTACH inference** — with ROOT on the child and a KEY accessor (S1) on the parent, `ATTACH ast TO fs` defaults to the ROOT ↔ parent-KEY join; `USING (…)` covers mismatches only. Default when unspecified: **the relation is one tree** (one partition; multiple roots still legal — R2 permits level returning to 0). Per-tree order resets without a declared key are non-monotone order, rejected by P13 — the key isn't bureaucracy; it's what makes resets legal. This is also why SHAPE ONLY is *required* for abstract trees: the key slot must exist before any row does.

Pipe composability falls out of A for free: `FROM 'code.parquet' |> USING TREE SHAPE ast |> MATCH WITH css '.fn' |> AGGREGATE count(*)`.

## 3. The implementation secret (found by prototyping, not design)
**A SHAPE compiles to a projection macro** — canonical columns (`_pre`, `_level`, `_type`, …) plus registry metadata — and `USING TREE SHAPE` is macro application; `MATCH` generates its query against the canonical columns only. Verified end-to-end tonight: `shape_toy(src)` as a projection table-macro over `query_table(name)`, then `match_toy(src)` nesting it — **the modifier chain already runs as macro composition in shipped DuckDB** (✓ chained, ✓ correct rows). Consequence: the pre-2.0 bridge is not a prototype of the design; it *is* the design, minus sugar — and P14 gets a mechanical enforcement for free, since MATCH physically cannot see columns the projection didn't emit.

## 4. Experiment log (all OK, DuckDB 1.x, this container)
- `tree`, `shape`, `match` all valid identifiers → soft-keyword path open, zero reserved-word cost.
- `FROM range(100) USING SAMPLE 10 ROWS` → the postfix-modifier precedent is live syntax.
- `TABLE src` → statement-shorthand precedent for candidate B.
- `query_table('src')` → name-to-relation indirection for the macro bridge.
- `shape_toy` / `match_toy` nested TABLE macros → shape application and matching compose today.
- `SELECT COLUMNS('attr_(.*)') AS '\\1'` → bulk ATTR binding with rename, shipped.
- `x -> x + 1` lambdas → tested viable at the time; **superseded by §2j** (PREDICATE takes row-scope expressions; lambdas removed — DuckDB's own lambda syntax also migrated to Python style).
- Bridge limitation: TABLE macros take names/scalars, not subqueries → pre-2.0 ad hoc form requires a named view or file path (acceptable: files and views are the ad hoc cases anyway).

## 5. Answers to the direct questions
- **ATTR/ATTR_MAP/PREDICATE as expressions:** yes, normative — every slot is an arbitrary scalar expression over the row; macro use is an ordinary call expression (§2j); the earlier macro-name and inline-lambda forms are removed.
- **COLUMNS expressions in ATTR:** yes, verified — `ATTR (COLUMNS('attr_(.*)') AS '\\1')` bulk-declares the named tier from column patterns; the DuckDB star-expression machinery is exactly the right borrowed tool.
- **Semantics without creation:** `CREATE TREE (SHAPE ONLY, …)` (named, reusable; §2c) + `USING TREE SHAPE (…)` (anonymous, inline) + form E (functional, today).

## 6. Ripple (on adoption — not yet applied)
CREATE TREE recomposes as `CREATE [VIRTUAL|TEMP] TREE t LIKE s AS FROM … [ATTACH …]` (§2c spelling); duckent build prompt M0 gains "SHAPE registry + projection compiler" as the actual first milestone; lesson examples carry the `USING TREE SHAPE` spelling (§2k; they carried `USING TREE` until 2026-10-15). Gate passed; all of this landed (lesson v18, handover v21).


## §2e — The FILTER question, dissolved (decided)
Raw row/column filtering needs **no keyword**; the itch marks four undeclared defaults:
1. **MATCH emits raw rows.** The shape projection is the *matcher's* view, not the result type — semantics see declarations, output sees rows. Post-match `WHERE` is the raw filter for subject nodes, typed, macro-free.
2. **Attrs default-open on concrete trees, closed on abstracts.** Every column unclaimed by R/O slots is automatically a named S3 attribute (bare-column accessor — already contract-legal), so `[col > 100]` works in any structural position with zero declaration. `SHAPE ONLY` abstracts stay closed: the declared interface is the type, and P14's differential test depends on it. Escape on a closed shape is composition, not a hole: `USING TREE SHAPE (LIKE shape, ATTR extra := col)`.
3. **Anonymous `FROM … MATCH`: producer-registered shapes, never column sniffing.** Table functions register default shapes for their own output (sitting_duck registers for `read_ast` — incl. `ROOT (file_path)`, which no sniffer could infer); otherwise refusal-with-hint. Sniffing misbinds silently: a column named `level` that isn't depth yields wrong *matches*, not errors. Anonymous trees are precisely the trees that get open attrs (points 2+3 fuse).
4. **P21, filter granularity.** Row removal *before* tree interpretation is ROOT-granular only (partition pruning); a pre-MATCH predicate on a non-ROOT column deletes interior rows and corrupts level sequences — refuse or route to post-match. Same knife as DML granularity.
Open decisions: D-N6 explicit `USING TREE SHAPE AUTO` opt-in sniff (default: no); D-N7 spelling of shape registration API for producers.


## §2f — Host escapes and MATCH delimiters (decided; partially supersedes §2e)
§2e's claim that open attrs cover structural positions was wrong — the attribute micro-language cannot express subqueries, BETWEEN, AND-trees, or function calls (Teague's counterexamples). Precedent: SQL:2023 `GRAPH_TABLE` embeds host-SQL WHERE over pattern variables inside MATCH.
1. **`[WHERE <sql>]` — the host-escape bracket.** Brackets already mean "predicate on this node"; the WHERE keyword switches dialect from micro-language to host SQL. Legal in any position, incl. inside `:has(…)` (a bracket is a valid simple selector). Rejected spellings: `.fn (WHERE …)` — whitespace is the descendant combinator, sacred; `.fn(FILTER …)` — collides visually with pseudo-class args. Keyword WHERE over FILTER: echoes SQL's `FILTER (WHERE …)` inner shape and GRAPH_TABLE.
2. **P14 intact by construction:** the escape compiles against the node's **projection view**, never the raw relation — concrete trees see everything (openness), closed abstracts still refuse undeclared columns. Power added, visibility unchanged. Mutant MN19: a `[WHERE]` compiled against the raw relation on a closed shape (must die).
3. **`MATCH $( … )` — yes, MATCH ends.** Needed exactly when selectors stop being string-shaped (SQL-in-selector-in-SQL quoting). Symmetry doctrine: **`$( )` is the door from SQL into selector-land; `[WHERE ]` is the door back.** Balanced delimiters, PEG-trivial. Pre-2.0: string form stays (dollar-quote `$sel$…$sel$` for gnarly cases); post-2.0: `$( )` recommended whenever a host escape appears.
4. **Dialect doctrine:** selectors containing `[WHERE]` are *host-bound*; the portable fragment (eval corpus, GBNF, cross-surface reuse, umwelt exact rules) excludes them. Two dialects, one grammar, flagged at parse.


## §2g — Escape heads and bare MATCH (decided)
1. **Host escapes require an explicit head**: `*[WHERE …]` or `type[WHERE …]`; bare `[WHERE …]` is ill-formed. Micro-language predicates keep CSS's implied-universal (`[x=3]`, `:docblock` legal bare — the flagship selector depends on it). Rationale: the stray-space bug — `a[WHERE…]` filters the node, `a [WHERE…]` inserts an anonymous descendant constraint; requiring the head turns the accident into a parse error instead of a wrong answer. XPath precedent (`*[pred]` is its only spelling). Doctrine line: *SQL never floats; it hangs off a node.* Mutant MN20: bare `[WHERE]` accepted (must refuse with the head hint).
2. **Bare MATCH flows into the clause pipeline** for the portable fragment: `FROM … USING TREE SHAPE … MATCH WITH css .fn:not(:has(:docblock)) SELECT … WHERE … GROUP BY …`. Termination = next top-level SQL clause keyword, scanned outside balanced brackets (bracketed strings invisible to the scan; bare mode has no outer string literal, dissolving quote-doubling entirely). Keyword-typed selectors — certain to occur, since the 28th grammar is SQL and its ASTs contain `select` nodes — use the host's identifier escaping: `MATCH WITH css "select" > "from"`; clause-keyword exit wins by ordered choice. `$( )` **required iff a host escape appears** (error legibility; symmetry doctrine: *if you open the inner door, close the outer one*), always permitted for certainty. Rejected: `MATCH … END` (CASE…END is sui generis; two closers is one too many) and plain `( )` (reads as a `match(…)` call).


## §2h — TYPE optional; the R/S refactor (decided)
R1+R2 are the minimal treeness set. TYPE moves out of R into **S0°** — total, default constant `'node'` — because a type dimension is a *selection* need, not a *tree* need: `CREATE TREE toy (LEVEL depth) AS FROM …` is complete, matches `*` and every structural combinator, and grows type selectors the moment `TYPE` is declared. R0° ROOT is required iff the relation holds >1 tree (unchanged default). Per-slot benefit tables now live in lesson chapters 4·R–4·S.


## §2i — Presentation order and O clause spellings (decided / provisional)
Teaching and definition order is **R → S → O → W** (structure, speech, speed, world) — dependency strata, each leaning only on earlier ones; the *name* stays **ROWS**, revealed as a rearrangement at the end (found, not planned). Honest wrinkle: O's staleness namespace cites W2's load watermark, so the layering is pedagogical, not a strict DAG — acceptable, since O is inert either way. O3/O4 DDL clause spellings **provisional (D-N8)**: `CHILDREN col OPTIMIZE`, `NEXT col OPTIMIZE` (consistent with settled `PARENT`/`SIZE … OPTIMIZE`).


## §2j — PREDICATE values are expressions, not lambdas (decided)
The PREDICATE clause value is an ordinary **expression in the tree's row scope** — the generated-column / CHECK-constraint precedent: SQL already evaluates expressions per row in table scope, so no lambda syntax and no binding machinery are needed. Macro use is just a call expression: `PREDICATE (docblock := has_docblock(file_path, node_id))`. Inline lambdas are removed from the design entirely — also prudent because DuckDB's lambda syntax itself migrated (arrow style deprecated in favor of Python-style `lambda x: …`), and a shape spec shouldn't sit on a moving target. **Two tiers beyond the per-name binding, and they are not the same tier.** The earlier one-line `PSEUDO PREFIX 'sel_…'` conflated them; as the macro surface implements and [`cheatsheet.md`](cheatsheet.md) measures them:
- A **prefix binding is explicit and per tree.** It names a macro prefix and an argument list, enumerates every catalog macro carrying that prefix, and binds each under the part of the name after it. `tree_catalog_predicates().origin` records `prefix`. Macro spelling today: `predicate := [{prefix: 'pre_', args: 'depth'}]`; the DDL clause spelling for this form is not settled, so no `PREDICATE PREFIX` syntax is claimed here.
- The **shared `sel_` tier is automatic and catalog-wide**, scanned for every tree, recorded as `origin = 'shared'` — but it **binds nothing unless the tree declares `predicate_args`**, because the shared tier has no other source of arguments. A tree without it gets zero shared predicates however many `sel_` macros exist.

A tree-local binding still shadows both (same name, one row, `origin = 'local'`). And a macro already bound under one name is not bound again under another: with both a `pre_` prefix binding and a `sel_shallow` macro in the catalog, `shallow` is bound once, by the prefix binding, to `pre_shallow(depth)` — the prefix binding claims the macro and the shared tier skips it.

## §2k — One grammar for a family of shaped relations (decided 2026-10-15; **supersedes §2b**)

**Decision: `USING <KIND> SHAPE <name> [INCLUDING/EXCLUDING …]`, and `MATCH [WITH <lang>] <selector>`
with TREEQL as the default dialect.** So the ad hoc apply slot takes an explicit `SHAPE` noun, and
a CSS selector now requires naming its dialect:

```sql
-- before (§2b)
FROM 'code.parquet' USING TREE SHAPE sitting_duck_ast MATCH WITH css .fn:not(:has(:docblock)) SELECT name;
-- after (§2k)
FROM 'code.parquet' USING TREE SHAPE sitting_duck_ast MATCH WITH css .fn:not(:has(:docblock)) SELECT name;
```

**This reverses §2b, whose third rationale was exactly the cost now being paid:** "Brevity —
`USING TREE SHAPE ast` spends two keywords where one carries the meaning." That reasoning was
sound on its own terms and is overtaken rather than refuted. §2b was choosing a spelling for *one*
kind of shaped relation; the decision here is that duckent is one member of a family that shares a
grammar:

| kind | what the shape describes | status |
|---|---|---|
| `TREE` | duckent's trees — the R/S/O decomposition of §1 | today |
| `NDARRAY` | n-D arrays presented as relations, same contract discipline (working name **czarr**) | sibling, forward reference only |
| `TABLE` | another table's structure — `FROM src USING TABLE SHAPE foo INCLUDING CONSTRAINTS, FOREIGN KEYS` | sibling |

Once `KIND` varies, the second keyword stops being redundant and starts being the noun the whole
family shares: `USING TREE <name>` cannot generalise, because `USING NDARRAY <name>` would read as
a different construct rather than the same one. The brevity §2b bought was brevity in a grammar
with one kind in it.

§2b's other two rationales survive intact and are *strengthened* by the change. PEG hygiene (1) is
unaffected: `USING` is still followed by one unambiguous head token, and `KIND` is that token.
Collision avoidance (2) — "to the duckdb-spatial audience, `USING SHAPE` reads *shapefile*" — is
better served here than by §2b's own spelling, because `SHAPE` never appears unqualified: `USING
TREE SHAPE` and `USING NDARRAY SHAPE` both name their kind first, so the shapefile reading has
nowhere to land.

**The anonymous inline-rules form folds in as `USING TREE SHAPE (rules)`.** §2b's alternation was
`USING TREE <shape-name | (rules)>`; the noun is inserted ahead of the alternation rather than
replacing it, so an inline shape stays expressible and reads as what it is — a shape given by value
instead of by name.

**The noun is `SHAPE`, not `SCHEMA`.** Verified on DuckDB **v1.5.6**: `shape` is not a keyword at
all, zero collision, whereas `schema` is unreserved but semantically loaded with SQL's own
namespace concept (`CREATE SCHEMA`, `information_schema`, qualified names) — the same
overload-avoidance principle behind §2b(2) and §2i. *(The keyword check was run on v1.5.6; this
repository pins 1.5.5, and both facts are stable across the 1.5.x line.)*

The stronger argument is not the keyword table but this repository's own practice: `SHAPE` is
**already** duckent's value-level noun. `TREE_SHAPE` is a declared type, `tree_shape(...)` is the
constructor callers write, and the DDL verb already holds both words apart in one signature —
`tree_ddl_create(db, schema, name, tree_spec(tree_shape(...)))`, where `schema` is the SQL
namespace and `shape` is the structure. Adopting `SCHEMA` for the structure would re-collide a
distinction duckent has been living with cleanly since M0. `SHAPE` is also the array-native word
(numpy and xarray both spell it `.shape`), which is what the `NDARRAY` sibling will want.

**Granular inheritance rides on `LIKE … INCLUDING/EXCLUDING`,** already reserved at §1's sketch
(`LIKE ast EXCLUDING O`). That is the mechanism for pulling constraints and foreign keys on the
`TABLE` case, and it is the reason `SHAPE` does not need to swallow `SCHEMA`'s richer connotation:
a shape is the skeleton, and what rides along with it is named explicitly at the call site rather
than implied by the noun.

### The dialect clause, and one consequence that is not yet resolved

`MATCH WITH <lang>` resolves `<lang>` through `tree_catalog.selector_languages`, which is the
existing front-end seam — the registry whose `bare_safe` column already decides whether a language
may appear undelimited (§2f, §2g). Nothing new is needed to *dispatch* a dialect.

**But the default dialect is the one language that cannot currently be parsed from text.** The
registry holds `('treeql', NULL, 'tree_selector_to_treeql', true)`, and that `NULL` is the parser
column: TREEQL is the IR's own spelling, so until the text parser lands (M-LANG) a selector handed
over as TREEQL text is refused — by that lookup rather than by a hardcoded branch, which is
deliberate. So on adoption of this decision, `MATCH WITH css` is the only spelling that resolves,
and a bare `MATCH` resolves only once M-LANG ships.

That is a sequencing question, recorded here rather than silently inherited:

- **either** M-LANG lands first, and bare `MATCH` means TREEQL from the day the grammar changes;
- **or** the grammar ships with CSS as the de-facto working dialect and the docs say so plainly,
  with bare `MATCH` reserved.

The inputs are measured and not in doubt: the printed TREEQL form needs a quote- and paren-aware
tokenizer (its separators appear inside `WHERE` and `ATTR` bodies), such a tokenizer **is**
expressible as a pure SQL macro, and the round-trip contract is exact on canonical IR and
normalising on hand-built IR. D-N15 is also already decided (bare identifiers accepted on input,
quoted literals still emitted). What remains is the order, which is a release decision rather than
a design one.
