#!/usr/bin/env python3
r"""The TREEQL front-end differential: two independent readings of one grammar, compared row for row.

    python3 test/sweep_treeql.py            every case
    python3 test/sweep_treeql.py --quick    the printer-output cases only

WHY A DIFFERENTIAL AND NOT A TEST. sql/09_css.sql states what the alternative is worth: "Two
independent readings of one grammar is the point; agreeing by construction would prove nothing."
test/css_parser.py is the css pair's second reading and has zero duckdb references for exactly that
reason; test/treeql_parser.py is this pair's, and this script is what binds it to the macros.

THE TWO READINGS ARE ARCHITECTURALLY DIFFERENT, which is what makes the agreement evidence:

  * sql/10_treeql.sql SPLITS FIRST. It cuts the text on a depth-0 newline, then on depth-0 commas,
    then before combinator keywords, and asks a per-part reader what each fragment is. Depth and
    "inside a quote" come from two window functions over the characters, so the scan knows nothing
    about which clause kind it is inside.
  * test/treeql_parser.py DESCENDS. It reads a keyword, then reads that keyword's body by the rule
    for its kind -- a literal body stops at its closing quote, a raw body runs to the next
    separator that is followed by a clause keyword -- so the scan always knows what it is inside.

Neither is a transcription of the other, and the shapes where they disagree are listed in
DIVERGENT below with the record that pins each one.

WHAT IS COMPARED, and the one place it is deliberately loose. For an accepted selector: every
field of every row, node ids included, which is the comparison test/sql/38_css_lower.test makes
for the css pair and the reason it is worth making -- a numbering that agreed on shape and not on
ids would still compile to a different query. For a REFUSED selector: the refusal's SENTENCE, and
the WORD it names where it names one. The FRAGMENT in `cannot read <fragment>` is NOT compared,
because a fragment is whatever the architecture had in hand when it gave up -- a split-first
reader names a part and a descent reader names the token it stopped on -- and requiring those to
match would be requiring one architecture. The sentence is the claim about the cause, and that is
what must agree. `--strict-frag` compares it anyway, for the record.

EXACT IS CHECKED TOO, on every case whose text came from the printer, and it is what breaks a tie:
when the two readings disagree, the one that returns the IR the printer was given is right. That
is why the generator builds IR and prints it rather than writing text by hand -- the text then
carries its own expected answer.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run as harness
import treeql_parser

FIELDS = ("node_id", "parent_id", "kind", "value", "op", "arg", "alias")


def sql_str(s):
    return "'" + s.replace("'", "''") + "'"


# ----------------------------------------------------------------------------------------------
# FAMILY A: IR built by the ordinary constructor, printed, and read back by both front-ends.
#
# Each entry is the argument to tree_steps, as SQL text. The text under test is
# tree_selector_to_treeql(tree_steps(<entry>)), so it is printer output by construction and the
# EXACT theorem quantifies over it: whatever the two readings do, the right answer is the IR the
# printer was handed.
#
# THE FIVE SHAPES THE PLAN NAMES are a19..a24 and b23, each marked with the blind spot it probes.
# ----------------------------------------------------------------------------------------------
IR_CASES = [
    ("a01 type", "[{type: 'a'}]"),
    ("a02 id", "[{id: 'x'}]"),
    ("a03 class", "[{class: 'fn'}]"),
    ("a04 pseudo", "[{pseudo: 'p'}]"),
    ("a05 attr", "[{attr: 'a = 1'}]"),
    ("a06 where", "[{\"where\": 'n = 1'}]"),
    ("a07 every clause kind on one step",
     "[{type: 't', id: 'i', class: 'c', attr: 'a = 1', pseudo: 'p', \"where\": 'n = 1'}]"),
    ("a08 alias", "[{type: 'a', \"as\": 'cap'}]"),
    ("a09 two steps, desc default", "[{type: 'a'}, {type: 'b'}]"),
    # every combinator the registry holds that is legal on a later top-level step. `self` is not:
    # tree_steps refuses it there, so it has no printer output to read back.
    ("a10 comb child", "[{type: 'a'}, {type: 'b', comb: 'child'}]"),
    ("a11 comb desc", "[{type: 'a'}, {type: 'b', comb: 'desc'}]"),
    ("a12 comb next", "[{type: 'a'}, {type: 'b', comb: 'next'}]"),
    ("a13 comb after", "[{type: 'a'}, {type: 'b', comb: 'after'}]"),
    ("a14 comb parent", "[{type: 'a'}, {type: 'b', comb: 'parent'}]"),
    ("a15 comb ancestor", "[{type: 'a'}, {type: 'b', comb: 'ancestor'}]"),
    ("a16 comb prev", "[{type: 'a'}, {type: 'b', comb: 'prev'}]"),
    ("a17 literal with an embedded quote", "[{type: 'it''s'}]"),
    ("a18 literal with a close paren", "[{type: 'has ) paren'}]"),
    ("a19 literal with a comma", "[{type: 'a, b'}]"),
    ("a20 literal with a newline", "[{type: 'a' || chr(10) || 'b'}]"),
    ("a21 literal with two doubled quotes", "[{type: 'two '''' quotes '''' here'}]"),
    ("a22 has group", "[{type: 'a', has: [{type: 'b'}]}]"),
    ("a23 not group", "[{type: 'a', \"not\": [{type: 'b'}]}]"),
    ("a24 has and not on one step",
     "[{type: 'a', has: [{type: 'b'}], \"not\": [{type: 'c'}]}]"),
    ("a25 group chain with combinators",
     "[{type: 'a', has: [{type: 'b'}, {type: 'c', comb: 'child'}]}]"),
    ("a26 group nested two deep",
     "[{type: 'a', has: [{type: 'b', has: [{type: 'c'}]}]}]"),
    ("a27 attr LIKE", "[{attr: 'n LIKE ''x%'''}]"),
    ("a28 attr NOT LIKE", "[{attr: 'n NOT LIKE ''x%'''}]"),
    ("a29 attr ILIKE", "[{attr: 'n ILIKE ''x%'''}]"),
    ("a30 attr <=", "[{attr: 'size <= 10'}]"),
    ("a31 attr <>", "[{attr: 'size <> 10'}]"),
    ("a32 attr no space", "[{attr: 'size<=10'}]"),
    ("a33 where with a comma inside parens", "[{\"where\": 'n IN (1, 2)'}]"),
    # ---- the five shapes the plan names, each a known or suspected splitter blind spot ----
    ("a34 apostrophe inside a WHERE body (plan case 1)", "[{\"where\": '\"o''k\" = 1'}]"),
    ("a35 apostrophe inside an ATTR body (plan case 2)", "[{attr: 'a = \"o''k\"'}]"),
    ("a36 comma inside a bracket pair (plan case 3)", "[{\"where\": '[1, 2] = [1, 2]'}]"),
    ("a37 comma inside a brace pair (plan case 4)",
     "[{\"where\": '{a: 1, b: 2} = {a: 1, b: 2}'}]"),
    # the boundary beside a36/a37, which 48_treeql_parse.test records: a bracket or a brace is not
    # itself the problem, only a COMMA inside one is. A fix that refused brackets turns these red.
    ("a38 bracket with no comma", "[{\"where\": 'x[1] = 1'}]"),
    ("a39 brace with no comma", "[{\"where\": '{a: 1} = {a: 1}'}]"),
    # two odd-quoted bodies: the shape R42 was written for, where the parity stand-down does not
    # engage because the two odd counts sum to an even one
    ("a40 two odd bodies, step and group",
     "[{type: 'a', \"where\": '\"o''k\" = 1', has: [{type: 'b', \"where\": '\"o''k\" = 1'}]}]"),
    ("a41 two odd bodies, both inside groups",
     "[{type: 'a', has: [{type: 'b', \"where\": '\"o''k\" = 1', "
     "has: [{type: 'c', \"where\": '\"o''k\" = 1'}]}]}]"),
    ("a42 two odd bodies across two top-level steps",
     "[{type: 'a', has: [{type: 'b', \"where\": '\"o''k\" = 1'}]}, "
     "{type: 'e', comb: 'child', \"where\": '\"o''k\" = 1'}]"),
    ("a43 odd bodies and a literal holding an unmatched close paren",
     "[{type: 'a ) unmatched', \"where\": '\"o''k\" = 1', "
     "has: [{type: 'b', \"where\": '\"o''k\" = 1'}]}]"),
    # F3's IR. The text it prints is byte-identical to what a person writes for TWO steps, and
    # EXACT requires the one-step reading. See THE F3 RULING in test/sql/48_treeql_parse.test.
    ("a44 F3's constructible IR", "[{attr: 'a = 1) (ATTR b = 2'}]"),
]

# ----------------------------------------------------------------------------------------------
# FAMILY B: TEXT written by hand. No theorem quantifies over these -- the printer never emits
# most of them -- so the only question is whether the two readings answer alike. Requirement 6's
# territory: tolerated input, and refusals.
# ----------------------------------------------------------------------------------------------
TEXT_CASES = [
    ("b01 parenless clause list at top level", "CLASS fn"),
    ("b02 bare identifier value (D-N15)", "(TYPE a)"),
    ("b03 lowercase keywords", "(type 'a')"),
    ("b04 mixed-case keywords", "(TyPe 'a')"),
    ("b05 tab after the keyword", "(TYPE\t'a')"),
    ("b06 form feed after the keyword", "(TYPE\f'a')"),
    ("b07 carriage return after the keyword", "(TYPE\r'a')"),
    ("b08 leading and trailing whitespace", "   (TYPE 'a')   "),
    ("b09 the documented comma limit", "(TYPE 'x', WHERE a = 1, PSEUDO 'p')"),
    ("b10 lowercase combinator", "(TYPE 'a')\nchild (TYPE 'b')"),
    ("b11 trailing newline", "(TYPE 'a')\n"),
    ("b12 leading newline before a clause keyword", "\nTYPE 'a'"),
    ("b13 leading newline before a parenthesised step", "\n(TYPE 'a')"),
    ("b14 leading newline before a combinator", "\nCHILD (TYPE 'b')"),
    ("b15 blank line between two steps", "(TYPE 'a')\n\nCHILD (TYPE 'b')"),
    ("b16 CRLF", "(TYPE 'a')\r\nCHILD (TYPE 'b')"),
    ("b17 alias only", " AS x"),
    ("b18 alias after a clause list", "(TYPE 'a') AS cap"),
    ("b19 AS inside a literal is not an alias", "(ATTR t = 'X AS y')"),
    ("b20 AS inside a WHERE body is not an alias", "(WHERE CAST(n AS INT) = 1)"),
    ("b21 a word that starts with AS", "ASx y"),
    ("b22 an attribute named as", "(ATTR as = x)"),
    ("b23 bare combinator keyword", "(TYPE 'a')\nCHILD"),
    # --- plan case 5: a raw body followed by another step inside a group ---
    ("b24 WHERE body then a step inside a group (plan case 5)",
     "(TYPE 'a', HAS ( WHERE a = 1 TYPE 'b' ))"),
    ("b25 ATTR body then a step inside a group (plan case 5)",
     "(TYPE 'a', HAS ( ATTR a = 1 TYPE 'b' ))"),
    ("b26 two literal-bodied steps inside a group", "(TYPE 'a', HAS ( TYPE 'b' TYPE 'c' ))"),
    # --- F3, by its text rather than by its IR ---
    ("b27 F3's text", "(ATTR a = 1) (ATTR b = 2)"),
    ("b28 F3's literal-bodied control", "(TYPE 'a') (TYPE 'b')"),
    # --- refusals ---
    ("b29 empty", ""),
    ("b30 whitespace only", "   "),
    ("b31 unclosed paren", "(TYPE 'a'"),
    ("b32 unopened paren", "TYPE 'a')"),
    ("b33 unterminated literal", "TYPE 'a"),
    ("b34 unterminated literal with a doubled quote", "TYPE 'it''s"),
    ("b35 closed literal with trailing text", "TYPE 'a' SIDEWAYS TYPE 'b'"),
    ("b36 unknown combinator", "KID (TYPE 'b')"),
    ("b37 unknown clause keyword", "FROBNICATE 'x'"),
    ("b38 parenless group", "HAS TYPE 'b'"),
    ("b39 parenless group as a clause part", "(TYPE 'a', HAS TYPE 'b')"),
    ("b40 empty group", "(TYPE 'a', HAS ( ))"),
    ("b41 a part that is no clause at all", "42"),
    ("b42 clause keyword with no operand", "TYPE"),
    ("b43 unknown combinator with an unreadable body", "SIDEWAYS (TYPE 'a', 42)"),
    ("b44 mismatched parens across two steps", "(TYPE 'b') KID (TYPE 'c')"),
    ("b45 attr whose name contains an operator name", "(ATTR ALIKE 'x')"),
    ("b46 attr with an operator and no argument", "(ATTR name =)"),
    ("b47 attr with a two-character operator and no argument", "(ATTR name <=)"),
    ("b48 attr with no operator", "(ATTR name)"),
    ("b49 attr operator with a word boundary fault", "(ATTR name LIKEx 'a')"),
    ("b50 attr operator case and spacing are free", "(ATTR n   not   like 'x%')"),
    ("b51 groups nested past the limit",
     "(TYPE 'a', HAS ( (TYPE 'b', HAS ( (TYPE 'c', HAS ( (TYPE 'd') )) )) ))"),
    ("b52 alias that is not an identifier", "(TYPE 'a') AS my-cap"),
    ("b53 group whose chain has no combinator but has parens",
     "(TYPE 'a', HAS ( (TYPE 'b') (TYPE 'c') ))"),
    ("b54 a quoted close paren does not end the clause list", "(TYPE 'a ) b') AS c"),
    # THE BOUNDARIES OF THIS SWEEP'S OWN TWO NEW RULES, probed rather than assumed. Each is a
    # shape where test/treeql_parser.py could have parted from the macros for a reason that is
    # about the Python and not about the splitter, so the sweep asks instead of my believing it.
    #
    # b55: a raw body whose top-level comma is NOT followed by a clause keyword. The Python's
    # clause-list rule keeps reading; the macros cut. Not reachable from a legal predicate -- the
    # record beside the documented limit in 48_treeql_parse.test measures that a bare top-level
    # comma is a syntax error -- so no printer output has this shape.
    ("b55 raw body with a bare top-level comma", "(WHERE a = 1, b = 2)"),
    # b56: an unterminated literal INSIDE a raw body. Both readings decline to judge it, for the
    # reason R42 gives: a quote count is evidence about a value only where the text is a value.
    ("b56 unterminated literal inside a WHERE body", "(WHERE a = 'x)"),
    # b57: a group keyword whose part carries a raw body and whose chain really has no
    # parentheses. The macros' groupparen arm stands down on raw-bodied text and the generic
    # counterweight row catches it instead.
    ("b57 parenless group whose part carries a raw body", "(TYPE 'a', HAS WHERE a = 1)"),
    # b58: a double-quoted identifier holding a comma. The Python reads `"..."` as a quoted
    # region, which is what the WHERE cases need; the macros do not.
    ("b58 comma inside a double-quoted identifier", "(WHERE \"a,b\" = 1)"),
]

# ----------------------------------------------------------------------------------------------
# THE DECLARED DIVERGENCES. A differential with no exceptions is the goal; a differential whose
# exceptions are a wildcard is worthless. Each entry names ONE case label, the record in
# test/sql/48_treeql_parse.test that pins the SQL side's answer, and WHICH reading is right.
#
# "sql" means the macros are right and this script's Python is wrong -- there are none of those,
# and the entry shape allows one so that a future divergence cannot be recorded without saying so.
# "py" means test/treeql_parser.py returns the answer the printer's own output requires and the
# macros do not.
# ----------------------------------------------------------------------------------------------
DIVERGENT = {
    # ---- CLASS 1: the splitter reads every `'` as a delimiter and knows nothing of `"..."` ----
    # R41, named in 48_treeql_parse.test's R42 block: "EXACT is NOT asserted here: it is FALSE at
    # BASE for these shapes, because the clause-list splitter mis-splits on the same unpaired
    # apostrophe. That is R41, it predates this task, and Task 7's differential generator carries
    # it." This is that carrying. A WHERE body is raw host SQL, so it may hold a double-quoted
    # IDENTIFIER whose content has an apostrophe -- `WHERE "o'k" = 1` is printer output from the
    # ordinary constructor and legal DuckDB SQL. The macros' quote parity loses its place on it.
    #
    # NOT FIXED HERE, and the reason is a measurement rather than a preference: the macros' scan is
    # a WINDOW SUM over one delimiter, which has a closed form. Tracking two delimiters that can
    # nest needs sequential state -- the state after character i depends on the state after i-1 and
    # not on a count -- so it is a recursive CTE or a list_reduce, inside a scalar macro that R22
    # already records a binder wall for. That is a piece of work with its own risk, and this sweep
    # is what will prove it when someone does it: every entry below turns into an `agree`.
    "a40": ("py", "the R42 record at 48_treeql_parse.test:2189 pins the REPRINT half only"),
    "a41": ("py", "the R42 record at 48_treeql_parse.test:2198 pins the REPRINT half only"),
    "a42": ("py", "the `cannot read` record at 48_treeql_parse.test:2267 (step2+has)"),
    "a43": ("py", "the R42 discriminator record at 48_treeql_parse.test:2225"),
    "b58": ("py", "no record: the same cause as a40..a43, found by this sweep"),

    # ---- CLASS 2: the R42 stand-downs, which decline to name a cause on raw-bodied text ----
    # Three refusal arms ask tree_treeql_no_raw_body first and stand down when it is FALSE, because
    # on mis-split raw-bodied text the fragment they would name is not evidence of the fault they
    # name. sql/10_treeql.sql states the cost of that at its `parenless` arms: "on raw-bodied text
    # this arm does not fire AND nothing downstream catches it, so a WHERE or ATTR body SWALLOWS
    # THE STEP THAT FOLLOWS IT and the parse is silently wrong."
    #
    # THIS READING NEEDS NO STAND-DOWN, which is why it diverges: its scan does not lose its place
    # on a raw body, so it can name the real cause. b24/b25 are F2 -- the macros return a clean
    # WRONG parse and this reading refuses by name.
    #
    # NOT FIXED HERE, by the authority file's own wording. 48_treeql_parse.test says of F1 "Task 7
    # owns the fix", and of this gap "THE GAP IS NOT FIXED HERE, by ruling ... Task 7's
    # differential generator owns it." The generator is what owns it, and these three entries are
    # it: the guard cannot be lifted while CLASS 1 is open, because then a genuinely mis-split
    # fragment would get a false `parenless` cause -- which is the defect R42 added the guard for.
    "b24": ("py", "F2, pinned at 48_treeql_parse.test:2380 -- the macros' wrong parse is the record"),
    "b25": ("py", "F2's ATTR twin; the record at :2380 pins the WHERE one"),
    "b57": ("py", "no record: the groupparen arm's stand-down, same cause as b24/b25"),

    # ---- CLASS 3: a raw body's own top-level comma, where no bracket or brace encloses it ----
    # The residue of F1 after the splitter learned `[ ]` and `{ }`. NOT REACHABLE FROM A LEGAL
    # PREDICATE: the record at 48_treeql_parse.test:2145 measures that a bare top-level comma is a
    # DuckDB syntax error, so the printer can never emit this shape from a WHERE body the host door
    # accepted. That is why the bracket and brace cases were the ones worth fixing and this one is
    # recorded instead -- and why it is listed here rather than left to be rediscovered.
    "b55": ("py", "no record: unreachable from a legal predicate, see the record at :2145"),
}


def rows_from_sql(con, text):
    """The SQL front-end's reading: a list of field tuples, or ('REFUSED', message)."""
    q = ("SELECT " + ", ".join(FIELDS) + " FROM (SELECT unnest(tree_parse_treeql("
         + sql_str(text) + "), recursive := true))")
    try:
        return [tuple(r) for r in con.execute(q).fetchall()]
    except Exception as e:
        return ("REFUSED", str(e).replace("\n", " | "))


