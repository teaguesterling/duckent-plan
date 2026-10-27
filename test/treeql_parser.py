#!/usr/bin/env python3
r"""A recursive-descent parser for TREEQL text, producing TREE_SELECTOR rows.

THE SECOND READING OF ONE GRAMMAR. sql/10_treeql.sql reads TREEQL text with macros;
sql/09_css.sql states what a second reading is for: "Two independent readings of one grammar is
the point; agreeing by construction would prove nothing." test/css_parser.py is the css pair's
second reading and imports no database driver for that reason. This module is the TREEQL pair's,
and it imports none for the same reason -- it may not consult the registry, the printer or the
macros, because a reading that asked them what the answer is would not be a reading.

THE STANDARD LIBRARY AND NOTHING ELSE, which is checkable rather than claimed: the module's only
import is `re`, and a grep for the database driver's module name answers 0 here exactly as it does
for test/css_parser.py. That grep is why neither this docstring nor any comment below spells that
name -- prose naming it would answer nonzero and defeat the very check it was describing. Measured
once already: an earlier draft of these two paragraphs used the name twice and the count was 2.

WHAT BINDS IT. test/sweep_treeql.py prints IR through tree_selector_to_treeql and asks both
front-ends to read the result, comparing every field of every row, node ids included. The
vocabulary copies below are bound by THAT, not by the registry -- see THE COPIES.

THE SPECIFICATION IS THE PRINTER, sql/06_selector.sql, and its grammar is:

    selector  := step (LF step)*
    step      := rtrim( [KEYWORD ' '] ['(' clauses ')'] [' AS ' alias] )
    clauses   := part (', ' part)*
    part      := clause | group
    clause    := KEYWORD ' ' body
                   type/id/class/pseudo:  body is tree_sql_lit(value) -- a '...' literal
                   attr:                  body is `value op arg`, UNQUOTED
                   where:                 body is raw host SQL, UNQUOTED
    group     := UPPER(kind) ' ( ' step (' ' step)* ' )'

and the reader is more tolerant than the printer on purpose: keyword case is free, every character
in WS separates, a top-level clause list may omit its parentheses, and a value may be a bare
identifier (D-N15). Tolerant input, canonical output.

HOW THIS READING DIFFERS IN KIND from the macros', which is what makes the differential evidence
rather than a round trip:

  * sql/10_treeql.sql SPLITS FIRST and asks afterwards. It cuts on a depth-0 newline, then on
    depth-0 commas, then before combinator keywords, and hands each fragment to a per-part reader.
    The scan is blind to which clause kind it is inside, so it cannot tell a raw body's own comma
    from a separator at the point where it cuts. It counts `[ ]` and `{ }` alongside `( )` -- Task
    7's one-line fix to tree_treeql_split_parts, which is why the bracket and brace cases AGREE
    below rather than appearing in DIVERGENT.
  * THIS MODULE DESCENDS and knows where it is. It reads a keyword, then reads that keyword's body
    by the rule for that kind: a literal body ends at its closing quote, a RAW body (attr, where)
    runs to the next separator that is followed by another clause keyword, so the scan never cuts
    inside a raw body at all.

TWO CLAIMS THAT STOOD HERE ARE WITHDRAWN, because they are what the macros USED to do and this
paragraph is where a reader decides how much the differential is worth. It said the macros take
depth and "inside a quote" from TWO WINDOW FUNCTIONS and that the splitter "reads EVERY `'` as a
delimiter", and it offered "tracks `'...'` literals AND `"..."` identifiers" as THIS reading's
distinguishing property. All three are false since R41: tree_treeql_quote_mask is one RE2 scan
that masks `'...'` and `"..."` alike, tree_treeql_depths is ONE window over that mask, and
sql/10_treeql.sql says so in as many words ("the depth is now ONE window over the mask ... so the
`quoted` CTE is gone"). MEASURED: `tree_treeql_quote_mask('(WHERE "o''k" = 1)')` masks the whole
double-quoted region, apostrophe included. The region rule is now SHARED -- test/sweep_treeql.py's
SHARED RULES note says what that costs the instrument, and says it FIRST.

Those two differences are the whole reason the sweep finds anything. Nothing in THIS file changes
the macros; what the differential found is fixed in sql/10_treeql.sql, where it belongs, and
test/sweep_treeql.py's DIVERGENT table names each shape where the two readings still part, with the
record in test/sql/48_treeql_parse.test that pins the macros' answer.

THE ONE PLACE THIS READING IS BOUND TO A RULING RATHER THAN TO THE GRAMMAR, stated here because
it looks like a quirk and is not: a step's clause list closes at the LAST ')' on the step's line,
not at the parenthesis that matches its first '('. See `_strip_clause_list`. That is what the
printer's grammar requires once a raw body is allowed to contain a parenthesis, and it is what
makes `(ATTR a = 1) (ATTR b = 2)` one step. THE F3 RULING in test/sql/48_treeql_parse.test is the
authority for that reading; EXACT requires it, because the text is printer output of an IR the
ordinary constructor builds.

EVERY REFUSAL message is `tree_parse_treeql: <sentence>`, and the sentences, their PRIORITY ORDER
and the `min(fragment)` tie-break are transcribed from sql/10_treeql.sql's refusal set. That set
is a RULING recorded in that file -- which fault to name when an input carries more than one --
and not something a second reading can derive, so agreeing on it is part of what the sweep checks
rather than something the sweep would be measuring twice.
"""
import re

__all__ = ["TreeqlError", "parse", "to_sql"]


class TreeqlError(Exception):
    """TREEQL text the grammar does not accept."""


