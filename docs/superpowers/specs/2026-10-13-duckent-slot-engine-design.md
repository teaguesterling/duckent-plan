# duckent slot engine: one declaration per vocabulary — design

*Status: designed 2026-10-13. Scope: the engine that consumes parsed TREEQL — the clause-kind
and combinator vocabularies, declared once and consulted everywhere, with the combinator set
opened for registration. Does not cover the TREEQL text parser (M-LANG), which this design
deliberately sets aside -- though §11 settles D-N15, whose answer this design constrains.
Baseline: main at `73dfd47`.*

## 1. What this is

The IR is a list of ordered, possibly nested predicates, and the engine that consumes it is
already two clean seams:

| seam | signature | produces |
|---|---|---|
| slot predicate | `tree_sql_clause(kind, value, op, arg, alias, attr_cols, has_map, elem)` | a boolean SQL expression on one step's alias |
| row relation | `tree_sql_comb(op, a, b, elem)` | a join condition between two step aliases |

Each clause kind is a predicate over exactly one declared S-block slot — `_type`, `_key`,
`_tags`, `_predicate`, `_attr`/`_attr_map` — plus `where` as the host door. Each combinator is a
structural relation between two rows. Every selector language, css included, is a translator into
this IR; the engine never sees anything else.

The seams are not the problem. Their **vocabularies** are: the set of valid kinds and the set of
valid combinators are declarations written out by hand at thirteen sites, with nothing checking
that the copies agree. This design makes each vocabulary declared once, consulted everywhere, and
— for combinators — extensible by adding a row.

This is the project's signature defect class pointed at its own engine: a declaration is
recorded, and nothing verifies the claim it makes.

## 2. The problem, measured

Counted on `73dfd47`. Two groups, and the distinction is the whole design.

**Sites that can read a declaration (8):**

| site | what it does with the set |
|---|---|
| `sql/06_selector.sql:153` | `tree_steps` unknown-field check |
| `sql/06_selector.sql:338` | printer's `bad_kind` whitelist |
| `sql/06_selector.sql:345` | printer's clause selection |
| `sql/07_match.sql:418` | compiler's clause selection |
| `sql/07_match.sql:457` | host-door kind check |
| `sql/07_match.sql:467` | part selection (clauses + groups) |
| `sql/07_match.sql:584` | the S-less refusal — **a partial copy**, see below |
| `test/gen_cheatsheet.py:220` | `SELECTOR_KINDS` — generates `docs/cheatsheet.md` |

The cheatsheet one matters more than its position suggests: it is what writes the documentation, so
a drifted copy there does not fail, it *publishes a false claim*.

`07_match.sql:584` is the most instructive of the eight, and the first inventory of this work
missed it. It writes the set with **five** members rather than six:

```sql
CASE WHEN ir.kind IN ('type', 'id', 'class', 'attr', 'pseudo') AND NOT (SELECT has_semantic FROM t)
```

`where` is absent because the host door reads no S slot and is available on a tree with no
`SEMANTIC` group. So this partial copy *is* the `needs_semantic` distinction — a rule encoded as an
omission from a list, stated nowhere, and discoverable only by noticing which member is missing.
A search for the full set does not find it, which is why it survived the first pass.

Two consequences. First, `needs_semantic` must be read **here** or it is a column declared and
consumed by nothing — the very defect this design exists to remove, reintroduced by the design.
Second, partial copies are the more dangerous kind precisely because they carry an exception that
the full-set copies do not, so the lint (§8) matches on *three or more* members rather than on the
complete set.

**Sites that cannot (5):**

| site | why not |
|---|---|
| `sql/00_types.sql:22,24,27` | `TREE_STEP_L0/L1/L2` are DuckDB `STRUCT` types. A struct's field list is fixed at definition; it cannot be generated from a table. Three copies because the constructor nests three literal levels. |
| `sql/06_selector.sql:105,111` | field extraction that mirrors those structs, once per level |

