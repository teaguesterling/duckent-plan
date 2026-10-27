# duckent cheatsheet

<!-- GENERATED FILE. Do not edit: every value below is read out of a live catalog.
     Regenerate with: python3 test/gen_cheatsheet.py   (--check verifies, writes nothing) -->

Measured against DuckDB v1.5.5, from the reference declarations in
`test/gen_cheatsheet.py`. An enumerated domain below is what those declarations
produce -- not everything the code can produce.

## Slots you declare

`tree_shape()` carries the structure blocks and nests the semantics block;
`tree_semantic()` carries the S slots. Block letters are the catalog's own.

| slot | block | argument | what it names |
|---|---|---|---|
| `ROOT` | R | `root` | which rows belong to one tree; every other slot is read within a root |
| `ORDER` | R | `order` | the document order of rows within a root; PRE is its gap-free rank |
| `UNIQUE KEY` | R | `unique_key` | the key slot, asserted unique per root. KEY alone makes no such claim |
| `LEVEL` | R | `level` | depth from the root. Declaring it chooses the LEVEL basis |
| `PARENT` | R | `parent` | the parent's key. Declaring it chooses the PARENT basis |
| `SIBLING_ORDER` | R | `sibling_order` | order among siblings; the PARENT basis needs it to recover ORDER |
| `SIZE` | O | `size` | descendants of this row. The stride from a row to its NEXT |
| `CHILDREN` | O | `children` | immediate children of this row |
| `NEXT` | O | `next` | the row after this row's whole subtree |
| `TYPE` | S | `type` | the polymorphism driver: exactly one per row, with a default |
| `KEY` | S | `key` | the row's own identifier within the tree |
| `TAGS` | S | `tags` | zero or more labels per row; matched as a set |
| `ATTR` | S | `attr` | the columns a selector may name in an attribute clause |
| `ATTR_MAP` | S | `attr_map` | attributes supplied as a MAP rather than as columns |
| `ELEMENT` | S | `element` | which rows are elements, when not every row is one |
| `PREDICATE_ARGS` | S | `predicate_args` | _(not described)_ |

`tree_semantic()` also takes `predicate`, `predicate_map`. These are not slots: they declare predicates, which the catalog records in `tree_catalog_predicates()`.

### What a declaration is refused for

A declaration either holds or is refused -- never an empty result -- and the refusal names the tree, plus the root and the value where there is an offending one. These are the messages, read off the refusals themselves:

| what it gets wrong | refused with |
|---|---|
| ORDER repeats within a root | ORDER is not a traversal in tree docs.bad_order: root {'file_path': f.py} has 2 rows with ORDER value 1 |
| an O slot disagrees with what R derives | O conformance violated in tree docs.bad_o: CHILDREN disagrees with its derived default at root {'file_path': f.py}, ORDER 1 (position 0): declared 0, derived 2 (a corrupted encoding, not a fast path) |
| a PARENT basis with no UNIQUE KEY for PARENT to refer to | tree_ddl_create: PARENT basis requires UNIQUE KEY (the column PARENT refers to) |
| an abstract shape given rows | tree_ddl_create: a SHAPE ONLY (abstract) tree cannot have a source |

## Columns projection adds

`tree_project(schema, tree)` returns the source's own columns plus these, whatever the declaration's basis:

`_root`, `_pre`, `_level`, `_parent`, `_size`, `_children`, `_next`, `_type`, `_key`, `_tags`, `_attr_map`, `_element`, `_predicate`

A canonical column is present whether its slot was declared or derived -- that is what makes a selector portable across declarations.

## Verbs

Statements, called with `CALL`. The C++ extension will provide these; the test runner emulates each one over the compile macro named here.

| verb | compiles with | what it does |
|---|---|---|
| `CALL tree_ddl_create(sch, nm, spec)` | `tree_compile_create` | declare a tree |
| `CALL tree_ddl_drop(sch, nm)` | `tree_compile_drop` | undeclare a tree and drop what it compiled |
| `CALL tree_ddl_alter(sch, nm, semantic)` | `tree_compile_alter` | replace a tree's semantics, leaving its structure alone |
| `CALL tree_insert(sch, nm, source)` | `tree_compile_insert` | add rows to a materialized tree |
| `CALL tree_replace(sch, nm, source)` | `tree_compile_replace` | replace a root's rows wholesale |
| `CALL tree_delete(sch, nm, root_predicate)` | `tree_compile_delete` | remove roots |
| `CALL tree_check(sch, nm)` | `tree_compile_check` | re-run the conformance assertions and record the verdicts |