# ----------------------------------------------------------------------------------------------
# THE COPIES, and what keeps each one honest.
#
# This module has NO database connection, so it cannot read tree_catalog.clause_kinds or
# tree_catalog.combinators -- the same position test/css_parser.py is in, and the reason
# scripts/check_vocabulary_single_source.py exempts that file's two tables by name. The copies are
# bound by test/sweep_treeql.py: every keyword below appears in printer output that the sweep reads
# back through BOTH front-ends, so a copy that drifted from the registry would stop agreeing with
# the macros, which DO read the registry. A registry row added without a line here shows up as a
# divergence on the first selector that uses it, not as silence.
#
# THAT IS WEAKER THAN READING THE REGISTRY and the difference is worth naming: the sweep binds a
# keyword only if some case exercises it. test/sql/46_slot_registry.test and 47_new_combinators.test
# are what gate the registry against growing a member no copy knows about.
# ----------------------------------------------------------------------------------------------

# keyword -> clause kind. tree_catalog.clause_kinds, measured: six rows.
#
# THESE TWO TABLES USED TO CARRY TRAILING MARKER COMMENTS -- `# CLAUSE_KEYWORDS, continued` and the
# same for COMBINATORS -- with an exemption entry each, justified as: "a declaration spread over
# two lines needs an anchor on each one". MEASURED FALSE: the lint's THRESHOLD is 3 members on ONE
# line, and a continuation line here carries two, so it is never an offending line and had nothing
# to exempt. Two of the four exemptions exempted nothing, and the sentence that justified them was
# reasoning about a reformat that has not happened, written in the register of a measurement. Both
# the markers and the entries are gone; the lint reports 8 exempt constructs, not 10.
CLAUSE_KEYWORDS = {"TYPE": "type", "ID": "id", "CLASS": "class",
                   "ATTR": "attr", "PSEUDO": "pseudo",
                   "WHERE": "where"}

# The kinds whose body reaches the text UNQUOTED and UNESCAPED, so the body's own commas,
# parentheses and apostrophes are not structure. The printer decides this same fact as it writes,
# in tree_treeql_clause's `CASE want_kind WHEN 'attr' ... WHEN 'where' ... ELSE tree_sql_lit`;
# sql/10_treeql.sql records it a second time in tree_treeql_raw_kw_re, whose own comment says
# there is no registry column for it. This is the third written record of one fact, and the sweep
# is what binds it: a kind that became raw-bodied without this line would mis-read its own
# printer output here and the sweep would say so.
RAW_BODY_KINDS = frozenset(("attr", "where"))

# keyword -> op. tree_catalog.combinators, measured: eight rows. The keyword is NOT the op
# upper-cased for half of them -- DESCENDANT is desc, SIBLING is next, FOLLOWING is after and
# PRECEDING is prev -- so this cannot be derived from the op and has to be written.
COMBINATORS = {"DESCENDANT": "desc", "CHILD": "child", "SELF": "self", "SIBLING": "next",
               "FOLLOWING": "after", "PARENT": "parent",
               "ANCESTOR": "ancestor", "PRECEDING": "prev"}

# A group's printed keyword is upper(kind), which is what tree_treeql_group_kinds() derives from
# tree_ir_kinds() less the two IR-shape kinds and the clause kinds. Measured: ['has', 'not'].
GROUP_KEYWORDS = {"HAS": "has", "NOT": "not"}

# tree_group_depth_limit(), measured: 2. The printer unrolls to this many group levels and so
# does the reader; past it the innermost group would be silently lost, so it is refused.
GROUP_DEPTH_LIMIT = 2

# tree_treeql_ws(): space, TAB, LF, FF, CR. EXACTLY RE2's `\s`, which is the point and not a
# coincidence -- sql/10_treeql.sql's header says so, and the VERTICAL TAB chr(11) is deliberately
# absent because RE2's `\s` does not hold it. Python's own `\s` DOES hold `\v`, so every pattern
# below writes this class out instead of using `\s`; `\s` here would accept a form feed's
# neighbour as a keyword separator and part company with the macros on one character.
WS = " \t\n\f\r"
_S = r"[ \t\n\f\r]"

# tree_treeql_as_re(), transcribed. `(?:^|\s+)` and not `\s+`: a step that is nothing but an alias
# prints as ' AS x', because tree_treeql_step right-trims only, so after the leading space is
# trimmed `AS` is at position 0 and there is no whitespace in front of it to match.
_AS_RE = re.compile(r"(?:^|" + _S + r"+)AS" + _S + r"+([^ \t\n\f\r]+)" + _S + r"*$", re.I | re.A)
# tree_sql_is_ident()
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$", re.A)
# the leading WORD, which is lexing and not identifier validation
_LEAD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)", re.A)
# tree_treeql_lit_ok()'s anchored pattern: the WHOLE text is one literal, '' being the escape
_LIT_RE = re.compile(r"^'(?:[^']|'')*'$")
# tree_treeql_clause_parse's ONE tokenisation of an attr body. A WORD operator needs whitespace
# separation from the identifier and a word boundary after itself -- without the first `aLIKE 'x'`
# reports LIKE, without the second `name LIKEx 'a'` does. A SYMBOL operator needs neither, because
# `ATTR size<='10'` must keep working. `<=`, `>=` and `<>` precede the one-character prefixes that
# would otherwise swallow them. `(.*)` and not `(.+)`, so an operator with NO argument is still
# reported rather than backtracking `<=` to `<` and offering `=` as the argument.
_ATTR_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:" + _S + r"*(<=|>=|<>|!=|=|<|>)"
    r"|" + _S + r"+(NOT" + _S + r"+LIKE|ILIKE|LIKE)\b)"
    + _S + r"*((?s:.*))$", re.I | re.A)

# THE REFUSAL PRIORITY ORDER, transcribed from the CASE at the end of tree_parse_treeql. One input
# can carry more than one fault and this decides which is named. Two of the orderings are rulings
# with measurements behind them in that file: PARENLESS BEFORE GENERIC is gated, because
# `HAS ( TYPE 'b' TYPE 'c' )` is also a clause whose literal cannot be read and the generic message
# would name the symptom; UNTERMINATED BEFORE UNBALANCED is correct and currently ungated, because
# an unterminated quote stops the parentheses after it from being counted.
PRIORITY = ("depth", "nosteps", "unterminated", "unbalanced", "groupparen",
            "parenless", "comb", "kw", "generic")

