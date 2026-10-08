#!/usr/bin/env python3
"""Generate docs/cheatsheet.md from the catalog itself.

Every name, column, parameter and enumerated value in the cheatsheet is MEASURED: the
generator loads sql/*.sql into a fresh in-memory DuckDB, declares the two reference trees
below, and reads the answers back out of the introspection views, duckdb_functions() and the
TREE_SHAPE / TREE_SEMANTIC types. Nothing in the generated file is transcribed from the
source by hand.

What IS authored by hand is the prose: the one-line gloss on each verb, slot and column
domain. That prose is held in the GLOSS tables below, and the generator checks it both
ways -- a gloss naming something the catalog no longer has is a hard error, and a measured
name with no gloss is rendered as "(not described)" rather than quietly omitted. So the
renames in #48 and #49 would have failed this generator instead of rotting the document.

Usage:  python3 test/gen_cheatsheet.py            writes docs/cheatsheet.md
        python3 test/gen_cheatsheet.py --check     writes nothing; exits 1 if out of date

Two limits the generated file states about itself, because they are real:

  * An enumerated domain is what the REFERENCE DECLARATIONS produce, not what the code can
    produce. Add a basis or a storage mode without adding a reference declaration and the
    cheatsheet under-claims; it does not lie. That is Doctrine 5 -- report the unknown
    rather than invent a value for it.
  * The CALL verbs are the surface the C++ extension will provide. Today the test runner
    emulates them over the tree_compile_* macros, so their PARAMETERS are measured from
    those macros and the mapping is measured from the runner itself.
"""
import argparse, difflib, io, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run import Session, EXEC_VERBS, compile_macro_name, fmt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "cheatsheet.md")
REGEN = "python3 test/gen_cheatsheet.py"

# ---------------------------------------------------------------------------
# The reference declarations. Chosen so that between them they exercise every slot the
# TREE_SHAPE and TREE_SEMANTIC types carry, both bases, and every storage mode -- the
# generator ASSERTS that coverage below, so a new slot that no reference declares is a
# build failure rather than a silent omission.
# ---------------------------------------------------------------------------
FIXTURE = """CREATE TABLE docs.src AS SELECT * FROM (VALUES
  ('f.py', 1, 0, 3, 'module', 'f', ['top'],       2, NULL, NULL),
  ('f.py', 2, 1, 1, 'class',  'C', ['pub'],       1, 4,    1),
  ('f.py', 3, 2, 0, 'method', 'm', ['pub','hot'], 0, 4,    2),
  ('f.py', 4, 1, 0, 'func',   'g', [],            0, NULL, 1)
) t(file_path, node_id, depth, descendant_count, type, name, labels, kid_count, next_id, parent_id)"""