`tree_match(sch, nm, sel, semantic, language)` is emulated the same way, but as an expression: the call is replaced by the query `tree_compile_match` returns. That is why it has no entry of its own in `duckdb_functions()`.

Expressions and relations, used in a query:

| macro | returns | what it does |
|---|---|---|
| `tree_ancestors(sch, nm, root_key, pre)` | relation | walk up from a row (`root_key` is `_root` cast to VARCHAR) |
| `tree_apply(shape, source)` | relation | project a shape over a source without declaring a tree |
| `tree_builtin_predicates()` | scalar | predicates every tree has without declaring them |
| `tree_canonical_columns()` | scalar | the columns projection adds |
| `tree_children(sch, nm, root_key, pre)` | relation | the row's immediate children |
| `tree_derive_parent(source, root_csv, order_col, level_col)` | relation | derive PARENT from an ORDER/LEVEL pair |
| `tree_descendants(sch, nm, root_key, pre)` | relation | walk down from a row |
| `tree_encode(source, key, parent, sibling_order)` | relation | derive ORDER and LEVEL from a key/parent pair |
| `tree_explain(sch, nm, sel, semantic, language)` | scalar | what a selector compiles to, without running it |
| `tree_first_child(sch, nm, root_key, pre)` | relation | the first child, in sibling order |
| `tree_last_child(sch, nm, root_key, pre)` | relation | the last child, in sibling order |
| `tree_nav(sch, nm, root_key, pre, rel)` | relation | the substrate the nine above are built on: `rel` is a SQL join predicate, not a relation name, so call one of them instead |
| `tree_next_sibling(sch, nm, root_key, pre)` | relation | the following sibling |
| `tree_parent(sch, nm, root_key, pre)` | relation | the row's parent |
| `tree_parse_css(sel)` | scalar | a CSS selector as duckent IR |
| `tree_prev_sibling(sch, nm, root_key, pre)` | relation | the preceding sibling |
| `tree_project(sch, nm)` | relation | the tree's rows with the canonical columns added |
| `tree_semantic(type, key, tags, attr, attr_map, element, predicate, predicate_map, predicate_args)` | scalar | declare semantics: the S slots and the predicates |
| `tree_shape(root, order, unique_key, level, parent, sibling_order, size, children, next, semantic)` | scalar | declare structure: the R and O slots, and the semantics block |
| `tree_siblings(sch, nm, root_key, pre)` | relation | every row sharing this row's parent |
| `tree_spec(shape, abstract, like, source, storage)` | scalar | a shape plus how it is stored and where its rows come from |
| `tree_steps(steps)` | scalar | build selector IR directly, bypassing any front-end |

## Reading the catalog

| view | columns |
|---|---|
| `tree_catalog_trees()` | `database_name`, `schema_name`, `tree_name`, `is_abstract`, `like_tree`, `source_sql`, `basis`, `profile`, `storage`, `order_source`, `has_semantic`, `description` |
| `tree_catalog_slots()` | `database_name`, `schema_name`, `tree_name`, `block`, `slot`, `expression` |
| `tree_catalog_predicates()` | `database_name`, `schema_name`, `tree_name`, `name`, `kind`, `body`, `origin`, `purity` |
| `tree_catalog_assertions()` | `database_name`, `schema_name`, `tree_name`, `artifact`, `status`, `checked_epoch`, `detail` |
| `tree_catalog_languages()` | `language`, `parser`, `printer`, `bare_safe` |
| `tree_catalog_tags(sch, nm)` | `tag`, `row_count` |

The columns whose values come from a fixed set, as the reference declarations exercise them:

| column | observed values | what it says |
|---|---|---|
| `basis` | `level` `parent` | which R slots carry the structure |
| `profile` | `full` `sibling_free` | `sibling_free` when a PARENT basis declares no SIBLING_ORDER |
| `storage` | `materialized` `projection` | where the projected rows live |
| `order_source` | `declared` `frozen` | `frozen` when no ORDER was declared: the row set's own order is it |
| `kind` | `expression` `macro` | the form the predicate was declared in |
| `origin` | `local` `prefix` `shared` | whether the predicate was declared on this tree or shared |
| `status` | `ok` | the verdict an assertion recorded |