These five are the constructor's **input surface**, not the engine's vocabulary, and they are
irreducible. They must nonetheless *agree* with the vocabulary — a kind in the registry with no
field on the struct cannot be built by `tree_steps`, and a field with no registry row is accepted
by the constructor and then refused by the compiler. Duplication that cannot be removed gets a
gate instead (§8).

**Combinators** are worse, because they carry a capability requirement that is spelled out
separately from the set itself. `sql/07_match.sql` refuses sibling relations on a tree with no
`SIBLING_ORDER`:

```sql
WHEN (SELECT profile FROM t) = 'sibling_free'
     AND ((ir.kind = 'step' AND ir.op IN ('next', 'after')) OR ...)
THEN tree_err('tree_match: tree ... is sibling-free (no SIBLING_ORDER declared);
               SIBLING, FOLLOWING, :first-child and :last-child are unavailable')
```

The op list is hardcoded and the message names four spellings by hand. A combinator registered
without being added to that `IN` list compiles against a `_pre` that no `SIBLING_ORDER` governs
and, in the words of the comment directly above it, answers "with whatever rows happened to land
there — the one thing the sibling-free profile exists to prevent." **This is why the registry is
a correctness requirement and not a tidiness exercise.**

## 3. What the engine already computes and TREEQL cannot say

Relation macros present in `sql/07_match.sql`, against the combinator set `tree_sql_comb` exposes:

| macro | callers | reachable from TREEQL |
|---|---|---|
| `tree_sql_subtree` | 4 | yes — `desc` / `DESCENDANT` |
| `tree_sql_children` | 9 | yes — `child` / `CHILD` |
| `tree_sql_self` | 1 | yes — `self` (no text spelling; see §7) |
| `tree_sql_next_sibling` | 2 | yes — `next` / `SIBLING` |
| `tree_sql_after` | 2 | yes — `after` / `FOLLOWING` |
| `tree_sql_parent` | 5 | **no** |
| `tree_sql_prev_sibling` | 1 | **no** |
| `tree_sql_ancestors` | 1 | **no** |
| `tree_sql_before` | **0** | no |

Three relations are implemented and exercised through `tree_nav` / `tree_ancestors`, and TREEQL
has no way to name them. Opening the combinator set turns them into rows.

