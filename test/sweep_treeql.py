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
import hashlib
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
# THE FIVE SHAPES THE PLAN NAMES are a34-a37 (marked `(plan case 1)`..`(plan case 4)`) and b24/b25
# (`plan case 5`), each marked in place with the blind spot it probes. An earlier draft of this
# line cited "a19..a24 and b23", which MEASURED is wrong on every label -- a19 is a literal with a
# comma, a24 is has-and-not on one step, b23 is a bare combinator keyword. Same defect class as the
# stale line-number citations this file apologises for twice, so it is corrected and not dropped.
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
    # ---- R41: a `"..."` region in a raw body. NOT ONE of these carries an apostrophe, which is
    # what shows the cause was never "reads every `'` as a delimiter" but "knows nothing of `"..."`
    # regions". a45 was `b58` and sat in family B, where EXACT is not evaluated, until the review
    # measured that the printer emits it; a46 was driven by neither family.
    ("a45 comma inside a double-quoted identifier, WHERE", "[{\"where\": '\"a,b\" = 1'}]"),
    ("a46 comma inside a double-quoted identifier, ATTR", "[{attr: 'a = \"b,c\"'}]"),
    # the boundary: a LONE double quote is NOT a region and must stay one ordinary character -- a
    # region rule that accepted an unterminated `"` would swallow this text's closing parenthesis
    ("a47 lone double quote in a raw body", "[{\"where\": 'a = \"b'}]"),
    # a combinator keyword inside a region inside a group: the shape that HID the chain reader's own
    # defect, because a printed inner step's clause list is parenthesised, so the keyword is never
    # at chain depth 0 where that scan looks
    ("a48 combinator keyword inside a region in a group",
     "[{type: 'a', has: [{\"where\": '\"a CHILD b\" = 1'}]}]"),
    ("a49 region holding a paren, inside a group",
     "[{type: 'a', has: [{\"where\": '\"a ) b\" = 1'}]}]"),
]