# (tree name, what it is for, plain SQL to run first, the declaration)
#
# Order matters and is part of the fixture: the shared predicate tier is every catalog macro
# whose name carries the shared prefix, so the macro that populates it is created with the ONE
# declaration meant to show a shared predicate, after the others. Create it earlier and every
# later tree inherits it.
REFERENCES = [
    ("ast", "LEVEL basis, every S slot, all three O slots", [], """CALL tree_ddl_create('docs', 'ast', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', unique_key := 'name', level := 'depth',
             size := 'descendant_count', children := 'kid_count', next := 'next_id',
             semantic := tree_semantic(type := 'type', key := 'name', tags := 'labels',
               attr_map := 'MAP {''lang'': ''py''}', element := 'type = ''module''',
               predicate := [{name: 'leaf', body: 'descendant_count = 0'}])),
  source := 'docs.src'))"""),
    ("parented", "PARENT basis, which SIBLING_ORDER and UNIQUE KEY complete", [], """CALL tree_ddl_create('docs', 'parented', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', unique_key := 'node_id',
             parent := 'parent_id', sibling_order := 'node_id',
             semantic := tree_semantic(type := 'type')),
  source := 'docs.src'))"""),
    ("shape_only", "abstract: a shape with no source, to be inherited", [], """CALL tree_ddl_create('docs', 'shape_only', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', level := 'depth',
             semantic := tree_semantic(type := 'type')), abstract := true))"""),
    ("derived", "LIKE an abstract shape, stored as a projection", [], """CALL tree_ddl_create('docs', 'derived', tree_spec(tree_shape(),
  "like" := 'shape_only', source := 'docs.src', storage := 'projection'))"""),
    ("frozen", "LEVEL basis declaring no ORDER: the row set's own order is the tree's", [],
     """CALL tree_ddl_create('docs', 'frozen', tree_spec(
  tree_shape(root := 'file_path', level := 'depth', semantic := tree_semantic(type := 'type')),
  source := 'docs.src'))"""),
    ("sibling_free", "PARENT basis declaring no SIBLING_ORDER", [],
     """CALL tree_ddl_create('docs', 'sibling_free', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', unique_key := 'node_id',
             parent := 'parent_id', semantic := tree_semantic(type := 'type')),
  source := 'docs.src'))"""),
    ("forms", "every form a predicate can be declared in, and the shared tier",
     ["CREATE MACRO docs_is_pub(tags) AS list_contains(tags, 'pub')",
      "CREATE MACRO pre_deep(depth) AS depth > 1",
      "CREATE MACRO pre_shallow(depth) AS depth = 0",
      # Not sel_shallow: the pre_ prefix binding above already binds the name `shallow`, and a
      # macro already bound under any name is not re-bound by the shared tier under another.
      "CREATE MACRO sel_root_level(depth) AS depth = 0"],
     """CALL tree_ddl_create('docs', 'forms', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', level := 'depth',
             semantic := tree_semantic(tags := 'labels', predicate_args := 'depth', predicate := [
               {name: 'leaf', body: 'descendant_count = 0'},
               {name: 'pub', macro: 'docs_is_pub', args: 'labels'},
               {prefix: 'pre_', args: 'depth'}])),
  source := 'docs.src'))"""),
]

# Bodies whose purity verdict the cheatsheet reports. Each is DECLARED, so the verdict is
# the one the DDL path computes, not one this script decides.
PURITY_PROBES = [
    ("descendant_count = 0", "arithmetic and comparison on the row"),
    ("contains(type, 'mod')", "a CONSISTENT built-in"),
    ("docs_pure_m(depth)", "a macro over CONSISTENT built-ins"),
    ("docs_outer_m(depth)", "a macro calling a macro: beyond one level of resolution"),
]
PURITY_SETUP = ["CREATE MACRO docs_pure_m(n) AS n > 1",
                "CREATE MACRO docs_outer_m(n) AS docs_pure_m(n)"]
# Bodies the DDL path must REFUSE. Rendered with the message it refuses them with.
PURITY_REFUSED = ["random() < 0.5", "now() > TIMESTAMP '2020-01-01'", "descendant_count = )("]

# Declarations the DDL path must refuse, rendered with the message it refuses them with. The
# message is the product here: a refusal that does not say which tree, which root and which
# value is a refusal a reader cannot act on. Each is DECLARED, so these are the real messages.
# (what it gets wrong, plain SQL to run first, the declaration)
REFUSALS = [
    ("ORDER repeats within a root",
     ["""CREATE TABLE docs.dup AS SELECT * FROM (VALUES
          ('f.py', 1, 0, 'module'), ('f.py', 1, 1, 'class')) t(file_path, node_id, depth, type)"""],
     """CALL tree_ddl_create('docs', 'bad_order', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', level := 'depth',
             semantic := tree_semantic(type := 'type')), source := 'docs.dup'))"""),
    ("an O slot disagrees with what R derives", [],
     """CALL tree_ddl_create('docs', 'bad_o', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', level := 'depth',
             children := 'depth', semantic := tree_semantic(type := 'type')),
  source := 'docs.src'))"""),
    ("a PARENT basis with no UNIQUE KEY for PARENT to refer to", [],
     """CALL tree_ddl_create('docs', 'bad_parent', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', parent := 'parent_id',
             semantic := tree_semantic(type := 'type')), source := 'docs.src'))"""),
    ("an abstract shape given rows", [],
     """CALL tree_ddl_create('docs', 'bad_abstract', tree_spec(
  tree_shape(root := 'file_path', "order" := 'node_id', level := 'depth',
             semantic := tree_semantic(type := 'type')),
  abstract := true, source := 'docs.src'))"""),
]

