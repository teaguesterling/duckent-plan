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

WHAT IS ALLOWED, and PER CONSTRUCT rather than per file. This mattered more than it looked:
exempting WHOLE FILES hollowed the lint out, because sql/06_selector.sql and sql/07_match.sql
between them hold EVERY converted consumer (06: the bad_key step_field read, tree_treeql_comb,
tree_treeql_clause, bad_kind, bad_comb, the clause CTE; 07: tree_sql_comb's lookup, bad_clause,
bad_kind, bad_parent, the needs_semantic arm, the two requires_sibling_order reads). Reverting any
one of them to a hand-written list was caught by NOTHING: this lint skipped the file, the
cheatsheet's cross-check greps only for the tree_ir_kinds() shape, and every behavioural test
passes because the literal is identical TODAY -- it diverges on the next vocabulary change, which
is precisely the defect class. So the exemptions below name a CONSTRUCT (a substring of the
offending line), and REGISTRY_READS asserts positively that each converted site still reads the
registry.

Measured while making that change: the four sql/*.sql whole-file exemptions were exempting ZERO
flagged lines. Every one of those declarations writes one member per physical line -- the struct
field lists in 00_types.sql are not quoted at all, and the INSERTs and tree_sql_clause's CASE take
one row or one arm per line -- so none of them reaches THRESHOLD. They are therefore scanned now,
with no exemption, and the reasons they would have needed one are recorded against EXEMPT_REASONS
in case that ever changes.

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
#
# These two lines ARE flagged by this script's own detector, and that is now visible rather than
# accidental: the globs below include scripts/*.py, and EXEMPT_CONSTRUCTS exempts these two
# declarations BY NAME with their reason. Before, GLOBS omitted scripts/*.py altogether, so the
# one site this file itself contributes was unchecked by omission -- exempt without appearing in
# the exemption table at all, which is the same failure this script exists to catch.
KIND_SET = ("type", "id", "class", "attr", "pseudo", "where")
COMB_SET = ("desc", "child", "self", "next", "after", "parent", "ancestor", "prev")

# PER-CONSTRUCT exemptions: relpath -> ((substring, reason), ...). A flagged line is skipped only
# if it CONTAINS one of its file's substrings, so the rest of the file stays scanned. Keyed on text
# rather than a line number so it survives edits above it.
EXEMPT_CONSTRUCTS = {
    # Pre-existing, database-free Python. Not copies of the registry a Task 5 sweep missed:
    "test/css_parser.py": (
        ('COMBINATOR = {',
         "the v0 css grammar's own symbol table, mapping css punctuation to an op name. This "
         "module stands in for a parser the C++ extension will own and, by design, has no "
         "database connection to read the registry from; agreement with sql/09_css.sql's "
         "tree_css_comb is proved by the corpus and differential suites, not by this lint"),
        ('CLAUSE_SLOT = {',
         "tree_steps' own slot numbering, which is the clause ORDER and not the clause SET. The "
         "registry holds no order column (see the dated follow-up in the slot-engine spec), so "
         "there is nothing here to read it from; test/sql/38_css_lower.test binds this copy to "
         "the two SQL copies by node_id-inclusive struct comparison on a MULTI-clause step"),
    ),
    "test/test_css_parser.py": (
        ('["selector", "step", "type", "id", "class", "has", "step", "type"]',
         "one assertEqual's expected VALUE -- the kind names appear together because that is what "
         "css_parser.parse('x:has(y).fn#i') returns, not because a vocabulary is declared here"),
    ),
    "test/import_astcss_eval.py": (
        ('COMBINATORS = (',
         "the CSS-REACHABLE subset (desc/child/next/after have css syntax; parent/ancestor/prev "
         "do not), used to flag corpus rows for the sitting_duck #127 differential -- a narrower, "
         "deliberately DIFFERENT set from the engine's own, not a copy of it"),
    ),
    # This script's own transcription, exempt explicitly rather than by glob omission:
    "scripts/check_vocabulary_single_source.py": (
        ('KIND_SET = (',
         "this lint's own copy of the clause-kind set. It is static text scanning with no database "
         "connection to read the registry from -- the same reason test/css_parser.py is exempt -- "
         "and test/sql/46_slot_registry.test and 47_new_combinators.test gate that the registry "
         "has not grown a member this list does not know about"),
        ('COMB_SET = (',
         "the same, for the combinator set"),
    ),
}

# The four sql/*.sql files that were exempt WHOLE and are now scanned with no exemption at all,
# with the reason each would have needed one if its declaration were ever written on a single
# line. Measured: none of them currently reaches THRESHOLD, because each writes one member per
# physical line. Kept as prose, not as an exemption, so the lint has real teeth over the files
# that hold every converted consumer.
EXEMPT_REASONS = {
    "sql/00_types.sql": "TREE_STEP_L0/L1/L2 STRUCT field lists are fixed at definition and cannot "
                        "be generated; test/sql/46_slot_registry.test gates agreement at all three "
                        "levels. The field lists are UNQUOTED identifiers, so this detector does "
                        "not see them in the first place.",
    "sql/01_catalog.sql": "the declaration itself: tree_catalog.clause_kinds' INSERT, one row per "
                          "line. Something has to write the one true copy.",
    "sql/06_selector.sql": "the clause extraction mirroring those structs, one UNION ALL arm per "
                           "kind per line.",
    "sql/07_match.sql": "the derived INSERT into tree_catalog.combinators (each row the relation "
                        "macro's own template, called rather than transcribed) and "
                        "tree_sql_clause's CASE -- the per-kind COMPILATION of a clause, not a "
                        "second copy of the vocabulary that names it. One row or one arm per line.",
}

# POSITIVE assertions, the other half of F3's fix. The detector above can only say that no site has
# grown a literal shaped like a vocabulary; it cannot say that the sites which WERE converted are
# still reading the registry. A reversion that happens to be formatted across two lines, or spelled
# with fewer than THRESHOLD members, would slip past it. So each converted consumer is named here
# by the construct that reads the registry, and this script fails if the construct is gone.
#
# A reformat that changes one of these strings fails this check. That is the intended trade: a
# LOUD failure asking the author to update one line here, rather than a silent one where a
# consumer quietly stopped reading the declaration.
#
# The COUNT is load-bearing where a construct is shared. `list_contains(tree_clause_kinds(),
# c.kind)` reads the registry at TWO sites in sql/07_match.sql -- bad_clause and bad_parent -- and
# presence alone would be satisfied by either one, so reverting bad_clause to a literal while
# bad_parent still read the registry would pass. Measured counts, all four entries at 1 except
# that one; a number here that is larger than the truth fails on the next run, which is the safe
# direction.
REGISTRY_READS = (
    ("sql/06_selector.sql", "tree_steps' unknown-field check reads step_field",
     "(SELECT list(step_field) FROM tree_catalog.clause_kinds)", 1),
    ("sql/06_selector.sql", "tree_treeql_comb's keyword lookup",
     "SELECT c.keyword FROM tree_catalog.combinators c WHERE c.op = want_op", 1),
    ("sql/06_selector.sql", "tree_treeql_clause's keyword lookup",
     "SELECT k.keyword FROM tree_catalog.clause_kinds k WHERE k.kind = want_kind", 1),
    ("sql/06_selector.sql", "the printer's bad_kind whitelist",
     "list_contains(tree_ir_kinds(), kind)", 1),
    ("sql/06_selector.sql", "the printer's bad_comb whitelist",
     "op NOT IN (SELECT c.op FROM tree_catalog.combinators c)", 1),
    ("sql/06_selector.sql", "the printer's clause selection",
     "list_contains(tree_clause_kinds(), c.kind)", 1),
    ("sql/07_match.sql", "tree_sql_comb's template lookup",
     "FROM tree_catalog.combinators c WHERE c.op = want_op", 1),
    ("sql/07_match.sql", "the compiler's bad_kind whitelist",
     "list_contains(tree_ir_kinds(), c.kind)", 1),
    ("sql/07_match.sql", "the compiler's bad_clause AND bad_parent clause selection (two sites)",
     "list_contains(tree_clause_kinds(), c.kind)", 2),
    ("sql/07_match.sql", "the S-less refusal reads needs_semantic",
     "SELECT k.kind FROM tree_catalog.clause_kinds k WHERE k.needs_semantic", 1),
    ("sql/07_match.sql", "the sibling-free refusal reads requires_sibling_order",
     "SELECT c.op FROM tree_catalog.combinators c", 1),
    ("sql/07_match.sql", "...and builds its message from the registry's keywords",
     "SELECT string_agg(c.keyword, ', ' ORDER BY c.keyword)", 1),
)

# THRESHOLD is how many distinct members of one set a single line must quote before it is
# flagged. Module-level, not a literal inside detect(), so Step 2's break-the-detector check
# (lower it to 1 and watch a must-NOT-flag case get flagged) is one assignment, not a rewrite.
THRESHOLD = 3

# What is scanned: sql/*.sql and test/*.py (both flat -- test/mutants/ and test/sql/ are not
# Python), plus scripts/*.py, which was MISSING. Its absence exempted this script's own KIND_SET
# and COMB_SET -- a fourteenth site -- by glob omission rather than by the documented exemption
# table, which is the one way an exemption can exist without anyone having decided it should.
GLOBS = ("sql/*.sql", "test/*.py", "scripts/*.py")

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

# (relpath, line, expect_exempt) -- the per-construct exemption must be NARROW. The first two are
# the real declarations it exists for; the last two are the whole point of the change away from
# whole-file exemptions: a hand-written vocabulary copy on ANY OTHER line of an exempt file must
# still be flagged. Under the old whole-file EXEMPT table both of those were skipped, which is
# what made the lint blind over the two files holding every converted consumer.
EXEMPT_CASES = [
    ("test/css_parser.py", 'CLAUSE_SLOT = {"type": 1, "id": 2, "class": 3, "attr": 4, "pseudo": 5}', True),
    ("scripts/check_vocabulary_single_source.py",
     'KIND_SET = ("type", "id", "class", "attr", "pseudo", "where")', True),
    ("sql/07_match.sql", "  WHERE c.kind IN ('type', 'id', 'class', 'attr', 'pseudo', 'where')", False),
    ("test/css_parser.py", 'SOMETHING_ELSE = ["type", "id", "class", "attr"]', False),
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


def exempt_construct(rel, line, exempt=None):
    """The reason this line is exempt, or None. PER CONSTRUCT: the line must CONTAIN one of the
    substrings declared for its file, so an exemption covers the one declaration it was written
    for and not every other line in the same file."""
    for frag, reason in (EXEMPT_CONSTRUCTS if exempt is None else exempt).get(rel, ()):
        if frag in line:
            return reason
    return None


def scan(root=ROOT, globs=GLOBS, exempt=None):
    """[(relpath, lineno, line, set_name, members), ...] for every hit no construct exempts."""
    hits = []
    for pattern in globs:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            rel = os.path.relpath(path, root)
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, start=1):
                    found = flagged_members(line)
                    if found and exempt_construct(rel, line, exempt) is None:
                        hits.append((rel, lineno, line.rstrip("\n"), found[0], found[1]))
    return hits


def missing_registry_reads(root=ROOT, reads=REGISTRY_READS):
    """[(relpath, label, construct, want, got), ...] for every converted consumer that no longer
    reads the registry as many times as it should. The POSITIVE half: the text detector says no
    literal came back, this says the registry read is still there -- and a reversion has to defeat
    both. Counted, not merely present, because one construct covers two sites (see REGISTRY_READS)
    and presence alone would be satisfied by whichever of them survived."""
    gone, cache = [], {}
    for rel, label, frag, want in reads:
        if rel not in cache:
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                cache[rel] = fh.read()
        got = cache[rel].count(frag)
        if got < want:
            gone.append((rel, label, frag, want, got))
    return gone


def self_test(threshold=THRESHOLD):
    """Prove all three mechanisms discriminate, not just the detector. Returns
    (checked, failures), failures naming each case whose actual outcome disagreed.

    1. the DETECTOR, over SELF_TEST_CASES at the given threshold;
    2. the per-construct EXEMPTION, over EXEMPT_CASES -- including two lines in exempt FILES that
       must still be flagged, which is the property whole-file exemptions did not have;
    3. the positive REGISTRY-READ check, against a construct deliberately not present, so "every
       named site still reads the registry" is known to be capable of failing."""
    failures, checked = [], 0
    for line, expect in SELF_TEST_CASES:
        checked += 1
        got = flagged_members(line, threshold=threshold) is not None
        if got != expect:
            failures.append("detector: expected %s, got %s: %r" % (expect, got, line))
    for rel, line, expect in EXEMPT_CASES:
        checked += 1
        got = exempt_construct(rel, line) is not None
        if got != expect:
            failures.append("exemption in %s: expected exempt=%s, got %s: %r"
                             % (rel, expect, got, line))
    checked += 1
    absent = ("sql/07_match.sql", "a construct no file contains",
              "list_contains(tree_vocabulary_that_does_not_exist(), c.kind)", 1)
    if [g[:4] for g in missing_registry_reads(reads=(absent,))] != [absent]:
        failures.append("registry-read check: did not report an absent construct as missing, so "
                        "it cannot report a real reversion either")
    checked += 1
    present = REGISTRY_READS[:1]
    if missing_registry_reads(reads=present):
        failures.append("registry-read check: reported %r missing although it is present, so it "
                        "would fail on every run and mean nothing" % (present[0][2],))
    checked += 1
    # the COUNT, not just presence: one of the two shared sites going back to a literal must be
    # reported, which a presence-only check could not do.
    shared = next(r for r in REGISTRY_READS if r[3] > 1)
    over = (shared[0], shared[1], shared[2], shared[3] + 1)
    if not missing_registry_reads(reads=(over,)):
        failures.append("registry-read check: counts are not compared, so losing ONE of the two "
                        "%r sites would pass" % (shared[2],))
    return checked, failures


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

    failed = False

    hits = scan()
    if hits:
        failed = True
        sys.stderr.write(
            "check_vocabulary_single_source: a clause-kind or combinator vocabulary is written "
            "out again, outside its registry and the constructs EXEMPT_CONSTRUCTS names:\n")
        for rel, lineno, line, set_name, members in hits:
            sys.stderr.write("  %s:%d: %s members %s\n    %s\n"
                              % (rel, lineno, set_name, members, line.strip()))

    gone = missing_registry_reads()
    if gone:
        failed = True
        sys.stderr.write(
            "check_vocabulary_single_source: a converted consumer no longer reads the registry. "
            "Either the site regressed to its own copy of the vocabulary, or it was reformatted "
            "and REGISTRY_READS in this script needs the new spelling -- say which in the commit:\n")
        for rel, label, frag, want, got in gone:
            sys.stderr.write("  %s: %s\n    expected %d occurrence(s), found %d: %s\n"
                              % (rel, label, want, got, frag))

    if failed:
        sys.exit(1)

    exempt_constructs = sum(len(v) for v in EXEMPT_CONSTRUCTS.values())
    print("check_vocabulary_single_source: no site outside the registry and the %d exempt "
          "construct(s) writes out the clause-kind or combinator vocabulary, and all %d converted "
          "consumer(s) still read it (%d file(s) formerly exempt WHOLE are now scanned: %s)"
          % (exempt_constructs, len(REGISTRY_READS), len(EXEMPT_REASONS),
             ", ".join(sorted(EXEMPT_REASONS))))


if __name__ == "__main__":
    main()