`status` is only ever `ok` here, and that is the point: the structural conditions a check would otherwise record as violated are refused at declaration instead, as above.

## Querying a tree

Three ways, and a predicate belongs to exactly one of them. Every query below was run against the `ast` reference declaration to produce the result shown.

### 1. The projection, with ordinary SQL

The usual answer, and it needs no duckent vocabulary: `tree_project` is a relation, so query it.

```sql
SELECT _level, type, name FROM tree_project('docs', 'ast') WHERE _level <= 1 ORDER BY _pre
```

| _level | type | name |
|---|---|---|
| 0 | module | f |
| 1 | class | C |
| 1 | func | g |

### 2. Navigation, from an anchor row

The nine navigation relations listed under **Verbs** walk from one row. The anchor is a `(root_key, pre)` pair, and **`root_key` is the `_root` struct cast to VARCHAR** -- here `{'file_path': f.py}`. That is the one thing about these macros a reader cannot guess:

```sql
SELECT type FROM tree_children('docs', 'ast', '{''file_path'': f.py}', 0) ORDER BY _pre
```

| type |
|---|
| class |
| func |

Handing one the struct itself, rather than its VARCHAR rendering, fails inside a macro the caller never wrote:

```sql
Binder Error: No function matches the given name and argument types 'replace(STRUCT(file_path VARCHAR), STRING_LITERAL, STRING_LITERAL)'. You might need to add explicit type casts.
```

A root or an anchor that does not exist is **not** an error: it answers with no rows, which is what a caller asking about a row that is not there is owed.

### 3. Selectors, which is where predicates are used

`tree_match` takes a selector and returns the rows it matches. A predicate declared on the tree is named in a step's `pseudo`, and the pair below is two types of the same tree -- one where every row satisfies `:leaf`, one where none does -- because a single count cannot tell a working predicate from one that matches everything:

| type | rows | `:leaf` rows | why this one |
|---|---|---|---|
| `method` | 1 | 1 | every row of this type is a leaf |
| `class` | 1 | 0 | no row of this type is a leaf |

A predicate is **not** a column, and cannot be used outside a selector:

```sql
SELECT count(*) FROM tree_project('docs', 'ast') WHERE leaf
-- Binder Error: Referenced column "leaf" not found in FROM clause!
Candidate bindings: "labels", "_level", "file_path", "descendant_count", "name"
```

## Selectors

| language | parser | printer | bare_safe |
|---|---|---|---|
| `css` | `tree_css_lower` | `tree_selector_to_treeql` | true |
| `treeql` | `tree_parse_treeql` | `tree_selector_to_treeql` | true |

Selector text that names no language is parsed as `css` (`tree_catalog.settings`). Text handed over as IR was never parsed, so its provenance stays `treeql` whatever the default says.

Predicates every tree has without declaring them: `:first-child`, `:last-child`. A declared predicate whose name starts with `sel_` is shared across trees rather than local to one.

An unknown predicate is not an error: it selects nothing, and the compiled SQL says so.

### Declaring one

Four forms, and what each records. These are the rows the `forms` reference declaration below produces -- one declaration, read straight back out:

| name | kind | body | origin | purity |
|---|---|---|---|---|
| `leaf` | `expression` | `descendant_count = 0` | `local` | `pure` |
| `pub` | `macro` | `docs_is_pub(labels)` | `local` | `pure` |
| `deep` | `macro` | `pre_deep(depth)` | `prefix` | `pure` |
| `shallow` | `macro` | `pre_shallow(depth)` | `prefix` | `pure` |
| `root_level` | `macro` | `sel_root_level(depth)` | `shared` | `pure` |

`local` is a predicate the declaration named. `prefix` came from a `{prefix: ...}` binding, which enumerates every catalog macro carrying that prefix and names each one by the part after it. `shared` came from the `sel_` tier, which is scanned for every tree -- but only one that declares `predicate_args`, since the shared tier has no other source of arguments; a tree without it gets 0 shared predicates however many `sel_` macros exist.