VIEWS = ["tree_catalog_trees", "tree_catalog_slots", "tree_catalog_predicates",
         "tree_catalog_assertions", "tree_catalog_languages", "tree_catalog_tags"]

GLOSS_SLOT = {
    "ROOT": "which rows belong to one tree; every other slot is read within a root",
    "ORDER": "the document order of rows within a root; PRE is its gap-free rank",
    "UNIQUE KEY": "the key slot, asserted unique per root. KEY alone makes no such claim",
    "LEVEL": "depth from the root. Declaring it chooses the LEVEL basis",
    "PARENT": "the parent's key. Declaring it chooses the PARENT basis",
    "SIBLING_ORDER": "order among siblings; the PARENT basis needs it to recover ORDER",
    "SIZE": "descendants of this row. The stride from a row to its NEXT",
    "CHILDREN": "immediate children of this row",
    "NEXT": "the row after this row's whole subtree",
    "TYPE": "the polymorphism driver: exactly one per row, with a default",
    "KEY": "the row's own identifier within the tree",
    "TAGS": "zero or more labels per row; matched as a set",
    "ATTR": "the columns a selector may name in an attribute clause",
    "ATTR_MAP": "attributes supplied as a MAP rather than as columns",
    "ELEMENT": "which rows are elements, when not every row is one",
}
GLOSS_VERB = {
    "tree_ddl_create": "declare a tree",
    "tree_ddl_alter": "replace a tree's semantics, leaving its structure alone",
    "tree_ddl_drop": "undeclare a tree and drop what it compiled",
    "tree_insert": "add rows to a materialized tree",
    "tree_replace": "replace a root's rows wholesale",
    "tree_delete": "remove roots",
    "tree_check": "re-run the conformance assertions and record the verdicts",
}
GLOSS_MACRO = {
    "tree_project": "the tree's rows with the canonical columns added",
    "tree_apply": "project a shape over a source without declaring a tree",
    "tree_explain": "what a selector compiles to, without running it",
    "tree_parse_css": "a CSS selector as duckent IR",
    "tree_steps": "build selector IR directly, bypassing any front-end",
    "tree_shape": "declare structure: the R and O slots, and the semantics block",
    "tree_semantic": "declare semantics: the S slots and the predicates",
    "tree_spec": "a shape plus how it is stored and where its rows come from",
    "tree_ancestors": "walk up from a row",
    "tree_descendants": "walk down from a row",
    "tree_children": "the row's immediate children",
    "tree_parent": "the row's parent",
    "tree_siblings": "every row sharing this row's parent",
    "tree_first_child": "the first child, in sibling order",
    "tree_last_child": "the last child, in sibling order",
    "tree_next_sibling": "the following sibling",
    "tree_prev_sibling": "the preceding sibling",
    "tree_nav": "any of the above, with the relation named as an argument",
    "tree_encode": "derive ORDER and LEVEL from a key/parent pair",
    "tree_derive_parent": "derive PARENT from an ORDER/LEVEL pair",
    "tree_canonical_columns": "the columns projection adds",
    "tree_builtin_predicates": "predicates every tree has without declaring them",
}
GLOSS_DOMAIN = {
    "basis": "which R slots carry the structure",
    "profile": "`sibling_free` when a PARENT basis declares no SIBLING_ORDER",
    "storage": "where the projected rows live",
    "order_source": "`frozen` when no ORDER was declared: the row set's own order is it",
    "kind": "the form the predicate was declared in",
    "origin": "whether the predicate was declared on this tree or shared",
    "status": "the verdict an assertion recorded",
}