def rows_from_py(text):
    """The Python front-end's reading, in the same shape."""
    try:
        return [tuple(r[f] for f in FIELDS) for r in treeql_parser.parse(text)]
    except treeql_parser.TreeqlError as e:
        return ("REFUSED", str(e))


def refusal_class(msg, strict_frag=False):
    """A refusal's comparable identity: the sentence, plus the word it names where it names one.

    The message is the duckent refusal `tree_parse_treeql: <sentence>`, which DuckDB wraps in its
    own prefix on the SQL side, so the sentence is found rather than sliced off a known offset.
    """
    i = msg.find("tree_parse_treeql: ")
    if i < 0:
        return "RAW:" + msg
    s = msg[i + len("tree_parse_treeql: "):].strip()
    if strict_frag:
        return s
    if s.startswith("cannot read"):
        return "generic"
    return s


def compare(sql, py, strict_frag):
    """(verdict, detail). Verdict is one of agree, both-refuse, diverge."""
    sql_ref, py_ref = isinstance(sql, tuple), isinstance(py, tuple)
    if sql_ref and py_ref:
        a, b = refusal_class(sql[1], strict_frag), refusal_class(py[1], strict_frag)
        if a == b:
            return "both-refuse", a
        return "diverge", "refused differently:\n    sql: %s\n    py : %s" % (sql[1], py[1])
    if sql_ref != py_ref:
        who = "sql refused, py accepted" if sql_ref else "py refused, sql accepted"
        msg = (sql if sql_ref else py)[1]
        acc = py if sql_ref else sql
        return "diverge", "%s\n    message: %s\n    accepted rows: %s" % (who, msg, acc)
    if sql != py:
        return "diverge", "accepted different IR:\n    sql: %s\n    py : %s" % (sql, py)
    return "agree", None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true",
                    help="the printer-output cases only")
    ap.add_argument("--strict-frag", action="store_true",
                    help="compare the fragment in `cannot read <fragment>` too")
    args = ap.parse_args()

    con = harness.Session().con
    cases = []
    for label, ir in IR_CASES:
        text = con.execute("SELECT tree_selector_to_treeql(tree_steps(" + ir + "))").fetchone()[0]
        want = [tuple(r) for r in con.execute(
            "SELECT " + ", ".join(FIELDS) + " FROM (SELECT unnest(tree_steps(" + ir
            + "), recursive := true))").fetchall()]
        cases.append((label, text, want))
    if not args.quick:
        cases += [(label, text, None) for label, text in TEXT_CASES]

    counts = {"agree": 0, "both-refuse": 0, "diverge": 0}
    exact_sql = exact_py = exact_checked = 0
    bad = []
    for label, text, want in cases:
        sql, py = rows_from_sql(con, text), rows_from_py(text)
        verdict, detail = compare(sql, py, args.strict_frag)
        counts[verdict] += 1
        if want is not None:
            exact_checked += 1
            if sql == want:
                exact_sql += 1
            if py == want:
                exact_py += 1
        if verdict == "diverge":
            declared = DIVERGENT.get(label.split()[0])
            line = "%s\n  text: %r\n  %s" % (label, text, detail)
            if declared:
                line += "\n  DECLARED: %s (%s is right)" % (declared[1], declared[0])
            else:
                bad.append(line)
            print(("DECLARED DIVERGENCE  " if declared else "DIVERGENCE  ") + line)
            print()

    print("%d case(s): %d agree, %d both-refuse, %d diverge (%d declared)"
          % (len(cases), counts["agree"], counts["both-refuse"], counts["diverge"],
             counts["diverge"] - len(bad)))
    print("EXACT over the %d printer-output case(s): sql %d/%d, py %d/%d"
          % (exact_checked, exact_sql, exact_checked, exact_py, exact_checked))
    if exact_checked == 0 or len(cases) == 0:
        print("FAIL: the sweep compared nothing")
        sys.exit(4)
    if bad:
        print("FAIL: %d undeclared divergence(s)" % len(bad))
        if args.strict_frag:
            # So a red run under this flag is not mistaken for a broken sweep. --strict-frag is a
            # DIAGNOSTIC and not the gate: it asks the two architectures to produce the same
            # fragment inside `cannot read <fragment>`, which neither claims to do. Measured in
            # Task 7: it is 2 of the 21 both-refuse cases, and both name the same SENTENCE. CI runs
            # this script without the flag.
            print("NOTE: --strict-frag compares the `cannot read` fragment, which the default run "
                  "deliberately does not. A divergence that is fragment-only is expected here; "
                  "read the sentences above to tell it from a real one.")
        sys.exit(1)
    print("OK: the two readings agree everywhere they are not declared to differ")
    sys.exit(0)


if __name__ == "__main__":
    main()
