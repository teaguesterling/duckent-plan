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
  SELECT row_number() OVER (ORDER BY lo) AS ord, trim(s[lo:hi]) AS part FROM spans ORDER BY lo);

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
-- The match is on `upper(keyword) || ' %'` rather than on a prefix, so a keyword is only
-- recognised when followed by a body -- a bare `TYPE` with no operand falls through to NULL and
-- is refused by name in Task 5 rather than parsing to a clause with no value.
CREATE OR REPLACE MACRO tree_treeql_clause_parse(txt) AS (
  WITH t AS (SELECT trim(txt) AS s),
  kw AS (SELECT k.kind, k.keyword,
                trim((SELECT s FROM t)[length(k.keyword) + 2 : ]) AS body
         FROM tree_catalog.clause_kinds k
         WHERE upper((SELECT s FROM t)) LIKE upper(k.keyword) || ' %')
  SELECT CASE
    WHEN (SELECT count(*) FROM kw) = 0 THEN NULL
    ELSE (SELECT {kind: kind,
                  value: CASE kind WHEN 'where' THEN body
                                   WHEN 'attr'  THEN regexp_extract(body, '^([A-Za-z_][A-Za-z0-9_]*)', 1)
                                   ELSE tree_treeql_unlit(body) END,
                  op:    CASE kind WHEN 'attr' THEN trim(regexp_extract(body, '^[A-Za-z_][A-Za-z0-9_]*\s*(=|!=|<>|<=|>=|<|>|LIKE|ILIKE|NOT LIKE)', 1)) END,
                  arg:   CASE kind WHEN 'attr' THEN trim(regexp_extract(body, '^[A-Za-z_][A-Za-z0-9_]*\s*(?:=|!=|<>|<=|>=|<|>|LIKE|ILIKE|NOT LIKE)\s*(.+)$', 1)) END}
          FROM kw) END);
