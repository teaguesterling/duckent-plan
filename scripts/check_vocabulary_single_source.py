#!/usr/bin/env python3
"""The clause-kind and combinator vocabularies must be declared once.

WHY A LINT AND NOT A TEST. The sets were written out at thirteen hand-copied sites across four
files before Task 5 collapsed them into tree_catalog.clause_kinds and tree_catalog.combinators.
The failure mode of a drifted copy is silence: the printer renders a clause as nothing, or the
door accepts a kind the compiler then refuses -- and the eighth site found during that work wrote
the set with `where` left out, so a search for the full six-member list did not even find it. A
SQL test can prove the registry is read where it is read; only a scan of the source text can
prove no site has quietly grown its own copy again, partial or complete. Partial copies are the
more dangerous kind, because the omission itself encodes a rule nothing else states.

THE DETECTOR. A physical line is flagged when it carries three or more members of either
vocabulary as quoted string literals -- not the complete set. Three, not six or eight, because a
partial copy (the five-member one above) is exactly the shape that must be caught; waiting for a
full copy would have let that one through. "Quoted" means the token between a matching pair of
quotes is EXACTLY the member spelling -- '._type = ' does not count as `type`, and a struct field
reference like (s).type is not quoted at all.

WHAT IS ALLOWED, and why each exemption exists (whole files, not lines within them). The first
four are sql/*.sql sites with a load-bearing reason they cannot read the registry; the last three
are pre-existing, database-free Python that this task newly brings into scope by scanning
test/*.py, and are exempt because they are not copies of the registry at all (see EXEMPT below
for the detail on each) -- not because fixing them was out of reach:
  sql/00_types.sql        TREE_STEP_L0/L1/L2 -- DuckDB STRUCT field lists are fixed at definition
                          and cannot be generated from a table. test/sql/46_slot_registry.test
                          gates their agreement with the registry instead.
  sql/06_selector.sql     the extraction mirroring those same structs, once per nesting level
                          (L0/L1/L2) -- it exists for the same reason the structs do, and for the
                          same reason cannot be generated.
  sql/01_catalog.sql      the declaration itself: tree_catalog.clause_kinds' INSERT. Something has
                          to write the one true copy.
  sql/07_match.sql        the derived INSERT into tree_catalog.combinators (each row is the
                          matching relation macro's own template, called rather than transcribed
                          -- see the comment at the INSERT) and tree_sql_clause's CASE, which is
                          the per-kind COMPILATION of a clause, not a second copy of the vocabulary
                          that names it. test/sql/46_slot_registry.test gates that agreement
                          separately.
  test/css_parser.py      a grammar symbol table and a slot order, both database-free by design.
  test/test_css_parser.py test assertions pinning one parse's output, not a vocabulary.
  test/import_astcss_eval.py  a deliberately narrower, CSS-reachable subset for one differential.

Usage:  python3 scripts/check_vocabulary_single_source.py              scan the tree
        python3 scripts/check_vocabulary_single_source.py --self-test  prove the detector discriminates
"""
import argparse, glob, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The vocabularies, as the registry declares them today (sql/01_catalog.sql's INSERT into
# tree_catalog.clause_kinds, 6 rows; sql/07_match.sql's INSERT into tree_catalog.combinators, 8
# rows). This lint is static text scanning, not a database read, so these are transcribed by
# hand -- but transcribed into ONE place, and test/sql/46_slot_registry.test and
# test/sql/47_new_combinators.test both gate that the registry itself has not grown a member
# these lists do not know about, which is what keeps this copy from being the fourteenth site.
KIND_SET = ("type", "id", "class", "attr", "pseudo", "where")
COMB_SET = ("desc", "child", "self", "next", "after", "parent", "ancestor", "prev")

# Whole-file exemptions, each with the reason it exists. See the module docstring for the
# reasoning; this is the table the detector actually consults.
EXEMPT = {
    "sql/00_types.sql": "TREE_STEP_L0/L1/L2 STRUCT field lists are fixed at definition and "
                         "cannot be generated; test/sql/46_slot_registry.test gates agreement",
    "sql/06_selector.sql": "the extraction mirroring those structs, once per nesting level",
    "sql/01_catalog.sql": "the declaration itself",
    "sql/07_match.sql": "the derived INSERT into tree_catalog.combinators (template-derived, not "
                         "transcribed) and tree_sql_clause's CASE -- the per-kind COMPILATION of "
                         "a clause, not a vocabulary copy; test/sql/46_slot_registry.test gates "
                         "that agreement separately",
    # The three below are NOT sql/*.sql sites a hand-copy could have drifted from the registry --
    # they are pre-existing, database-free Python, and scanning test/*.py (new in this task) finds
    # them for a reason that is not "Task 5 missed a site":
    "test/css_parser.py": "the v0 css grammar's own symbol table (COMBINATOR maps css punctuation "
                           "to an op name; CLAUSE_SLOT is tree_steps' own slot numbering). This "
                           "module stands in for a parser the C++ extension will own and, by "
                           "design, has no database connection to read the registry from; "
                           "agreement with sql/09_css.sql's tree_css_comb is proved by the corpus "
                           "and differential suites, not by this lint",
    "test/test_css_parser.py": "test assertions pinning css_parser.py's parsed output for one "
                                "example apiece -- the kind names appearing together are an "
                                "expected VALUE being checked, not a vocabulary being declared",
    "test/import_astcss_eval.py": "COMBINATORS there is the CSS-REACHABLE subset (desc/child/next/"
                                   "after have css syntax; parent/ancestor/prev do not) used to "
                                   "flag corpus rows for the sitting_duck #127 differential -- a "
                                   "narrower, deliberately different set from the engine's own, "
                                   "not a copy of it",
}

# THRESHOLD is how many distinct members of one set a single line must quote before it is
# flagged. Module-level, not a literal inside detect(), so Step 2's break-the-detector check
# (lower it to 1 and watch a must-NOT-flag case get flagged) is one assignment, not a rewrite.
THRESHOLD = 3

# Globs the brief says to scan: sql/*.sql (flat -- no subdirectories carry vocabulary copies
# today) and test/*.py (flat -- test/mutants/ and test/sql/ are not Python).
GLOBS = ("sql/*.sql", "test/*.py")

# (line, expect_flagged) -- strings that MUST be flagged (True) and strings that MUST NOT be
# (False), counted in the summary rather than asserted as a magic total. Drawn from real sites:
# the first two are the two shapes a drifted copy of the clause-kind set actually took (a NOT IN
# naming all six, and one naming five with `where` dropped -- the dangerous partial copy this
# detector exists for); the third is the cheatsheet's literal this task repoints at the registry.
# The last two are real call sites that must NOT be flagged, or the detector is useless by being
# too eager.
SELF_TEST_CASES = [
    ("  WHERE k NOT IN ('comb', 'type', 'id', 'class', 'attr', 'pseudo', 'where')", True),
    ("  kind NOT IN ('selector', 'step', 'has', 'not', 'type', 'id', 'class', 'attr')", True),
    ('SELECTOR_KINDS = ["type", "id", "class", "attr", "pseudo", "where"]', True),
    ("COMB_OPS = ['desc', 'child', 'self', 'next', 'after', 'parent', 'ancestor', 'prev']", True),
    ("  WHERE list_contains(tree_clause_kinds(), c.kind)", False),
    ("    WHEN 'type' THEN alias || '._type = ' || tree_sql_lit(value)", False),
    ("  ('desc',  'DESCENDANT', tree_sql_subtree('{a}','{b}'),  NULL, false),", False),
    ("""    UNION ALL SELECT a.*, 2, 'id', a.id, NULL, NULL FROM allsteps a WHERE a.id IS NOT NULL""", False),
]


def quoted_tokens(line):
    """Every substring found between a matching pair of quotes (single or double), as written --
    not unescaped, since no member spelling this scans for contains a quote or a backslash."""
    tokens = []
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch in ("'", '"'):
            end = line.find(ch, i + 1)
            if end == -1:
                break
            tokens.append(line[i + 1:end])
            i = end + 1
        else:
            i += 1
    return tokens


def flagged_members(line, threshold=THRESHOLD):
    """(set name, members found) for whichever vocabulary this line quotes `threshold` or more
    distinct members of, or None if neither reaches it. Distinct, not occurrences: a member
    repeated on one line (a dict key and its own value, say) says nothing a single mention
    doesn't."""
    tokens = set(quoted_tokens(line))
    for name, vocab in (("clause kind", KIND_SET), ("combinator", COMB_SET)):
        found = tokens & set(vocab)
        if len(found) >= threshold:
            return name, sorted(found)
    return None


def scan(root=ROOT, globs=GLOBS, exempt=EXEMPT):
    """[(relpath, lineno, line, set_name, members), ...] for every non-exempt hit."""
    hits = []
    for pattern in globs:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            rel = os.path.relpath(path, root)
            if rel in exempt:
                continue
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, start=1):
                    found = flagged_members(line)
                    if found:
                        hits.append((rel, lineno, line.rstrip("\n"), found[0], found[1]))
    return hits