MESSAGES = {
    "depth": "groups nested deeper than %d levels are not supported" % GROUP_DEPTH_LIMIT,
    "nosteps": "selector has no steps",
    "unterminated": "unterminated quoted value",
    "unbalanced": "unbalanced parentheses",
    "groupparen": "HAS/NOT needs parentheses around its chain",
    "parenless": ("a step inside HAS/NOT needs a combinator or parentheses, so its clauses can "
                  "be told from the next step's"),
    "comb": "unknown combinator %s",
    "kw": "unknown clause keyword %s",
    "generic": "cannot read %s",
}


# ----------------------------------------------------------------------------------------------
# THE CHARACTER SCAN. This is the one piece that is not recursive descent, and it is where this
# reading's structural knowledge lives.
# ----------------------------------------------------------------------------------------------
def _scan(s):
    """Per-character structural state: (inq, pdepth, sdepth, open_literal).

    Each of the first three is a list as long as `s`:

      inq[i]     the character is inside a quoted region -- a `'...'` literal or a `"..."`
                 identifier. Inside one, nothing is structure.
      pdepth[i]  PARENTHESIS depth, counted the way tree_treeql_depths counts it: the running sum
                 INCLUDING this character, so an opening '(' at depth 0 reads 1 and its partner
                 ')' reads 0. This is the depth the balance test and the clause-list strip read.
      sdepth[i]  the same, counting '[' ']' and '{' '}' too. This is the depth a SEPARATOR is
                 judged at, and the difference from pdepth is deliberate: a WHERE body may hold a
                 list or a struct literal, so `(WHERE [1, 2] = [1, 2])` has commas that are not
                 separators. Brackets are NOT required to balance -- an unbalanced one is host-SQL's
                 business and refusing it here would reject text the macros accept.

    `open_literal` is True when a `'...'` region ran to the end of the text with no closing quote,
    which is what "unterminated quoted value" names.

    TWO QUOTE CHARACTERS, not one, and the reason is the grammar rather than a difference from the
    macros. A WHERE or ATTR body is raw host SQL, so it can hold a double-quoted IDENTIFIER whose
    content has an apostrophe -- `WHERE "o'k" = 1` is printer output from the ordinary constructor
    and legal DuckDB SQL. Reading every `'` as a delimiter makes the scan lose its place there;
    reading the region that opened FIRST, to its own closing delimiter, does not. The doubled
    delimiter is the escape in both regions.

    THIS USED TO SAY "that is the substantive difference from the macros ... exactly as `''`
    restores the macros' quote parity". Both halves are false since R41: tree_treeql_quote_mask
    reads two quote characters by the same opened-first rule, and there is no parity left for `''`
    to restore -- the mask replaced the count. The two readings now AGREE on this rule and the
    differential cannot see a defect in it, which is the first entry of test/sweep_treeql.py's
    SHARED RULES note.

    AN UNPAIRED `"` IS AN ORDINARY CHARACTER, while an unpaired `'` swallows the rest of the text.
    The asymmetry is deliberate: a double-quoted identifier that never closes is not an identifier,
    so treating the character as literal keeps the structural scan usable, while an unterminated
    `'` is precisely the fault the reader has a name for and must keep seeing.
    """
    n = len(s)
    inq = [False] * n
    pdepth = [0] * n
    sdepth = [0] * n
    open_literal = False
    p = extra = 0
    i = 0
    while i < n:
        c = s[i]
        if c == "'" or c == '"':
            j = i + 1
            while j < n:
                if s[j] == c:
                    if j + 1 < n and s[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                # NO PARTNER. An unclosed `'` is REPORTED -- "unterminated quoted value" is that
                # fault's name -- but for the STRUCTURAL arrays the delimiter is an ordinary
                # character either way, and that separation is the point. Letting it swallow the
                # rest of the text makes the parenthesis that follows it stop being counted, so a
                # quote fault presents as a PAREN fault: measured, `(WHERE a = 'x)` came back
                # `unbalanced parentheses` with its parentheses matched, which is a refusal naming
                # a cause the text does not have. The fault is detected here and the depth is left
                # alone, so each rule answers about what it can actually see.
                if c == "'":
                    open_literal = True
                inq[i] = False
                pdepth[i] = p
                sdepth[i] = p + extra
                i += 1
                continue
            for k in range(i, j + 1):
                inq[k] = True
                pdepth[k] = p
                sdepth[k] = p + extra
            i = j + 1
            continue
        if c == "(":
            p += 1
        elif c == ")":
            p -= 1
        elif c == "[" or c == "{":
            extra += 1
        elif c == "]" or c == "}":
            extra -= 1
        pdepth[i] = p
        sdepth[i] = p + extra
        i += 1
    return inq, pdepth, sdepth, open_literal


def _split_top_level(text):
    """The selector's lines: the text cut at every LF that is at parenthesis depth 0 and outside a
    quoted region. Requirement 1. A newline inside a clause list or inside a value cannot end a
    step, which is why this is a structural scan and not `text.split(chr(10))`.

    The parts are returned UNTRIMMED, because the keep rule below needs to tell a blank part from
    a part that merely has leading space, and the trim happens per part afterwards -- exactly the
    order tree_treeql_split_parts uses. Part count is separators + 1 always, so a trailing newline
    yields a final empty part rather than none.
    """
    inq, pdepth, _sd, _ol = _scan(text)
    out, start = [], 0
    for i, c in enumerate(text):
        if c == "\n" and not inq[i] and pdepth[i] == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return out


def _lead_word(s):
    m = _LEAD_RE.match(s)
    return m.group(1) if m else None


def _unlit(v):
    """The printer's literal form, undone: '...' with '' for an embedded quote. A bare identifier
    value (D-N15) has no quotes to strip and passes through, which is why the test is on the
    delimiters and not on the content."""
    if len(v) >= 2 and v.startswith("'") and v.endswith("'"):
        return v[1:-1].replace("''", "'")
    return v


def _lit_ok(v):
    """Is this the source text of a well-formed quoted value? True when it does not begin with a
    quote at all, and otherwise only when the WHOLE text is one literal. The test is on the SOURCE
    and never on the stored value: `it's` legitimately holds one quote once _unlit has run."""
    return not v.startswith("'") or _LIT_RE.match(v) is not None


def sql_str(s):
    """One SQL text literal, single quotes doubled."""
    return "'" + str(s).replace("'", "''") + "'"


class Parser:
    """One selector text. Faults are collected rather than raised, so the priority order above
    decides which one is named -- the same arrangement as tree_parse_treeql's CASE, and for the
    same reason: an input with two faults must not report whichever was noticed first."""

    def __init__(self, text):
        self.text = text
        self.faults = []          # (code, fragment)
        self.nodes = []           # (path, ppath, kind, value, op, arg, alias)

    # --- faults ----------------------------------------------------------
    def fault(self, code, frag):
        self.faults.append((code, "" if frag is None else frag))

    def verdict(self):
        """The refusal to raise, or None. `min(fragment)` within a code is the macros' own
        tie-break: the CASE reads `min(frag)` per code, so two faults of one kind name the
        alphabetically smaller fragment. Arbitrary, but it has to be the SAME arbitrary."""
        for code in PRIORITY:
            frags = sorted(f for c, f in self.faults if c == code)
            if not frags:
                continue
            msg = MESSAGES[code]
            return TreeqlError("tree_parse_treeql: " + (msg % frags[0] if "%s" in msg else msg))
        return None

    # --- the step reader -------------------------------------------------
    def read_step(self, part):
        """One step's text to (op, body, alias, unknown_word, tail).

        The printer emits `rtrim(comb? '(' clauses ')'? (' AS ' alias)?)`, so all three parts are
        optional and a combinator can appear with no clause list at all. THE ALIAS COMES OFF FIRST,
        because `AS` may follow ')'; it is found by an anchored tail match, which is what makes it
        correct with no depth scan -- a quoted or parenthesised `AS` is never followed by a bare
        identifier at end-of-string, so `(ATTR t = 'X AS y')` and `(WHERE CAST(n AS INT) = 1)` have
        an `AS` and no alias. The captured token is deliberately loose and _IDENT_RE decides whether
        it is an alias; a token that fails is not stripped either, and stays in the text to be
        refused rather than disappearing.

        The leading word is CONSUMED when it is a combinator or an unknown word, and LEFT when it
        is a clause keyword -- there it is the start of the clause list, not a combinator slot.
        """
        s = part.strip(WS)
        m = _AS_RE.search(s)
        tok = m.group(1) if m else None
        alias = tok if tok and _IDENT_RE.match(tok) else None
        rest = (s if alias is None else _AS_RE.sub("", s, count=1)).strip(WS)
        lead = _lead_word(rest)
        op = COMBINATORS.get(lead.upper()) if lead else None
        is_clause = bool(lead) and lead.upper() in CLAUSE_KEYWORDS
        unknown = lead if (lead and op is None and not is_clause) else None
        tail = (rest[len(lead):] if (op or unknown) else rest).strip(WS)
        body = None if tail == "" else self._strip_clause_list(tail)
        return op, body, alias, unknown, tail

    @staticmethod
    def _strip_clause_list(tail):
        """A step's clause list, with its parentheses removed when it has them.

        THE CLOSE IS THE LAST ')' OUTSIDE A QUOTED REGION, and it must be the last non-blank
        character -- not the parenthesis that matches the first '('. This is the one reading in
        this file taken from a ruling rather than from the grammar alone, so the reason is written
        out:

        An ATTR or WHERE body reaches the text unquoted, so it may CONTAIN a parenthesis that
        pairs with nothing -- `tree_steps([{attr: 'a = 1) (ATTR b = 2'}])` is built by the ordinary
        constructor and prints `(ATTR a = 1) (ATTR b = 2)`. Matching the first '(' against its
        partner reads that text as one step followed by trailing junk and refuses it, which refuses
        the printer's own output. The printer puts the clause list last on the line before the
        optional alias, so its closing parenthesis IS the line's last -- and reading it that way
        returns the IR the printer was given. EXACT requires this, and THE F3 RULING in
        test/sql/48_treeql_parse.test is the authority: that text is a COLLISION in the surface
        syntax, byte-identical to what a person writes for two steps, and no parser can serve both
        readings.

        A top-level step is one printer LINE -- tree_selector_to_treeql joins top-level steps with
        chr(10) -- which is what makes "the line's last ')'" well defined. Inside a group the steps
        are separated by spaces instead, and `_chain_parts` finds those boundaries before any step
        text reaches here.
        """
        if not tail.startswith("("):
            return tail
        inq, _pd, _sd, _ol = _scan(tail)
        last = -1
        for i, c in enumerate(tail):
            if c == ")" and not inq[i]:
                last = i
        if last < 0 or tail[last + 1:].strip(WS) != "":
            return tail
        return tail[1:last].strip(WS)

    # --- the clause list -------------------------------------------------
    def clause_parts(self, body):
        """The clause list's parts.

        A LITERAL-bodied clause ends at the next separator. A RAW-bodied one -- attr, where -- runs
        PAST a separator unless what follows it opens another part, which is a clause keyword or a
        group keyword.

        THE MACROS REACH THE SAME ANSWER BY A DIFFERENT ROUTE, which this used to deny ("that is
        the rule the macros do not have ... so `(WHERE [1, 2] = [1, 2])` comes apart"). Measured,
        both halves are stale: tree_treeql_split_parts cuts on every UNENCLOSED depth-0 comma
        whatever body it sits in, and then tree_treeql_clause_parts puts a raw body's own
        separators back by SPAN --

            tree_treeql_split_parts('WHERE a = 1, b = 2', ',')  ->  'WHERE a = 1' and 'b = 2'
            tree_treeql_clause_parts('WHERE a = 1, b = 2')      ->  ONE part, the whole body

        -- and the bracket example does not come apart at all, because Task 7's one-line fix made
        the splitter count `[ ]` and `{ }` as well as `( )`. So this is a rule the two readings
        SHARE, by the second entry of test/sweep_treeql.py's SHARED RULES note, and what parts them
        is only WHERE the decision is made: this module never cuts inside a raw body, the macros
        cut and then merge.

        WHAT THE RULE GIVES UP, stated rather than hidden: a raw body whose own top-level comma IS
        followed by a clause keyword is read as two parts. `(TYPE 'x', WHERE a = 1, PSEUDO 'p')` is
        therefore three clauses and not a WHERE body of `a = 1, PSEUDO 'p'` -- the documented limit
        in test/sql/48_treeql_parse.test. The macros take the same reading, which is why the
        DIFFERENTIAL cannot see it rather than why it is right: measured, `pseudo` is slot 5 and
        `where` slot 6, so the printer emits PSEUDO first and the three-clause IR prints DIFFERENT
        BYTES -- the text has exactly ONE constructor-accepted preimage and this reading is WRONG
        on it. The class is declared as KNOWN EXACT FAILURES in test/sweep_treeql.py, this member
        included, as `k13`; "the two agree on it" stood here and read a shared defect as agreement.

        AND WHERE IT DECLINES TO GUESS: a raw group absorbs its continuations only when the NEXT
        group opens a GROUP keyword, or when there is no next group. If the next group opens a
        CLAUSE keyword the parts stay separate, so `(WHERE a = 1, b = 2, TYPE c)` REFUSES rather
        than returning a two-clause IR the printer would never emit in that order. A silent wrong
        parse replacing a loud refusal is the worse of the two failures.

        THIS RULE IS SHARED WITH THE MACROS, and that is a cost this file should name rather than
        hide: see the SHARED RULES note in test/sweep_treeql.py. A differential cannot see a defect
        its two readings share, and the keyword-continuation class above is one they do share.
        """
        inq, _pd, sdepth, _ol = _scan(body)
        seps = [i for i, c in enumerate(body) if c == "," and not inq[i] and sdepth[i] == 0]
        marks = [-1] + seps + [len(body)]
        spans = [(marks[j] + 1, marks[j + 1]) for j in range(len(marks) - 1)]

        def props(lo, hi):
            lead = _lead_word(body[lo:hi].strip(WS))
            u = lead.upper() if lead else None
            return (u is not None and (u in CLAUSE_KEYWORDS or u in GROUP_KEYWORDS),
                    u is not None and CLAUSE_KEYWORDS.get(u) in RAW_BODY_KINDS,
                    u is not None and u in GROUP_KEYWORDS)

        info = [(lo, hi) + props(lo, hi) for lo, hi in spans]
        gid, g = [], 0
        for n, it in enumerate(info):
            if n == 0 or it[2]:
                g += 1
            gid.append(g)
        head = {}
        for n, gg in enumerate(gid):
            head.setdefault(gg, info[n])
        out = []
        for gg in sorted(head):
            members = [n for n, x in enumerate(gid) if x == gg]
            nxt = head.get(gg + 1)
            # A RAW group absorbs its continuations UNLESS the NEXT group opens a CLAUSE keyword.
            # There the text is ambiguous and absorbing it would turn a loud refusal into a silent
            # wrong parse -- which is the worse of the two failures. A GROUP keyword after a raw
            # body is legitimate, because the printer puts groups after clauses.
            tail_ok = nxt is None or nxt[4]
            if head[gg][3] and tail_ok:
                out.append(body[info[members[0]][0]:info[members[-1]][1]].strip(WS))
            else:
                out.extend(body[info[n][0]:info[n][1]].strip(WS) for n in members)
        return out

    @staticmethod
    def read_clause(part):
        """One clause's text to {kind, value, op, arg, lit_ok}, or None when no keyword matches.

        The keyword must be followed by WHITESPACE rather than by a literal space, so every
        character WS names separates -- but something must follow, so a bare `TYPE` with no operand
        answers None and is refused by name rather than parsing to a clause with no value.
        """
        s = part.strip(WS)
        up = s.upper()
        for kw, kind in CLAUSE_KEYWORDS.items():
            if not (up.startswith(kw) and len(s) > len(kw) and s[len(kw)] in WS):
                continue
            body = s[len(kw):].strip(WS)
            if kind == "where":
                return {"kind": kind, "value": body, "op": None, "arg": None, "lit_ok": True}
            if kind == "attr":
                m = _ATTR_RE.match(body)
                name = _LEAD_RE.match(body)
                # a body with no operator still reports its name and an EMPTY op, which is what
                # lets the refusal set tell `ATTR name` from `ATTR name =` by name
                op = arg = ""
                if m:
                    op = re.sub(_S + r"+", " ", (m.group(2) or m.group(3) or "")).upper()
                    arg = m.group(4) or ""
                return {"kind": kind, "value": name.group(1) if name else "",
                        "op": op, "arg": arg, "lit_ok": True}
            return {"kind": kind, "value": _unlit(body), "op": None, "arg": None,
                    "lit_ok": _lit_ok(body)}
        return None

    # --- a group's inner chain -------------------------------------------
    def chain_parts(self, s):
        """A group's inner chain, cut BEFORE each step boundary.

        The printer joins a group's inner steps with a SINGLE SPACE, and a space is not a separator
        anywhere else in TREEQL, so there is no character to cut on. Two things mark a boundary:

          * a COMBINATOR KEYWORD at depth 0 outside quotes, compared as a WHOLE WORD -- a prefix
            comparison would cut `CHILDREN` and `SELFISH`. Every inner step the printer emits has
            one, because the constructor defaults a group chain's combinator to desc.
          * a depth-0 '(' whose previous non-blank character is a depth-0 ')'. The printer emits no
            combinator word for an inner step whose op is NULL, so `HAS ( (TYPE 'b') (TYPE 'c') )`
            is printer output; with the keyword as the only boundary the whole chain would arrive
            as one step. Inside a step's clause list every parenthesis is deeper than 0, so the
            only ')' that can precede a depth-0 '(' is the previous step's own close.

        The boundary character is KEPT -- the keyword belongs to the step it starts. Empty spans
        are dropped, so an empty chain answers NO steps and the empty group is refused rather than
        built as a group node with nothing under it.
        """
        inq, pdepth, sdepth, _ol = _scan(s)
        bounds = {0}
        i, n = 0, len(s)
        while i < n:
            if inq[i] or sdepth[i] != 0 or not (s[i].isalnum() or s[i] == "_"):
                i += 1
                continue
            j = i
            while j < n and not inq[j] and (s[j].isalnum() or s[j] == "_"):
                j += 1
            if s[i:j].upper() in COMBINATORS:
                bounds.add(i)
            i = j
        prev_nz = None
        for i, c in enumerate(s):
            if c == "(" and not inq[i] and pdepth[i] == 1 and prev_nz is not None:
                k = prev_nz
                if s[k] == ")" and not inq[k] and pdepth[k] == 0:
                    bounds.add(i)
            if c not in WS:
                prev_nz = i
        marks = sorted(bounds) + [n]
        out = []
        for a, b in zip(marks, marks[1:]):
            frag = s[a:b].strip(WS)
            if frag != "":
                out.append(frag)
        return out

    # --- assembly --------------------------------------------------------
    def node(self, path, ppath, kind, value=None, op=None, arg=None, alias=None):
        self.nodes.append((path, ppath, kind, value, op, arg, alias))

    def read_parts(self, body, path_of, step_path, level):
        """One step's clause list: the clause rows and the group rows, in the macros' slot order.

        Requirement 2 orders a step's CLAUSES before its GROUPS, each set keeping its textual
        position. `a` is the part's textual position and not tree_steps' slot number -- a
        deliberate difference, because only the RELATIVE order of paths survives the numbering and
        the printer emits a step's parts ORDER BY node_id, so on canonical IR the textual order of
        the parts IS their slot order. Reading a slot number instead would need a clause ORDINAL,
        and the registry has no order column.
        """
        parts = self.clause_parts(body)
        read = []
        for n, part in enumerate(parts, start=1):
            cl = self.read_clause(part)
            op, gbody, _al, uw, gtail = self.read_step(part)
            gkind = None
            if cl is None and uw is not None and uw.upper() in GROUP_KEYWORDS:
                gkind = GROUP_KEYWORDS[uw.upper()]
            read.append((n, part, cl, gkind, gbody, gtail, uw))
        read.sort(key=lambda r: (0 if r[3] is None else 1, r[0]))
        groups = []
        for a, (n, part, cl, gkind, gbody, gtail, uw) in enumerate(read, start=1):
            path = path_of(a)
            if cl is not None:
                self.node(path, step_path, cl["kind"], cl["value"], cl["op"], cl["arg"])
                if not cl["lit_ok"]:
                    self.fault("generic", part)
                continue
            if gkind is not None:
                self.node(path, step_path, gkind)
                if not self._wrapped(gtail):
                    self.fault("groupparen", part)
                    continue
                groups.append((path, gbody, part))
                continue
            # NEITHER A CLAUSE NOR A GROUP: the catch-all, which names the fragment and claims
            # nothing about why.
            #
            # AND IT STAYS GENERIC EVEN WHEN THE PART HAS AN UNKNOWN LEADING WORD. This used to
            # call classify_unknown here, giving `(WHERE a = 1, b = 2, TYPE c)` the refusal
            # `unknown clause keyword b` where the macros say `cannot read b = 2`. The macros are
            # right and this was wrong: their comb/kw arms read `uws`, which collects the unknown
            # leading word of a STEP at each of the three levels, never of a clause-list PART. The
            # distinction is deliberate there -- a step's leading word sits in a combinator slot,
            # so naming it as a misspelled combinator or clause keyword points at something; a
            # part inside a clause list has no such slot, and `cannot read <fragment>` is the
            # honest answer. MEASURED: this divergence was invisible until fix round 3 added a case
            # whose unreadable part HAS a leading word -- `42` and the empty part, the two shapes
            # that reached here before, have none.
            self.fault("generic", part)
        return groups

    @staticmethod
    def _wrapped(tail):
        """Does this text consist of ONE parenthesised group? Used only for a GROUP's chain, where
        the printer always writes `KIND ( chain )`. The '(' must be first and the matching ')' --
        the first position where the depth returns to 0 -- must be the last character. The old
        first-and-last-character test accepted `(TYPE 'b') KID (TYPE 'c')` with MISMATCHED
        parentheses and handed the clause reader a malformed step wearing a well-formed shape."""
        if tail is None or not tail.startswith("("):
            return False
        inq, pdepth, _sd, _ol = _scan(tail)
        for i in range(len(tail)):
            if not inq[i] and pdepth[i] == 0:
                return i == len(tail) - 1
        return False

    def classify_unknown(self, part, uw, body, tail):
        """An unknown leading word: a misspelled COMBINATOR, a misspelled CLAUSE KEYWORD, or a
        parenless group. One question separates the first two, and it is asked of the clause reader
        rather than guessed from the word's shape: does what follows read as a legal clause list?
        `SIDEWAYS (TYPE 'b')` leaves a body that does, so SIDEWAYS was meant to be a combinator;
        `FROBNICATE 'x'` leaves one that does not, so it was meant to be a clause keyword. EVERY
        part must read as a clause, which is why it is a count and not an any(): naming SIDEWAYS an
        unknown combinator on a body of `TYPE 'a', 42` would point at the wrong token."""
        if uw.upper() in GROUP_KEYWORDS:
            if not self._wrapped(tail):
                self.fault("groupparen", uw)
            else:
                self.fault("generic", part)
            return
        if body is None:
            self.fault("kw", uw)
            return
        parts = self.clause_parts(body)
        if parts and all(self.read_clause(p) is not None for p in parts):
            self.fault("comb", uw)
        else:
            self.fault("kw", uw)

    def read_chain(self, gbody, parent_path, level, base):
        """A group's inner chain, and the level below it. Unrolled to GROUP_DEPTH_LIMIT levels
        rather than recursed, because the printer unrolls to the same depth and a group at the last
        level gets its NODE and no inside -- which is what lets the depth measure see one past the
        ceiling and fire the refusal instead of silently losing the innermost group."""
        if gbody is None:
            self.fault("generic", base)
            return
        steps = self.chain_parts(gbody)
        if not steps:
            self.fault("generic", base)
            return
        for i, part in enumerate(steps, start=1):
            op, body, alias, uw, tail = self.read_step(part)
            # R35: an inner step with no combinator word keeps op NULL. There is no desc default
            # here -- the printer writes no combinator word for a NULL op, so coalescing to desc
            # would make print(parse(print(ir))) differ from print(ir).
            step_path = parent_path[:2 * level] + (i, 0) + (0,) * (4 - 2 * level)
            self.node(step_path, parent_path, "step", None, op, None, alias)
            if uw is not None and uw.upper() not in GROUP_KEYWORDS:
                self.classify_unknown(part, uw, body, tail)
            elif op is None and uw is None and not part.startswith("("):
                # a step inside a group has nothing marking where its clause list ends and the
                # next step's begins. At BASE `HAS ( TYPE 'b' TYPE 'c' )` returned clean IR.
                self.fault("parenless", part)
            if body is None:
                continue
            if level >= GROUP_DEPTH_LIMIT:
                # the last level the ceiling allows: a group here gets its node and nothing under
                # it, so the depth measure sees GROUP_DEPTH_LIMIT + 1 and the refusal fires
                for a, part2 in enumerate(self.clause_parts(body), start=1):
                    cl = self.read_clause(part2)
                    gp_op, gp_body, _a, gp_uw, gp_tail = self.read_step(part2)
                    pp = step_path[:2 * level + 1] + (a,) + (0,) * (4 - 2 * level)
                    if cl is not None:
                        self.node(pp, step_path, cl["kind"], cl["value"], cl["op"], cl["arg"])
                        if not cl["lit_ok"]:
                            self.fault("generic", part2)
                    elif gp_uw is not None and gp_uw.upper() in GROUP_KEYWORDS:
                        self.node(pp, step_path, GROUP_KEYWORDS[gp_uw.upper()])
                    elif gp_uw is not None:
                        self.classify_unknown(part2, gp_uw, gp_body, gp_tail)
                    else:
                        self.fault("generic", part2)
                continue
            groups = self.read_parts(
                body,
                lambda a, _sp=step_path, _l=level: _sp[:2 * _l + 1] + (a,) + (0,) * (4 - 2 * _l),
                step_path, level)
            for gpath, gb, gpart in groups:
                self.read_chain(gb, gpath, level + 1, gpart)

    def parse(self):
        text = self.text
        if text is None:
            raise TreeqlError("tree_parse_treeql: " + MESSAGES["nosteps"])

        inq, pdepth, _sd, open_literal = _scan(text)

        # LEVEL 0: the top-level chain.
        raw = _split_top_level(text)
        # R26/R30/R31: a blank top-level part is dropped, with ONE exception -- the empty FIRST
        # step. A step with no clauses and no combinator prints as NOTHING, and only the FIRST step
        # can be in that position, because every later step carries a combinator the printer emits
        # as a keyword. So a leading blank part is an empty first step IFF the next part begins
        # with a combinator keyword; every other blank part stays dropped, which is what leaves the
        # trailing newline, the CRLF pair and the blank line between two steps alone. A LONE blank
        # part is not kept: it prints as the empty string and no parser can recover a step from no
        # characters. The renumbering is load-bearing -- i0 decides which step is FIRST, and only
        # the first keeps a NULL combinator, so filtering without renumbering would give a selector
        # a combinator its text does not contain.
        lines = []
        for ord_, part in enumerate(raw, start=1):
            if part.strip(WS) != "":
                lines.append(part)
                continue
            nxt = raw[ord_] if ord_ < len(raw) else None
            if ord_ == 1 and nxt is not None and self.read_step(nxt)[0] is not None:
                lines.append(part)

        if not lines:
            raise TreeqlError("tree_parse_treeql: " + MESSAGES["nosteps"])

        # DO THE PARENTHESES BALANCE? Both signs matter and for different reasons: the depth must
        # never go NEGATIVE (`TYPE 'a')` closes a group nobody opened) and it must END at zero
        # (`(TYPE 'a'` leaves one open). A single `= 0` test at the end accepts `)TYPE 'a'(`.
        #
        # NO STAND-DOWN HERE, and THAT IS A DEFECT OF THIS FILE, not a difference worth having.
        # It refuses PRINTER OUTPUT. MEASURED, duckdb 1.5.5:
        #
        #     tree_steps([{"where": 'a = 1)'}])  prints  (WHERE a = 1))
        #       macros: parsed, one `where` clause of `a = 1)`, EXACT true
        #       here:   TreeqlError `unbalanced parentheses`
        #     tree_steps([{attr: 'a = 1)'}])     prints  (ATTR a = 1))     the same, both ways
        #
        # A raw body is host SQL passed through verbatim, so it may legitimately carry an unmatched
        # parenthesis, and then the printer emits text whose parentheses do not balance. "The
        # printer is the specification. A refusal that rejects printer output is a defect" -- the
        # Global Constraint. The macros honour it; this reading does not.
        #
        # THE REASON THAT STOOD HERE WAS FALSE IN BOTH HALVES, and acting on it is what produced
        # the defect. It said tree_treeql_balanced stands down "because its scan reads every `'` as
        # a delimiter", and that this scan "reads `"..."` as well ... and needs no exemption". The
        # macro's scan has read tree_treeql_quote_mask since R41, so quoting is not the cause --
        # and decisively, the stand-down is not about quoting AT ALL: a raw body can hold an
        # unmatched parenthesis with no quote anywhere in the text. So this reading DOES need the
        # exemption, and concluded otherwise from a cause that had already been superseded.
        #
        # WHY THE GUARD IS NOT HERE YET, because an unlanded fix with no reason is worse than a
        # named one. The guard the fix wants is `self._no_raw_body(text) and ...`, borrowing the
        # predicate that already guards the `unterminated` check below. The coordinator's condition
        # for borrowing it was that it AGREE with tree_treeql_quotes_trusted across the sweep
        # corpus, and MEASURED it does not: 121 of 123 texts agree, and `TYPE 'a` and `TYPE 'it''s`
        # disagree, because quotes_trusted is `quotes_even AND no_raw_body` and those two texts
        # have an ODD quote count with no raw body. The disagreement cannot be observed at THIS
        # site -- both texts have an all-zero paren depth, so this test cannot fire on either, and
        # both readings answer `unterminated quoted value` on them -- but the condition was a hard
        # stop and the predicate really is not the same rule, so the ruling is the coordinator's.
        # test/sweep_treeql.py drives no case in this class yet, by the same decision: a case with
        # no fix behind it would leave the gate red.
        if pdepth and (min(pdepth) < 0 or pdepth[-1] != 0):
            self.fault("unbalanced", text)

        root = (0, 0, 0, 0, 0, 0)
        self.node(root, (-1, 0, 0, 0, 0, 0), "selector", "treeql")

        for i0, part in enumerate(lines, start=1):
            op, body, alias, uw, tail = self.read_step(part)
            # the FIRST step of the outer chain keeps whatever combinator the text gives it, which
            # for printer output is none; a LATER top-level step defaults to desc (requirement 4),
            # which is what tree_steps does. A combinator written on the first step is assembled as
            # written: tree_steps refuses to BUILD that IR, but the printer emits `CHILD (TYPE 'a')`
            # for it from hand-built IR and EXACT is true for it, so refusing here would reject
            # printer output.
            step_op = op if i0 == 1 else (op or "desc")
            step_path = (i0, 0, 0, 0, 0, 0)
            self.node(step_path, root, "step", None, step_op, None, alias)
            if uw is not None:
                self.classify_unknown(part, uw, body, tail)
            if body is None:
                continue
            groups = self.read_parts(
                body, lambda a, _i=i0: (_i, a, 0, 0, 0, 0), step_path, 0)
            for gpath, gb, gpart in groups:
                self.read_chain(gb, gpath, 1, gpart)

        # AN UNTERMINATED QUOTED VALUE. The guard is the macros' and the reason is R42's: a quote
        # count is evidence about a VALUE only where the text IS a value. A WHERE or ATTR body is
        # raw host SQL and reaches the text unquoted, so an apostrophe in it is not a delimiter and
        # the scan cannot be told where the literals are -- `(WHERE a = 'x)` is not a value this
        # reader may adjudicate. So the fault is raised only on text carrying no raw-bodied keyword.
        if open_literal and self._no_raw_body(text):
            self.fault("unterminated", text)

        # requirement 5, and FIRST in the priority order: the depth is measured on the ASSEMBLED
        # selector, which is what the printer and tree_steps_group both do.
        if self._group_depth() > GROUP_DEPTH_LIMIT:
            self.fault("depth", text)

        err = self.verdict()
        if err is not None:
            raise err
        return self._rows()

    @staticmethod
    def _no_raw_body(s):
        return not any(re.search(r"\b" + kw + r"\b", s.upper(), re.A)
                       for kw, kind in CLAUSE_KEYWORDS.items() if kind in RAW_BODY_KINDS)

    def _group_depth(self):
        """How many HAS/NOT nodes the deepest path through the assembled selector crosses, which is
        tree_selector_group_depth's measure."""
        by_path = {n[0]: n for n in self.nodes}
        best = 0
        for n in self.nodes:
            d, cur = 0, n
            while cur is not None:
                if cur[2] in ("has", "not"):
                    d += 1
                cur = by_path.get(cur[1])
            best = max(best, d)
        return best

    def _rows(self):
        """The nodes as TREE_SELECTOR rows. Every path is unique, so the parent link is one tuple
        comparison and no arithmetic on ids is done anywhere: the numbering is reproduced by
        sorting the same key tree_steps sorts, not by a counter that happens to count alike.
        Ancestry precedes depth in the key, which is what makes the order depth-first."""
        ordered = sorted(self.nodes, key=lambda n: n[0])
        ids = {n[0]: i for i, n in enumerate(ordered)}
        return [{"node_id": i, "parent_id": ids.get(n[1]), "kind": n[2], "value": n[3],
                 "op": n[4], "arg": n[5], "alias": n[6]} for i, n in enumerate(ordered)]


def parse(text):
    """The TREEQL text as IR rows; raises TreeqlError."""
    return Parser(text).parse()


def to_sql(rows):
    """The IR rows as a TREE_SELECTOR literal, ready to splice into a tree_match call."""
    def lit(v):
        return "NULL" if v is None else sql_str(v)
    parts = ["{node_id: %d, parent_id: %s, kind: %s, value: %s, op: %s, arg: %s, alias: %s}" % (
        r["node_id"], "NULL" if r["parent_id"] is None else r["parent_id"],
        lit(r["kind"]), lit(r["value"]), lit(r["op"]), lit(r["arg"]), lit(r["alias"]))
        for r in rows]
    return "[" + ", ".join(parts) + "]::TREE_SELECTOR"