# ----------------------------------------------------------------------------------------------
# FAMILY B: TEXT written by hand, where no IR is known by construction.
#
# WHICH OF THESE THE PRINTER CAN EMIT IS COMPUTED, NOT ASSERTED. This header used to read "No
# theorem quantifies over these -- the printer never emits most of them", and MEASURED that was
# false for at least one member: `(WHERE "a,b" = 1)` sat here and is exactly what
# `tree_steps([{"where": '"a,b" = 1'}])` prints. Because a family-B case was never counted in the
# EXACT line, a refusal of printer output was hiding in the family whose header said it could not
# be, and the gate understated the denominator it reports about itself. The sentence was doing the
# work a check should do, so `is_printer_output` now does it per case, every run, and the sweep
# FAILS on any member it finds -- such a case belongs in family A, where its IR is known by
# construction rather than recovered.
#
# What is left here is genuinely requirement 6's territory: tolerated input, and refusals.
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
    # ---- CLASS 1: R41, the splitter knowing nothing of `"..."` regions ---- CLOSED.
    #
    # FIVE ENTRIES STOOD HERE -- a40, a41, a42, a43 and b58 -- declared with this reason:
    #
    #   "NOT FIXED HERE, and the reason is a measurement rather than a preference: the macros' scan
    #    is a WINDOW SUM over one delimiter, which has a closed form. Tracking two delimiters that
    #    can nest needs sequential state ... so it is a recursive CTE or a list_reduce, inside a
    #    scalar macro that R22 already records a binder wall for."
    #
    # HALF OF THAT WAS TRUE AND STRONGER THAN IT CLAIMED: no window in the count family can compute
    # the prefix state, because the two delimiters' state maps generate a non-abelian group. THE
    # OTHER HALF WAS FALSE and had never been tested -- RE2 alternation inside one scalar call does
    # the sequential scan and binds in every shape R22 names. R41 is fixed in
    # sql/10_treeql.sql's tree_treeql_quote_mask, which carries both halves with the measurement.
    #
    # AND THE REASON NAMED THE WRONG CAUSE: it blamed the apostrophe. `(WHERE "a,b" = 1)` and
    # `(ATTR a = "b,c")` are printer output and failed with no apostrophe anywhere. The cause was
    # having no notion of a region at all.
    #
    # The five shapes are now a40-a43 and a45 in family A, and all five AGREE. Nothing is left of
    # this class, and this comment is what stands where the entries did -- a table that only ever
    # loses entries silently teaches the next reader nothing about why they were there.

    # ---- CLASS 2: the `groupparen` arm's R42 stand-down ----
    # An arm that asks tree_treeql_no_raw_body first stands down when it is FALSE, on the reasoning
    # that on mis-split raw-bodied text the fragment it would name is not evidence of the fault it
    # names. THIS READING NEEDS NO STAND-DOWN -- its scan does not lose its place on a raw body --
    # so it names the real cause, and that is where the two part.
    #
    # THE `parenless` HALF OF THIS CLASS WAS F2 AND IS FIXED, which is why b24/b25 are gone from
    # here. The `groupparen` arm was NOT touched: a different arm, its own R42 reason, and no
    # measurement behind lifting it. b57 is what keeps that visible rather than remembered.
    #
    # b57's SQL message moved once already, with F2's fix: it was `cannot read HAS WHERE a = 1` and
    # is now the `parenless` sentence, because `groupparen` stands down here and `parenless` now
    # fires first. Both refuse and both point at missing parentheses; the new one names the inner
    # step where the GROUP's own parentheses are what is missing, so it is less precise, not false.
    # It is not printer output, so R42's rule about never rejecting printer output is untouched.
    "b57": ("py",
            "no record: the groupparen arm's stand-down, the half of CLASS 2 still open",
            "both-refuse | sql:a step inside HAS/NOT needs a combinator or parentheses, so its "
            "clauses can be told from the next step's | py:HAS/NOT needs parentheses around its "
            "chain"),

    # ---- CLASS 3: a raw body's own top-level comma, with no enclosure ---- CLOSED in fix round 2.
    #
    # ONE ENTRY STOOD HERE, b55, and the sweep's own STALE check is what retired it -- the first
    # time that check has fired on a real fix rather than on a plant. Its reason had already been
    # corrected once: it said "unreachable from a legal predicate", which is TRUE about SQL
    # validity, and let that stand as "no theorem over printer output quantifies over it", which
    # does not follow. The COMPUTED denominator put the text in the EXACT count and convicted the
    # declaration; the coordinator then ruled it a defect rather than a second F3, on the
    # discriminator that `(b = 2)` alone is REFUSED -- so exactly one reading of the text is valid,
    # where F3 has two and no parser can choose.
    #
    # tree_treeql_clause_parts gives a raw body its own separators back, by SPAN rather than by
    # re-joining, because the printer emits `(WHERE a = 1,b = 2)` verbatim and a canonical `, `
    # would break NORMALISING on it. The second obstacle I reported against doing this -- that it
    # moves generic fragments and the refusal set's `body_is_clauses` reads them -- turned out to be
    # an artifact of the COARSER rule I had sketched, not of the fix: merging only within a
    # RAW-bodied group leaves all four of those refusals byte-identical. MEASURED, and recorded in
    # test/sql/48_treeql_parse.test beside the fix.
    #
    # ONE ENTRY IS LEFT IN THE WHOLE TABLE, b57, and it is NOT an EXACT failure -- it is a refusal
    # WORDING that the two readings name differently on HAND-WRITTEN text. So `sql == py` now holds
    # on every one of the 62 printer-output cases, which is the state this sweep was built to reach;
    # what remains is a difference about how to describe a text neither reading accepts.
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


def signature(sql, py):
    """A divergence's CONTENT, as one comparable line, so a DIVERGENT entry pins WHAT the two
    readings disagree about and not merely THAT they do.

    WHY THIS EXISTS. The entries used to key on the case LABEL alone, so a declared case could
    regress to a DIFFERENT disagreement and stay declared: `a40` could have started returning a new
    wrong IR and the sweep would have said nothing. A declaration that survives any change to the
    thing it declares is not a declaration.

    IT IS LEGIBLE FIRST AND EXACT SECOND. The refusal classes and the row counts read as English,
    so the table states its claim without anything being run. The digest is appended ONLY where
    both sides accept, because that is the one case the readable part cannot discriminate -- two
    different wrong IRs of the same shape would sign alike. It is deliberately opaque: its job is
    to force a human decision when the content moves, not to describe the move.
    """
    sql_ref, py_ref = isinstance(sql, tuple), isinstance(py, tuple)
    if sql_ref and py_ref:
        return "both-refuse | sql:%s | py:%s" % (refusal_class(sql[1]), refusal_class(py[1]))
    if sql_ref:
        return "sql-refuses:%s | py-accepts:%d rows" % (refusal_class(sql[1]), len(py))
    if py_ref:
        return "sql-accepts:%d rows | py-refuses:%s" % (len(sql), refusal_class(py[1]))
    return "both-accept-different-ir | sql:%d rows | py:%d rows | sql-digest:%s" % (
        len(sql), len(py), hashlib.sha256(repr(sql).encode()).hexdigest()[:10])