def self_test(threshold=THRESHOLD):
    """Run SELF_TEST_CASES through flagged_members() at the given threshold. Returns
    (checked, failures) where failures names each case whose actual outcome disagreed."""
    failures = []
    for line, expect in SELF_TEST_CASES:
        got = flagged_members(line, threshold=threshold) is not None
        if got != expect:
            failures.append("expected %s, got %s: %r" % (expect, got, line))
    return len(SELF_TEST_CASES), failures


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true",
                     help="prove the detector discriminates; write nothing, scan nothing")
    args = ap.parse_args()

    if args.self_test:
        checked, failures = self_test()
        if failures:
            sys.stderr.write("check_vocabulary_single_source --self-test FAILED:\n")
            for f in failures:
                sys.stderr.write("  - " + f + "\n")
            sys.exit(1)
        print("check_vocabulary_single_source --self-test: %d cases checked, all correct"
              % checked)
        return

    hits = scan()
    if hits:
        sys.stderr.write(
            "check_vocabulary_single_source: a clause-kind or combinator vocabulary is written "
            "out again, outside its registry and the exempt files listed in this script's "
            "docstring:\n")
        for rel, lineno, line, set_name, members in hits:
            sys.stderr.write("  %s:%d: %s members %s\n    %s\n"
                              % (rel, lineno, set_name, members, line.strip()))
        sys.exit(1)
    print("check_vocabulary_single_source: no site outside the registry and the %d exempt "
          "file(s) writes out the clause-kind or combinator vocabulary" % len(EXEMPT))


if __name__ == "__main__":
    main()