`tree_sql_before` is defined with **zero callers anywhere in `sql/` or `test/`**. Nothing has ever
executed it, so it is an unverified relation. It is excluded from this increment: it earns tests
before it earns a spelling. (The rule is duck_block_utils': fix before moving.)

## 4. The two declarations

```sql
-- CLOSED. Six rows, one per S-block slot plus the host door. Not registerable: the S block is
-- fixed by the ROWS contract, so a seventh kind is extensibility nothing has asked for.
CREATE TABLE IF NOT EXISTS tree_catalog.clause_kinds(
  kind VARCHAR PRIMARY KEY,   -- the IR kind
  keyword VARCHAR,            -- the TREEQL keyword the printer emits
  slot VARCHAR,               -- the canonical column it reads, NULL for the host door
  needs_semantic BOOLEAN,     -- refuse on a tree with no SEMANTIC group
  step_field VARCHAR          -- the TREE_STEP_* field that builds it, for the §8 agreement gate
);

-- OPEN. A front-end extension registers a row the way 09_css.sql registers a selector language:
-- the registration API is SQL, not C++.
CREATE TABLE IF NOT EXISTS tree_catalog.combinators(
  op VARCHAR PRIMARY KEY,     -- the IR op
  keyword VARCHAR,            -- the TREEQL keyword
  template VARCHAR,           -- join condition with {a} and {b} placeholders
  template_elem VARCHAR,      -- the ELEMENT-aware variant, NULL when the relation ignores it
  requires_sibling_order BOOLEAN  -- refuse on a sibling-free tree (§2)
);
```

Rows are **derived from the existing macros, not transcribed**. The five the engine exposes today:

```sql
INSERT INTO tree_catalog.combinators VALUES
  ('desc',  'DESCENDANT', tree_sql_subtree('{a}','{b}'),      NULL,                                     false),
  ('child', 'CHILD',      tree_sql_children('{a}','{b}'),     NULL,                                     false),
  ('self',  'SELF',       tree_sql_self('{a}','{b}'),         NULL,                                     false),
  ('next',  'SIBLING',    tree_sql_next_sibling('{a}','{b}', false),
                          tree_sql_next_sibling('{a}','{b}', true),                                     true),
  ('after', 'FOLLOWING',  tree_sql_after('{a}','{b}'),        NULL,                                     true);
```

and the three §3 found implemented with no spelling, which this increment adds (§7.5). All three
are `(a, b)`-shaped and templatize exactly, measured on `73dfd47`:

```sql
INSERT INTO tree_catalog.combinators VALUES
  ('parent',   'PARENT',   tree_sql_parent('{a}','{b}'),    NULL,                                      false),
  ('ancestor', 'ANCESTOR', tree_sql_ancestors('{a}','{b}'), NULL,                                      false),
  ('prev',     'PRECEDING', tree_sql_prev_sibling('{a}','{b}', false),
                            tree_sql_prev_sibling('{a}','{b}', true),                                  true);
```

`tree_sql_ancestors(a, b)` is defined as `tree_sql_subtree(b, a)` — the subtree relation read
backwards — so its row is derived from a macro that is itself derived, and the derivation gate
(§8) covers both without a special case. `PRECEDING` is the spelling for the previous *sibling*;
it carries `requires_sibling_order = true` for the same reason `next` and `after` do, and it is
the first row to exercise the capability gate against a relation the hardcoded
`IN ('next','after')` list never knew about.

The relation macros stay exactly where they are. They remain the source of the logic *and* of the
reasoning recorded around it — the root `COALESCE` in `tree_sql_first_child`, the
`IS NOT DISTINCT FROM` that makes level-0 rows siblings of each other, the keyed-lookup form of
`last_child`. None of that moves into a table row.

## 5. Dispatch without dynamic dispatch

A DuckDB macro cannot be selected by name at runtime, so `op → macro` is not a table lookup. It
does not need to be. The relation macros are pure string concatenation over their two alias
arguments, so calling one with placeholder aliases yields a reusable template. Measured on
`73dfd47`:

```
tree_sql_subtree('{a}','{b}')  ->  {b}._root = {a}._root AND {b}._pre BETWEEN {a}._pre + 1
                                                            AND {a}._pre + {a}._size
tree_sql_children('{a}','{b}') ->  {b}._root = {a}._root AND {b}._parent = {a}._pre
tree_sql_parent('{a}','{b}')   ->  {b}._root = {a}._root AND {b}._pre = {a}._parent
```

and substitution is exact — for `desc`, `child`, `after` and `next` (both `elem` arms),
`replace(replace(template,'{a}',a),'{b}',b)` is byte-identical to calling the macro directly on
those aliases. `tree_sql_comb` becomes a lookup plus that substitution.

Placeholder safety: `{a}` and `{b}` can only appear in a template because a relation macro put
them there. No user text reaches a template — a step `WHERE` body is substituted by
`tree_sql_clause`, a different seam — so the substitution cannot be made to rewrite caller text.

`tree_sql_clause` keeps its `CASE`. The vocabulary is closed, and the `attr` arm — projected
column versus `ATTR MAP`, `TRY_CAST` by literal type, the negation prefix, the canonical-column
refusal — is not expressible as a placeholder template and must not be forced into one. What the
registry takes from it is the **keyword mapping** (`tree_treeql_clause`) and the `needs_semantic`
flag, not the compilation.

## 6. Capability requirements

Two per-vocabulary properties currently live apart from their vocabulary, and both move into it:

**`requires_sibling_order`** (combinators). The `sibling_free` refusal reads the column instead of
a hardcoded `IN ('next','after')`, and builds its message from the registry's keywords instead of
naming four spellings in a string literal. A newly registered sibling relation is then refused
correctly on a sibling-free tree *because it said it needs sibling order*, not because someone
remembered to edit a list.

**`needs_semantic`** (clause kinds). True for `type`, `id`, `class`, `attr`, `pseudo`; false for
`where`. Read by the S-less refusal at `07_match.sql:584`, which today encodes the same rule by
*omitting* `where` from a five-member list (§2). The built-in positional predicates stay an
exception on the **value**, not the kind: `pseudo` with a name in `tree_builtin_predicates()` reads
no S slot and is exempt. That exemption is about which predicate was named, so it does not belong
in a per-kind column and is not moved.

## 7. Decisions taken in this design

1. **Clause kinds stay closed at six.** One per S-block slot plus the host door; the S block is
   fixed by the ROWS contract.
2. **Combinators open.** Named consumers exist: the design's Cypher front-end maps relationship
   types to combinators, and three implemented relations have no spelling (§3).
3. **`attr` keeps its `CASE` arm.** Not templatable; see §5.
4. **`before` is excluded.** Zero callers, therefore unverified; tests first.
5. **`parent`, `ancestor`, `prev_sibling` are in scope** as rows over already-exercised macros,
   with `prev_sibling` carrying `requires_sibling_order = true`.
6. **`self` gains a text spelling.** `SELF` is already in `tree_treeql_comb`, so the printer can
   emit text the grammar never specified — the open item at `core-design.md:322`.
7. **D-N13 is recorded as already decided, not re-opened.** `tree_treeql_comb` maps
   `after → FOLLOWING` and css maps `~ → after`, so `FOLLOWING` has been the live spelling since
   M2 while the core design still lists it as a candidate. The registry makes it visible.

## 8. Gates

A vocabulary is a declaration, so each gate asks whether the declaration is actually *read*.
Passing today proves nothing on its own; every gate below is verified to fail when its subject is
removed.

| gate | what it catches | how it is proven to have teeth |
|---|---|---|
| **delete a row** | a site that kept a private copy of the set | remove each row in turn; every consumer must fail, and fail legibly — not render the clause as nothing, not accept at the door and refuse at compile |
| **derivation** | a hand-edited `template` drifting from its macro | for every row, substituted `template` equals the macro called directly on those aliases |
| **agreement** | registry versus the irreducible struct surface (§2) | every `clause_kinds.step_field` is a field of `TREE_STEP_L0`; every non-structural field of `TREE_STEP_L0` (not `comb`, not `as`) has a row |
| **no literals remain** | the seven collapsed copies coming back | a lint over `sql/` and `test/` for the written-out kind set, in the style of `scripts/check_macro_identity.py` |
| **capability** | a registered relation bypassing the sibling-free refusal | register a probe combinator with `requires_sibling_order = true`, assert it refuses on a sibling-free tree; flip the column, assert it stops refusing |
| **mutants** | a template nothing exercises | mutate each template; the corpus must kill it. A template whose mutation survives is reported, not quietly skipped |

The capability gate is the one that justifies the whole design, so it is the one that must not be
allowed to pass vacuously: it asserts a *behaviour change* when the column flips, which a gate
reading the column but not acting on it cannot fake.

## 9. Two-repo consequence

**No C++ changes.** The door's kind checks live in the macros (`tree_sql_clause`'s `ELSE` arm and
the compile-path checks at `07_match.sql:457`), not in the extension — verified by searching
`duckent/src` for the refusal texts and the kind set and finding neither. The extension embeds
`sql/*.sql` byte-identically and CI fails on a single byte of drift, so it gains the new tables,
the derived rows and the rewritten `tree_sql_comb` with no executor change at all.