The two tiers can reach the same name. With both a `pre_` binding and a `sel_shallow` macro in the catalog, the name `shallow` is bound once, by the `prefix` binding, to `pre_shallow(depth)`: a macro already claimed under one name is not bound again under another.

### Handing over a pre-parsed selector

TREEQL text is read by `tree_parse_treeql`, the parser its registry row above names. A language whose `parser` is `_none_` refuses a text selector instead, and the message names the registry row it consulted. Every language has a door as well: hand the IR over directly. A front-end that parses its own syntax elsewhere -- in the host, in another extension -- emits these rows and passes them as a `TREE_SELECTOR`, which is what `tree_steps` itself produces.

| column | type |
|---|---|
| `node_id` | `INTEGER` |
| `parent_id` | `INTEGER` |
| `kind` | `VARCHAR` |
| `value` | `VARCHAR` |
| `op` | `VARCHAR` |
| `arg` | `VARCHAR` |
| `alias` | `VARCHAR` |

`node_id` and `parent_id` are the structure: one `selector` row is the root, every other row names its parent. A kind is one of `selector`, `step`, `has`, `not`, `attr`, `class`, `id`, `pseudo`, `type`, `where` -- the four structural kinds (`selector`, `step`, `has`, `not`), which are the IR's own shape, plus every registered clause kind.

### Combinators

The relation between one step and the step before it, keyed by `op` in the IR and spelled with `keyword` in TREEQL text. `requires_sibling_order` is a capability check: a combinator that needs it is refused on a tree whose PARENT basis declares no SIBLING_ORDER (see "What a declaration is refused for" above) -- `PARENT`, `ANCESTOR` and `PRECEDING` are registered here like any other relation.

| keyword | op | requires_sibling_order |
|---|---|---|
| `FOLLOWING` | `after` | true |
| `ANCESTOR` | `ancestor` | false |
| `CHILD` | `child` | false |
| `DESCENDANT` | `desc` | false |
| `SIBLING` | `next` | true |
| `PARENT` | `parent` | false |
| `PRECEDING` | `prev` | true |
| `SELF` | `self` | false |

The door is checked, not trusted -- nothing parsed these rows, so the match path validates them. Each refusal below is the real message:

| handed over | refused with |
|---|---|
| a kind nothing defines | `tree_match: unknown clause kind frobnicate` |
| two nodes sharing a node_id | `tree_match: selector node ids are not unique` |
| a step whose parent is neither the selector nor a group | `tree_match: node 1 has kind step which is not allowed under <none>` |
| no steps at all | `tree_match: selector has no steps` |

And the well-formed one those mutate matches 1 row, so the refusals above are the checks firing rather than the selector being empty.

## What a predicate body may contain

A predicate's body is substituted into a plan, so a body that reads anything but its row is refused at declaration. These verdicts are read back out of `tree_catalog_predicates()` after declaring each body:

| body | purity | why |
|---|---|---|
| `descendant_count = 0` | `pure` | arithmetic and comparison on the row |
| `contains(type, 'mod')` | `pure` | a CONSISTENT built-in |
| `docs_pure_m(depth)` | `pure` | a macro over CONSISTENT built-ins |
| `docs_outer_m(depth)` | `unknown` | a macro calling a macro: beyond one level of resolution |

`unknown` is accepted: a macro that calls a macro is beyond one level of resolution, and DuckDB reports every macro's stability as NULL whatever it calls, so nothing can be proven either way. Refusing it would refuse a pure body on no evidence.

Refused outright:

| body | refused with |
|---|---|
| `random() < 0.5` | tree_ddl_create: PREDICATE p is not pure: its body reads a VOLATILE or CONSISTENT_WITHIN_QUERY function, so the same selector would not answer the same twice |
| `now() > TIMESTAMP '2020-01-01'` | tree_ddl_create: PREDICATE p is not pure: its body reads a VOLATILE or CONSISTENT_WITHIN_QUERY function, so the same selector would not answer the same twice |
| `descendant_count = )(` | tree_ddl_create: PREDICATE p does not parse |

## The reference declarations

Every reading above was taken from these. The fixture is four rows of one tree:

