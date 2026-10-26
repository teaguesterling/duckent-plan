-- sql/10_treeql.sql
--
-- M-LANG: the reader for TREEQL text. The printer (sql/06_selector.sql) is the specification --
-- everything here accepts is defined by what tree_selector_to_treeql emits, and where the two
-- could disagree the printer is right.
--
-- WHY THIS FILE EXISTS. tree_catalog.selector_languages held ('treeql', NULL, ...) since M0: the
-- language the IR is named after could be printed and not read. Three things made that
-- structural rather than inconvenient -- doc 14 §2k made TREEQL the DEFAULT dialect, css's own
-- refusal directs authors to TREEQL text, and the slot engine added PARENT, ANCESTOR and
-- PRECEDING, which with the host door is four constructs reachable only through TREEQL.
--
-- WHY IT IS MACROS. The extension embeds sql/*.sql byte-identically and its global constraint is
-- that the C++ decides nothing about trees. A macro parser ships there with no C++.

-- EVERY whitespace character, as a character set for trim(). The parser family read the ASCII
-- space as the only whitespace at four sites, and the failure was silent: `TYPE<TAB>'fn'` parsed
-- to NULL and `TYPE <TAB>'fn'` parsed to the VALUE "<TAB>'fn'". CRLF `\r` is that same defect.
--
-- WHY ALL WHITESPACE IS FREE HERE. Only a depth-0 newline in the FULL selector is structural, and
-- that split happens upstream of this file, so a newline that reaches a clause or a clause list
-- has already been decided not to be a boundary. Treating it as whitespace cannot swallow a
-- step boundary that was not already gone.
--
-- Declared once, read at every site, because four sites patched one at a time is how the same
-- defect survives in three places.
--
-- THIS SET IS EXACTLY RE2's `\s` -- space, TAB, LF, FF, CR -- and that is the point, not a
-- coincidence. The trim sites read this macro; the five regex sites in this file write `\s`, and
-- a regex cannot read a macro. So the only way the two can agree is for them to BE the same set.
-- R11 originally declared four characters, which left `\s` one character wider, and the gap
-- behaved exactly like the defect R11 exists to remove: `\s` accepted a form feed as a keyword
-- separator, the trim then could not remove it, and `TYPE<FF>'fn'` came back with the VALUE
-- "<FF>'fn'" -- silently wrong, measured. R11's four characters are superseded; the principle was
-- always ONE definition.
--
-- The VERTICAL TAB chr(11) is deliberately absent: it is whitespace to a C programmer and is NOT
-- in RE2's `\s` -- measured, not assumed. Adding it would recreate the gap in the other
-- direction. test/sql/48_treeql_parse.test asserts the agreement over every ASCII character
-- rather than pinning the one character this round found, so the invariant is stated and not
-- sampled.
CREATE OR REPLACE MACRO tree_treeql_ws() AS ' ' || chr(9) || chr(10) || chr(12) || chr(13);

-- A clause list split on `sep` at paren depth 0 and outside single quotes.
--
-- THE SEPARATORS OCCUR INSIDE THE BODIES. The printer emits ATTR and WHERE bodies unquoted and
-- unescaped, so `(TYPE 'x', WHERE name IN ('a', 'b'))` contains a ", " that is not a separator
-- and a ")" that is not the step's. A split on ', ' mis-parses it, and so do the other cases in
-- 48_treeql_parse.test.
--
-- "Inside a quote" is the PARITY of quote characters strictly before a position, which is what
-- makes the '' escape free: two quotes restore the parity. Paren depth is a second window over
-- the column the first produced, which needs its own CTE -- window functions do not nest.
--
-- `sep` IS ONE CHARACTER. The scan compares `c = sep` per character, so a two-character separator
-- never matches and the input comes back silently as one part -- a wrong answer, not an error.
-- Every separator this parser needs is one character: ',' between clauses, and the combinator
-- characters between steps. Whoever needs a longer one changes `c = sep` to a slice comparison.
-- There is deliberately NO test pinning the current multi-character behaviour: a test would
-- enshrine the wrong answer as the intended one.
-- R22: WHY THE BOUNDARIES COME FROM A WINDOW AND NOT FROM A LOOKUP. This scan worked on a
-- literal and died on a correlated reference:
--
--     FROM (VALUES (1, 'TYPE ''a'', CLASS ''b''')) s(id, t), LATERAL tree_treeql_split(s.t, ',')
--     INTERNAL Error: Failed to bind column reference "" : inequal types (BIGINT != VARCHAR)
--
-- raised by the binder before the query ran, in the table shape and in a scalar list-returning
-- variant of the same body alike. The CAUSE was isolated to one expression, not to correlation as
-- such -- a correlated `generate_series`, `range(1, length(s) + 1)` and `string_split` all bind:
--
--     COALESCE((SELECT min(i) FROM seps WHERE i > b.lo), length(s) + 1)
--
-- an inner CORRELATED SUBQUERY, looking each part's end up per row, which the decorrelator could
-- not rewrite once `s` was itself correlated. So the ends now come from `lead()` over the
-- boundary positions and there is no inner subquery left. That is not a tidying: every caller of
-- this family from Task 4 on reads a COLUMN -- Task 6's registry dispatch parses selector text
-- out of a table -- and until this bound, the whole parser was literal-only.
--
-- The 0 and the length(s) + 1 are SENTINEL boundaries, which is what lets one window serve both
-- ends: each part runs from one boundary + 1 to the next boundary - 1, and the sentinel row's own
-- `lead()` is NULL and is dropped. Part count is therefore separators + 1 always, so an empty
-- trailing part survives ('TYPE ''x'',' plus whitespace still answers two parts, the second
-- empty) and the empty input answers one empty part rather than none. Measured, both.
--
-- The LIST form is the one implementation and the TABLE form is derived from it below, rather
-- than two copies of the scan that are free to drift. The list is what Task 4's assembly reads,
-- because `unnest()` of it over a relation needs no LATERAL at all.
--
-- `unnest(range(...))` AND NOT `FROM generate_series(...)`, which is the OTHER way this scan can
-- be called and the other way it did not bind. generate_series is a TABLE FUNCTION, and a table
-- function's argument may not contain a subquery; every scalar macro here IS a subquery once it
-- is inlined, so splitting the PRINTER's own output -- the first thing the assembly has to do --
-- raised `Binder Error: Table function cannot contain subqueries`. `range(1, n)` is a SCALAR
-- returning BIGINT[], so unnesting it in the select list binds with a subquery bound and leaves
-- no table function in the scan at all.
--
-- Measured, and it is why the gate in the test file uses a MACRO argument: a bare `(SELECT ...)`
-- argument binds either way, because the binder folds it before the table function sees it. Only
-- an inlined macro body reaches it unfolded.
CREATE OR REPLACE MACRO tree_treeql_split_parts(s, sep) AS (
  WITH chars AS (SELECT i, s[i:i] AS c FROM (SELECT unnest(range(1, length(s) + 1)) AS i)),
  quoted AS (
    SELECT i, c,
           (COALESCE(sum(CASE WHEN c = '''' THEN 1 ELSE 0 END)
              OVER (ORDER BY i ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) % 2) = 1 AS inq
    FROM chars),
  depthed AS (
    SELECT i, c, inq,
           sum(CASE WHEN inq THEN 0 WHEN c = '(' THEN 1 WHEN c = ')' THEN -1 ELSE 0 END)
             OVER (ORDER BY i) AS depth
    FROM quoted),
  bounds AS (SELECT 0 AS p
             UNION ALL SELECT i FROM depthed WHERE c = sep AND NOT inq AND depth = 0
             UNION ALL SELECT length(s) + 1),
  spans AS (SELECT p + 1 AS lo, lead(p) OVER (ORDER BY p) - 1 AS hi FROM bounds),
  -- The part TEXT and the part BOUNDARIES are the two whitespace-sensitive things here, and only
  -- one of them turned out to be sensitive: the boundaries come from separator position alone,
  -- and whitespace moves neither the quote parity nor the paren depth. Measured over whitespace
  -- after a separator, before a separator, at both ends of the input, and alone in a trailing
  -- part: the full character set on this one trim answers all four.
  parts AS (
    SELECT CAST(row_number() OVER (ORDER BY lo) AS INTEGER) AS ord,
           trim(s[lo:hi], tree_treeql_ws()) AS part
    FROM spans WHERE hi IS NOT NULL)
  SELECT list({ord: ord, part: part} ORDER BY ord) FROM parts);

-- The TABLE form, derived from the list above. This is the tested interface and the shape
-- `tree_treeql_split(s, sep)` has always had; it is one `unnest` over the one scan, so there is
-- nothing here that can disagree with the list form.
CREATE OR REPLACE MACRO tree_treeql_split(s, sep) AS TABLE (
  SELECT (x).ord AS ord, (x).part AS part
  FROM (SELECT unnest(tree_treeql_split_parts(s, sep)) AS x) ORDER BY ord);

-- The printer's literal form, undone: '...' with '' for an embedded quote. A bare identifier
-- (D-N15, decided 2026-10-15: accepted on input, never emitted) has no quotes to strip and
-- passes through, which is why the test is on the delimiters and not on the content.
CREATE OR REPLACE MACRO tree_treeql_unlit(v) AS
  CASE WHEN v LIKE '''%''' THEN replace(v[2:length(v)-1], '''''', '''') ELSE v END;

-- R38: THE QUOTE-AWARE PARENTHESIS DEPTH of every character, as a list. One scan, declared once
-- and read by tree_treeql_wrapped and tree_treeql_balanced below.
--
-- WHY IT EXISTS AT ALL. The parser tested "does this text wrap in parentheses?" with
-- `s LIKE '(%' AND s LIKE '%)'` -- the FIRST character and the LAST character, and nothing in
-- between. `(TYPE 'b') KID (TYPE 'c')` satisfies that with MISMATCHED parentheses, and the strip
-- then handed the clause reader `TYPE 'b') KID (TYPE 'c'`, which parsed to a type clause whose
-- value was `b') KID (TYPE 'c` -- a malformed step wearing the shape of a well-formed one.
-- Measured, at four sites: the body strip in tree_treeql_step_parse and the three `gtail` tests
-- in the assembly. SF-3 recorded that the predicate was copied verbatim; it is factored here and
-- fixed once.
--
-- THE DEPTH IS QUOTE-AWARE, which is the whole reason this cannot be a character count. The
-- printer emits a value's own parenthesis inside a literal -- `(TYPE 'has ) paren')` round-trips
-- exactly today -- so a count that does not know where the quotes are refuses printer output.
-- "Inside a quote" is the PARITY of quote characters strictly before a position, exactly as in
-- tree_treeql_split_parts, which is what makes the '' escape free.
--
-- The two windows and their reasons are tree_treeql_split_parts', and the comment there carries
-- them. What is deliberately different here is the RESULT: a LIST, not a relation, because both
-- readers want one answer about the whole string rather than a row per character. The list form
-- also keeps the readers free of an inner subquery, which is the R22 binder wall -- measured,
-- all three macros below bind when called with a correlated COLUMN argument.
CREATE OR REPLACE MACRO tree_treeql_depths(s) AS (
  WITH chars AS (SELECT i, s[i:i] AS c FROM (SELECT unnest(range(1, length(s) + 1)) AS i)),
  quoted AS (
    SELECT i, c,
           (COALESCE(sum(CASE WHEN c = '''' THEN 1 ELSE 0 END)
              OVER (ORDER BY i ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) % 2) = 1 AS inq
    FROM chars),
  depthed AS (
    SELECT i, sum(CASE WHEN inq THEN 0 WHEN c = '(' THEN 1 WHEN c = ')' THEN -1 ELSE 0 END)
                 OVER (ORDER BY i) AS d
    FROM quoted)
  SELECT CAST(list(d ORDER BY i) AS INTEGER[]) FROM depthed);

-- Does the text consist of ONE parenthesised group? True when the first character is '(' and the
-- '(' it opens CLOSES AT THE LAST CHARACTER -- which is what the old first-and-last-character test
-- only looked like it asked. `list_position` finds the first position where the depth returns to
-- 0, and that position must be the end.
--
-- COALESCE to FALSE, not to NULL: a NULL here would make every CASE that reads it return NULL,
-- and the caller would get a selector of NULL instead of a refusal. `(TYPE 'a'` never returns to
-- depth 0, so list_position answers NULL for exactly the input this test exists to reject.
-- WHEN THE QUOTE COUNT IS ODD, THE DEPTH SCAN IS NOT EVIDENCE, and this is the correction to a
-- defect this task shipped and then measured. The scan decides "inside a quote" by PARITY, which
-- assumes every `'` is a TREEQL literal delimiter. A WHERE body breaks that assumption: the
-- printer emits a WHERE body UNQUOTED AND UNESCAPED -- see this file's own header -- so it never
-- passes through tree_sql_lit and its quotes are not doubled. Measured, and it is printer output
-- from the ORDINARY constructor, not from hand-built IR:
--
--     tree_selector_to_treeql(tree_steps([{"where": '"o''k" = 1'}]))  ->  (WHERE "o'k" = 1)
--
-- A double-quoted IDENTIFIER holding an apostrophe. That is legal DuckDB SQL -- measured, the
-- binder accepts `WHERE "o'k" = 1` and the row matches -- it round-tripped exactly at BASE, and
-- with the depth scan trusted unconditionally it was REFUSED as an unterminated quoted value. A
-- refusal that rejects printer output is a defect and not a gate, so the three rules that count
-- quotes all stand down when the parity is odd. An E-string, `E'it\'s'`, is the same shape.
--
-- Declared once, read at three sites, because three rules standing down on three different
-- conditions is how the defect would come back in one of them.
CREATE OR REPLACE MACRO tree_treeql_quotes_even(s) AS
  COALESCE((length(s) - length(replace(s, '''', ''))) % 2 = 0, true);

-- Does the text consist of ONE parenthesised group? When the quotes are even, the first `(` must
-- close at the LAST character. When they are ODD the scan cannot locate the strings, so this
-- falls back to the first-and-last-character test -- which is exactly what the parser used before
-- this macro existed, so an odd-quote input is no worse off than it was at BASE. The stronger
-- test applies wherever it can be trusted, and SF-3's three inputs all have EVEN quote counts.
--
-- COALESCE to FALSE, not to NULL: a NULL here would make every CASE that reads it return NULL,
-- and the caller would get a selector of NULL instead of a refusal. `(TYPE 'a'` never returns to
-- depth 0, so list_position answers NULL for exactly the input this test exists to reject.
CREATE OR REPLACE MACRO tree_treeql_wrapped(s) AS
  COALESCE(s LIKE '(%'
           AND CASE WHEN tree_treeql_quotes_even(s)
                    THEN list_position(tree_treeql_depths(s), 0) = length(s)
                    ELSE s LIKE '%)' END, false);

-- Do the parentheses BALANCE across the whole text? Both signs matter and for different reasons:
-- the depth must never go NEGATIVE (`TYPE 'a')` closes a group nobody opened) and it must END at
-- zero (`(TYPE 'a'` leaves one open). A single `= 0` test at the end accepts `)TYPE 'a'(`.
--
-- AN ODD QUOTE COUNT ANSWERS TRUE, because then the depth is not evidence (see above) and a
-- refusal built on it would reject printer output. Nothing is lost: an odd quote count in a part
-- that is supposed to hold a LITERAL is refused by the unterminated arm, which runs first, and
-- `(TYPE 'a'` and `TYPE 'a')` -- the two inputs this rule exists for -- both have even counts.
--
-- COALESCE to TRUE: empty and NULL text have no parentheses to balance, and the no-steps arm --
-- which runs first -- is the refusal that owns them.
CREATE OR REPLACE MACRO tree_treeql_balanced(s) AS (
  SELECT COALESCE(NOT tree_treeql_quotes_even(s) OR (list_min(d) >= 0 AND d[-1] = 0), true)
  FROM (SELECT tree_treeql_depths(s) AS d));

-- R38: IS THIS THE SOURCE TEXT OF A WELL-FORMED QUOTED VALUE? True when it does not begin with a
-- quote at all -- a bare identifier value is legal input (D-N15) -- and otherwise only when the
-- WHOLE text is one literal: `'(?:[^']|'')*'`.
--
-- THE TEST IS ON THE SOURCE, NEVER ON THE STORED VALUE, and that is the ruling rather than a
-- detail. `it's` legitimately contains one quote once tree_treeql_unlit has run, so a check on
-- the stored value refuses `(TYPE 'it''s')` -- printer output that round-trips exactly today.
--
-- WHAT IT CATCHES, measured: the quoted-value reader took the FIRST quote to the LAST quote, so
-- `TYPE 'a` stored the value `'a` quote and all, `TYPE 'it''s` stored `'it''s`, and
-- `TYPE 'a' SIDEWAYS TYPE 'b'` stored `a' SIDEWAYS TYPE 'b`. One greedy match, three garbage
-- parses that all returned CLEAN IR. The anchored pattern separates them from every printer
-- output that carries a quote or a parenthesis -- `(TYPE 'it''s')`, `(TYPE 'has ) paren')` and
-- `(TYPE 'two '' quotes '' here')` all satisfy it, and the controls in
-- test/sql/48_treeql_parse.test measure that rather than asserting it.
--
-- THIS MACRO IS NOT ASKED ABOUT EVERY BODY. A WHERE body is raw host SQL and may legitimately
-- BEGIN with a quote -- `WHERE 'a' = n` is printer output and fails this pattern, measured -- and
-- an ATTR body is `name op arg`. So tree_treeql_clause_parse asks it only for the kinds whose
-- body IS the literal, in the same CASE that already decides each kind's body shape.
CREATE OR REPLACE MACRO tree_treeql_lit_ok(v) AS
  COALESCE(NOT (v LIKE '''%') OR regexp_matches(v, '^''(?:[^'']|'''')*''$'), true);

-- One clause's text to its IR fields, or NULL when no registered keyword matches.
--
-- THE KEYWORD AND THE KIND COME FROM tree_catalog.clause_kinds, so this reader gains a clause
-- kind the day one is registered and there is no list of kinds in this file. Only the BODY's
-- shape is per-kind, exactly as tree_treeql_clause renders it: TYPE/ID/CLASS/PSEUDO carry a
-- quoted literal, ATTR carries `name op arg` unquoted, WHERE carries raw host SQL.
--
-- The match requires the keyword to be followed by WHITESPACE rather than by a literal space, so
-- the whole character set tree_treeql_ws() names is free here too -- but it still requires
-- SOMETHING after the keyword, so a bare `TYPE` with no operand falls through to NULL and is
-- refused by name in Task 5 rather than parsing to a clause with no value.
--
-- THE ATTR OPERATOR IS ONE TOKENISATION, not three. `value`, `op` and `arg` used to be three
-- independent regexp_extract calls over the same body, and nothing made them agree where the
-- identifier ended: measured, `ATTR ALIKE 'x'` returned {value: ALIKE, op: LIKE, arg: 'x'} --
-- the op regex backtracked the greedy identifier and found LIKE inside the name that `value`
-- reported whole. Lowercase `alike` escaped only because the alternation was case-sensitive, so
-- making operator case free would have widened the defect to every identifier containing `like`.
--
-- So op and arg now come from ONE regexp_extract with named groups, and cannot disagree by
-- construction. The alternation is written ONCE.
--
--   * a WORD operator needs whitespace separation from the identifier (`\s+`) and a word boundary
--     after itself (`\b`), which is the left and the right half of the same defect: without the
--     first, `aLIKE 'x'` reports LIKE; without the second, `name LIKEx 'a'` reports LIKE with
--     "x 'a'" stranded in arg.
--   * a SYMBOL operator needs neither, because `ATTR size<='10'` worked and must keep working.
--     This is why the two kinds are separate alternatives with separate separator rules, rather
--     than one list.
--   * `<=`, `>=` and `<>` still precede the one-character prefixes that would otherwise swallow
--     them -- the order inside the symbol group is load-bearing exactly as before.
--   * `(?s)` on the arg, because `.` does not match a newline by default and a WHERE-shaped
--     literal can contain one; without it the whole match fails and the operator vanishes.
--   * `(.*)` and NOT `(.+)` for the arg, so an operator with NO argument is still REPORTED. With
--     `(.+)` a body ending at the operator failed the whole match and reported an EMPTY op --
--     indistinguishable from a body with no operator at all, while R13 has Task 5 refuse those two
--     as SEPARATE named refusals, so Task 5 would have told an author that `ATTR name =` has no
--     operator. Worse, and measured: `ATTR name <=` returned op '<' with arg '=', because with no
--     argument to consume the symbol alternation BACKTRACKED from `<=` to `<` so that `=` could
--     serve as the argument -- an operator the text does not contain, which is R19's own defect
--     class surviving in the corner `(.+)` created. The operator itself is still REQUIRED, so a
--     body with no operator still reports an empty op, which is what R13 wants.
--
-- `value` keeps its own extract of the maximal leading identifier, for two reasons: it must still
-- be reported for a body with NO operator (an empty op is the correct answer there, and R13 makes
-- Task 5 refuse it by name), and it cannot disagree with the single tokenisation -- the only
-- character that could extend the identifier further is itself an identifier character, which is
-- neither whitespace nor the start of any symbol operator, so no shorter identifier can match.
--
-- The reported op is CANONICAL: upper-cased and internal whitespace collapsed, so `not   like`
-- and `not<TAB>like` both yield exactly `NOT LIKE`. Tolerant input, canonical output.
CREATE OR REPLACE MACRO tree_treeql_clause_parse(txt) AS (
  WITH t AS (SELECT trim(txt, tree_treeql_ws()) AS s),
  kw AS (SELECT k.kind, k.keyword,
                trim((SELECT s FROM t)[length(k.keyword) + 1 : ], tree_treeql_ws()) AS body
         FROM tree_catalog.clause_kinds k
         WHERE regexp_matches(upper((SELECT s FROM t)), '^' || upper(k.keyword) || '\s')),
  a AS (SELECT kind, body,
               regexp_extract(body,
                 '^([A-Za-z_][A-Za-z0-9_]*)(?:\s*(<=|>=|<>|!=|=|<|>)|\s+((?i)NOT\s+LIKE|ILIKE|LIKE)\b)\s*(?s)(.*)$',
                 ['v', 'sym', 'word', 'arg']) AS m
         FROM kw)
  SELECT CASE
    WHEN (SELECT count(*) FROM a) = 0 THEN NULL
    ELSE (SELECT {kind: kind,
                  value: CASE kind WHEN 'where' THEN body
                                   WHEN 'attr'  THEN regexp_extract(body, '^([A-Za-z_][A-Za-z0-9_]*)', 1)
                                   ELSE tree_treeql_unlit(body) END,
                  op:    CASE kind WHEN 'attr'
                           THEN upper(regexp_replace(COALESCE(nullif(m.sym, ''), m.word), '\s+', ' ', 'g')) END,
                  arg:   CASE kind WHEN 'attr' THEN m.arg END,
                  -- R38: IS THE BODY'S QUOTING WELL FORMED? The question is per-kind for the same
                  -- reason `value` is, and it is answered in the same CASE so the two cannot
                  -- disagree about which kinds carry a literal. A WHERE body is raw host SQL and
                  -- an ATTR body is `name op arg`; neither is a literal, and a WHERE body may
                  -- legitimately begin with a quote -- measured, `WHERE 'a' = n` is printer
                  -- output. For every other kind the body IS the literal, so the source test
                  -- applies to it whole.
                  --
                  -- REPORTED RATHER THAN REFUSED HERE. This reader's contract is "NULL when no
                  -- registered keyword matches", and a malformed literal DID match a keyword, so
                  -- answering NULL would lose the distinction Task 5's refusal needs: the
                  -- assembly can say "unterminated quoted value" only if it can tell a malformed
                  -- literal from a part that is no clause at all.
                  lit_ok: CASE kind WHEN 'where' THEN true
                                    WHEN 'attr'  THEN true
                                    ELSE tree_treeql_lit_ok(body) END}
          FROM a) END);

-- THE RESERVED WORD SET, derived: both registries plus the three STRUCTURAL words. This is the
-- only place that set appears, and it gains a word the day a combinator or a clause kind is
-- registered. AS, HAS and NOT are structural -- measured today, neither registry holds any of
-- them -- so they are the only part written out, and they are written out once.
--
-- Sorted, so the list has one printed form rather than whatever order the UNION produced.
CREATE OR REPLACE MACRO tree_treeql_reserved() AS
  (SELECT list(keyword ORDER BY keyword) FROM (
     SELECT keyword FROM tree_catalog.clause_kinds
     UNION SELECT keyword FROM tree_catalog.combinators
     UNION SELECT unnest(['AS', 'HAS', 'NOT']) AS keyword));

-- One step's text to {op, body, alias, unknown_word}. The printer is the specification:
-- tree_treeql_step emits `rtrim(comb? '(' clauses ')'? (' AS ' alias)?)`, so all three parts are
-- optional, a combinator can appear with no clause list at all (`CHILD` prints bare), and the
-- alias is last.
--
-- WHY FOUR FIELDS AND NOT THREE.
--   * `body` is NULL ONLY when there is no clause list at all. A PARENLESS clause list returns
--     its text exactly as a parenthesised one does -- requirement 6 makes `CLASS fn` legal, and
--     with `body` NULL whenever the parentheses are absent the clause list would just vanish.
--   * `unknown_word` holds the leading word that is in NEITHER registry. Without it,
--     `KID (TYPE 'b')` and `KID TYPE 'b'` would both arrive as op NULL with a body -- which is
--     indistinguishable from a step that has no combinator, so Task 5 could not refuse an
--     unknown combinator BY NAME. HAS and NOT land here too, which is what lets Task 5 refuse a
--     parenless group. This reader adds NO group logic and NO refusal: groups are Task 4's and
--     the refusals are Task 5's.
--
-- "IN NEITHER REGISTRY" IS WELL FORMED ONLY BECAUSE THE TWO KEYWORD SETS ARE DISJOINT. Measured:
-- clause_kinds.keyword INTERSECT combinators.keyword returns 0 rows, and 48_treeql_parse.test
-- asserts it, because requirement 2 depends on it silently.
--
-- THE COMBINATOR KEYWORD IS LOOKED UP IN tree_catalog.combinators, case-insensitively, so there
-- is no list of keywords here: PARENT, ANCESTOR and PRECEDING were added to the engine as rows
-- with no macro changed, and this reader inherits a ninth the same way.
--
-- THE ALIAS COMES OFF FIRST (requirement 3), because `AS` may follow `)`. It is found by an
-- ANCHORED TAIL MATCH and not by tree_treeql_split(step, ' AS '): that splitter compares one
-- character at a time, so a two-character separator matches nothing and returns the step as one
-- part -- the alias would be always NULL and every test without an alias would still pass.
--
-- The anchor is what makes it correct with no depth or quote scan: a quoted or parenthesised `AS`
-- is never followed by a bare identifier at END-OF-STRING. `(ATTR t = 'X AS y')` and
-- `(WHERE CAST(n AS INT) = 1)` both have an `AS` and neither has an alias. The captured token is
-- deliberately LOOSE (`\S+`) and tree_sql_is_ident decides whether it is an alias, so the
-- identifier rule lives in that macro and is not restated here; a token that fails it is not
-- stripped either, and stays in the text for Task 5 to refuse rather than disappearing.
--
-- `(?:^|\s+)` AND NOT `\s+`, because the printer emits a step that is NOTHING BUT an alias.
-- tree_treeql_step is `rtrim(comb? '(' clauses ')'? (' AS ' alias)?)`; with op NULL and clauses
-- NULL the first two parts collapse to '' and rtrim trims only the RIGHT side, so the step prints
-- as ' AS x' and the AS is the first non-space character once this macro has trimmed. `\s+` --
-- R18's original anchor, measured on 11 cases that did not include this shape -- cannot match at
-- position 0, so the alias was missed and `AS` was reported as an unknown leading word: legal
-- printer output refused by name. The shape is reachable through the ordinary constructor, not
-- only by calling the printer by hand, and an alias-only step is OBLIGED to take it: an alias is
-- confined to depth 0, where a written combinator is refused outright.
--
-- Widening to position 0 is also how `AS` could stop being a WORD and become a PREFIX. The two
-- gates for that are in the test file: `ASx y` (a word starting with AS) and `ATTR as = x` (an
-- attribute named `as` with a bare identifier value), each with its own measured wrong fix.
--
-- ONE PATTERN, read at both sites. It was written twice -- once to capture and once to strip --
-- which is the two-copies shape the R19 comment above argues against, and M1's fix had to land on
-- both lines or the alias would be captured and then not stripped. The capture group does not
-- change what the pattern matches, so regexp_replace strips the whole match with the identical
-- pattern and there is nothing left to keep in step.
--
-- KNOWN LIMIT, documented rather than inferred away: a PARENLESS `WHERE n AS m` is genuinely
-- ambiguous and is read as body `WHERE n` with alias `m`. That is a limit for Task 5 to refuse,
-- not something this reader can decide.
--
-- The outer parentheses are stripped when the remainder is ONE parenthesised group, which
-- tree_treeql_wrapped decides by quote-aware depth.
--
-- THAT USED TO BE A FIRST-AND-LAST-CHARACTER TEST, and this comment used to record it as a
-- documented limit owned by Task 5. Task 5 closed it instead, because it was one cause with five
-- effects rather than a corner. "A clause list always starts with a keyword, so a leading '(' is
-- the step's own" establishes the LEADING parenthesis and says nothing about the trailing one
-- being its partner. Measured at BASE, the input that showed the gap:
--
--     tree_treeql_step_parse('(TYPE ''a'') (TYPE ''b'')')  -> body "TYPE 'a') (TYPE 'b'"
--
-- fed on to the clause reader, which yielded a `type` clause whose value was `a') (TYPE 'b` -- a
-- malformed step wearing the shape of a well-formed one. The printer never emits it, so the
-- round-trip contract was safe, but `(TYPE 'a') (CLASS 'b')` is a plausible hand-written mistake,
-- which is the input class requirement 6 exists to serve.
--
-- The depth scan it needed is now tree_treeql_depths, a SCALAR macro returning a list, so this
-- scalar macro can call it; that is why the fix is possible here and was not before. Both shapes
-- keep their text now and are refused by name downstream, and
-- test/sql/48_treeql_parse.test pins the refusals rather than the garbage values.
-- The alias pattern, declared ONCE. It is read at two sites below -- the capture and the strip --
-- and they must not drift apart, because a capture that finds an alias the strip then leaves in
-- the text would report both at once.
--
-- `(?:^|\s+)` and not `\s+`: a step that is NOTHING BUT an alias prints as ` AS x`, because
-- tree_treeql_step uses a right-only rtrim, so after the leading space is trimmed `AS` is the
-- first character and there is no whitespace left in front of it to match.
CREATE OR REPLACE MACRO tree_treeql_as_re() AS '(?i)(?:^|\s+)AS\s+(\S+)\s*$';

-- ONE STEP'S TEXT to {op, body, alias, unknown_word}. The block above this macro's own header
-- documents the four fields, the alias rule and the paren-strip limit; it is long because each
-- part of it is a ruling, and it sits with the code it governs.
CREATE OR REPLACE MACRO tree_treeql_step_parse(txt) AS (
  WITH s0 AS (SELECT trim(txt, tree_treeql_ws()) AS s),
  cap AS (SELECT s, nullif(regexp_extract(s, tree_treeql_as_re(), 1), '') AS tok FROM s0),
  al AS (SELECT s, CASE WHEN tree_sql_is_ident(tok) THEN tok END AS alias FROM cap),
  r AS (SELECT alias,
               trim(CASE WHEN alias IS NULL THEN s
                         ELSE regexp_replace(s, tree_treeql_as_re(), '') END,
                    tree_treeql_ws()) AS rest
        FROM al),
  -- the leading WORD, which is lexing and not identifier validation: it is what the two
  -- registries are consulted about. NULL when the remainder begins with '(' or is empty.
  w AS (SELECT alias, rest, nullif(regexp_extract(rest, '^([A-Za-z_][A-Za-z0-9_]*)', 1), '') AS lead
        FROM r),
  k AS (SELECT alias, rest, lead,
               (SELECT x.op FROM tree_catalog.combinators x WHERE upper(x.keyword) = upper(w.lead)) AS op,
               EXISTS (SELECT 1 FROM tree_catalog.clause_kinds k WHERE upper(k.keyword) = upper(w.lead))
                 AS is_clause
        FROM w),
  -- the leading word is CONSUMED when it is a combinator or an unknown word, and LEFT when it is
  -- a clause keyword -- in that case it is the start of the clause list, not a combinator slot.
  u AS (SELECT alias, rest, lead, op,
               CASE WHEN lead IS NOT NULL AND op IS NULL AND NOT is_clause THEN lead END AS unknown_word
        FROM k),
  t AS (SELECT alias, op, unknown_word,
               trim(CASE WHEN op IS NOT NULL OR unknown_word IS NOT NULL
                         THEN rest[length(lead) + 1 : ] ELSE rest END,
                    tree_treeql_ws()) AS tail
        FROM u)
  SELECT {op: op,
          -- R38/SF-3: the strip now asks tree_treeql_wrapped, which counts quote-aware depth,
          -- instead of testing the FIRST and LAST character. `(TYPE 'b') KID (TYPE 'c')`
          -- satisfied the old test with mismatched parentheses and was stripped into
          -- `TYPE 'b') KID (TYPE 'c'`; it now keeps its text and is refused downstream. The
          -- documented limit two blocks above this macro -- `(TYPE 'a') (CLASS 'b')` read as one
          -- step -- is the same defect and closes with it.
          body: CASE WHEN tail = '' THEN NULL
                     WHEN tree_treeql_wrapped(tail)
                       THEN trim(tail[2 : length(tail) - 1], tree_treeql_ws())
                     ELSE tail END,
          alias: alias,
          unknown_word: unknown_word}
  FROM t);

-- THE GROUP KINDS, derived. A group's printed keyword is `upper(kind)` -- that is literally what
-- tree_selector_to_treeql's grpA pass emits -- so reading a group means recognising a leading word
-- whose lower case is a group kind. There is no registry of them: tree_ir_kinds() writes the four
-- STRUCTURAL kinds out once, and this subtracts the two that are not groups rather than restating
-- HAS and NOT as a second list that could drift from it. Today the answer is ['has', 'not'].
--
-- The two names written here are IR SHAPE, not vocabulary: 'selector' is the root and 'step' is a
-- step, and neither is a set anything extends. The clause kinds and the combinators -- the two
-- sets that ARE open -- are read from their registries and appear nowhere in this file.
CREATE OR REPLACE MACRO tree_treeql_group_kinds() AS
  (SELECT list(k ORDER BY k) FROM (SELECT unnest(tree_ir_kinds()) AS k)
   WHERE k NOT IN ('selector', 'step') AND NOT list_contains(tree_clause_kinds(), k));

-- R23: A GROUP'S INNER CHAIN, split BEFORE each depth-0 combinator keyword, read from
-- tree_catalog.combinators case-insensitively. No keyword is written here, so the chain reader
-- gains a ninth combinator the day a front-end registers one, exactly as the step reader does.
--
-- WHY THE KEYWORDS ARE THE SEPARATOR AND NOT A CHARACTER. The printer joins a group's inner steps
-- with a SINGLE SPACE -- `HAS ( DESCENDANT (TYPE 'b') CHILD (TYPE 'c') )` -- and a space is not a
-- separator anywhere else in TREEQL, so there is no character to split on. What marks a step
-- boundary is the keyword itself, and every inner step has one: tree_steps and tree_steps_group
-- both COALESCE a group chain's combinator to desc, so the printer emits it explicitly even for
-- the first step. The leading span before the first keyword is kept, because hand-written input
-- may omit it; requirement 4 then defaults that step to desc.
--
-- THE CORNER THIS RULE CREATES, recorded here because it is the ruling's consequence and not an
-- oversight: a BARE IDENTIFIER VALUE spelled like a combinator keyword is legal input (D-N15),
-- and this rule cannot tell it from a keyword. `HAS ( CHILD TYPE child )` splits into
-- `CHILD TYPE` and `child`, and `TYPE` with no operand is then refused by name. The alternative
-- considered was to split only before a keyword preceded by ')' or by another keyword; it was
-- measured and REJECTED, because it keeps that corner AND silently returns clean IR for
-- `HAS ( DESCENDANT TYPE x CHILD (TYPE 'b') )` with the type value `x CHILD (TYPE 'b')`. A loud
-- refusal on a legal-but-ambiguous input is worth more than a wrong answer on it. Both forms are
-- parenless, which the printer never emits, so the round-trip contract is untouched either way.
--
-- A WORD, not a prefix: the scan marks maximal runs of identifier characters at paren depth 0 and
-- outside quotes, and compares the WHOLE run to the registry. Comparing a prefix would split
-- `CHILDREN` and `SELFISH`. Depth and quote state come from the same two windows the clause-list
-- splitter uses, for the same reasons -- a keyword inside a nested clause list or inside a quoted
-- value is not a boundary.
--
-- EMPTY SPANS ARE DROPPED here, unlike in the clause-list splitter, where an empty trailing part
-- is a real part. A keyword at position 1 would otherwise answer an empty first step, and an
-- empty inner chain must answer NO steps so that the assembly can refuse the empty group rather
-- than build a group node with nothing under it.
CREATE OR REPLACE MACRO tree_treeql_chain_parts(s) AS (
  WITH chars AS (SELECT i, s[i:i] AS ch FROM (SELECT unnest(range(1, length(s) + 1)) AS i)),
  quoted AS (
    SELECT i, ch,
           (COALESCE(sum(CASE WHEN ch = '''' THEN 1 ELSE 0 END)
              OVER (ORDER BY i ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) % 2) = 1 AS inq
    FROM chars),
  depthed AS (
    SELECT i, ch, inq,
           sum(CASE WHEN inq THEN 0 WHEN ch = '(' THEN 1 WHEN ch = ')' THEN -1 ELSE 0 END)
             OVER (ORDER BY i) AS depth
    FROM quoted),
  wordy AS (SELECT i, ch, depth = 0 AND NOT inq AND regexp_matches(ch, '[A-Za-z0-9_]') AS isw
            FROM depthed),
  -- a word STARTS at an identifier character whose predecessor is not one; `sum` over that marker
  -- then gives every character the id of the word it belongs to
  marked AS (
    SELECT i, ch, isw,
           CASE WHEN isw AND NOT COALESCE(lag(isw) OVER (ORDER BY i), false) THEN 1 ELSE 0 END AS wstart
    FROM wordy),
  ided AS (SELECT i, ch, isw, sum(wstart) OVER (ORDER BY i) AS wid FROM marked),
  words AS (SELECT min(i) AS lo, string_agg(ch, '' ORDER BY i) AS word
            FROM ided WHERE isw GROUP BY wid),
  -- R20: the registry scan is aliased `cb` and NOT `c`. tree_treeql_comb reads
  -- `FROM tree_catalog.combinators c WHERE c.op = want_op`, and inlining puts that `c` in scope;
  -- measured, alias `c` with a column named `op` present makes the predicate self-compare and the
  -- scalar subquery return all eight rows.
  starts AS (
    SELECT lo FROM words
    WHERE EXISTS (SELECT 1 FROM tree_catalog.combinators cb
                  WHERE upper(cb.keyword) = upper(words.word))),
  -- R36: A PARENTHESISED STEP ALSO STARTS A STEP, and the keyword is not the only boundary there
  -- is. The printer emits NO combinator word for an inner step whose op is NULL, so
  -- `HAS ( (TYPE 'b') (TYPE 'c') )` is printer output -- measured -- and with the keyword as the
  -- only boundary the whole chain arrived as ONE step, whose paren strip then produced the type
  -- value `b'') (TYPE ''c`. Clean IR for text that means two steps.
  --
  -- THE RULE: a depth-0 '(' whose previous NON-BLANK character is a depth-0 ')'. That is a
  -- boundary the printer can emit only BETWEEN steps, which is what makes it safe -- inside a
  -- step's clause list every parenthesis is at depth 1 or deeper, so the only ')' that can
  -- precede a depth-0 '(' is the one closing the previous step's own clause list. Measured, the
  -- two ways this could have gone wrong: `CHILD (TYPE 'b')` is NOT split (the previous non-blank
  -- character is `D`), and a ')' inside a quoted value is not one either, because `inq` excludes
  -- it -- `(TYPE 'a ) b') (TYPE 'c')` splits at the real boundary and not at the quoted one.
  --
  -- The previous non-blank character is found by a running max of its POSITION and then one
  -- join, rather than by `lag(... ) IGNORE NULLS`, so the scan stays in the window vocabulary the
  -- rest of this file already uses.
  prevnz AS (SELECT i, ch, inq, depth,
               max(CASE WHEN NOT regexp_matches(ch, '\s') THEN i END)
                 OVER (ORDER BY i ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pj
             FROM depthed),
  opens AS (
    SELECT p.i AS lo
    FROM prevnz p JOIN depthed q ON q.i = p.pj
    WHERE NOT p.inq AND p.ch = '(' AND p.depth = 1
      AND NOT q.inq AND q.ch = ')' AND q.depth = 0),
  -- 1 and length(s) + 1 are sentinels, so one lead() window serves both ends, exactly as in the
  -- clause-list splitter. Here the boundary character is KEPT -- the keyword belongs to the step
  -- it starts -- so the span runs from the boundary itself, not from one past it. UNION, not
  -- UNION ALL: a keyword at position 1 makes the sentinel and the boundary the same position, and
  -- a keyword and a parenthesis boundary can never coincide.
  bounds AS (SELECT 1 AS p UNION SELECT lo FROM starts UNION SELECT lo FROM opens
             UNION SELECT length(s) + 1),
  spans AS (SELECT p AS lo, lead(p) OVER (ORDER BY p) - 1 AS hi FROM bounds),
  spanned AS (SELECT lo, trim(s[lo:hi], tree_treeql_ws()) AS part FROM spans WHERE hi IS NOT NULL),
  kept AS (SELECT CAST(row_number() OVER (ORDER BY lo) AS INTEGER) AS ord, part
           FROM spanned WHERE part <> '')
  SELECT list({ord: ord, part: part} ORDER BY ord) FROM kept);

-- TREEQL TEXT to a TREE_SELECTOR, node ids included. This is the macro that makes the exact
-- theorem true: tree_parse_treeql(tree_selector_to_treeql(sel)) = sel as a WHOLE VALUE.
--
-- HOW THE NUMBERING IS REPRODUCED, and why it is not a counter. tree_steps numbers by sorting a
-- PATH struct {i0, a0, i1, a1, i2, a2} -- `i` the 1-based position in a chain, `a` which of a
-- step's parts comes next -- and taking row_number() over that order. This macro rebuilds the
-- same struct from the TEXT and numbers it the same way, so the two agree by construction rather
-- than by two counters that happen to count alike. Ancestry precedes depth in the key, which is
-- what makes the order depth-first; a row's parent link is its parent's path, so the parent join
-- is one struct comparison and no arithmetic on ids is done anywhere.
--
-- `a` IS THE PART'S TEXTUAL POSITION, NOT tree_steps' SLOT NUMBER, and that is a deliberate
-- difference. Only the RELATIVE order of paths survives row_number(), and the printer emits a
-- step's parts `ORDER BY node_id`, so on canonical IR the textual order of the parts IS their
-- slot order and the two numberings produce identical ids. Reading the slot number instead would
-- need a clause ORDINAL, and the registry has none: measured, tree_clause_kinds() returns the
-- kinds in SCAN order and not in slot order -- the registry has no order column, which
-- test/css_parser.py's CLAUSE_SLOT exemption also records -- so list_position() over it would be
-- wrong, quietly and for most selectors. Clauses are still
-- ordered BEFORE groups (requirement 2) rather than purely by position, which costs nothing and
-- matches the constructor for a hand-written `(HAS ( ... ), TYPE 'a')` as well.
--
-- GROUPS UNROLL, three step levels and two group levels, and do not recurse: DuckDB macros cannot
-- self-recurse, which is the same reason the printer unrolls to the same depth and the same reason
-- TREE_STEP_L0/L1/L2 spell the ceiling out as types. Raising tree_group_depth_limit() means adding
-- one level here, in the printer and in the type list together.
--
-- WHY NOT list_transform. tree_treeql_step_parse and tree_treeql_clause_parse both query the
-- catalog, so both are subqueries, and a subquery is illegal anywhere inside an expression
-- carrying a lambda. Every level is therefore set-based: `unnest()` of the splitters' list forms
-- over a relation, with the readers applied per row.
--
-- THE FIRST STEP OF THE OUTER CHAIN keeps whatever combinator the text gives it, which for
-- printer output is none. A LATER TOP-LEVEL step defaults to desc (requirement 4), which is what
-- tree_steps does. A step of a GROUP's chain does NOT -- see R35 at stp1 below: the printer emits
-- no combinator word for a NULL op, so the no-word form inside a group means NULL and not desc.
--
-- R34: A COMBINATOR WRITTEN ON THE FIRST STEP IS ASSEMBLED AS WRITTEN, and that is adjudicated
-- rather than overlooked. `tree_steps` refuses to BUILD that IR -- measured,
-- `tree_steps([{type: 'a', comb: 'child'}])` raises "the first step takes no combinator" -- but
-- the PRINTER emits `CHILD (TYPE 'a')` for it from hand-built IR, and `parse(print(ir)) = ir` is
-- exactly TRUE for it. A refusal here would therefore reject printer output and break the exact
-- theorem, which is what the Global Constraint forbids. The printer/constructor disagreement is
-- reported to the repo owner instead; this parser stays exactly as tolerant as the host door.
CREATE OR REPLACE MACRO tree_parse_treeql(txt) AS (
WITH
-- LEVEL 0: the top-level chain. Requirement 1 -- the split is on a DEPTH-0 newline, so a newline
-- inside a quoted value or a clause list cannot end a step.
raw0 AS (SELECT (x).ord AS ord, (x).part AS part
         FROM (SELECT unnest(tree_treeql_split_parts(txt, chr(10))) AS x)),
-- R26/R31: A BLANK TOP-LEVEL PART IS DROPPED, WITH ONE EXCEPTION KEPT -- see R31 below, the
-- empty FIRST step. A trailing newline otherwise assembled an INVENTED
-- step -- op 'desc', no clauses -- and that step is not inert: it compiles to a DESCENDANT with
-- no predicate and matches different rows. Every file and every editor adds that newline unasked,
-- and Task 6 reads selector text out of a table where it comes with the data.
--
-- THE TWO SEPARATORS ARE DELIBERATELY NOT SYMMETRIC, which is what keeps this from contradicting
-- R6. R6 makes an empty part in the CLAUSE list a syntax error, and that is right there: the
-- separator is a comma, and nobody types a comma by accident. Here the separator is a NEWLINE,
-- which comes from the medium and not from the author, so dropping it is whitespace tolerance of
-- the same kind that makes keyword case free -- "tolerant input, canonical output". Clause-list
-- behaviour is untouched; an empty clause part still comes back as a part.
--
-- THE RENUMBERING IS LOAD-BEARING. `i0` decides which step is FIRST, and only the first step of
-- the outer chain keeps a NULL combinator. Filter on the splitter's own ordinals and a LEADING
-- newline leaves the surviving step at i0 = 2, which then defaults to desc -- so the selector
-- would gain a combinator its text does not contain. Measured: with the renumbering removed the
-- leading-newline assertion in 48_treeql_parse.test is the one record that fails.
--
-- If this leaves NO parts the selector has no steps, which the refusal set below reports; Task 5
-- owns the wording for it.
--
-- R30: ONE BLANK PART IS NOT NOISE -- THE EMPTY FIRST STEP. A step with no clauses and no
-- combinator prints as NOTHING, and only the FIRST step can be in that position, because every
-- later step carries a combinator the printer emits as a keyword. Measured over the whole empty
-- step space: an empty step LAST prints "(TYPE 'a')\nDESCENDANT" and an empty step in the MIDDLE
-- prints "(TYPE 'a')\nDESCENDANT\nCHILD (TYPE 'b')", both of which already round-tripped; an
-- empty FIRST step prints "\nCHILD (TYPE 'b')", and R26 threw that leading blank away. The
-- printer is injective here, so the theorem was achievable and R26 was simply too wide.
--
-- THE RULE IS COMPLETE AND NOT A PATCH FOR ONE CASE: a leading blank part is an empty first step
-- IFF the next part begins with a combinator keyword. Every other blank part stays dropped, so
-- the trailing newline, the CRLF pair and the blank line between two steps are unaffected.
--
-- WHY THAT TEST IS SOUND. A legitimate first step can never lead with a combinator -- measured,
-- `tree_steps([{comb: 'child', type: 'b'}])` is refused by name with "the first step takes no
-- combinator" -- so the only reading this rule takes away is input the constructor already
-- rejects. The keyword is resolved by tree_treeql_step_parse, which looks the leading word up in
-- tree_catalog.combinators (R23), so no keyword is written here and the lexing is not restated.
--
-- BOTH HALVES OF THIS RULE ARE GATED, shown by mutation rather than argued. The records are
-- named by their INPUT and not by line, because adding a comment above them moves the line
-- and the citation goes stale -- which is exactly what happened to the first draft of this
-- very block.
--
-- Replacing the combinator lookup with "any leading word"
-- (`regexp_matches(nxt, '^[A-Za-z_]')`) fails exactly ONE record in 48_treeql_parse.test:
-- `chr(10) || 'TYPE ''a'''`, whose next part is a CLAUSE keyword. That record is the only one
-- separating this rule from the sloppier one, which is why it exists.
--
-- Dropping the test entirely, leaving a bare `ord = 1`, fails THREE: that same record, the
-- `chr(10) || '(TYPE ''a'')'` one, and the `tree_parse_treeql('')` refusal -- the last
-- because a lone blank part then survives and the no-steps arm stops firing.
--
-- Both counts were predicted before the mutants were run.
--
-- A LONE blank part is deliberately NOT kept: `nxt` is NULL for it, so a selector that is
-- nothing but an empty step stays unreadable. It has to -- it prints as the empty string, and no
-- parser can recover a step from no characters. That it can be BUILT at all is a gap in
-- tree_steps, which this task may not edit.
mark0 AS (SELECT ord, part,
            trim(part, tree_treeql_ws()) = '' AS blank,
            lead(part) OVER (ORDER BY ord) AS nxt
          FROM raw0),
lvl0 AS (SELECT CAST(row_number() OVER (ORDER BY ord) AS INTEGER) AS i0, part
         FROM mark0
         WHERE NOT blank
            OR (ord = 1 AND (tree_treeql_step_parse(nxt)).op IS NOT NULL)),
rd0 AS (SELECT i0, part, tree_treeql_step_parse(part) AS p FROM lvl0),
stp0 AS (SELECT i0, part,
           CASE WHEN i0 = 1 THEN (p).op ELSE COALESCE((p).op, 'desc') END AS op,
           (p).body AS body, (p).alias AS alias, (p).unknown_word AS uw
         FROM rd0),
pt0 AS (SELECT i0, (x).ord AS n, (x).part AS part
        FROM (SELECT i0, unnest(tree_treeql_split_parts(body, ',')) AS x
              FROM stp0 WHERE body IS NOT NULL)),
-- A PART IS A CLAUSE OR A GROUP, and the two readers are asked in that order: a clause keyword is
-- never a group keyword (the registries are disjoint and 48_treeql_parse.test asserts it), so a
-- part the clause reader claims cannot also be a group. A part the clause reader returns NULL for
-- is a group when its LEADING WORD is a group kind -- which is exactly what Task 3 leaves in
-- unknown_word.
cg0 AS (SELECT i0, n, part, tree_treeql_clause_parse(part) AS cl,
               tree_treeql_step_parse(part) AS gp
        FROM pt0),
-- `gtail` reads the parentheses off the RAW part text on purpose. tree_treeql_step_parse STRIPS
-- them, so after it `HAS ( X )` and `HAS X` carry the same body, and a parenless group would be
-- built from a chain nobody wrote instead of refused.
kd0 AS (SELECT i0, n, part, cl,
          CASE WHEN cl IS NULL AND (gp).unknown_word IS NOT NULL
                    AND list_contains(tree_treeql_group_kinds(), lower((gp).unknown_word))
               THEN lower((gp).unknown_word) END AS gkind,
          (gp).unknown_word AS guw, (gp).body AS gbody,
          CASE WHEN (gp).unknown_word IS NOT NULL
               THEN trim(part[length((gp).unknown_word) + 1 : ], tree_treeql_ws()) END AS gtail
        FROM cg0),
sl0 AS (SELECT *, CAST(row_number() OVER (PARTITION BY i0
            ORDER BY CASE WHEN gkind IS NULL THEN 0 ELSE 1 END, n) AS INTEGER) AS a0
        FROM kd0),
gr0 AS (SELECT i0, a0, gkind, gbody FROM sl0 WHERE gkind IS NOT NULL),

-- LEVEL 1: each depth-1 group's inner chain, and the same four passes over it.
lvl1 AS (SELECT i0, a0, (x).ord AS i1, (x).part AS part
         FROM (SELECT i0, a0, unnest(tree_treeql_chain_parts(gbody)) AS x FROM gr0)),
rd1 AS (SELECT i0, a0, i1, part, tree_treeql_step_parse(part) AS p FROM lvl1),
-- R35: AN INNER STEP WITH NO COMBINATOR WORD KEEPS op NULL. There is no `desc` default here any
-- more, and its absence is the ruling rather than an omission. The printer writes no combinator
-- word for an inner step whose op is NULL -- measured, it emits `(TYPE 'a', HAS ( (TYPE 'b') ))`
-- for that IR -- so coalescing to desc made `print(parse(print(ir)))` differ from `print(ir)` and
-- the normalising theorem FALSE for it. The printer is the specification.
--
-- WHAT COVERS THE INPUT THE DEFAULT USED TO: a PARENLESS inner step with no combinator is now
-- refused by name (R36), because nothing separates its clause list from the next step's, and a
-- PARENTHESISED one is unambiguous and lands here with op NULL. So every text the default could
-- still have applied to is either refused or has a combinator of its own, and
-- test/sql/48_treeql_parse.test gates that by re-adding the COALESCE as a mutant.
--
-- The TOP-LEVEL default in stp0 is untouched: there the separator is a newline, the first step is
-- the only one that may carry no combinator, and R35 is scoped to inner steps.
stp1 AS (SELECT i0, a0, i1, part, (p).op AS op,
           (p).body AS body, (p).alias AS alias, (p).unknown_word AS uw
         FROM rd1),
pt1 AS (SELECT i0, a0, i1, (x).ord AS n, (x).part AS part
        FROM (SELECT i0, a0, i1, unnest(tree_treeql_split_parts(body, ',')) AS x
              FROM stp1 WHERE body IS NOT NULL)),
cg1 AS (SELECT i0, a0, i1, n, part, tree_treeql_clause_parse(part) AS cl,
               tree_treeql_step_parse(part) AS gp
        FROM pt1),
kd1 AS (SELECT i0, a0, i1, n, part, cl,
          CASE WHEN cl IS NULL AND (gp).unknown_word IS NOT NULL
                    AND list_contains(tree_treeql_group_kinds(), lower((gp).unknown_word))
               THEN lower((gp).unknown_word) END AS gkind,
          (gp).unknown_word AS guw, (gp).body AS gbody,
          CASE WHEN (gp).unknown_word IS NOT NULL
               THEN trim(part[length((gp).unknown_word) + 1 : ], tree_treeql_ws()) END AS gtail
        FROM cg1),
sl1 AS (SELECT *, CAST(row_number() OVER (PARTITION BY i0, a0, i1
            ORDER BY CASE WHEN gkind IS NULL THEN 0 ELSE 1 END, n) AS INTEGER) AS a1
        FROM kd1),
gr1 AS (SELECT i0, a0, i1, a1, gkind, gbody FROM sl1 WHERE gkind IS NOT NULL),

-- LEVEL 2: the last level tree_group_depth_limit() allows. Its steps may carry clauses and they
-- may carry a group KEYWORD, but a group here has nowhere to go -- so the group's own node is
-- still emitted below and its inside is never read. That is what lets the depth measure see 3.
lvl2 AS (SELECT i0, a0, i1, a1, (x).ord AS i2, (x).part AS part
         FROM (SELECT i0, a0, i1, a1, unnest(tree_treeql_chain_parts(gbody)) AS x FROM gr1)),
rd2 AS (SELECT i0, a0, i1, a1, i2, part, tree_treeql_step_parse(part) AS p FROM lvl2),
-- R35 again, at the second group level. The rule is the chain reader's and not the level's, so it
-- is the same rule here; the block above stp1 carries it.
stp2 AS (SELECT i0, a0, i1, a1, i2, part, (p).op AS op,
           (p).body AS body, (p).alias AS alias, (p).unknown_word AS uw
         FROM rd2),
pt2 AS (SELECT i0, a0, i1, a1, i2, (x).ord AS n, (x).part AS part
        FROM (SELECT i0, a0, i1, a1, i2, unnest(tree_treeql_split_parts(body, ',')) AS x
              FROM stp2 WHERE body IS NOT NULL)),
cg2 AS (SELECT i0, a0, i1, a1, i2, n, part, tree_treeql_clause_parse(part) AS cl,
               tree_treeql_step_parse(part) AS gp
        FROM pt2),
kd2 AS (SELECT i0, a0, i1, a1, i2, n, part, cl,
          CASE WHEN cl IS NULL AND (gp).unknown_word IS NOT NULL
                    AND list_contains(tree_treeql_group_kinds(), lower((gp).unknown_word))
               THEN lower((gp).unknown_word) END AS gkind,
          (gp).unknown_word AS guw, (gp).body AS gbody,
          CASE WHEN (gp).unknown_word IS NOT NULL
               THEN trim(part[length((gp).unknown_word) + 1 : ], tree_treeql_ws()) END AS gtail
        FROM cg2),
sl2 AS (SELECT *, CAST(row_number() OVER (PARTITION BY i0, a0, i1, a1, i2
            ORDER BY CASE WHEN gkind IS NULL THEN 0 ELSE 1 END, n) AS INTEGER) AS a2
        FROM kd2),

-- EVERY NODE AT EVERY LEVEL as one relation, each carrying its own path and its parent's path.
-- Requirement 2's pre-order falls out of the struct order and is not re-stated as a traversal.
nodes AS (
  -- the root: a ppath no row carries, so the parent join leaves its parent_id NULL. Its value is
  -- this front-end's name -- the provenance tree_selector_language reads back (requirement 3).
  -- Canonical IR already carries it, which is what leaves the exact theorem undisturbed.
  SELECT {i0: 0, a0: 0, i1: 0, a1: 0, i2: 0, a2: 0} AS path,
         {i0: -1, a0: 0, i1: 0, a1: 0, i2: 0, a2: 0} AS ppath,
         'selector' AS kind, 'treeql'::VARCHAR AS value, NULL::VARCHAR AS op,
         NULL::VARCHAR AS arg, NULL::VARCHAR AS alias
  UNION ALL SELECT {i0: i0, a0: 0, i1: 0, a1: 0, i2: 0, a2: 0},
                   {i0: 0, a0: 0, i1: 0, a1: 0, i2: 0, a2: 0},
                   'step', NULL, op, NULL, alias FROM stp0
  UNION ALL SELECT {i0: i0, a0: a0, i1: 0, a1: 0, i2: 0, a2: 0},
                   {i0: i0, a0: 0, i1: 0, a1: 0, i2: 0, a2: 0},
                   (cl).kind, (cl).value, (cl).op, (cl).arg, NULL FROM sl0 WHERE cl IS NOT NULL
  UNION ALL SELECT {i0: i0, a0: a0, i1: 0, a1: 0, i2: 0, a2: 0},
                   {i0: i0, a0: 0, i1: 0, a1: 0, i2: 0, a2: 0},
                   gkind, NULL, NULL, NULL, NULL FROM sl0 WHERE gkind IS NOT NULL
  UNION ALL SELECT {i0: i0, a0: a0, i1: i1, a1: 0, i2: 0, a2: 0},
                   {i0: i0, a0: a0, i1: 0, a1: 0, i2: 0, a2: 0},
                   'step', NULL, op, NULL, alias FROM stp1
  UNION ALL SELECT {i0: i0, a0: a0, i1: i1, a1: a1, i2: 0, a2: 0},
                   {i0: i0, a0: a0, i1: i1, a1: 0, i2: 0, a2: 0},
                   (cl).kind, (cl).value, (cl).op, (cl).arg, NULL FROM sl1 WHERE cl IS NOT NULL
  UNION ALL SELECT {i0: i0, a0: a0, i1: i1, a1: a1, i2: 0, a2: 0},
                   {i0: i0, a0: a0, i1: i1, a1: 0, i2: 0, a2: 0},
                   gkind, NULL, NULL, NULL, NULL FROM sl1 WHERE gkind IS NOT NULL
  UNION ALL SELECT {i0: i0, a0: a0, i1: i1, a1: a1, i2: i2, a2: 0},
                   {i0: i0, a0: a0, i1: i1, a1: a1, i2: 0, a2: 0},
                   'step', NULL, op, NULL, alias FROM stp2
  UNION ALL SELECT {i0: i0, a0: a0, i1: i1, a1: a1, i2: i2, a2: a2},
                   {i0: i0, a0: a0, i1: i1, a1: a1, i2: i2, a2: 0},
                   (cl).kind, (cl).value, (cl).op, (cl).arg, NULL FROM sl2 WHERE cl IS NOT NULL
  -- the TOO-DEEP group: its node and nothing under it, so tree_selector_group_depth below
  -- measures tree_group_depth_limit() + 1 and the refusal fires. Dropping it instead would leave
  -- a selector measuring exactly the limit, the arm would never fire, and the innermost group
  -- would be silently lost -- which is the failure that refusal exists to prevent.
  UNION ALL SELECT {i0: i0, a0: a0, i1: i1, a1: a1, i2: i2, a2: a2},
                   {i0: i0, a0: a0, i1: i1, a1: a1, i2: i2, a2: 0},
                   gkind, NULL, NULL, NULL, NULL FROM sl2 WHERE gkind IS NOT NULL),
-- every path is unique, so the parent link is one struct comparison. The cast to INTEGER is
-- load-bearing: row_number() is BIGINT, and TREE_SELECTOR's node_id is INTEGER, so without it
-- whole-value equality against canonical IR fails on TYPE alone.
nmb AS (SELECT CAST(row_number() OVER (ORDER BY path) - 1 AS INTEGER) AS node_id, * FROM nodes),
prt AS (SELECT n.node_id, p.node_id AS parent_id, n.kind, n.value, n.op, n.arg, n.alias
        FROM nmb n LEFT JOIN nmb p ON p.path = n.ppath),
asm AS (SELECT list({node_id: node_id, parent_id: parent_id, kind: kind, value: value,
                     op: op, arg: arg, alias: alias} ORDER BY node_id)::TREE_SELECTOR AS v
        FROM prt),
-- THE REFUSALS. R25 left Task 4's one provisional message here -- `cannot read <fragment>` --
-- holding an INVARIANT rather than a vocabulary: nothing the assembly cannot build returns clean
-- IR, and the message names the offending text so that this task could specialise without
-- re-deriving it. It did; the invariant is unchanged and the generic message survives as the
-- catch-all for a fault that carries no word worth naming.
--
-- WHAT IS NEW HERE, beside the wording: two faults that were not refused at all, because the
-- reader returned clean IR for them. An unterminated quoted value and a parenless inner step
-- both parsed, silently and wrongly, so the arms for them required fixing tree_treeql_depths'
-- two callers first. R38 has the measurements.
--
-- EVERY RULE IS ROUTED THROUGH ITS EXISTING HOLDER rather than restated: tree_sql_is_ident for
-- an alias (inside tree_treeql_step_parse), tree_selector_group_depth against
-- tree_group_depth_limit() for nesting, tree_treeql_group_kinds() for HAS and NOT, and the two
-- catalog registries for the two open vocabularies. No clause kind and no combinator keyword
-- appears in this file.
--
-- THE STEPS WHOSE LEADING WORD IS IN NEITHER REGISTRY, at all three levels, with the raw tail
-- the word was taken off. The tail is re-derived from `part` and NOT read from `body`, for the
-- same reason `gtail` is below: tree_treeql_step_parse STRIPS the parentheses, so after it
-- `HAS ( X )` and `HAS X` carry the same body and the one difference that matters is gone.
uws AS (SELECT part, uw, body, trim(part[length(uw) + 1 : ], tree_treeql_ws()) AS utail
        FROM stp0 WHERE uw IS NOT NULL
        UNION ALL SELECT part, uw, body, trim(part[length(uw) + 1 : ], tree_treeql_ws())
        FROM stp1 WHERE uw IS NOT NULL
        UNION ALL SELECT part, uw, body, trim(part[length(uw) + 1 : ], tree_treeql_ws())
        FROM stp2 WHERE uw IS NOT NULL),
-- R37: DOES WHAT FOLLOWS THE UNKNOWN WORD READ AS A LEGAL CLAUSE LIST? That one question
-- separates an unknown COMBINATOR from an unknown CLAUSE KEYWORD, and it is asked of the clause
-- reader rather than guessed from the word's shape. Measured: `SIDEWAYS (TYPE 'b')` leaves the
-- body `TYPE 'b'`, which reads as a clause, so SIDEWAYS was meant to be a combinator;
-- `FROBNICATE 'x'` leaves `'x'`, which does not, so FROBNICATE was meant to be a clause keyword.
--
-- EVERY part must read as a clause, which is why this is a count and not an EXISTS: a body of
-- `TYPE 'a', 42` is not a legal clause list, and naming SIDEWAYS an unknown combinator there
-- would point at the wrong token.
uwp AS (SELECT part, uw, (x).part AS cpart
        FROM (SELECT part, uw, unnest(tree_treeql_split_parts(body, ',')) AS x
              FROM uws WHERE body IS NOT NULL)),
uwc AS (SELECT part, uw,
               count(*) FILTER (WHERE tree_treeql_clause_parse(cpart) IS NOT NULL) = count(*)
                 AS body_is_clauses
        FROM uwp GROUP BY part, uw),
-- A LEFT JOIN and not a correlated EXISTS: R22's binder wall is an inner correlated subquery, and
-- every caller of this macro from Task 6 on passes a COLUMN. A step with no body at all (`KID`
-- printed bare) has no uwp rows, so COALESCE decides it, and `false` sends it to the clause-keyword
-- arm -- R37's third rule, which is what "else" means there.
uwk AS (SELECT u.part, u.uw, u.utail,
               list_contains(tree_treeql_group_kinds(), lower(u.uw)) AS is_group,
               COALESCE(c.body_is_clauses, false) AS body_is_clauses
        FROM uws u LEFT JOIN uwc c ON c.part = u.part AND c.uw = u.uw),
-- EVERY CLAUSE-LIST PART AT EVERY LEVEL as one relation, so each rule below is written once
-- instead of three times. The three sl CTEs were the three copies the old refusal set carried.
cps AS (SELECT part, cl, gkind, gtail, gbody FROM sl0
        UNION ALL SELECT part, cl, gkind, gtail, gbody FROM sl1
        UNION ALL SELECT part, cl, gkind, gtail, gbody FROM sl2),
-- EVERY FAULT, CLASSIFIED. Task 4 left one generic message here and R25 said Task 5 owns the
-- wording; this is that wording. Each row carries its CODE and the offending FRAGMENT, and the
-- CASE below reads them in priority order.
--
-- WHY A PRIORITY ORDER AND NOT min() ALONE. One input can carry more than one fault, and the old
-- `min(f)` picked the alphabetically smallest FRAGMENT -- arbitrary once the messages differ.
-- ONE ordering is load-bearing and one is not, both measured by mutation:
--   * PARENLESS BEFORE GENERIC is GATED, because `HAS ( TYPE 'b' TYPE 'c' )` is ALSO a clause
--     whose literal cannot be read, and `cannot read TYPE 'b' TYPE 'c'` names the symptom instead
--     of the mistake. Silencing the parenless arm fails three records.
--   * UNTERMINATED BEFORE UNBALANCED is NOT gated since the odd-quote stand-down. The reasoning
--     holds -- an unterminated quote stops the parentheses after it from being counted, so a
--     quote fault presents as a paren fault -- but tree_treeql_balanced now stands down on an odd
--     count, so the input that needed the order never reaches the unbalanced arm. Measured:
--     swapping the two arms now fails ZERO records, where before the stand-down it failed one.
--     Kept as the correct order if that stand-down is ever narrowed, and named UNGATED here so
--     the harmless swap is not mistaken for the arms being interchangeable.
-- The order lives in the CASE below, where it is visible, and not in a sort key here.
prob AS (
  -- NO STEPS AT ALL. R26 drops a blank top-level part, so empty, whitespace-only and NULL text
  -- all arrive here. The fragment is unused by this message and is kept non-NULL anyway, because
  -- a NULL fragment in a GROUP BY row would make the arm's test miss.
      SELECT 'nosteps' AS code, COALESCE(txt, '<NULL>') AS frag
        WHERE NOT EXISTS (SELECT 1 FROM lvl0)
  -- AN UNTERMINATED QUOTED VALUE, detected as an ODD number of quote characters in one part.
  --
  -- WHY PARITY AND NOT tree_treeql_lit_ok, WHICH IS A NARROWING OF R38. R38's anchored pattern
  -- says whether a body is a well-formed literal; it does not say WHY it is not one. Both of
  -- R38's own named inputs -- `TYPE 'a` and `TYPE 'it''s` -- have an odd quote count, because a
  -- quote was opened and never closed, and that is what "unterminated" states. An EVEN count
  -- that still fails the pattern is a different fault: `TYPE 'a' SIDEWAYS TYPE 'b'` closed every
  -- quote it opened and then carried trailing text, so calling it unterminated would tell the
  -- author the wrong thing. Those go to the generic arm below, which names the fragment and
  -- claims nothing about the cause. Refused either way -- that is R38's requirement.
  --
  -- CANNOT REJECT PRINTER OUTPUT, and the OTHER TWO THIRDS of this condition are what make that
  -- true. A part's quote count is evidence about a VALUE only when the part IS a value; this rule
  -- shipped twice believing otherwise, so the reasoning is written out rather than summarised.
  --
  -- A WHERE OR ATTR BODY IS NOT A LITERAL. The printer emits it unquoted and unescaped -- see this
  -- file's header -- so it never passes through tree_sql_lit and its quote count can be ODD.
  -- Measured, from the ordinary constructor: `(WHERE "o'k" = 1)`, a double-quoted IDENTIFIER
  -- holding an apostrophe, legal DuckDB SQL, and it round-tripped at BASE. So `lit_ok` decides a
  -- clause part, because tree_treeql_clause_parse already answers "is this body's quoting well
  -- formed, FOR THIS KIND" and that is the holder of the per-kind rule.
  --
  -- AND A GROUP PART IS NOT A VALUE EITHER, which is the second defect of the same shape and the
  -- one `lit_ok` alone did not stop. A group part carries a whole nested CHAIN, so any WHERE body
  -- anywhere inside it contributes to the part's count -- measured, the printer emits
  -- `(TYPE 'a', HAS ( DESCENDANT (TYPE 'b', WHERE "o'k" = 1) ))` with FIVE quotes, `cl` is NULL
  -- because a group is not a clause, and the rule fired on a part whose own quoting is perfect.
  -- `gkind IS NULL` excludes it: a part the assembly reads as a group is judged by the group
  -- rules, never by counting characters across its contents. An unterminated value INSIDE the
  -- group is still caught, by this same rule applied to the inner part at the inner level.
  --
  -- WHAT IS LEFT, and it is the only shape where the count is evidence: a part that is a
  -- value-carrying clause whose literal is malformed (`TYPE 'a`), or a part the readers could make
  -- nothing of at all (`(TYPE 'c`). Neither can be printer output.
  UNION ALL SELECT 'unterminated', part FROM cps
        WHERE NOT tree_treeql_quotes_even(part)
          AND gkind IS NULL
          AND (cl IS NULL OR NOT (cl).lit_ok)
  -- UNBALANCED PARENTHESES, counted quote-aware over the WHOLE input. It runs AFTER the
  -- unterminated arm deliberately: an unterminated quote swallows the rest of the text, so the
  -- parentheses after it stop being counted and a quote fault LOOKS like a paren fault.
  -- Measured, the input that shows it: `(CLASS 'f', HAS ( CHILD (TYPE 'b') ))<LF>CHILD (TYPE 'c`
  -- is unbalanced only because the value never closed.
  --
  -- CANNOT REJECT PRINTER OUTPUT: the printer emits '(' and ')' only as a matched pair, and a
  -- value's own parenthesis is inside a literal, where tree_treeql_depths does not count it.
  UNION ALL SELECT 'unbalanced', COALESCE(txt, '<NULL>') WHERE NOT tree_treeql_balanced(txt)
  -- A GROUP WHOSE CHAIN IS NOT PARENTHESISED (R37's first rule). Two shapes, one message: the
  -- group keyword as a clause-list PART, which is the shape the printer emits, and as a STEP's
  -- leading word.
  --
  -- NARROWED TO THE UNWRAPPED TAIL, which R37's wording does not say and which measurement
  -- requires. `HAS ( )` HAS its parentheses, and so does a top-level bare `HAS ( (TYPE 'b') )`;
  -- telling their author to add parentheses that are already there is worse than saying nothing.
  -- Both fall to the generic arm instead.
  --
  -- CANNOT REJECT PRINTER OUTPUT: tree_selector_to_treeql's group pass emits
  -- `upper(kind) || ' ( ' || chain || ' )'` at every level, so a printed group always wraps.
  UNION ALL SELECT 'groupparen', part FROM cps
        WHERE gkind IS NOT NULL AND NOT tree_treeql_wrapped(gtail)
  UNION ALL SELECT 'groupparen', uw FROM uwk
        WHERE is_group AND NOT tree_treeql_wrapped(utail)
  -- A PARENLESS INNER STEP WITH NO COMBINATOR (R36). Inside a group the steps are separated by a
  -- SPACE, so a step with neither a combinator keyword nor parentheses has nothing marking where
  -- its clause list ends and the next step's begins. At BASE this returned clean IR:
  -- `HAS ( TYPE 'b' TYPE 'c' )` became one type clause whose value was `b' TYPE 'c`.
  --
  -- LEVELS 1 AND 2 ONLY, never level 0: a parenless clause list at top level is requirement 6 --
  -- `CLASS fn` is legal -- and there the separator is a newline, which marks the boundary this
  -- rule is about.
  --
  -- `part NOT LIKE '(%'` IS THE TEST, so this says "parenless" and nothing more. A step whose
  -- text starts with '(' but does not WRAP is a different fault and goes to the generic arm, where
  -- the message names the fragment instead of asking for parentheses it has.
  --
  -- CANNOT REJECT PRINTER OUTPUT: tree_treeql_step wraps a step's clause list in parentheses
  -- whenever the step HAS one, so a printed step with clauses and no combinator word always
  -- carries its own parentheses and this rule requires their absence.
  UNION ALL SELECT 'parenless', part FROM stp1
        WHERE op IS NULL AND uw IS NULL AND part NOT LIKE '(%'
  UNION ALL SELECT 'parenless', part FROM stp2
        WHERE op IS NULL AND uw IS NULL AND part NOT LIKE '(%'
  -- AN UNKNOWN COMBINATOR, and AN UNKNOWN CLAUSE KEYWORD: R37's second and third rules. The
  -- message names the OFFENDING WORD. At BASE it named the remainder -- `FROBNICATE 'x'` refused
  -- with `cannot read 'x'`, pointing at the operand.
  --
  -- CANNOT REJECT PRINTER OUTPUT: both registries are read from the catalog, case-insensitively,
  -- so every keyword the printer can emit is known to this test and a front-end that registers a
  -- ninth combinator is accepted the day the row lands.
  UNION ALL SELECT 'comb', uw FROM uwk WHERE NOT is_group AND body_is_clauses
  UNION ALL SELECT 'kw',   uw FROM uwk WHERE NOT is_group AND NOT body_is_clauses
  -- EVERYTHING ELSE, which keeps Task 4's generic message as the CATCH-ALL rather than replacing
  -- it. A fault that carries no offending word has nothing for a specialised message to name, and
  -- `cannot read <fragment>` is the honest answer: a part that is neither a clause nor a group
  -- (`42`), a clause keyword with no operand (`TYPE`), an EMPTY group, a group whose tail wraps
  -- but whose chain is unreadable, and a clause whose literal is malformed with its quotes
  -- balanced.
  --
  -- CANNOT REJECT PRINTER OUTPUT: this is the arm Task 4 shipped and the 18 corpus selectors
  -- round-trip through it untouched; every row here is a shape the assembly cannot build.
  UNION ALL SELECT 'generic', part FROM cps WHERE cl IS NULL AND gkind IS NULL
  UNION ALL SELECT 'generic', part FROM cps WHERE cl IS NOT NULL AND NOT (cl).lit_ok
  UNION ALL SELECT 'generic', part FROM cps
        WHERE gkind IS NOT NULL AND tree_treeql_chain_parts(gbody) IS NULL
  UNION ALL SELECT 'generic', part FROM uwk
        WHERE is_group AND tree_treeql_wrapped(utail)),
-- ONE ROW PER CODE, so each arm below is one scalar read. `n` and not `frag IS NOT NULL` decides
-- whether an arm fires: a rule whose fragment went NULL would otherwise be SILENTLY SKIPPED, and
-- absence of signal is not success.
pb AS (SELECT code, count(*) AS n, min(frag) AS frag FROM prob GROUP BY code)
SELECT CASE
  -- requirement 5, and FIRST: the depth is measured on the ASSEMBLED selector with
  -- tree_selector_group_depth against tree_group_depth_limit(), which is what the printer and
  -- tree_steps_group both do, and the wording is the printer's own. It comes before every other
  -- arm so that a selector nested too deep is always refused in those words.
  WHEN tree_selector_group_depth((SELECT v FROM asm)) > tree_group_depth_limit()
    THEN tree_err('tree_parse_treeql: groups nested deeper than ' || tree_group_depth_limit()
                  || ' levels are not supported')
  -- THE ARM ORDER IS THE PRIORITY ORDER. Every concatenated piece is COALESCEd: a NULL anywhere
  -- in a refusal message makes the whole message NULL, which tree_err reports as "refusal with a
  -- NULL message" -- losing the one sentence the caller needed. This repo has shipped that twice.
  WHEN (SELECT n FROM pb WHERE code = 'nosteps') > 0
    THEN tree_err('tree_parse_treeql: selector has no steps')
  WHEN (SELECT n FROM pb WHERE code = 'unterminated') > 0
    THEN tree_err('tree_parse_treeql: unterminated quoted value')
  WHEN (SELECT n FROM pb WHERE code = 'unbalanced') > 0
    THEN tree_err('tree_parse_treeql: unbalanced parentheses')
  WHEN (SELECT n FROM pb WHERE code = 'groupparen') > 0
    THEN tree_err('tree_parse_treeql: HAS/NOT needs parentheses around its chain')
  WHEN (SELECT n FROM pb WHERE code = 'parenless') > 0
    THEN tree_err('tree_parse_treeql: a step inside HAS/NOT needs a combinator or parentheses, '
                  || 'so its clauses can be told from the next step''s')
  WHEN (SELECT n FROM pb WHERE code = 'comb') > 0
    THEN tree_err('tree_parse_treeql: unknown combinator '
                  || COALESCE((SELECT frag FROM pb WHERE code = 'comb'), '<NULL>'))
  WHEN (SELECT n FROM pb WHERE code = 'kw') > 0
    THEN tree_err('tree_parse_treeql: unknown clause keyword '
                  || COALESCE((SELECT frag FROM pb WHERE code = 'kw'), '<NULL>'))
  WHEN (SELECT n FROM pb WHERE code = 'generic') > 0
    THEN tree_err('tree_parse_treeql: cannot read '
                  || COALESCE((SELECT frag FROM pb WHERE code = 'generic'), '<NULL>'))
  ELSE (SELECT v FROM asm) END);
