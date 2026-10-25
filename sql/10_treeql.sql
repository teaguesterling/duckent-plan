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
CREATE OR REPLACE MACRO tree_treeql_split(s, sep) AS TABLE (
  WITH chars AS (SELECT i, s[i:i] AS c FROM generate_series(1, length(s)) t(i)),
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
  seps AS (SELECT i FROM depthed WHERE c = sep AND NOT inq AND depth = 0),
  bounds AS (SELECT 0 AS lo UNION ALL SELECT i FROM seps),
  spans AS (
    SELECT lo + 1 AS lo,
           COALESCE((SELECT min(i) FROM seps WHERE i > b.lo), length(s) + 1) - 1 AS hi
    FROM bounds b)
  -- The part TEXT and the part BOUNDARIES are the two whitespace-sensitive things here, and only
  -- one of them turned out to be sensitive: the boundaries come from separator position alone,
  -- and whitespace moves neither the quote parity nor the paren depth. Measured over whitespace
  -- after a separator, before a separator, at both ends of the input, and alone in a trailing
  -- part: the full character set on this one trim answers all four.
  SELECT row_number() OVER (ORDER BY lo) AS ord,
         trim(s[lo:hi], tree_treeql_ws()) AS part
  FROM spans ORDER BY lo);

-- The printer's literal form, undone: '...' with '' for an embedded quote. A bare identifier
-- (D-N15, decided 2026-10-15: accepted on input, never emitted) has no quotes to strip and
-- passes through, which is why the test is on the delimiters and not on the content.
CREATE OR REPLACE MACRO tree_treeql_unlit(v) AS
  CASE WHEN v LIKE '''%''' THEN replace(v[2:length(v)-1], '''''', '''') ELSE v END;

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
                  arg:   CASE kind WHEN 'attr' THEN m.arg END}
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
-- The outer parentheses are stripped when the remainder both starts with '(' and ends with ')'.
--
-- THAT IS NOT A BALANCE CHECK, AND THIS COMMENT USED TO CLAIM MORE THAN THE CODE DOES. "A clause
-- list always starts with a keyword, so a leading '(' is the step's own" establishes the LEADING
-- parenthesis and says nothing about the trailing one being its partner. Measured, the input that
-- shows the gap:
--
--     tree_treeql_step_parse('(TYPE ''a'') (TYPE ''b'')')  -> body "TYPE 'a') (TYPE 'b'"
--
-- and fed on to the clause reader that yields a `type` clause whose value is `a') (TYPE 'b` --
-- a malformed step wearing the shape of a well-formed one. The printer never emits this, so the
-- round-trip contract is safe, but `(TYPE 'a') (CLASS 'b')` is a plausible hand-written mistake,
-- which is the input class requirement 6 exists to serve.
--
-- NO BALANCE CHECK IS ADDED, and that is adjudicated rather than overlooked: a real check needs
-- the depth scan, which lives in a TABLE macro and cannot be called from this scalar one, and the
-- two refusals already exist downstream. R6 makes unbalanced parentheses Task 5's, and R13 makes
-- "a value still carrying its delimiters" a named refusal -- which is what that garbage value is.
-- So this is a DOCUMENTED LIMIT owned by Task 5, not a defect this macro hides. No test pins the
-- garbage value: pinning it would enshrine a wrong answer as the intended one.
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
          body: CASE WHEN tail = '' THEN NULL
                     WHEN tail LIKE '(%' AND tail LIKE '%)'
                       THEN trim(tail[2 : length(tail) - 1], tree_treeql_ws())
                     ELSE tail END,
          alias: alias,
          unknown_word: unknown_word}
  FROM t);