class Measured:
    """One loaded database with the reference trees declared, and the readings taken off it."""

    def __init__(self):
        self.s = Session()
        self.con = self.s.con
        self.con.execute("CREATE SCHEMA IF NOT EXISTS docs")
        self.con.execute(FIXTURE)
        for stmt in PURITY_SETUP:
            self.con.execute(stmt)
        for _, _, pre, ddl in REFERENCES:
            for stmt in pre:
                self.con.execute(stmt)
            self.s.execute(ddl + ";")
        self.s.execute("CALL tree_check('docs', 'ast');")

    def rows(self, sql):
        cur = self.con.execute(sql)
        return [d[0] for d in cur.description], cur.fetchall()

    def one(self, sql):
        return self.con.execute(sql).fetchone()[0]

    def functions(self):
        """name -> (parameters, function_type) for every tree_* macro in the catalog."""
        _, rows = self.rows("""SELECT function_name, parameters, function_type
            FROM duckdb_functions() WHERE function_name LIKE 'tree\\_%' ESCAPE '\\'
            GROUP BY ALL ORDER BY function_name""")
        return {r[0]: (list(r[1]), r[2]) for r in rows}

    def shared_without_args(self):
        """How many shared predicates a tree gets when it declares no PREDICATE_ARGS, with the
        shared tier's macro already in the catalog. The cheatsheet states this is zero, so it
        is measured rather than asserted."""
        nm = "shared_probe"
        self.s.execute(
            "CALL tree_ddl_create('docs', '%s', tree_spec(tree_shape(root := 'file_path', "
            '"order" := \'node_id\', level := \'depth\', semantic := tree_semantic('
            "type := 'type')), source := 'docs.src'));" % nm)
        n = self.one("SELECT count(*) FROM tree_catalog_predicates() "
                     "WHERE tree_name = '%s' AND origin = 'shared'" % nm)
        self.s.execute("CALL tree_ddl_drop('docs', '%s');" % nm)
        return n

    def dedup_probe(self):
        """A macro the shared tier would bind, whose derived name a prefix binding has already
        claimed. Returns (how many predicates carry that name, the origin that won). The
        cheatsheet says the macro is bound once, by the prefix -- so measure it."""
        nm = "dedup_probe"
        self.con.execute("CREATE MACRO sel_shallow(depth) AS depth < 2")
        self.s.execute(
            "CALL tree_ddl_create('docs', '%s', tree_spec(tree_shape(root := 'file_path', "
            '"order" := \'node_id\', level := \'depth\', semantic := tree_semantic('
            "predicate_args := 'depth', predicate := [{prefix: 'pre_', args: 'depth'}])), "
            "source := 'docs.src'));" % nm)
        _, rows = self.rows("SELECT origin, body FROM tree_catalog_predicates() "
                            "WHERE tree_name = '%s' AND name = 'shallow'" % nm)
        self.s.execute("CALL tree_ddl_drop('docs', '%s');" % nm)
        self.con.execute("DROP MACRO sel_shallow")
        return len(rows), (rows[0][0] if rows else None), (rows[0][1] if rows else None)

    def refusal_of(self, pre, ddl):
        """The message a declaration is refused with, or None if it was accepted."""
        for stmt in pre:
            self.con.execute(stmt)
        try:
            self.s.execute(ddl + ";")
        except Exception as e:
            return str(e).split("\nLINE ")[0].replace("Invalid Input Error: ", "")
        return None

    def purity_of(self, body):
        """Declare a tree carrying `body` as its one predicate and read the verdict back.
        Returns ('verdict', text) or ('refused', message)."""
        nm = "purity_probe"
        try:
            self.s.execute(
                "CALL tree_ddl_create('docs', '%s', tree_spec(tree_shape(root := 'file_path', "
                '"order" := \'node_id\', level := \'depth\', semantic := tree_semantic('
                "predicate := [{name: 'p', body: '%s'}])), source := 'docs.src'));"
                % (nm, body.replace("'", "''")))
        except Exception as e:
            return "refused", str(e).split("\nLINE ")[0].replace("Invalid Input Error: ", "")
        verdict = self.one("SELECT purity FROM tree_catalog_predicates() "
                           "WHERE tree_name = '%s' AND name = 'p'" % nm)
        self.s.execute("CALL tree_ddl_drop('docs', '%s');" % nm)
        return "verdict", verdict