```sql
CREATE TABLE docs.src AS SELECT * FROM (VALUES
  ('f.py', 1, 0, 3, 'module', 'f', ['top'],       2, NULL, NULL),
  ('f.py', 2, 1, 1, 'class',  'C', ['pub'],       1, 4,    1),
  ('f.py', 3, 2, 0, 'method', 'm', ['pub','hot'], 0, 4,    2),
  ('f.py', 4, 1, 0, 'func',   'g', [],            0, NULL, 1)
) t(file_path, node_id, depth, descendant_count, type, name, labels, kid_count, next_id, parent_id);
```

`ast` -- LEVEL basis, every S slot, all three O slots:

```sql
CALL tree_ddl_create('docs', 'ast', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', unique_key := 'name', level := 'depth',
             size := 'descendant_count', children := 'kid_count', next := 'next_id',
             semantic := tree_semantic(type := 'type', key := 'name', tags := 'labels',
               attr_map := 'MAP {''lang'': ''py''}', element := 'type = ''module''',
               predicate := [{name: 'leaf', body: 'descendant_count = 0'}])),
  source := 'docs.src'));
```

`parented` -- PARENT basis, which SIBLING_ORDER and UNIQUE KEY complete:

```sql
CALL tree_ddl_create('docs', 'parented', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', unique_key := 'node_id',
             parent := 'parent_id', sibling_order := 'node_id',
             semantic := tree_semantic(type := 'type')),
  source := 'docs.src'));
```

`shape_only` -- abstract: a shape with no source, to be inherited:

```sql
CALL tree_ddl_create('docs', 'shape_only', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', level := 'depth',
             semantic := tree_semantic(type := 'type')), abstract := true));
```

`derived` -- LIKE an abstract shape, stored as a projection:

```sql
CALL tree_ddl_create('docs', 'derived', tree_spec(tree_shape(),
  "like" := 'shape_only', source := 'docs.src', storage := 'projection'));
```

`frozen` -- LEVEL basis declaring no ORDER: the row set's own order is the tree's:

```sql
CALL tree_ddl_create('docs', 'frozen', tree_spec(
  tree_shape(root := 'file_path', level := 'depth', semantic := tree_semantic(type := 'type')),
  source := 'docs.src'));
```

`sibling_free` -- PARENT basis declaring no SIBLING_ORDER:

```sql
CALL tree_ddl_create('docs', 'sibling_free', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', unique_key := 'node_id',
             parent := 'parent_id', semantic := tree_semantic(type := 'type')),
  source := 'docs.src'));
```

`forms` -- every form a predicate can be declared in, and the shared tier:

```sql
CREATE MACRO docs_is_pub(tags) AS list_contains(tags, 'pub');
CREATE MACRO pre_deep(depth) AS depth > 1;
CREATE MACRO pre_shallow(depth) AS depth = 0;
CREATE MACRO sel_root_level(depth) AS depth = 0;
CALL tree_ddl_create('docs', 'forms', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', level := 'depth',
             semantic := tree_semantic(tags := 'labels', predicate_args := 'depth', predicate := [
               {name: 'leaf', body: 'descendant_count = 0'},
               {name: 'pub', macro: 'docs_is_pub', args: 'labels'},
               {prefix: 'pre_', args: 'depth'}])),
  source := 'docs.src'));
```

| tree_name | is_abstract | like_tree | basis | storage | has_semantic |
|---|---|---|---|---|---|
| `ast` | false |  | `level` | `materialized` | true |
| `derived` | false | `shape_only` | `level` | `projection` | true |
| `forms` | false |  | `level` | `materialized` | true |
| `frozen` | false |  | `level` | `materialized` | true |
| `parented` | false |  | `parent` | `materialized` | true |
| `shape_only` | true |  | `level` | `materialized` | true |
| `sibling_free` | false |  | `parent` | `materialized` | true |

`CALL tree_check('docs', 'ast')` records:

| tree_name | artifact | status | detail |
|---|---|---|---|
| `ast` | `assert_o_children` | `ok` | 0 disagreeing rows |
| `ast` | `assert_o_next` | `ok` | 0 disagreeing rows |
| `ast` | `assert_o_size` | `ok` | 0 disagreeing rows |
| `ast` | `assert_p13` | `ok` | 0 violating rows |

`tree_catalog_tags('docs', 'ast')` counts the tag column's contents: `hot` = 1, `pub` = 2, `top` = 1.

---

Not yet described, and so marked open rather than omitted: `PREDICATE_ARGS`.