def is_printer_output(con, text, py):
    """Is this text something tree_selector_to_treeql can emit? COMPUTED, never declared.

    WHY IT IS COMPUTED. Family B's header used to say "the printer never emits most of them", and
    MEASURED that was false for at least one member: `(WHERE "a,b" = 1)` is exactly what
    `tree_steps([{"where": '"a,b" = 1'}])` prints. A family-B case is never counted in the EXACT
    line, so a refusal of printer output was hiding in the family whose header asserted it could
    not be there -- which made the gate understate the denominator it reports about itself. A
    classification that is recomputed every run cannot go stale the way that sentence did.

    THE TEST. If the Python reading accepts the text, and PRINTING that reading reproduces the text
    byte for byte, then the text is in the printer's image and the Python's IR is a preimage of it.
    That is decidable here and needs no guess about which IR was meant. It also makes EXACT
    meaningful for such a case: the text IS print(ir) for that ir, so `sql == py` on it is the
    exact theorem for the macros, which is what the sweep already measures.

    WHAT IT CANNOT DO: prove a text is NOT printer output. A text the Python refuses, or whose
    reprint differs, is merely not shown to be printer output by this route -- so the denominator
    it produces is a LOWER BOUND, and the sweep prints it as one.
    """
    if isinstance(py, tuple):
        return False
    try:
        lit = treeql_parser.to_sql([dict(zip(FIELDS, r)) for r in py])
        return con.execute("SELECT tree_selector_to_treeql(" + lit + ") = "
                           + sql_str(text)).fetchone()[0] is True
    except Exception:
        return False


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
    matched = {}            # label -> the signature actually observed, for every DIVERGING case
    agreed = set()          # labels that did NOT diverge, so a declaration for them is stale
    printer_output_in_b = []  # family-B cases the printer CAN emit, found by computation
    for label, text, want in cases:
        key = label.split()[0]
        sql, py = rows_from_sql(con, text), rows_from_py(text)
        verdict, detail = compare(sql, py, args.strict_frag)
        counts[verdict] += 1
        # THE DENOMINATOR IS COMPUTED, not taken from which list the case sits in. A family-A case
        # is printer output by construction and carries the IR it was printed from; a family-B case
        # is printer output if it reprints to itself through the second reading, and then the
        # second reading's IR is a preimage, so EXACT for the macros is `sql == py`.
        if want is not None:
            exact_checked += 1
            exact_sql += (sql == want)
            exact_py += (py == want)
        elif is_printer_output(con, text, py):
            # A FAMILY-B CASE THAT IS PRINTER OUTPUT IS STILL IN THE DENOMINATOR. It is not moved
            # into family A, and that is deliberate rather than lazy: family A is keyed by an IR
            # literal, and several of these shapes have no IR tree_steps will build -- the empty
            # FIRST step and the alias-only step are both printer output that the constructor
            # refuses to construct. Relocating them would mean hand-building IR; evaluating EXACT
            # on them where they sit costs nothing and cannot be forgotten.
            printer_output_in_b.append(label)
            exact_checked += 1
            exact_sql += (sql == py)
            exact_py += 1
        if verdict == "diverge":
            matched[key] = signature(sql, py)
            declared = DIVERGENT.get(key)
            line = "%s\n  text: %r\n  %s" % (label, text, detail)
            if declared:
                line += "\n  DECLARED: %s (%s is right)" % (declared[1], declared[0])
            else:
                bad.append(line)
            print(("DECLARED DIVERGENCE  " if declared else "DIVERGENCE  ") + line)
            print()
        else:
            agreed.add(key)

    # ------------------------------------------------------------------------------------------
    # THE DECLARATIONS ARE CHECKED IN BOTH DIRECTIONS, which is what makes them declarations.
    #
    # They were checked in one. `DIVERGENT.get` was consulted ONLY inside the diverge branch, and
    # the "(N declared)" figure was computed as `diverge - len(undeclared)`, so an entry that
    # matched nothing contributed to nothing. MEASURED by planting, before this was written: an
    # entry for a case that AGREES (`a01`) and an entry naming a label no case carries (`zz99`)
    # each left the sweep at exit 0 with output byte-identical to the unplanted run. On the R41 fix
    # the sweep printed OK with FIVE entries stale. A mute with no expiry is not a gate -- it is
    # the exact failure this sweep exists to catch, sitting inside the sweep.
    #
    # Three ways a declaration can be wrong, and all three are loud and non-zero now:
    #   UNKNOWN  the label matches no case at all -- a typo, or a case that was renamed or deleted
    #   STALE    the case no longer diverges, so the entry is a fix that was never swept up
    #   MOVED    the case still diverges but about something ELSE than the entry says
    # ------------------------------------------------------------------------------------------
    # THE KNOWN-LABEL SET COMES FROM BOTH FAMILIES, never from the cases this RUN selected.
    # MEASURED, by the check immediately after it was written: with `--quick`, which loads family A
    # only, b55 and b57 were reported as naming no case -- so the new gate failed a correct
    # declaration because of the mode it ran in. A label is UNKNOWN only when no case anywhere
    # carries it; a declaration whose case simply did not run this time is neither unknown nor
    # stale, because `agreed` holds only cases that actually ran. The cost, stated: `--quick`
    # cannot detect a STALE family-B declaration. The full run is the gate CI runs.
    labels = ({lbl.split()[0] for lbl, _ir in IR_CASES}
              | {lbl.split()[0] for lbl, _t in TEXT_CASES})
    unknown = sorted(k for k in DIVERGENT if k not in labels)
    stale = sorted(k for k in DIVERGENT if k in agreed)
    moved = sorted((k, DIVERGENT[k][2], matched[k]) for k in DIVERGENT
                   if k in matched and len(DIVERGENT[k]) > 2 and DIVERGENT[k][2] != matched[k])
    for k in unknown:
        print("UNKNOWN DECLARATION  %s names no case in this sweep.\n"
              "  Its stated reason was: %s\n"
              "  Either the case was renamed or deleted, or the label is a typo. Remove the entry "
              "or fix the label.\n" % (k, DIVERGENT[k][1]))
    for k in stale:
        print("STALE DECLARATION  %s is declared divergent but now AGREES.\n"
              "  Its stated reason was: %s\n"
              "  That is a fix landing. Delete the entry -- a declaration left behind a fix is how "
              "this table becomes a parking lot.\n" % (k, DIVERGENT[k][1]))
    for k, want_sig, got_sig in moved:
        print("MOVED DECLARATION  %s still diverges, but about something else than it declares.\n"
              "  declared: %s\n  observed: %s\n"
              "  The entry pins the CONTENT of the disagreement, so this is a behaviour change "
              "that needs a decision, not a resignature.\n" % (k, want_sig, got_sig))

    print("%d case(s): %d agree, %d both-refuse, %d diverge (%d declared, %d undeclared)"
          % (len(cases), counts["agree"], counts["both-refuse"], counts["diverge"],
             counts["diverge"] - len(bad), len(bad)))
    print("EXACT over the %d printer-output case(s) -- a LOWER BOUND, see is_printer_output: "
          "sql %d/%d, py %d/%d"
          % (exact_checked, exact_sql, exact_checked, exact_py, exact_checked))
    if printer_output_in_b:
        print("  of which %d came from family B, found to be printer output by computation: %s"
              % (len(printer_output_in_b),
                 ", ".join(l.split()[0] for l in printer_output_in_b)))
    if exact_checked == 0 or len(cases) == 0:
        print("FAIL: the sweep compared nothing")
        sys.exit(4)
    if unknown or stale or moved:
        print("FAIL: %d unknown, %d stale, %d moved declaration(s)"
              % (len(unknown), len(stale), len(moved)))
        sys.exit(1)
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
