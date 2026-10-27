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
    then before combinator keywords, and asks a per-part reader what each fragment is. The scan
    knows nothing about which clause kind it is inside, so a raw body's separators are put back
    AFTER the cut, by tree_treeql_clause_parts. ("Depth and `inside a quote` come from two window
    functions" stood here and is stale: since R41 it is ONE window over tree_treeql_quote_mask.)
  * test/treeql_parser.py DESCENDS. It reads a keyword, then reads that keyword's body by the rule
    for its kind -- a literal body stops at its closing quote, a raw body runs to the next
    separator that is followed by a clause keyword -- so the scan always knows what it is inside.

Neither is a transcription of the other, and the shapes where they disagree are listed in
DIVERGENT below with the record that pins each one.

SHARED RULES, AND WHAT THEY COST THIS INSTRUMENT. Read this before reading the numbers below.

A differential is evidence because two independent readings can only agree by both being right.
That argument weakens exactly as far as the two readings share a rule, and THREE TIMES in this
task a fix gave them one:

  * the QUOTE MASK. Both readings now treat `'...'` and `"..."` as regions and both pair them
    globally, so an unpaired quote in two different raw bodies pairs across a real separator in
    BOTH. MEASURED: before that fix the macros and this reading DISAGREED on five such shapes, and
    the differential caught them; after it they AGREE, and it cannot.
  * the RAW-BODY MERGE. Both put a raw body's own separators back by span, and both cut the body
    when the continuation opens a clause keyword. MEASURED: the KNOWN_EXACT_FAILURES table below
    now holds 14 entries, and 12 of them are this rule being wrong in BOTH readings at once --
    k01-k13 less k12, whose cause is the mask instead. `k13` is the newest and the clearest: the
    text has exactly ONE constructible preimage, so a reader CAN choose, and both readings choose
    the same wrong one. The count said "ten shapes" here and in the EXACT paragraph below.
  * the REFUSAL PRIORITY ORDER and the `min(fragment)` tie-break, transcribed rather than derived
    -- which this file has always said, and which is the same cost in a smaller place.
  * THE `unbalanced` STAND-DOWN -- added as a rule the two readings DO NOT yet share, so the note
    is not silent about where the instrument is pointed next. tree_treeql_balanced stands down on
    raw-bodied text and test/treeql_parser.py does not, so the macros ACCEPT `(WHERE a = 1))` --
    printer output -- and the second reading refuses it. No case drives that class yet; the
    measurement and why the guard is not landed are in test/treeql_parser.py beside the check.

So the honest reading of a green run is: the two readings agree, AND where they share a rule that
agreement is not independent evidence. What still carries weight is EXACT, because it compares a
reading against an IR built by a third thing -- the constructor -- rather than against the other
reading. That is why the EXACT line is printed separately from the agreement counts, why its
independent half is reported apart from its construction-true half, and why KNOWN_EXACT_FAILURES
exists at all: 14 of the shapes below are cases where BOTH readings fail and nothing but EXACT
can say so. That figure moves, so it is also PRINTED by every run -- and the printed one is the
measurement; this sentence is a reader's bearing and said "ten" until the final-review fix round.

THIS LIMIT IS NOT REMOVED AND CANNOT BE REMOVED BY THIS METHOD. Two readings that must agree on
printer output will converge on a shared rule wherever the grammar is ambiguous, because there is
only one right answer to converge on and the printer does not disambiguate. Naming it is the
remedy available here; a second INDEPENDENT oracle -- the C++ front-end, when it exists -- is the
remedy that is not.

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
    # ---- THE KEYWORD-CONTINUATION CLASS. Printer output whose raw body continues after a comma
    # with text that OPENS a clause or group. These are KNOWN EXACT FAILURES, declared below in
    # KNOWN_EXACT_FAILURES, and they are cases rather than prose so the EXACT line counts them.
    ("k01 where, continuation opens TYPE", "[{\"where\": 'a = 1, TYPE b'}]"),
    ("k02 where, continuation opens WHERE", "[{\"where\": 'a = 1, WHERE b'}]"),
    ("k03 where, continuation opens CLASS", "[{\"where\": 'a = 1, CLASS x'}]"),
    ("k04 where, continuation opens ID", "[{\"where\": 'a = 1, ID x'}]"),
    ("k05 where, continuation opens PSEUDO", "[{\"where\": 'a = 1, PSEUDO p'}]"),
    ("k06 where, continuation opens a LOWERCASE keyword", "[{\"where\": 'a = 1, type x'}]"),
    ("k07 attr, continuation opens TYPE", "[{attr: 'a = 1, TYPE b'}]"),
    ("k08 where, two continuations then a keyword", "[{\"where\": 'a = 1, b = 2, TYPE c'}]"),
    ("k09 where, continuation opens HAS", "[{\"where\": 'a = 1, HAS ( TYPE ''b'' )'}]"),
    ("k10 where, continuation opens NOT", "[{\"where\": 'a = 1, NOT ( TYPE ''b'' )'}]"),
    # ---- THE EMPTY SELECTOR. It was `b29`, a family-B case with the text '', and it fell OUT of
    # the denominator because is_printer_output asks the PYTHON and the Python refuses ''. So the
    # one case this task's own both-refuse audit had just discovered to be printer output was
    # counted nowhere, and the EXACT line's "enumerated rather than excluded" was false on the
    # sweep's own case list. As a family-A case it enters the denominator BY CONSTRUCTION -- the
    # generator prints it from IR -- instead of through the Python's acceptance, which is the whole
    # point: the admission rule cannot find a case both readings refuse.
    ("a50 the empty selector", "[{comb: NULL}]"),
    # ---- A GENUINE COLLISION IN THE ATTR CONTINUATION, as a PAIR so it is legible as one. k07's
    # declaration used to claim its own case was a collision; it is not (see KNOWN_EXACT_FAILURES).
    # These two are: the same bytes from two constructible IRs. a51 is the preimage that SURVIVES.
    ("a51 attr then WHERE, the multi-part preimage", "[{attr: 'a = 1', \"where\": 'b'}]"),
    ("k11 attr then WHERE, the one-part preimage", "[{attr: 'a = 1, WHERE b'}]"),
    # ---- THE OTHER COLLISION CLASS, so both are CASES and not one case plus a paragraph. The note
    # at the head of KNOWN_EXACT_FAILURES names two classes that resolve OPPOSITE ways, and only
    # k11/a51 was driven here: the unpaired-`"` class was described in prose and in file 48, where
    # EXACT is not counted. So the sweep's own EXACT figure said nothing about it.
    #
    # The two preimages of `(ATTR a = "b, WHERE c = "d)` -- MEASURED, the same bytes:
    #     [{attr: 'a = "b, WHERE c = "d'}]            the ONE-part reading,   EXACT TRUE
    #     [{attr: 'a = "b', "where": 'c = "d'}]       the MULTI-part reading, EXACT FALSE  <- k12
    # The mask BLANKS the separator, because the unpaired `"` in the attr body pairs with the one
    # in the where body and everything between them is masked, so both readings see ONE part. That
    # is the reverse of k11/a51, where the separator stays visible and the multi-part preimage is
    # the one that survives. Only the FAILING preimage is a case here: the surviving one is EXACT
    # true, so it would add a passing case and no coverage of the failure.
    ("k12 unpaired double quote across a separator, the multi-part preimage",
     "[{attr: 'a = \"b', \"where\": 'c = \"d'}]"),
    # ---- THE DOCUMENTED COMMA LIMIT, AS A CASE. `b09` below carries this exact text by hand, and
    # the EXACT line said nothing about it: b09 is admitted into the denominator on the PYTHON's IR
    # as the witness, and that witness is the three-clause reading, which the CONSTRUCTOR cannot
    # build. Printing a non-canonical witness reproduces the text, so the case was admitted and
    # scored `sql == py` -- both readings take the same wrong reading, so it passed. A differential
    # cannot see a defect its readings share, and this is a live instance of the SHARED RULES note
    # above. Driven from family A, the IR comes from the constructor and the failure is counted.
    #
    # AND THE TEXT IS NOT A COLLISION -- MEASURED, under duckdb 1.5.5:
    #     tree_steps([{type: 'x', "where": 'a = 1, PSEUDO ''p'''}])  prints
    #       (TYPE 'x', WHERE a = 1, PSEUDO 'p')          <- this case's text
    #     tree_steps([{type: 'x', "where": 'a = 1', pseudo: 'p'}])   prints
    #       (TYPE 'x', PSEUDO 'p', WHERE a = 1)          <- DIFFERENT BYTES
    # `pseudo` is slot 5 and `where` slot 6, so the printer emits PSEUDO FIRST and the three-clause
    # IR cannot print this text. Among constructor-accepted IR the text has exactly ONE preimage --
    # this one -- so a reader CAN choose, and the parse that returns a `pseudo` node the original
    # never had is a WRONG parse rather than one horn of an ambiguity.
    ("k13 where, continuation opens PSEUDO after a TYPE clause -- b09's one constructible preimage",
     "[{type: 'x', \"where\": 'a = 1, PSEUDO ''p'''}]"),
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
# "sql" means the macros are right and this script's Python is wrong -- there are no ENTRIES of
# that kind, and the entry shape allows one so that a future divergence cannot be recorded without
# saying so. "py" means test/treeql_parser.py returns the answer the printer's own output requires
# and the macros do not.
#
# THAT DIRECTION IS NOT HYPOTHETICAL ANY MORE, and the table says none only because the class is
# UNDRIVEN. MEASURED, duckdb 1.5.5: `tree_steps([{"where": 'a = 1)'}])` prints `(WHERE a = 1))`,
# the macros parse it with EXACT true, and this script's Python refuses it as `unbalanced
# parentheses` -- a refusal of printer output, which the Global Constraint makes a defect. The same
# for `(ATTR a = 1))`. No case drives either, so no entry is needed and none exists; the fix is one
# guard in test/treeql_parser.py, held on a ruling, with the measurement beside the check there.
# An empty table row is not the same as an empty world, and this is the place that could have said
# so and did not.
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
    # WORDING that the two readings name differently on HAND-WRITTEN text. So `sql == py` holds on
    # every one of the 75 printer-output cases this run admits -- MEASURED at this commit, and the
    # figure the run PRINTS is the one to read; the number here said 62 and had gone stale. What
    # remains is a difference about how to describe a text neither reading accepts.
}


