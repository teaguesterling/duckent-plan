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
CREATE OR REPLACE MACRO tree_treeql_ws() AS ' ' || chr(9) || chr(10) || chr(13);

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
                 '^([A-Za-z_][A-Za-z0-9_]*)(?:\s*(<=|>=|<>|!=|=|<|>)|\s+((?i)NOT\s+LIKE|ILIKE|LIKE)\b)\s*(?s)(.+)$',
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