Two constraints follow:

- The new tables are created in `sql/01_catalog.sql`, which the MVP extension **does** embed, so
  the registry must be complete for a core-only build. It is: all eight combinators after this
  increment — the five exposed today plus `parent`, `ancestor` and `prev` — are core relations
  defined in `sql/07_match.sql`, which the extension also embeds. No row in a core-only build
  names a macro that build lacks.
- A front-end extension that registers a combinator does so by inserting a row from its own
  `.sql` file, exactly as `09_css.sql` inserts its selector-language row. Nothing about
  registration is C++.

## 10. Out of scope

- **The TREEQL text parser (M-LANG).** Set aside deliberately. The parser's own design work —
  measured and recorded 2026-10-13 — established that the printed form needs a quote- and
  paren-aware tokenizer, that such a tokenizer is expressible as a SQL macro, and that the
  round-trip contract is exact on canonical IR and normalizing on hand-built IR. That stands as
  input to a later increment; nothing here depends on it.
- **D-N15** (`TYPE foo` versus `TYPE 'foo'`) is a text-grammar question and its implementation
  waits for the parser — but the decision is taken, because this design has a consequence for it
  (§11).
- **Issue #33** (W's mutants MN9/MN10/MN11/MN16, needing a tree that splices and a frontier that
  can be unloaded) is engine *correctness*, not engine *declaration*, and is untouched here.