# ----------------------------------------------------------------------------------------------
# KNOWN EXACT FAILURES. Printer-output cases on which `parse(print(ir)) = ir` is FALSE and which
# are NOT fixed. They are declared here, and they are CASES rather than a comment, so the EXACT
# line counts them against the denominator instead of the project being able to say EXACT holds
# while they fail.
#
# THE RULING THEY REST ON, stated by the coordinator in fix round 3 and the reason these are
# counterexamples rather than exempt shapes:
#
#   EXACT quantifies over the PRINTER'S IMAGE: every text tree_selector_to_treeql can emit for IR
#   the ordinary constructor accepts. Whether a raw body is executable host SQL is a DIFFERENT
#   predicate and is not a term in either theorem.
#
# WHY THAT IS THE RIGHT SIDE and not merely the consistent one: the Global Constraint makes the
# printer the specification and conditions nothing on a body's semantics -- the printer passes raw
# bodies through without inspecting them. And the alternative is unimplementable HERE: narrowing
# EXACT to "bodies that are legal host SQL" would need the sweep to decide SQL validity, which
# needs the database that the second reading deliberately does not have. A qualification the
# instrument cannot evaluate is an escape hatch, not a qualification. `b55` was first declared
# under exactly that defence and then fixed, which rejected it in practice; this states it.
#
# THE CAUSE OF TWELVE OF THE FOURTEEN ENTRIES below is one thing -- k01-k11 and k13:
# tree_treeql_clause_parts decides a part is a new clause-list item by `tree_treeql_opener_re()`,
# so a raw body's continuation that BEGINS with a clause or group keyword is read as a new item and
# the body is cut. Fixing it needs the merge to know the SLOT ORDER of the clause kinds -- `where`
# is the last slot, so nothing but a group can follow a WHERE clause in printer output -- and the
# registry has NO ORDER COLUMN, which test/css_parser.py's own CLAUSE_SLOT exemption records from
# the other side.
#
# THE OTHER TWO HAVE THEIR OWN CAUSES, and each entry says so: `a50` is the EMPTY SELECTOR, already
# ruled IRREDUCIBLE -- no parser can recover a step from no characters -- and `k12` is the
# unpaired-`"` collision, which the slot order CANNOT fix because the mask removes the separator
# before the merge ever sees it. This sentence used to read "THE CAUSE of every entry below is one
# thing", which its own table contradicted in two rows.
#
# k08 IS HERE, at its own entry, and the sentence that said "k08 IS NOT HERE and that is
# deliberate" contradicted its own last clause three lines later. What is true of k08 is the rest
# of what that sentence said: it is the one shape in the class that REFUSES rather than returning a
# wrong IR, restored in fix round 3 because a silent wrong parse replacing a loud refusal is the
# worse of the two failures. It still fails EXACT, so it is declared, and its entry says refusal.
#
# WHICH PREIMAGE SURVIVES A COLLISION, AND WHY IT GOES BOTH WAYS. Two entries below sit on texts
# with TWO constructible preimages, and EXACT can hold for at most one. Which one survives depends
# on whether the clause SEPARATOR survives the quote mask, and the two known classes come out
# opposite ways -- same mechanism, two outcomes:
#
#   the UNPAIRED-QUOTE class (`k12` here since 9ff1e82, and in file 48 -- this line said "not a
#     case here", which that commit made false): the mask BLANKS the separator, because an unpaired
#     `"` in one raw body pairs with one in another and everything between is masked. The reader
#     therefore sees ONE part, and the ONE-PART preimage survives.
#   k11 / a51 here: the separator is VISIBLE and the continuation opens a clause keyword, so the
#     reader cuts there and sees TWO parts. The MULTI-PART preimage survives (a51 passes) and the
#     one-part preimage fails (k11).
#
# So "which reading a collision resolves to" is not a policy this parser applies; it is whatever the
# mask leaves visible. Worth knowing before reading either entry as a decision.
KNOWN_EXACT_FAILURES = {
    "k01": "raw body cut at `, TYPE` -- slot order would be needed to know a clause cannot follow",
    "k02": "raw body cut at `, WHERE`",
    "k03": "raw body cut at `, CLASS`",
    "k04": "raw body cut at `, ID`",
    "k05": "raw body cut at `, PSEUDO`",
    "k06": "raw body cut at a lowercase keyword -- the opener test is case-insensitive",
    "k07": "an ATTR body cut the same way, and SINGLE-PREIMAGE exactly like k01-k06. This entry "
           "used to call it a COLLISION on the reasoning that `attr` is slot 4 so a later clause "
           "can follow it. The reasoning is sound and was attached to the one continuation that "
           "cannot exhibit it: MEASURED, `type` is slot 1, so the two-clause IR prints "
           "`(TYPE 'b', ATTR a = 1)` -- DIFFERENT BYTES, in either key order -- and k07's text has "
           "ONE preimage. The continuations that DO exhibit it are WHERE and PSEUDO; the WHERE one "
           "is k11/a51 below",
    "k08": "REFUSES rather than returning a wrong IR -- restored in fix round 3. Still not EXACT",
    "k09": "both readings REFUSE: the continuation opens a GROUP, and a group after a raw body is "
           "legitimate, so the merge keeps it separate and the remainder reads as nothing",
    "k10": "the same for NOT",

    # NOT a keyword-continuation shape: the empty selector, moved here from family B by finding 1.
    "a50": "THE EMPTY SELECTOR. `tree_steps([{comb: NULL}])` builds two nodes and the printer emits "
           "'' for it, so '' IS printer output -- and both readings refuse it. A refusal of printer "
           "output is a defect under the Global Constraint, and this one is already ruled "
           "IRREDUCIBLE at sql/10_treeql.sql: no parser can recover a step from no characters. The "
           "ruling locates the gap in tree_steps, which builds a selector that cannot be read back; "
           "sql/06_selector.sql is frozen for this task, but its REPORTING is not, which is why "
           "this is a declared EXACT failure rather than a sentence in a commit body",

    # a COLLISION, and the direction is the reverse of the unpaired-quote class -- see the note at
    # the head of this table.
    "k11": "A GENUINE COLLISION, unlike k07. `(ATTR a = 1, WHERE b)` is printed by BOTH "
           "`[{attr: 'a = 1, WHERE b'}]` and `[{attr: 'a = 1', \"where\": 'b'}]` -- same bytes, "
           "measured -- because `where` is slot 6 and so CAN follow an attr clause. EXACT can hold "
           "for at most one preimage; the MULTI-part one survives (a51 passes) and this one fails. "
           "`(ATTR a = 1, PSEUDO 'p')` is the same collision and is not a separate case",

    # the UNPAIRED-QUOTE class, which the note above describes and which no case drove until now.
    "k12": "THE UNPAIRED-`\"` COLLISION, and the opposite resolution to k11. `(ATTR a = \"b, WHERE "
           "c = \"d)` is printed by BOTH `[{attr: 'a = \"b', \"where\": 'c = \"d'}]` (this case) and "
           "`[{attr: 'a = \"b, WHERE c = \"d'}]` -- same bytes, measured. The mask pairs the two "
           "unpaired `\"` across the separator and blanks it, so both readings see ONE part: the "
           "ONE-part preimage survives (measured EXACT true) and this MULTI-part one fails. Not "
           "fixable by the slot order k01-k07 want, because the separator is not visible to the "
           "merge at all -- the mask removed it before the merge ran",

    # the 14th member of the k01-k07 class, and the one the EXACT line used to score as a PASS.
    "k13": "NOT A COLLISION, and the three documents that called it one -- file 48, "
           "test/treeql_parser.py and the plan -- are corrected in this "
           "round. `(TYPE 'x', WHERE a = 1, PSEUDO 'p')` has exactly ONE constructor-accepted "
           "preimage -- this case -- because `pseudo` is slot 5 and `where` slot 6, so the "
           "three-clause IR prints `(TYPE 'x', PSEUDO 'p', WHERE a = 1)`, DIFFERENT BYTES, "
           "measured. The parse cuts the raw body at `, PSEUDO` and returns a `pseudo` node the "
           "original never had, so a reader CAN choose here and this one chooses wrong -- a "
           "SILENT WRONG PARSE and not one horn of an ambiguity. Blocked on exactly what k01-k07 "
           "are blocked on: the merge would need the clause kinds' SLOT ORDER to know that "
           "nothing but a group can follow a WHERE clause in printer output, and the registry has "
           "NO ORDER COLUMN. Fixing one member of the class while its siblings stay parked would "
           "make their entries wrong about why they are parked, so this is declared with them. "
           "`b09` is the same TEXT, written by hand, and is no longer admitted to the EXACT "
           "denominator: the witness that admitted it is this text's NON-CANONICAL reading -- see "
           "is_printer_output",
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


def steps_literal(rows):
    """The tree_steps ARGUMENT that would build these IR rows, as SQL text -- or None when this
    reconstruction cannot express the shape.

    It exists for one question, asked by is_printer_output below: is a witness IR the IR the
    CONSTRUCTOR builds, or merely one the printer can print? treeql_parser.to_sql writes node rows
    directly and so bypasses tree_steps entirely, which is what let a non-canonical witness admit a
    case. Handing the rows back to tree_steps is the only oracle here for "canonical", because
    canonical means nothing more or less than "what tree_steps builds".

    NONE RATHER THAN A GUESS. A row kind this does not know, a chain whose child is not a step, or
    a group it cannot descend all answer None, and the caller then reports the case as UNCHECKED
    instead of admitting it. An attr body is rebuilt as `value op arg` with single spaces, which
    need not be the printer's spacing -- it does not have to be, because the comparison is against
    the witness ROWS and the constructor re-splits the body it is given.
    """
    kids = {}
    for r in rows:
        kids.setdefault(r["parent_id"], []).append(r)
    roots = [r for r in rows if r["kind"] == "selector"]
    if len(roots) != 1:
        return None

    def key(k):
        return '"%s"' % k if k in ("where", "not", "as") else k

    def chain(parent_id):
        out = []
        for s in kids.get(parent_id, []):
            if s["kind"] != "step":
                return None
            one = step(s)
            if one is None:
                return None
            out.append(one)
        return "[" + ", ".join(out) + "]"

    def step(s):
        # NO CLAUSE-KIND VOCABULARY IS WRITTEN OUT HERE, and that is a requirement rather than a
        # style: scripts/check_vocabulary_single_source.py refuses a second copy of the registry's
        # vocabulary at any site that could read the registry, and this script HAS a connection.
        # Listing the five plain-value kinds failed that lint -- measured, it did -- so the kinds
        # are told apart by SHAPE instead: a group has children, an attr is split into value/op/arg,
        # and every other clause carries its body in `value`. A clause kind added to the registry
        # therefore needs no line here, which is the same property reading the registry would give.
        # A GROUP is recognised by having CHILDREN -- its chain of steps -- which is why no group
        # vocabulary is written out either. An empty group has none, so it falls through to the
        # value branch, answers None and is reported UNCHECKED; tree_steps refuses to build one.
        fields = []
        for c in kids.get(s["node_id"], []):
            if kids.get(c["node_id"]):
                inner = chain(c["node_id"])
                if inner is None:
                    return None
                fields.append("%s: %s" % (key(c["kind"]), inner))
            elif c["op"] is not None or c["arg"] is not None:
                body = " ".join(x for x in (c["value"], c["op"], c["arg"]) if x is not None)
                fields.append("%s: %s" % (key(c["kind"]), sql_str(body)))
            elif c["value"] is not None:
                fields.append("%s: %s" % (key(c["kind"]), sql_str(c["value"])))
            else:
                return None
        if s["op"] is not None:
            fields.append("comb: %s" % sql_str(s["op"]))
        if s["alias"] is not None:
            fields.append('"as": %s' % sql_str(s["alias"]))
        # a step with nothing at all is the EMPTY step, which `a50` builds as `{comb: NULL}`
        return "{" + ", ".join(fields or ["comb: NULL"]) + "}"

    return chain(roots[0]["node_id"])


ADMITTED = ""           # is_printer_output's verdict for a case that ENTERS the EXACT denominator


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

    AND THE WITNESS MUST BE CANONICAL, which this used to leave unasked -- the hole `k13` was found
    through. The reprint proves the text is print(W) for the witness W, and nothing more. If W is
    not the IR the CONSTRUCTOR builds, the text may have a DIFFERENT, constructor-accepted preimage
    that the readings are getting wrong, and `sql == py` scored against W says nothing about it.
    MEASURED, duckdb 1.5.5, on `b09`:

        the witness        [{type: 'x', "where": 'a = 1', pseudo: 'p'}]-shaped rows, which
                           tree_steps prints as `(TYPE 'x', PSEUDO 'p', WHERE a = 1)`
        the text           `(TYPE 'x', WHERE a = 1, PSEUDO 'p')`, whose ONE constructible
                           preimage is k13's one-clause WHERE body -- on which EXACT is FALSE

    So the case was admitted, both readings took the same wrong reading, `sql == py` held, and it
    counted among the passes. The headline "all declared" was a property of the case list.

    THE ORACLE IS tree_steps, because canonical means what tree_steps builds and nothing else:
    steps_literal above rebuilds the constructor's argument from the witness rows and the rows that
    come back are compared field for field, node ids included. Three verdicts, and only the first
    is admitted -- a case this cannot CHECK is named rather than admitted, which is the rule the
    old `return False` had no way to express.

    MEASURED, the whole corpus, duckdb 1.5.5: of the 13 cases this admitted before, ELEVEN
    reconstruct to rows tree_steps reproduces exactly, and TWO do not -- `b09` above, and `b53`,
    `(TYPE 'a', HAS ( (TYPE 'b') (TYPE 'c') ))`, whose witness gives the group's inner steps a NULL
    combinator. tree_steps coalesces those to `desc` (measured: with NULL, with 'desc' and with
    'child' it prints `DESCENDANT` keywords and never this text), so b53's text is printer output
    of HAND-BUILT IR only and has no constructible preimage at all. That is a weaker fault than
    b09's -- nothing is being read wrong -- but the admission was unsound for the same reason, so
    it leaves the denominator too and is named in the run's output.
    """
    if isinstance(py, tuple):
        return "py refuses"
    rows = [dict(zip(FIELDS, r)) for r in py]
    try:
        lit = treeql_parser.to_sql(rows)
        same = con.execute("SELECT tree_selector_to_treeql(" + lit + ") = "
                           + sql_str(text)).fetchone()[0] is True
    except Exception:
        return "py accepts but its reprint differs"
    if not same:
        return "py accepts but its reprint differs"
    arg = steps_literal(rows)
    if arg is None:
        return "py reprints it, but canonicality is UNCHECKED: no tree_steps argument for this IR"
    try:
        built = [tuple(r) for r in con.execute(
            "SELECT " + ", ".join(FIELDS) + " FROM (SELECT unnest(tree_steps(" + arg
            + "), recursive := true))").fetchall()]
    except Exception as e:
        return ("py reprints it, but canonicality is UNCHECKED: tree_steps refused the "
                "reconstruction (%s)" % str(e).split("\n")[0])
    if built != [tuple(r) for r in py]:
        return "py reprints it, but its IR is NOT CANONICAL: tree_steps builds different rows"
    return ADMITTED


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true",
                    help="the printer-output cases only")
    ap.add_argument("--both-refuse-audit", action="store_true",
                    help="list every both-refuse case so a human can decide whether it is "
                         "printer output -- the admission rule cannot decide it")
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
    indep_sql = indep_py = indep_n = 0      # family A: scored against a SEPARATELY constructed IR
    adm_sql = adm_n = 0                     # family B: admitted by the Python's own reprint
    both_refuse_cases = []                  # for --both-refuse-audit
    excluded = []                           # family-B cases NOT in the denominator, with why
    exact_fail = []                         # family-A cases where EXACT is FALSE for either side
    bad = []
    matched = {}            # label -> the signature actually observed, for every DIVERGING case
    agreed = set()          # labels that did NOT diverge, so a declaration for them is stale
    printer_output_in_b = []  # family-B cases the printer CAN emit, found by computation
    unsound_witness = []      # family-B cases a NON-CANONICAL or UNCHECKED witness would admit
    for label, text, want in cases:
        key = label.split()[0]
        sql, py = rows_from_sql(con, text), rows_from_py(text)
        verdict, detail = compare(sql, py, args.strict_frag)
        counts[verdict] += 1
        # THE DENOMINATOR IS COMPUTED, not taken from which list the case sits in. A family-A case
        # is printer output by construction and carries the IR it was printed from; a family-B case
        # is printer output if it reprints to itself through the second reading, and then the
        # second reading's IR is a preimage, so EXACT for the macros is `sql == py`.
        #
        # ASKED ONCE. The two branches below used to call is_printer_output separately, so every
        # family-B case paid for the reprint twice -- it parses the text with the Python, builds an
        # IR literal from it and asks the database to print it. The `want is None` conjunct keeps
        # the short-circuit the second branch had: a family-A case never reaches the call at all.
        why_not = ADMITTED if want is not None else is_printer_output(con, text, py)
        printer_output = want is None and why_not == ADMITTED
        if want is not None:
            exact_checked += 1
            indep_n += 1
            indep_sql += (sql == want)
            indep_py += (py == want)
            exact_sql += (sql == want)
            exact_py += (py == want)
            if sql != want or py != want:
                exact_fail.append((key, label, text, sql == want, py == want))
        elif not printer_output:
            # ROW B's CHECK, AND IT RUNS EVERY TIME. A family-B case can leave the denominator
            # FOUR ways and the first two used to be silent: the Python refuses, the Python accepts
            # and its reprint differs, the reprint holds but the witness is NOT CANONICAL, or the
            # reprint holds and canonicality cannot be checked. Finding 1 of the task review was
            # the first -- `''` is printer output, the Python refuses it, and the case was counted
            # nowhere while the gate printed "enumerated rather than excluded"; the third is
            # k13/b09. is_printer_output names which, so the question "is any of these printer
            # output, and is any of them admitted on the wrong witness?" is asked of the gate
            # instead of of a reader's memory.
            excluded.append((label, text, why_not))
            if "CANONICAL" in why_not or "UNCHECKED" in why_not:
                unsound_witness.append((label, why_not))
        if printer_output:
            # A FAMILY-B CASE THAT IS PRINTER OUTPUT IS STILL IN THE DENOMINATOR. It is not moved
            # into family A, and that is deliberate rather than lazy: family A is keyed by an IR
            # LITERAL, which is a text a person writes, while what a family-B case has is ROWS --
            # relocating one means hand-writing the literal that builds those rows and keeping the
            # two in step. Evaluating EXACT on them where they sit costs nothing and cannot be
            # forgotten. (The reason that stood here was that "several of these shapes have no IR
            # tree_steps will build -- the empty FIRST step and the alias-only step". MEASURED
            # FALSE by the canonicality check added below it: `b14`'s empty first step rebuilds as
            # `[{comb: NULL}, {type: 'b', comb: 'child'}]` and `b17`'s alias-only step as
            # `[{"as": 'x'}]`, and tree_steps builds both, row for row. The shapes the constructor
            # really does refuse are b53's NULL combinator inside a group -- and that one is no
            # longer admitted.)
            printer_output_in_b.append(label)
            exact_checked += 1
            adm_n += 1
            adm_sql += (sql == py)
            exact_sql += (sql == py)
            # CONSTRUCTION-TRUE, NOT A CONFIRMATION. The admission rule admits this text only
            # because the Python already reprinted it, so the Python's IR IS the preimage and
            # `py == want` cannot fail here. It is counted so the denominator is whole, and
            # reported separately so it is never read as 13 more confirmations of the Python.
            exact_py += 1
        if verdict == "both-refuse":
            both_refuse_cases.append((label, text, refusal_class(sql[1]), refusal_class(py[1])))
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
    # KNOWN_EXACT_FAILURES gets the SAME discipline as DIVERGENT, for the same reason: a
    # declaration that outlives the thing it declares is a mute. An EXACT failure with no entry
    # FAILS; an entry whose case now passes, or whose label names nothing, is LOUD.
    ef_keys = {k for k, _l, _t, _a, _b in exact_fail}
    ef_undeclared = sorted((k, l) for k, l, _t, _a, _b in exact_fail
                           if k not in KNOWN_EXACT_FAILURES)
    ef_unknown = sorted(k for k in KNOWN_EXACT_FAILURES if k not in labels)
    ef_stale = sorted(k for k in KNOWN_EXACT_FAILURES if k in labels and k not in ef_keys)
    for k, l in ef_undeclared:
        print("UNDECLARED EXACT FAILURE  %s\n"
              "  parse(print(ir)) != ir for a printer-output case, and nothing declares it. Fix "
              "it, or add a KNOWN_EXACT_FAILURES entry saying why not.\n" % l)
    for k in ef_unknown:
        print("UNKNOWN EXACT-FAILURE DECLARATION  %s names no case in this sweep.\n"
              "  Its stated reason was: %s\n" % (k, KNOWN_EXACT_FAILURES[k]))
    for k in ef_stale:
        print("STALE EXACT-FAILURE DECLARATION  %s is declared a known EXACT failure but now "
              "PASSES.\n  Its stated reason was: %s\n  That is a fix landing. Delete the entry.\n"
              % (k, KNOWN_EXACT_FAILURES[k]))
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

    if args.both_refuse_audit:
        # THE ONE THING THE ADMISSION RULE CANNOT TELL YOU. A both-refuse case leaves the
        # denominator SILENTLY: the Python refuses, so no preimage can be exhibited, so
        # is_printer_output answers false -- and it answers false identically for "malformed text
        # both readings correctly refuse" and for "printer output both readings wrongly refuse".
        # The second is a defect under the Global Constraint. The sweep cannot separate them, so
        # it lists them instead of pretending to, and a human decides once.
        print("\nBOTH-REFUSE AUDIT -- %d case(s). The admission rule CANNOT decide whether any of"
              " these is printer output;\nthese are listed so the question is asked rather than"
              " assumed. A refusal of printer output is a defect.\n" % len(both_refuse_cases))
        for label, text, a, b in both_refuse_cases:
            print("  %s\n    text: %r\n    sql: %s\n    py : %s" % (label, text, a, b))
        print()
        print("EXCLUDED FROM THE EXACT DENOMINATOR -- %d family-B case(s). is_printer_output needs"
              " the Python to\naccept AND reprint the text, so these are not SHOWN to be printer"
              " output; that is not the same as\nbeing shown NOT to be. Any of them that IS"
              " printer output belongs in family A, where its IR is\nknown by construction --"
              " which is how `a50` got there.\n" % len(excluded))
        for label, text, why in excluded:
            print("  %-52s %-34s %s" % (label, repr(text), why))
        print()
    print("%d case(s): %d agree, %d both-refuse, %d diverge (%d declared, %d undeclared)"
          % (len(cases), counts["agree"], counts["both-refuse"], counts["diverge"],
             counts["diverge"] - len(bad), len(bad)))
    print("EXACT over the %d printer-output case(s) -- a LOWER BOUND, see is_printer_output: "
          "sql %d/%d, py %d/%d"
          % (exact_checked, exact_sql, exact_checked, exact_py, exact_checked))
    # THE TWO HALVES OF THAT py FIGURE ARE NOT THE SAME KIND OF FACT, and printing one number read
    # as N independent confirmations when some of them cannot fail. Family A is scored against an
    # IR built separately from the parse; family B is admitted BECAUSE the Python reprinted it, so
    # its `py` column is true by the admission rule's construction. The macros' column is a real
    # measurement in both halves -- in family B it is scored against the Python as the witness,
    # which is the best available when the printer is not injective (F3's own ruling).
    print("  of which %d are INDEPENDENT (family A, against a constructed IR): sql %d/%d, py %d/%d"
          % (indep_n, indep_sql, indep_n, indep_py, indep_n))
    print("  and %d are ADMITTED by the Python's own reprint, so py is CONSTRUCTION-TRUE there "
          "and not a confirmation: sql %d/%d, py %d/%d (forced)"
          % (adm_n, adm_sql, adm_n, adm_n, adm_n))
    if exact_fail:
        # "ALL DECLARED" IS CONDITIONED ON THE CHECK BESIDE IT. These two lines printed that claim
        # unconditionally, over every exact_fail key, so a run that had just printed an UNDECLARED
        # EXACT FAILURE block said "all declared ... enumerated rather than excluded" three lines
        # later. MEASURED by planting, with three undriven cases added in a scratch copy: the old
        # text printed "14 printer-output case(s) FAIL EXACT, all declared ... k13, z01, z02, z03"
        # in the same output that named z01-z03 as undeclared. The run exits 1 either way, so the
        # effect was cosmetic -- and a cosmetic sentence that contradicts the gate beside it is how
        # a reader learns to trust the wrong half of the output.
        print("  %d printer-output case(s) FAIL EXact, %s: %s"
              .replace("EXact", "EXACT")
              % (len(exact_fail),
                 "all declared in KNOWN_EXACT_FAILURES" if not ef_undeclared
                 else "%d declared in KNOWN_EXACT_FAILURES and %d UNDECLARED (named above)"
                      % (len(exact_fail) - len(ef_undeclared), len(ef_undeclared)),
                 ", ".join(sorted(k for k, _l, _t, _a, _b in exact_fail))))
        print("  so EXACT does NOT hold over the printer's image. It holds on the %d that pass, "
              "and the %d failures are %s."
              % (exact_checked - len(exact_fail), len(exact_fail),
                 "enumerated rather than excluded" if not ef_undeclared
                 else "NOT all enumerated -- see the UNDECLARED EXACT FAILURE block above"))
    if excluded:
        print("  %d family-B case(s) are NOT in this denominator (listed by --both-refuse-audit): "
              "%s" % (len(excluded), ", ".join(l.split()[0] for l, _t, _w in excluded)))
    if printer_output_in_b:
        print("  of which %d came from family B, found to be printer output by computation: %s"
              % (len(printer_output_in_b),
                 ", ".join(l.split()[0] for l in printer_output_in_b)))
    # NAMED IN THE DEFAULT OUTPUT, not only under --both-refuse-audit, and not merely counted among
    # the exclusions above. A case here reprints to itself, so the old rule ADMITTED it and scored
    # `sql == py` as the exact theorem on it -- which is exactly what the theorem is not when the
    # witness is not the constructor's IR. The whole defect was that this was silent.
    for label, why in unsound_witness:
        print("  WITNESS NOT SOUND, so NOT in the denominator: %s\n    %s" % (label, why))
    if exact_checked == 0 or len(cases) == 0:
        print("FAIL: the sweep compared nothing")
        sys.exit(4)
    if unknown or stale or moved or ef_undeclared or ef_unknown or ef_stale:
        print("FAIL: %d unknown, %d stale, %d moved divergence declaration(s); "
              "%d undeclared, %d unknown, %d stale EXACT-failure declaration(s)"
              % (len(unknown), len(stale), len(moved),
                 len(ef_undeclared), len(ef_unknown), len(ef_stale)))
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
