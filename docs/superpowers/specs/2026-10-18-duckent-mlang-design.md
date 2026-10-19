# M-LANG: a reader for TREEQL text — design

*Status: designed 2026-10-18. Scope: the text parser for the `treeql` selector language — the
first non-NULL value in `tree_catalog.selector_languages.parser` for that row. Baseline: main at
`260d272`, after the slot engine (#66) and the grammar unification (#67).*

## 1. The gap, stated exactly

duckent has two surface languages and one IR. One of them can only be written, never read:

| | text → IR | IR → text |
|---|---|---|
| `css` | **yes** — two independent front-ends, bound by a differential | yes, via the TREEQL printer |
| `treeql` | **no** | yes — `tree_selector_to_treeql` |

`tree_catalog.selector_languages` records that asymmetry as data:

```
('css',    'tree_css_lower', 'tree_selector_to_treeql', true)
('treeql',  NULL,            'tree_selector_to_treeql', true)
```

That `NULL` is the parser column. A selector handed to `tree_match` as TREEQL *text* is refused by
a lookup that finds no parser — deliberately, by a registry read rather than a hardcoded branch,
so the refusal names the missing capability instead of pretending the language does not exist.

**Three things make the gap worse than an inconvenience, and all three are new since M2.**

1. **The grammar unification made TREEQL the default dialect.** Doc 14 §2k settles
   `MATCH [WITH <lang>]` with TREEQL as the default, so a bare `MATCH` means TREEQL — the one
   language that cannot be parsed. Until this lands, `MATCH WITH css` is the only spelling that
   resolves, and the default is a trap. §2k records the sequencing as an open release decision;
   this design is the half that closes it.
2. **css tells the author to use TREEQL text.** The refusal is live, in six places:
   `css: css has no host escape: mint a PREDICATE, or MATCH USING TREEQL`. It directs the author
   to a language with no reader. (It also spells the clause the pre-§2k way; renaming it to
   `MATCH WITH treeql` is a separate code-and-tests change, recorded as a follow-up in §2k.)
3. **The slot engine added three relations css cannot express.** `PARENT`, `ANCESTOR` and
   `PRECEDING` joined `desc`, `child`, `self`, `next`, `after`. With the host door (`WHERE`), that
   is four constructs reachable only through TREEQL — and TREEQL is unreadable.

So the engine can now say more than any readable language can ask.

## 2. The language, read off the printer

The printer is the specification. Measured on `260d272`:

```
selector  <- step ( NEWLINE step )*
step      <- rtrim( comb? '(' clauses ')'? ( ' AS ' alias )? )
clauses   <- part ( ', ' part )*
part      <- clause / group
group     <- ('HAS' / 'NOT') ' ( ' step ( ' ' step )* ' )'
clause    <- 'TYPE' lit / 'ID' lit / 'CLASS' lit / 'PSEUDO' lit
           / 'ATTR' name op arg          -- unquoted, all three
           / 'WHERE' sql                 -- raw host predicate
lit       <- "'" ( [^'] / "''" )* "'"
comb      <- DESCENDANT / CHILD / SIBLING / FOLLOWING / SELF / PARENT / ANCESTOR / PRECEDING
```

Real output, and note the asymmetries — they are the printer's accidents, not design:

```
(CLASS 'fn')                                        -- step parens UNPADDED
(CLASS 'fn', NOT ( DESCENDANT (PSEUDO 'docblock') )) -- group parens PADDED
(TYPE 'block', ID 'x', ATTR name = 'y')             -- ATTR body unquoted
SIBLING (TYPE 'string')
(CLASS 'fn') AS f
CHILD                                                -- a comb with no clauses prints bare
(TYPE 'it''s')                                       -- doubled-quote escaping
(TYPE 'fn', WHERE length(name) > 3)                  -- raw SQL in a clause body
```

### 2.1 Why this needs a real tokenizer

`WHERE` and `ATTR` bodies are emitted **unquoted and unescaped**, so the clause separator and the
step's closing paren both occur *inside* clause bodies:

```
(TYPE 'x', WHERE name IN ('a', 'b'))    -- ", " inside WHERE; ")" before the step's own
(ATTR lang = 'p)y')                     -- ")" inside a quoted literal
(TYPE 'a, b', PSEUDO 'p')               -- ", " inside a quoted literal
```

A split on `', '` or `')'` mis-parses all three. The reader must track single-quote state and
paren depth.

**This was spiked before the design was accepted, and the spike passed.** A quote- and
paren-aware split is expressible as a pure DuckDB SQL macro: "inside a quote" is the *parity* of
quote characters strictly before a position — which makes the `''` escape fall out for free, since
two quotes restore the parity — and paren depth is a second window over the column the first
produced, which needs a CTE layer rather than nesting. Seven cases pass, including all three
above; the naive split fails the sharpened ones, so the cases discriminate. Macro composition was
verified two levels deep, because the printer records a 1.5.5 binder bug for CTE references across
macro boundaries and that bug would have killed this approach.

### 2.2 The one genuine ambiguity, and why it is a limit rather than a hole

A `WHERE` body containing a **top-level** comma is ambiguous: `WHERE a = 1, PSEUDO 2` reads as two
clauses. No valid boolean predicate has a bare top-level comma — commas appear inside function
calls and `IN` lists, which are parenthesised — so this is unreachable from valid input. It is
asserted as a documented limit rather than reasoned about, because "unreachable" is a claim and
claims in this repo get tests.

## 3. The contract

Two theorems. The first is the strong one and holds only for canonical IR; the second covers
everything the printer accepts.

**Exact, on canonical IR.** For any selector `tree_steps` builds,
`tree_parse_treeql(tree_selector_to_treeql(ir)) == ir`, row for row, node ids included.

This is achievable because canonical numbering is recoverable from the text. Canonical IR is
dense, 0-based and pre-order — a step, then its clauses in slot order, then its groups:

```
0 selector 'treeql' | 1 step AS f | 2 type 'fn' | 3 has | 4 step child | 5 type 'block' | 6 step desc | 7 type 'string'
```

The printer orders steps and parts by `node_id`, so textual order *is* node_id order, and a
counter incremented as parts are encountered reproduces the ids.

**Normalising, on everything else.** For any IR the printer accepts — including hand-built rows
with sparse ids, which the host door exists to allow — `parse(print(ir))` is the *canonical
renumbering* of `ir`, and `print(parse(print(ir))) == print(ir)` byte for byte.

The weaker claim is not a concession: the host door's whole purpose is to accept rows nothing
numbered canonically, so a design that promised exactness there would be promising to recover
information printing discards.

**Provenance.** The parser stamps `value = 'treeql'` on the selector row, which is what
`tree_selector_language` reads back and what `_match_language` coalesces against. Canonical IR
already carries that stamp, so the exact theorem is undisturbed; css stamps `'css'`, which is how
one IR records which of two readings produced it.

## 4. Grammar scope: tolerant input, canonical output

**Accepted:** whitespace and keyword case freely. `( type 'x' )  as  fn` and `(TYPE 'x') AS fn`
parse to the same IR. This matters because the printer's own spacing is inconsistent (§2) — a
reader that demanded byte-exact printer output would make the rule a human must learn an accident
of the printer rather than a design.

**Emitted:** unchanged. The printer keeps writing `TYPE 'foo'`.

That split is what makes the theorems in §3 stateable: they are stated over the printer's output,
which is one point in the accepted set, so tolerance costs them nothing. Every expectation already
pinned in the corpus stays valid.

**Bare identifiers are accepted (D-N15, decided 2026-10-15).** `TYPE foo` parses as `TYPE 'foo'`.
A bare operand must match `[A-Za-z_][A-Za-z0-9_]*` and must not be a reserved word. Anything else
is quoted; a value containing a quote keeps the printer's doubling.

### 4.1 The reserved set is data, not a list in the parser

This is the slot engine's dividend and it is load-bearing. The reserved words are
`clause_kinds.keyword ∪ combinators.keyword ∪ {AS, HAS, NOT}` — read from the catalog. Seventeen
on `260d272`:

```
ANCESTOR AS ATTR CHILD CLASS DESCENDANT FOLLOWING HAS ID NOT
PARENT PRECEDING PSEUDO SELF SIBLING TYPE WHERE
```

Three consequences, each a reason not to hardcode them:

1. **Registering a combinator extends the grammar with no parser edit.** `PARENT`, `ANCESTOR` and
   `PRECEDING` were added to the engine as rows, with no macro changed; the parser inherits them
   the same way.
2. **Registering a combinator is therefore a grammar change.** A row spelled `ANCESTOR` makes a
   bare `TYPE ANCESTOR` ambiguous from that point on, and it must be written `TYPE 'ANCESTOR'`.
   §11 of the slot-engine spec records this; the parser is where it becomes operative.
3. **No selector becomes unexpressible** — only some become un-bare-able, because the quoted form
   is always available and always unambiguous. That is why the coupling is acceptable.

## 5. Where the parser lives, and why

**`sql/10_treeql.sql`, as macros.** Two reasons, and the first is not a preference:

- **The extension embeds `sql/*.sql` byte-identically** and fails CI on a single byte of drift. A
  parser written as macros ships in the extension with **no C++**, which the extension's own
  global constraint requires: "the C++ is an executor layer only. It decides nothing about trees."
- **It registers itself from its own file**, exactly as `09_css.sql` inserts the css row:
  `UPDATE tree_catalog.selector_languages SET parser = 'tree_parse_treeql' WHERE language =
  'treeql'`. The `CREATE TABLE` stays in `01_catalog.sql`, which the MVP extension does embed, so
  a core-only build still finds `parser IS NULL` and still refuses text — the byte-identity
  invariant is "the extension's difference is WHICH FILES it embeds, not what they say", and this
  preserves it.

**`test/treeql_parser.py`, as the independent second reading.** Test-only, never shipped, and
deliberately **database-free** — the reason `test/css_parser.py` has zero duckdb references. A
differential between two readings is evidence only if the readings are independent; one that read
the registry would agree by construction, and `sql/09_css.sql` states what that is worth:
"Two independent readings of one grammar is the point; agreeing by construction would prove
nothing."

Note the cost this accepts, because it is the one place this design knowingly duplicates: the
Python reference must carry its own copy of the reserved set and the slot order, and that copy is
bound by the differential rather than by the registry. That is the same arrangement css already
lives with, and the slot-engine review confirmed the binding works — `38_css_lower.test` compares
IR structs including `node_id`.

## 6. Groups unroll; they do not recurse

DuckDB macros cannot self-recurse, so the parser unrolls to `tree_group_depth_limit()` — **2** on
`260d272` — exactly as the printer does, and inherits the printer's justification verbatim: a
selector nested deeper is **refused**, because the alternative is silently losing its innermost
groups. Raising the limit means adding one pass to each of the printer and the parser, which is
the cost the printer already documents.

## 7. Refusals

Prefixed `tree_parse_treeql:`, for what only a reader can detect:

| input | refused with |
|---|---|
| a clause keyword nothing defines | `unknown clause keyword FROBNICATE` |
| a combinator keyword nothing defines | `unknown combinator SIDEWAYS` |
| an unterminated quoted value | `unterminated quoted value` |
| unbalanced parentheses | `unbalanced parentheses` |
| no steps at all | `selector has no steps` |
| groups nested past the limit | the printer's own wording, reused |

**Every rule that already exists is routed through its existing holder, never restated.**
`tree_sql_is_ident` for aliases, `tree_selector_group_depth` against `tree_group_depth_limit()`
for nesting, and the clause-kind and combinator vocabularies from the registry. Restating a rule
the macros already state is what the slot engine removed thirteen copies of; this design does not
reintroduce the pattern.

## 8. Gates

Each one with how it is shown to fail, because a gate never seen to fail is not evidence — the
slot engine found four gates that passed while covering less than they claimed, including one that
was blind to exactly the inputs it existed to police.

| gate | what it proves | shown to fail by |
|---|---|---|
| **exact round-trip** | `parse(print(ir)) == ir` on canonical IR, over every `tree_steps` selector in the corpus | perturbing one node id in the expected IR |
| **idempotence** | `print(parse(print(ir))) == print(ir)` for hand-built sparse-id rows too | renumbering a hand-built selector non-canonically and asserting the text is unchanged |
| **tolerance** | whitespace and case variants reach identical IR | removing the normalising step; the variants then differ |
| **differential** | the SQL parser and `treeql_parser.py` agree row for row, and refuse with the same words, over generated selectors | planting a divergence in one reading |
| **separator** | the three §2.1 cases parse correctly | substituting a naive `', '` split, which fails all three |
| **reserved set is read** | the parser consults the registry, not a literal | registering a combinator and asserting a bare operand of that spelling becomes ambiguous |
| **limit** | §2.2's top-level-comma ambiguity is a documented limit | asserting the refusal, so the claim "unreachable from valid input" is tested rather than argued |
| **mutants** | the corpus kills a wrong tokenizer and a wrong numbering | planting each and confirming the kill is attributable to the planted edit |

The reserved-set gate is the one that would otherwise pass vacuously, so it asserts a *behaviour
change* when a row is added rather than merely reading the column.

## 9. Two-repo consequence

**No C++ semantics — but one C++ change, and it is plumbing.** Populating the `parser` column
makes the extension reach an arm written for this day:

```cpp
if (!parser.IsNull()) {
    // Unreachable in a core-only build ... Kept, and kept distinct from the refusal below,
    // because a front-end extension registering its parser is the whole point of the registry,
    // and the day one does the refusal has to name what is missing -- the DISPATCH
    throw NotImplementedException("... registers the parser %s ... but this build has no front-end dispatch ...");
```

So the extension needs the dispatch that comment anticipates: read the parser's macro name from
the registry, call it with the text, use the resulting IR. It marshals and executes; it decides
nothing about trees.

The plan repo's runner needs the mirror-image change. `rewrite_selectors` currently hardcodes
`if lang != "css": raise RuntimeError("tree_match: TREEQL text parsing arrives with M-LANG; pass
tree_steps(...)")` — the error message names this increment. It should dispatch through the
registry. Note it dispatches css to the **Python** parser while the extension will dispatch to the
**macro**; for treeql, point the runner at the macro, so plan-repo tests exercise the artifact the
extension ships rather than a sibling of it.

Mirroring obligation, measured on the slot engine: the extension mirrors `sql/`, `test/sql/*.test`
and `test/mutants/` with no mutant exemptions, and its identity gate goes red at merge until
re-embedded. `sql/10_treeql.sql` is a new embedded file, so `extension_config.cmake` and the
embed step must learn it.

## 10. Out of scope

- **The PEG grammar front-end.** DuckDB 1.5.5 has a PEG grammar (37 `.gram` files under the
  autocomplete extension) and a `PEGTransformer` with `grammar_rules` and `transform_functions`,
  but they are internal to that extension and the real parser is still bison/`libpg_query`. The
  only public extension point, `ParserExtension`, is a whole-statement fallback, not grammar
  composition — so doc 14 §2a's "each modifier a TableRef-suffix PEG rule (small extension
  surface)" is not supported by the API that exists today, and that claim needs correcting
  separately. M-LANG is a prerequisite for that work, not part of it: the PEG rule for `MATCH`
  hands its selector to a dialect parser, and the default dialect has none until this lands.
- **Renaming `MATCH USING TREEQL`** in its six live sites — §2k's follow-up, code and tests.
- **The clause slot order** as a registry column; recorded in the slot-engine spec §10.
- **A friendlier surface** than the printed form — symbols for combinators, parens optional on a
  single clause. Each is a grammar rule with no printer counterpart, so nothing round-trips
  through it and the differential cannot cover it.