- **`before`** — §7.4.

## 11. D-N15 decided: bare identifiers accepted, quoted literals emitted

**Decision (2026-10-13): a clause operand may be written as a bare identifier, and the printer
goes on emitting a quoted literal.** D-N15 asked `TYPE foo` or `TYPE 'foo'` and recorded that "the
proposal's examples use both"; the answer is both, with the two roles separated — bare on input,
quoted on output.

This follows the contract already chosen for the parser: tolerant input, canonical output. The
round-trip theorems are stated over the *printer's* output, which stays `TYPE 'foo'`, so they are
untouched; and every expectation already pinned in the suite — all of `(TYPE 'function_definition')`
and its kin — remains valid. Emitting bare where a value happens to be identifier-shaped was
considered and rejected: it would make the canonical form value-dependent, change `tree_explain`'s
`treeql` field for some selectors and not others, and rewrite expectations across the corpus to buy
brevity in a format whose job is canonicality.

**A bare identifier needs a reserved-word rule, and css already set the precedent.** css makes you
quote a type that collides with its own syntax — `"select" > "from"` lowers to `(TYPE 'select')` —
so TREEQL mirrors it: a bare operand must match `[A-Za-z_][A-Za-z0-9_]*` and must not be one of the
language's keywords. Anything else is quoted, and a value containing a quote keeps the doubling the
printer already emits (`TYPE 'it''s'`).

**The consequence this design creates.** The keyword set is no longer a fixed list in the grammar:
it is the clause keywords plus the combinator keywords, both of which now live in the registry.
So the reserved words are *data*, and registering a combinator enlarges them. Register one spelled
`ANCESTOR` — as §7.5 does — and a bare `TYPE ANCESTOR` becomes ambiguous from that point on and has
to be written `TYPE 'ANCESTOR'`.

That is a real coupling between an open vocabulary and a tolerant grammar, and it is recorded here
rather than left for the parser's author to discover:

- the parser derives its reserved set from `tree_catalog.clause_kinds` and
  `tree_catalog.combinators`, never from a literal list, for the same reason every other consumer
  does;
- a front-end registering a combinator is therefore making a grammar change, not only a semantics
  change, and the registration's keyword should be chosen with that in mind;
- the quoted form is always available and always unambiguous, so no selector becomes
  *unexpressible* — only some become un-bare-able. That is why this coupling is acceptable rather
  than disqualifying.

Nothing in Tasks 1–7 implements any of this. It is recorded now because the registry is what makes
the reserved set dynamic, and a reader of the registry should know what else it governs.