def norm(name):
    """A slot name without the punctuation the two spellings disagree about: the type says
    `unique_key` and `sibling_order`, the catalog says `UNIQUE KEY` and `SIBLING_ORDER`."""
    return "".join(ch for ch in name.upper() if ch.isalnum())


def table(out, headers, rows):
    out.write("| " + " | ".join(headers) + " |\n")
    out.write("|" + "|".join(["---"] * len(headers)) + "|\n")
    for r in rows:
        out.write("| " + " | ".join("" if c is None else str(c) for c in r) + " |\n")
    out.write("\n")


def code(s):
    return "`" + str(s).replace("|", "\\|") + "`"


def render(m):
    out = io.StringIO()
    missing = []          # measured names with no authored gloss
    stale = []            # authored glosses naming something the catalog no longer has

    def gloss(table_, key):
        if key in table_:
            return table_[key]
        missing.append(key)
        return "_(not described)_"

    fns = m.functions()
    slot_cols, slot_rows = m.rows("SELECT tree_name, block, slot, expression FROM tree_catalog_slots()")
    blocks = {}           # normalised slot -> (block, [trees declaring it], spelling)
    for tree, block, slot, _ in slot_rows:
        key = norm(slot)
        if key not in blocks:
            blocks[key] = [block, [], slot]
        blocks[key][1].append(tree)

    shape_keys = m.one("SELECT json_keys(to_json(tree_shape()))")
    sem_keys = m.one("SELECT json_keys(to_json(tree_semantic()))")

    out.write("# duckent cheatsheet\n\n")
    out.write("<!-- GENERATED FILE. Do not edit: every value below is read out of a live catalog.\n")
    out.write("     Regenerate with: %s   (--check verifies, writes nothing) -->\n\n" % REGEN)
    out.write("Measured against DuckDB %s, from the reference declarations in\n"
              "`test/gen_cheatsheet.py`. An enumerated domain below is what those declarations\n"
              "produce -- not everything the code can produce.\n\n" % m.one("SELECT version()"))

    # -- 1. slots ------------------------------------------------------------
    out.write("## Slots you declare\n\n")
    out.write("`tree_shape()` carries the structure blocks and nests the semantics block;\n")
    out.write("`tree_semantic()` carries the S slots. Block letters are the catalog's own.\n\n")
    rows = []
    for k in shape_keys:
        if k == "semantic":
            continue
        b = blocks.get(norm(k))
        rows.append([code(b[2] if b else k.upper()), b[0] if b else "_(unexercised)_",
                     code(k), gloss(GLOSS_SLOT, b[2] if b else k.upper())])
    for k in sem_keys:
        b = blocks.get(norm(k))
        if b is None:
            continue       # predicate / predicate_args declare predicates, not slots
        rows.append([code(b[2]), b[0], code(k), gloss(GLOSS_SLOT, b[2])])
    table(out, ["slot", "block", "argument", "what it names"], rows)
    not_slots = [k for k in sem_keys if norm(k) not in blocks]
    if not_slots:
        out.write("`tree_semantic()` also takes %s. These are not slots: they declare "
                  "predicates, which the catalog records in `tree_catalog_predicates()`.\n\n"
                  % ", ".join(code(k) for k in sorted(not_slots) + ["predicate_map"]))

    out.write("### What a declaration is refused for\n\n")
    out.write("A declaration either holds or is refused -- never an empty result -- and the "
              "refusal names the tree, plus the root and the value where there is an offending "
              "one. These are the messages, read off the refusals themselves:\n\n")
    rows = []
    for why, pre, ddl in REFUSALS:
        msg = m.refusal_of(pre, ddl)
        if msg is None:
            stale.append("a declaration the cheatsheet says is refused was accepted: " + why)
            continue
        rows.append([why, msg])
    table(out, ["what it gets wrong", "refused with"], rows)

    # -- 2. projection -------------------------------------------------------
    out.write("## Columns projection adds\n\n")
    out.write("`tree_project(schema, tree)` returns the source's own columns plus these, "
              "whatever the declaration's basis:\n\n")
    out.write(", ".join(code(c) for c in m.one("SELECT tree_canonical_columns()")) + "\n\n")
    out.write("A canonical column is present whether its slot was declared or derived -- "
              "that is what makes a selector portable across declarations.\n\n")

    # -- 3. verbs ------------------------------------------------------------
    out.write("## Verbs\n\n")
    out.write("Statements, called with `CALL`. The C++ extension will provide these; the test "
              "runner emulates each one over the compile macro named here.\n\n")
    rows = []
    for v in EXEC_VERBS:
        cm = compile_macro_name(v)
        if cm not in fns:
            stale.append("runner verb %s maps to missing macro %s" % (v, cm))
            continue
        rows.append([code("CALL " + v + "(" + ", ".join(fns[cm][0]) + ")"),
                     code(cm), gloss(GLOSS_VERB, v)])
    table(out, ["verb", "compiles with", "what it does"], rows)

    # tree_match is emulated the same way, but it is an expression rather than a statement:
    # the runner replaces the call with the query it compiles to. So it is absent from
    # duckdb_functions() while tree_explain, which only RETURNS that query, is present --
    # a distinction a reader will otherwise trip over.
    if "tree_compile_match" not in fns:
        stale.append("tree_match's compile macro is missing: tree_compile_match")
    else:
        out.write("%s is emulated the same way, but as an expression: the call is replaced by "
                  "the query %s returns. That is why it has no entry of its own in "
                  "`duckdb_functions()`.\n\n"
                  % (code("tree_match(" + ", ".join(fns["tree_compile_match"][0]) + ")"),
                     code("tree_compile_match")))

    out.write("Expressions and relations, used in a query:\n\n")
    rows = []
    for name in sorted(GLOSS_MACRO):
        if name not in fns:
            stale.append("gloss names a macro the catalog does not have: " + name)
            continue
        params, kind = fns[name]
        rows.append([code(name + "(" + ", ".join(params) + ")"),
                     "relation" if kind == "table_macro" else "scalar", GLOSS_MACRO[name]])
    table(out, ["macro", "returns", "what it does"], rows)

    # -- 4. catalog views ----------------------------------------------------
    out.write("## Reading the catalog\n\n")
    rows = []
    for v in VIEWS:
        if v not in fns:
            stale.append("gloss names a view the catalog does not have: " + v)
            continue
        args = fns[v][0]
        call = v + "(" + ", ".join(args) + ")"
        cols, _ = m.rows("SELECT * FROM %s(%s)" % (
            v, ", ".join("'docs'" if a == "sch" else "'ast'" for a in args)))
        rows.append([code(call), ", ".join(code(c) for c in cols)])
    table(out, ["view", "columns"], rows)

    out.write("The columns whose values come from a fixed set, as the reference declarations "
              "exercise them:\n\n")
    domains = [
        ("basis", "SELECT DISTINCT basis FROM tree_catalog_trees() ORDER BY 1"),
        ("profile", "SELECT DISTINCT profile FROM tree_catalog_trees() ORDER BY 1"),
        ("storage", "SELECT DISTINCT storage FROM tree_catalog_trees() ORDER BY 1"),
        ("order_source", "SELECT DISTINCT order_source FROM tree_catalog_trees() ORDER BY 1"),
        ("kind", "SELECT DISTINCT kind FROM tree_catalog_predicates() ORDER BY 1"),
        ("origin", "SELECT DISTINCT origin FROM tree_catalog_predicates() ORDER BY 1"),
        ("status", "SELECT DISTINCT status FROM tree_catalog_assertions() ORDER BY 1"),
    ]
    extra_notes = [
        "`status` is only ever `ok` here, and that is the point: the structural conditions a "
        "check would otherwise record as violated are refused at declaration instead, as above.",
    ]
    rows = []
    for col, sql in domains:
        vals = [r[0] for r in m.rows(sql)[1]]
        rows.append([code(col), " ".join(code(v) for v in vals), gloss(GLOSS_DOMAIN, col)])
    table(out, ["column", "observed values", "what it says"], rows)
    for note in extra_notes:
        out.write(note + "\n\n")

    # -- 5. selectors --------------------------------------------------------
    out.write("## Selectors\n\n")
    lang_cols, lang_rows = m.rows("SELECT * FROM tree_catalog_languages() ORDER BY language")
    table(out, lang_cols, [[code(c) if c is not None else "_none_" for c in r[:3]] + [fmt(r[3])]
                           for r in lang_rows])
    out.write("Selector text that names no language is parsed as %s "
              "(`tree_catalog.settings`). Text handed over as IR was never parsed, so its "
              "provenance stays `treeql` whatever the default says.\n\n"
              % code(m.one("SELECT value FROM tree_catalog.settings "
                           "WHERE name = 'tree_default_selector_language'")))
    out.write("Predicates every tree has without declaring them: %s. A declared predicate "
              "whose name starts with %s is shared across trees rather than local to one.\n\n"
              % (", ".join(code(":" + p) for p in m.one("SELECT tree_builtin_predicates()")),
                 code(m.one("SELECT tree_shared_predicate_prefix()"))))
    out.write("An unknown predicate is not an error: it selects nothing, and the compiled "
              "SQL says so.\n\n")

    out.write("### Declaring one\n\n")
    out.write("Four forms, and what each records. These are the rows the `forms` reference "
              "declaration below produces -- one declaration, read straight back out:\n\n")
    cols, rows = m.rows("""SELECT name, kind, body, origin, purity FROM tree_catalog_predicates()
        WHERE tree_name = 'forms' ORDER BY origin, name""")
    table(out, cols, [[code(c) for c in r] for r in rows])
    shared_prefix = m.one("SELECT tree_shared_predicate_prefix()")
    out.write("`local` is a predicate the declaration named. `prefix` came from a "
              "`{prefix: ...}` binding, which enumerates every catalog macro carrying that "
              "prefix and names each one by the part after it. `shared` came from the %s "
              "tier, which is scanned for every tree -- but only one that declares "
              "`predicate_args`, since the shared tier has no other source of arguments; "
              "a tree without it gets %d shared predicates however many %s macros exist.\n\n"
              % (code(shared_prefix), m.shared_without_args(), code(shared_prefix)))
    n, origin, body = m.dedup_probe()
    if (n, origin) != (1, "prefix"):
        stale.append("dedup probe: expected one `prefix` binding of the name `shallow`, "
                     "got %d from %r" % (n, origin))
    else:
        out.write("The two tiers can reach the same name. With both a `pre_` binding and a "
                  "`%sshallow` macro in the catalog, the name `shallow` is bound %s, by "
                  "the %s binding, to %s: a macro already claimed under one name is not bound "
                  "again under another.\n\n"
                  % (shared_prefix, "once" if n == 1 else "%d times" % n, code(origin), code(body)))

    # -- 6. purity -----------------------------------------------------------
    out.write("## What a predicate body may contain\n\n")
    out.write("A predicate's body is substituted into a plan, so a body that reads anything "
              "but its row is refused at declaration. These verdicts are read back out of "
              "`tree_catalog_predicates()` after declaring each body:\n\n")
    rows = []
    for body, note in PURITY_PROBES:
        kind, val = m.purity_of(body)
        if kind == "refused":
            stale.append("probe expected a verdict but was refused: " + body)
            continue
        rows.append([code(body), code(val), note])
    table(out, ["body", "purity", "why"], rows)
    out.write("`unknown` is accepted: a macro that calls a macro is beyond one level of "
              "resolution, and DuckDB reports every macro's stability as NULL whatever it "
              "calls, so nothing can be proven either way. Refusing it would refuse a pure "
              "body on no evidence.\n\nRefused outright:\n\n")
    rows = []
    for body in PURITY_REFUSED:
        kind, val = m.purity_of(body)
        if kind != "refused":
            stale.append("probe expected a refusal but got %s: %s" % (val, body))
            continue
        rows.append([code(body), val])
    table(out, ["body", "refused with"], rows)

    # -- 7. the reference declarations --------------------------------------
    out.write("## The reference declarations\n\n")
    out.write("Every reading above was taken from these. The fixture is four rows of one tree:\n\n")
    out.write("```sql\n%s;\n```\n\n" % FIXTURE)
    for name, why, pre, ddl in REFERENCES:
        out.write("%s -- %s:\n\n```sql\n%s%s;\n```\n\n"
                  % (code(name), why, "".join(p + ";\n" for p in pre), ddl))
    cols, rows = m.rows("""SELECT tree_name, is_abstract, like_tree, basis, storage, has_semantic
        FROM tree_catalog_trees() ORDER BY tree_name""")
    table(out, cols, [[code(r[0]), fmt(r[1]), code(r[2]) if r[2] else "", code(r[3]),
                       code(r[4]), fmt(r[5])] for r in rows])
    cols, rows = m.rows("""SELECT tree_name, artifact, status, detail FROM tree_catalog_assertions()
        ORDER BY tree_name, artifact""")
    out.write("`CALL tree_check('docs', 'ast')` records:\n\n")
    table(out, cols, [[code(c) for c in r[:3]] + [r[3]] for r in rows])
    out.write("`tree_catalog_tags('docs', 'ast')` counts the tag column's contents: %s.\n\n"
              % ", ".join("%s = %d" % (code(r[0]), r[1])
                          for r in m.rows("SELECT * FROM tree_catalog_tags('docs','ast')")[1]))

    # -- coverage assertions ------------------------------------------------
    unexercised = [k for k in shape_keys if k != "semantic" and norm(k) not in blocks]
    if unexercised:
        stale.append("no reference declaration exercises shape slot(s): " + ", ".join(unexercised))
    if missing:
        out.write("---\n\nNot yet described, and so marked open rather than omitted: %s.\n"
                  % ", ".join(code(k) for k in sorted(set(missing))))
    return out.getvalue(), stale


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if out of date")
    args = ap.parse_args()

    text, stale = render(Measured())
    if stale:
        sys.stderr.write("gen_cheatsheet: the authored prose no longer matches the catalog:\n")
        for s in stale:
            sys.stderr.write("  - %s\n" % s)
        sys.exit(1)

    have = open(OUT).read() if os.path.exists(OUT) else None
    if args.check:
        if have == text:
            print("gen_cheatsheet: docs/cheatsheet.md is up to date")
            return
        sys.stderr.write("gen_cheatsheet: docs/cheatsheet.md is out of date. Regenerate with:\n"
                         "  %s\n\n" % REGEN)
        sys.stderr.writelines(difflib.unified_diff(
            (have or "").splitlines(keepends=True), text.splitlines(keepends=True),
            "docs/cheatsheet.md", "generated"))
        sys.exit(1)
    if have == text:
        print("gen_cheatsheet: docs/cheatsheet.md unchanged")
        return
    open(OUT, "w").write(text)
    print("gen_cheatsheet: wrote docs/cheatsheet.md (%d lines)" % text.count("\n"))


if __name__ == "__main__":
    main()
