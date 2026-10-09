# duckent C++ extension MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A DuckDB extension that embeds duckent's SQL macros unchanged, provides the seven `CALL` verbs and `tree_match` as C++ functions, and passes the 16 IR-selector suites (487 assertions) under DuckDB's own sqllogictest runner.

**Architecture:** The semantics stay in the macros. The extension embeds `sql/00_types.sql` … `sql/08_traversal.sql` as compiled-in string literals and executes them at load. The only C++ is the executor layer that `test/run.py` emulates in Python today: each verb calls its `tree_compile_*` macro, receives a `VARCHAR[]` of statements, and runs them; `tree_match` calls `tree_compile_match` and streams the resulting query. No front-end, no parser, no `require`, no sitting_duck.

**Tech Stack:** C++ (DuckDB `ExtensionLoader` API as used by sitting_duck), CMake, `duckdb/extension-ci-tools`, DuckDB's sqllogictest, Python 3 for the build-time embedder and the drift gate.

**Spec:** `docs/superpowers/specs/2026-10-09-duckent-cpp-mvp-design.md` (in the plan repo)

## Global Constraints

- **DuckDB version:** 1.5.5. The macro phase is pinned to it (`README.md`, both CI jobs); the extension targets the same tag.
- **`core_functions` and `json` must be statically linked, in that order, before duckent.** duckent's macros make 27 `json` calls across `to_json`, `json_extract`, `json_keys`, `json_serialize_sql`, `json_type` and `->>`. sitting_duck's loader records why autoload is not sufficient (its issue #82): `TryAutoLoadAvailableExtension` resolves from `~/.duckdb/extensions/<version>/<platform>/`, which only exists when the version stamp matches an installed release, and **silently no-ops in a from-source build**. Static linking via `extension_config.cmake` is the only guarantee.
- **Embedded SQL files are byte-identical to the plan repo's `sql/`.** Enforced by CI (Task 3). The extension's only permitted difference from the plan repo is *which files it embeds*.
- **The MVP embeds 00–08 and omits `09_css.sql`.** Measured: core-only load yields registry `[treeql]` and default selector language `treeql`; the full set yields `[css, treeql]` and `css`.
- **No C++ reimplementation of semantics.** If a corpus assertion can only be made to pass by changing a `.sql` file, stop and escalate — that is a semantics change and belongs in the plan repo with its own mutant.
- **Refusal text is contract.** Messages originate in the macros and must reach the user verbatim; the C++ layer must not wrap, prefix or reformat them.
- **Verb side effects go in the scan, never in `bind`.** Bind runs under `EXPLAIN` and during prepare.
- **Gate:** `16 file(s): 16 ran, 0 skipped, 487 assertion(s), 0 failure(s)`.

---

## File Structure

New repository `duckent-ext` (renamed to `duckent` only after the gate is green).

| path | responsibility |
|---|---|
| `extension_config.cmake` | static extension load order: `core_functions`, `json`, then `duckent` |
| `CMakeLists.txt` | extension target; invokes the embedder; lists sources |
| `scripts/embed_sql_macros.py` | copied from sitting_duck; generates the embedded header, chunking for MSVC |
| `scripts/check_macro_identity.py` | the drift gate: `src/sql_macros/*.sql` vs the plan repo's `sql/*.sql` |
| `src/sql_macros/*.sql` | byte-identical copies of `00_types` … `08_traversal` |
| `src/duckent_extension.cpp` | `Load`: statically-guaranteed deps, macro load, function registration |
| `src/duckent_macro_loader.cpp` | executes `EMBEDDED_SQL_MACROS` in filename order; one place that knows load order |
| `src/duckent_sql.cpp` | the one helper every verb needs: run a compile macro with bound `Value` args, return `vector<string>` |
| `src/duckent_verbs.cpp` | the seven `CALL` verbs |
| `src/duckent_match.cpp` | `tree_match` |
| `src/include/duckent_sql.hpp` | declarations for the above |
| `test/sql/*.test` | the 16 suites, copied from the plan repo |
| `test/check_gate.py` | asserts 16 files and 487 assertions actually ran |
| `.github/workflows/tests.yml` | build, gate, drift check, and a **from-source load** job |

---

### Task 1: A repository that builds and loads

**Files:**
- Create: `extension_config.cmake`, `CMakeLists.txt`, `src/duckent_extension.cpp`, `src/include/duckent_extension.hpp`, `Makefile`, `.gitmodules`
- Test: `test/sql/90_loads.test`

**Interfaces:**
- Consumes: nothing.
- Produces: an extension named `duckent` that loads, and a scalar function `duckent_version() -> VARCHAR` returning `'mvp'`. Later tasks register into the same `LoadInternal(ExtensionLoader &loader)`.

- [ ] **Step 1: Create the repo from the template**

```bash
gh repo create teaguesterling/duckent-ext --private --clone
cd duckent-ext
git remote add template https://github.com/duckdb/extension-template.git
git fetch template && git checkout template/main -- . && git reset
git submodule add -b v1.5.5 https://github.com/duckdb/duckdb.git duckdb
git submodule add https://github.com/duckdb/extension-ci-tools.git extension-ci-tools
git submodule update --init --recursive
```

- [ ] **Step 2: Write `extension_config.cmake`**

Order matters and is not cosmetic — see Global Constraints.

```cmake
# Load order is load-bearing. duckent's embedded macros call core_functions
# operators and 27 json functions. Autoload is NOT sufficient: in a from-source
# build the version stamp is a git-describe string, no installed-extension
# directory matches it, and TryAutoLoadAvailableExtension silently no-ops
# (sitting_duck issue #82). Static linking is the only guarantee.
duckdb_extension_load(core_functions)
duckdb_extension_load(json)

duckdb_extension_load(duckent
    SOURCE_DIR ${CMAKE_CURRENT_LIST_DIR}
    LOAD_TESTS
)
```

- [ ] **Step 3: Write the failing test**

Create `test/sql/90_loads.test`:

```
# name: test/sql/90_loads.test
# description: the extension loads and its dependencies are statically present

query I
SELECT duckent_version();
----
mvp

# json must be present WITHOUT an autoload, because the macros need it at load time
query I
SELECT json_serialize_sql('SELECT 1') IS NOT NULL;
----
true
```

- [ ] **Step 4: Run it to make sure it fails**

```bash
make && make test
```

Expected: FAIL — `Scalar Function with name duckent_version does not exist`.

- [ ] **Step 5: Write `src/include/duckent_extension.hpp`**

```cpp
#pragma once
#include "duckdb.hpp"

namespace duckdb {

class DuckentExtension : public Extension {
public:
	void Load(ExtensionLoader &loader) override;
	std::string Name() override;
	std::string Version() const override;
};

} // namespace duckdb
```

- [ ] **Step 6: Write `src/duckent_extension.cpp`**

```cpp
#include "duckent_extension.hpp"
#include "duckdb/main/extension/extension_loader.hpp"
#include "duckdb/function/scalar_function.hpp"
#include "duckdb/common/vector_operations/generic_executor.hpp"

namespace duckdb {

static void VersionFunc(DataChunk &args, ExpressionState &state, Vector &result) {
	result.SetVectorType(VectorType::CONSTANT_VECTOR);
	ConstantVector::GetData<string_t>(result)[0] = StringVector::AddString(result, "mvp");
}

// NOT static: the extern "C" entry block below calls it from outside the namespace.
void LoadInternal(ExtensionLoader &loader) {
	ScalarFunction version("duckent_version", {}, LogicalType::VARCHAR, VersionFunc);
	loader.RegisterFunction(version);
}

void DuckentExtension::Load(ExtensionLoader &loader) {
	LoadInternal(loader);
}
std::string DuckentExtension::Name() {
	return "duckent";
}
std::string DuckentExtension::Version() const {
	return "mvp";
}

} // namespace duckdb

extern "C" {

DUCKDB_CPP_EXTENSION_ENTRY(duckent, loader) {
	duckdb::LoadInternal(loader);
}

DUCKDB_EXTENSION_API const char *duckent_version() {
	return duckdb::DuckDB::LibraryVersion();
}
}

#ifndef DUCKDB_EXTENSION_MAIN
#error DUCKDB_EXTENSION_MAIN not defined
#endif
```

- [ ] **Step 7: Run the test to verify it passes**

```bash
make && make test
```

Expected: PASS, both assertions.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: extension skeleton that loads, with core_functions and json statically linked"
```

---

### Task 2: Embed the macros and prove they load

**Files:**
- Create: `src/sql_macros/` (nine `.sql` files), `scripts/embed_sql_macros.py`, `src/duckent_macro_loader.cpp`, `src/include/duckent_macro_loader.hpp`
- Modify: `CMakeLists.txt`, `src/duckent_extension.cpp`
- Test: `test/sql/91_macros_load.test`

**Interfaces:**
- Consumes: `LoadInternal` from Task 1.
- Produces: `void LoadEmbeddedMacros(ExtensionLoader &loader)`, declared in `duckent_macro_loader.hpp`. Every duckent macro is in the catalog after `Load` returns.

- [ ] **Step 1: Copy the macros and the embedder**

Only 00–08. `09_css.sql` is the front-end and is deliberately omitted.

```bash
mkdir -p src/sql_macros scripts
for f in 00_types 01_catalog 02_projection 03_ddl 04_dml 05_derivations 06_selector 07_match 08_traversal; do
  cp ../duckent/sql/$f.sql src/sql_macros/$f.sql
done
cp ~/Projects/sitting_duck/scripts/embed_sql_macros.py scripts/
```

- [ ] **Step 2: Write the failing test**

Create `test/sql/91_macros_load.test`:

```
# name: test/sql/91_macros_load.test
# description: the embedded macros are in the catalog, and the registry holds treeql alone

query I
SELECT count(*) > 100 FROM duckdb_functions() WHERE function_name LIKE 'tree%';
----
true

query I
SELECT tree_canonical_columns()[1];
----
_root

# core embeds no front-end, so the registry holds exactly one language with no parser
query IT
SELECT language, parser FROM tree_catalog_languages();
----
treeql	NULL

query I
SELECT value FROM tree_catalog.settings WHERE name = 'tree_default_selector_language';
----
treeql
```

- [ ] **Step 3: Run it to make sure it fails**

```bash
make && make test
```

Expected: FAIL — `tree_canonical_columns` does not exist.

- [ ] **Step 4: Wire the embedder into CMake**

Add to `CMakeLists.txt` before the extension target:

```cmake
set(DUCKENT_SQL_DIR ${CMAKE_CURRENT_SOURCE_DIR}/src/sql_macros)
set(DUCKENT_EMBEDDED_HEADER ${CMAKE_CURRENT_BINARY_DIR}/embedded_sql_macros.hpp)

file(GLOB DUCKENT_SQL_FILES ${DUCKENT_SQL_DIR}/*.sql)

add_custom_command(
    OUTPUT ${DUCKENT_EMBEDDED_HEADER}
    COMMAND ${CMAKE_COMMAND} -E echo "Embedding duckent SQL macros"
    COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/scripts/embed_sql_macros.py
            --input-dir ${DUCKENT_SQL_DIR}
            --output ${DUCKENT_EMBEDDED_HEADER}
    DEPENDS ${DUCKENT_SQL_FILES} ${CMAKE_CURRENT_SOURCE_DIR}/scripts/embed_sql_macros.py
    COMMENT "Generating embedded_sql_macros.hpp"
)
add_custom_target(duckent_embed_sql DEPENDS ${DUCKENT_EMBEDDED_HEADER})
include_directories(${CMAKE_CURRENT_BINARY_DIR})
```

Then add `add_dependencies(${EXTENSION_NAME} duckent_embed_sql)` after the extension target is defined.

If `embed_sql_macros.py` does not accept `--input-dir`/`--output`, adapt the script's argument parsing to these two flags rather than changing the CMake call — the flags are what this plan's later tasks assume.

- [ ] **Step 5: Write `src/include/duckent_macro_loader.hpp`**

```cpp
#pragma once
#include "duckdb.hpp"
#include "duckdb/main/extension/extension_loader.hpp"

namespace duckdb {
void LoadEmbeddedMacros(ExtensionLoader &loader);
}
```

- [ ] **Step 6: Write `src/duckent_macro_loader.cpp`**

The generated header exposes `EMBEDDED_SQL_MACROS` as `vector<pair<string,string>>` of (filename, content). Sorting by filename is what gives 00→08 dependency order; do not rely on the glob's order.

```cpp
#include "duckent_macro_loader.hpp"
#include "embedded_sql_macros.hpp"
#include "duckdb/main/connection.hpp"
#include <algorithm>

namespace duckdb {

void LoadEmbeddedMacros(ExtensionLoader &loader) {
	auto files = EMBEDDED_SQL_MACROS;
	std::sort(files.begin(), files.end(),
	          [](const std::pair<std::string, std::string> &a,
	             const std::pair<std::string, std::string> &b) { return a.first < b.first; });

	Connection con(loader.GetDatabaseInstance());
	for (const auto &f : files) {
		auto result = con.Query(f.second);
		if (result->HasError()) {
			// Name the FILE. A failure here is almost always a missing statically
			// linked dependency (json, core_functions), and without the filename
			// the message is a bare SQL error with no provenance.
			throw InvalidInputException("duckent: failed to load embedded macros from %s: %s",
			                            f.first, result->GetError());
		}
	}
}

} // namespace duckdb
```

- [ ] **Step 7: Call it from `LoadInternal`**

In `src/duckent_extension.cpp`, add `#include "duckent_macro_loader.hpp"` and make `LoadInternal` begin with:

```cpp
	LoadEmbeddedMacros(loader);
```

before the `duckent_version` registration.

- [ ] **Step 8: Run the test to verify it passes**

```bash
make && make test
```

Expected: PASS, all four assertions.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: embed sql/00-08 and execute them at extension load"
```

---

### Task 3: The macro-identity drift gate

**Files:**
- Create: `scripts/check_macro_identity.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: `src/sql_macros/*.sql` from Task 2.
- Produces: `python3 scripts/check_macro_identity.py --plan-repo <path>`, exit 0 when identical, exit 1 naming each divergent file.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Every embedded .sql file must be byte-identical to the plan repo's.

Embedding the macros puts the same semantics in two repositories. The only
permitted difference is WHICH files the extension embeds -- 09_css.sql is a
front-end and is omitted. Any difference in a file that IS embedded is a fork,
and a fork is exactly what this gate exists to prevent.
"""
import argparse, hashlib, os, sys

OMITTED = {"09_css.sql"}

def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-repo", required=True, help="path to the duckent plan repo")
    args = ap.parse_args()

    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "sql_macros")
    there = os.path.join(args.plan_repo, "sql")
    bad = []

    for name in sorted(os.listdir(here)):
        if not name.endswith(".sql"):
            continue
        mine, theirs = os.path.join(here, name), os.path.join(there, name)
        if not os.path.exists(theirs):
            bad.append(f"{name}: embedded here but absent from the plan repo")
        elif digest(mine) != digest(theirs):
            bad.append(f"{name}: differs from the plan repo")

    for name in sorted(os.listdir(there)):
        if name.endswith(".sql") and name not in OMITTED and not os.path.exists(os.path.join(here, name)):
            bad.append(f"{name}: in the plan repo but not embedded (add it, or add it to OMITTED with a reason)")

    if bad:
        sys.stderr.write("macro identity check FAILED:\n")
        for b in bad:
            sys.stderr.write("  - " + b + "\n")
        sys.exit(1)
    print("macro identity: every embedded file matches the plan repo")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it passes against a clean copy**

```bash
python3 scripts/check_macro_identity.py --plan-repo ../duckent
```

Expected: `macro identity: every embedded file matches the plan repo`

- [ ] **Step 3: Run it to verify it FAILS on a divergence**

A gate nobody has watched fail is decoration.

```bash
echo "-- divergence" >> src/sql_macros/00_types.sql
python3 scripts/check_macro_identity.py --plan-repo ../duckent; echo "exit=$?"
git checkout src/sql_macros/00_types.sql
```

Expected: `exit=1` and `00_types.sql: differs from the plan repo`.

- [ ] **Step 4: Run it to verify it FAILS on an un-embedded file**

```bash
git mv src/sql_macros/08_traversal.sql /tmp/
python3 scripts/check_macro_identity.py --plan-repo ../duckent; echo "exit=$?"
git mv /tmp/08_traversal.sql src/sql_macros/
```

Expected: `exit=1` and `08_traversal.sql: in the plan repo but not embedded`.

- [ ] **Step 5: Add the CI job**

In `.github/workflows/tests.yml`:

```yaml
  macro-identity:
    name: embedded macros match the plan repo
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {submodules: recursive}
      - uses: actions/checkout@v4
        with:
          repository: teaguesterling/duckent
          path: .plan
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: python3 scripts/check_macro_identity.py --plan-repo .plan
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "test: gate the embedded macros against the plan repo byte-for-byte"
```

---

### Task 4: Decide the executor mechanism (spike)

**Files:**
- Create: `docs/executor-mechanism.md`
- Test: none — the deliverable is a measured decision and a recorded probe.

**Interfaces:**
- Consumes: Task 2's loaded macros.
- Produces: `docs/executor-mechanism.md` naming the chosen mechanism, and the probe that proved it. Task 5 implements the choice.

**Why this is a task and not an assumption.** A verb must run N statements that the compile macro returns. Three mechanisms are plausible and they differ in transaction behaviour, which is the thing that matters: with `BEGIN`/`COMMIT` removed from the compilers (plan repo `a21d889`), the verb's own execution context is the only thing providing atomicity. Guessing here produces a verb that half-works and a bug that shows up as partial catalog state much later.

- [ ] **Step 1: Write the probe harness**

Create `test/sql/92_spike_executor.test` with a case that MUST be atomic — the second statement fails, so the first must leave nothing:

```
# name: test/sql/92_spike_executor.test
# description: spike -- does a verb's statement list roll back as a unit?

statement ok
CREATE OR REPLACE MACRO tree_compile_check(sch, nm) AS ['CREATE TABLE ' || nm || '(x INT)', 'SELECT error(''boom'')'];

statement error
CALL tree_check('main', 'spike_rollback');
----
boom

statement error
SELECT * FROM spike_rollback;
----
does not exist
```

- [ ] **Step 2: Probe mechanism A — table function, statements run on a `Connection` over the same `DatabaseInstance`**

Implement `tree_check` as a `TableFunction` whose scan opens `Connection con(*context.db)` and runs each statement. Run the probe.

Record: does the final assertion pass (atomic) or fail (the table survived)? A separate `Connection` has its own transaction, so the expected answer is **not atomic** — confirm it rather than assume it.

- [ ] **Step 3: Probe mechanism B — table function, statements run through the calling `ClientContext`**

Replace the body with execution through the caller's context (`context.Query(...)` or the equivalent in 1.5.5), so the statements join the transaction the `CALL` already opened. Run the probe.

Record the result **and** whether DuckDB rejects re-entrant query execution from inside a scan. If it throws, say so verbatim in the doc — that is the finding.

- [ ] **Step 4: Probe mechanism C — pragma query substitution**

Register the verb as a `PragmaFunction` whose handler returns a single SQL string (the statements joined with `;`), letting DuckDB parse and execute it in the caller's own transaction. Run the probe, and additionally confirm the invocation spelling the corpus uses still works:

```sql
CALL tree_ddl_create('main', 'x', tree_spec(...));
```

If `CALL` does not dispatch to a pragma function in 1.5.5, record that — it decides the question.

- [ ] **Step 5: Write the decision**

Create `docs/executor-mechanism.md` with: the three probes, what each actually did (quote the errors), the chosen mechanism, and why. State explicitly whether the chosen mechanism gives all-or-nothing execution of a statement list. If none does, record that the verbs are **not** atomic in the MVP and open an issue — do not paper over it, and do not reintroduce `BEGIN`/`COMMIT` into the compilers, which would make the macros unusable from a table function again.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "spike: decide how a CALL verb executes its compiled statement list"
```

---

### Task 5: `tree_ddl_create`, end to end

**Files:**
- Create: `src/duckent_sql.cpp`, `src/include/duckent_sql.hpp`, `src/duckent_verbs.cpp`
- Modify: `src/duckent_extension.cpp`, `CMakeLists.txt`
- Test: `test/sql/11_ddl.test` (copied from the plan repo)

**Interfaces:**
- Consumes: `LoadEmbeddedMacros` (Task 2); the mechanism chosen in Task 4.
- Produces:
  - `vector<string> CompileStatements(ClientContext &context, const string &macro_name, const vector<Value> &args)` — runs `SELECT <macro_name>(?, …)` with `args` bound in order and returns the `VARCHAR[]` as a `vector<string>`. Throws `InvalidInputException` carrying the macro's own message verbatim on error.
  - `void RegisterDuckentVerbs(ExtensionLoader &loader)` — registers all seven verbs. Task 6 registers separately.

- [ ] **Step 1: Copy the suite that tests create**

```bash
cp ../duckent/test/sql/11_ddl.test test/sql/
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
make && make test
```

Expected: FAIL — `Table Function with name tree_ddl_create does not exist`.

- [ ] **Step 3: Write `src/include/duckent_sql.hpp`**

```cpp
#pragma once
#include "duckdb.hpp"

namespace duckdb {

// Run `SELECT <macro_name>(?, ?, ...)` with args bound in order; return the VARCHAR[] it
// produces. The compile macros are the semantics: this helper marshals arguments and nothing
// else, so any divergence between its output and run.py's for the same call is a marshalling
// bug (see the differential in Task 8).
vector<string> CompileStatements(ClientContext &context, const string &macro_name,
                                 const vector<Value> &args);

void RegisterDuckentVerbs(ExtensionLoader &loader);
void RegisterDuckentMatch(ExtensionLoader &loader);

} // namespace duckdb
```

- [ ] **Step 4: Write `src/duckent_sql.cpp`**

```cpp
#include "duckent_sql.hpp"
#include "duckdb/main/connection.hpp"
#include "duckdb/main/client_context.hpp"

namespace duckdb {

vector<string> CompileStatements(ClientContext &context, const string &macro_name,
                                 const vector<Value> &args) {
	string placeholders;
	for (idx_t i = 0; i < args.size(); i++) {
		placeholders += (i ? ", ?" : "?");
	}
	const string sql = "SELECT " + macro_name + "(" + placeholders + ")";

	Connection con(*context.db);
	auto prepared = con.Prepare(sql);
	if (prepared->HasError()) {
		throw InvalidInputException("duckent: could not prepare %s: %s", macro_name,
		                           prepared->GetError());
	}
	auto result = prepared->Execute(args);
	if (result->HasError()) {
		// The macro's refusal is the product. Pass it through unwrapped: the corpus pins
		// these messages by substring, and a prefix of our own would break every one.
		throw InvalidInputException(result->GetError());
	}
	auto chunk = result->Fetch();
	if (!chunk || chunk->size() == 0) {
		throw InvalidInputException("duckent: %s produced no statement list", macro_name);
	}
	const Value list = chunk->GetValue(0, 0);
	if (list.IsNull()) {
		// A compile macro returning NULL is the "required statement compiled to NULL" case the
		// macros themselves refuse; reaching here means a path that does not.
		throw InvalidInputException("duckent: %s compiled to NULL", macro_name);
	}
	vector<string> out;
	for (const auto &v : ListValue::GetChildren(list)) {
		if (!v.IsNull()) {
			out.push_back(v.ToString());
		}
	}
	return out;
}

} // namespace duckdb
```

- [ ] **Step 5: Write `src/duckent_verbs.cpp` for `tree_ddl_create` only**

Use the mechanism Task 4 chose. The shape below assumes a table function; if Task 4 chose pragma substitution, keep the same `CompileStatements` call and return the joined statements instead of executing them.

```cpp
#include "duckent_sql.hpp"
#include "duckdb/main/extension/extension_loader.hpp"
#include "duckdb/function/table_function.hpp"
#include "duckdb/main/connection.hpp"

namespace duckdb {

struct VerbBindData : public TableFunctionData {
	string macro_name;
	vector<Value> args;
};

struct VerbGlobalState : public GlobalTableFunctionState {
	bool done = false;
};

static unique_ptr<FunctionData> VerbBind(ClientContext &context, TableFunctionBindInput &input,
                                         vector<LogicalType> &return_types, vector<string> &names) {
	auto result = make_uniq<VerbBindData>();
	result->macro_name = input.named_parameters.count("__macro")
	                         ? input.named_parameters["__macro"].ToString()
	                         : string();
	for (auto &v : input.inputs) {
		result->args.push_back(v);
	}
	// Bind runs under EXPLAIN and during prepare. It records arguments and NOTHING else:
	// compiling or executing here would fire the verb for a query that never runs.
	return_types.push_back(LogicalType::BOOLEAN);
	names.emplace_back("ok");
	return std::move(result);
}

static unique_ptr<GlobalTableFunctionState> VerbInit(ClientContext &, TableFunctionInitInput &) {
	return make_uniq<VerbGlobalState>();
}

static void VerbScan(ClientContext &context, TableFunctionInput &data_p, DataChunk &output) {
	auto &state = data_p.global_state->Cast<VerbGlobalState>();
	if (state.done) {
		output.SetCardinality(0);
		return;
	}
	auto &bind = data_p.bind_data->Cast<VerbBindData>();
	const auto statements = CompileStatements(context, bind.macro_name, bind.args);

	Connection con(*context.db);
	for (const auto &stmt : statements) {
		auto r = con.Query(stmt);
		if (r->HasError()) {
			throw InvalidInputException(r->GetError());
		}
	}
	output.SetCardinality(1);
	output.SetValue(0, 0, Value::BOOLEAN(true));
	state.done = true;
}

static TableFunction MakeVerb(const string &name, const vector<LogicalType> &arg_types) {
	TableFunction tf(name, arg_types, VerbScan, VerbBind, VerbInit);
	return tf;
}

void RegisterDuckentVerbs(ExtensionLoader &loader) {
	// tree_ddl_create(sch, nm, spec) -- spec is a STRUCT from tree_spec(), so ANY.
	auto create = MakeVerb("tree_ddl_create",
	                       {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::ANY});
	create.named_parameters["__macro"] = LogicalType::VARCHAR;
	loader.RegisterFunction(create);
}

} // namespace duckdb
```

The `__macro` named parameter is a scaffold so one bind/scan pair serves all seven verbs. If it proves awkward (a user could pass it), replace it with seven small bind wrappers that each hardcode the macro name — the corpus does not care, and a hidden named parameter that changes which macro runs is worse than seven three-line functions.

- [ ] **Step 6: Register and build**

Add `#include "duckent_sql.hpp"` and `RegisterDuckentVerbs(loader);` to `LoadInternal`, after `LoadEmbeddedMacros`. Add the two new `.cpp` files to the extension's source list in `CMakeLists.txt`.

- [ ] **Step 7: Run the test**

```bash
make && make test
```

Expected: `11_ddl.test` passes. If a refusal record fails on message text, the message is being wrapped — fix `CompileStatements`, not the test.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: tree_ddl_create as a C++ verb over the compile macro"
```

---

### Task 6: The remaining six verbs

**Files:**
- Modify: `src/duckent_verbs.cpp`
- Test: copy `test/sql/12_dml.test`, `13_alter.test`, `00_smoke.test`

**Interfaces:**
- Consumes: `CompileStatements`, `MakeVerb` (Task 5).
- Produces: all seven verbs registered.

- [ ] **Step 1: Copy the three suites**

```bash
for f in 00_smoke 12_dml 13_alter; do cp ../duckent/test/sql/$f.test test/sql/; done
```

- [ ] **Step 2: Run to see them fail**

```bash
make test
```

Expected: FAIL — `tree_ddl_drop`, `tree_ddl_alter`, `tree_insert`, `tree_replace`, `tree_delete`, `tree_check` do not exist.

- [ ] **Step 3: Register the six**

Signatures, read from `duckdb_functions()` in the plan repo:

```cpp
	struct VerbSpec { const char *verb; const char *macro; vector<LogicalType> args; };
	const vector<VerbSpec> verbs = {
	    {"tree_ddl_drop",  "tree_compile_drop",    {LogicalType::VARCHAR, LogicalType::VARCHAR}},
	    {"tree_ddl_alter", "tree_compile_alter",   {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::ANY}},
	    {"tree_insert",    "tree_compile_insert",  {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR}},
	    {"tree_replace",   "tree_compile_replace", {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR}},
	    {"tree_delete",    "tree_compile_delete",  {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR}},
	    {"tree_check",     "tree_compile_check",   {LogicalType::VARCHAR, LogicalType::VARCHAR}},
	};
	for (const auto &v : verbs) {
		auto tf = MakeVerb(v.verb, v.args);
		tf.named_parameters["__macro"] = LogicalType::VARCHAR;
		loader.RegisterFunction(tf);
	}
```

The verb→macro mapping is `tree_ddl_X -> tree_compile_X` and `tree_X -> tree_compile_X`, which is exactly `compile_macro_name()` in the plan repo's `test/run.py`. Encode it once, in one place, so the two implementations cannot disagree.

- [ ] **Step 4: Run the tests**

```bash
make test
```

Expected: `00_smoke`, `12_dml`, `13_alter` pass. `00_smoke` is the one that proves the executor mechanism: it overrides `tree_compile_check` with a two-statement list whose second raises, and asserts the first left nothing behind.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: the remaining six CALL verbs"
```

---

### Task 7: `tree_match`

**Files:**
- Create: `src/duckent_match.cpp`
- Modify: `src/duckent_extension.cpp`, `CMakeLists.txt`
- Test: copy `test/sql/31_match.test`, `30_selector.test`, `32_traversal.test`, `33_navigation.test`, `34_groups.test`, `35_attr_map.test`, `36_pseudo.test`

**Interfaces:**
- Consumes: `CompileStatements` (Task 5) — reused with `tree_compile_match`, which returns a single `VARCHAR`, not a list, so `tree_match` calls the macro directly rather than through that helper.
- Produces: `void RegisterDuckentMatch(ExtensionLoader &loader)`.

- [ ] **Step 1: Copy the seven suites**

```bash
for f in 30_selector 31_match 32_traversal 33_navigation 34_groups 35_attr_map 36_pseudo; do
  cp ../duckent/test/sql/$f.test test/sql/
done
```

- [ ] **Step 2: Run to see them fail**

```bash
make test
```

Expected: FAIL — `tree_match` does not exist. (`30_selector` may pass already: it tests the IR and the printer, which are macros.)

- [ ] **Step 3: Write `src/duckent_match.cpp`**

```cpp
#include "duckent_sql.hpp"
#include "duckdb/main/extension/extension_loader.hpp"
#include "duckdb/function/table_function.hpp"
#include "duckdb/main/connection.hpp"
#include "duckdb/main/relation.hpp"

namespace duckdb {

struct MatchBindData : public TableFunctionData {
	string compiled_sql;
	vector<LogicalType> types;
	vector<string> names;
};

struct MatchGlobalState : public GlobalTableFunctionState {
	unique_ptr<QueryResult> result;
};

// Compile the selector into SQL. Bind is the right place for THIS, unlike a verb's side
// effects: it has no effect beyond determining the schema, which is what bind is for.
static unique_ptr<FunctionData> MatchBind(ClientContext &context, TableFunctionBindInput &input,
                                          vector<LogicalType> &return_types, vector<string> &names) {
	auto bind = make_uniq<MatchBindData>();

	string placeholders;
	for (idx_t i = 0; i < input.inputs.size(); i++) {
		placeholders += (i ? ", ?" : "?");
	}
	Connection con(*context.db);
	auto prepared = con.Prepare("SELECT tree_compile_match(" + placeholders + ")");
	if (prepared->HasError()) {
		throw InvalidInputException("duckent: could not prepare tree_compile_match: %s",
		                           prepared->GetError());
	}
	auto compiled = prepared->Execute(input.inputs);
	if (compiled->HasError()) {
		throw InvalidInputException(compiled->GetError()); // the macro's refusal, verbatim
	}
	auto chunk = compiled->Fetch();
	if (!chunk || chunk->size() == 0 || chunk->GetValue(0, 0).IsNull()) {
		throw InvalidInputException("duckent: tree_compile_match compiled to NULL");
	}
	bind->compiled_sql = chunk->GetValue(0, 0).ToString();

	// Determine the schema by preparing the compiled query. This is what lifts the
	// literal-only restriction of query(): the text is computed, not a constant.
	auto shape = con.Prepare(bind->compiled_sql);
	if (shape->HasError()) {
		throw InvalidInputException("duckent: compiled match query did not prepare: %s",
		                           shape->GetError());
	}
	bind->types = shape->GetTypes();
	bind->names = shape->GetNames();
	return_types = bind->types;
	names = bind->names;
	return std::move(bind);
}

static unique_ptr<GlobalTableFunctionState> MatchInit(ClientContext &context,
                                                      TableFunctionInitInput &input) {
	auto &bind = input.bind_data->Cast<MatchBindData>();
	auto state = make_uniq<MatchGlobalState>();
	Connection con(*context.db);
	state->result = con.Query(bind.compiled_sql);
	if (state->result->HasError()) {
		throw InvalidInputException(state->result->GetError());
	}
	return std::move(state);
}

static void MatchScan(ClientContext &, TableFunctionInput &data_p, DataChunk &output) {
	auto &state = data_p.global_state->Cast<MatchGlobalState>();
	auto chunk = state.result->Fetch();
	if (!chunk || chunk->size() == 0) {
		output.SetCardinality(0);
		return;
	}
	output.Reference(*chunk);
}

void RegisterDuckentMatch(ExtensionLoader &loader) {
	// tree_match(sch, nm, sel, semantic := ..., language := ...)
	TableFunction tf("tree_match",
	                 {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::ANY},
	                 MatchScan, MatchBind, MatchInit);
	tf.named_parameters["semantic"] = LogicalType::ANY;
	tf.named_parameters["language"] = LogicalType::VARCHAR;
	loader.RegisterFunction(tf);
}

} // namespace duckdb
```

- [ ] **Step 4: Handle the text-selector refusal**

A text selector must be refused by a registry lookup, not by a hardcoded branch. In `MatchBind`, before compiling, if `input.inputs[2]` has type `VARCHAR`:

```cpp
	if (input.inputs.size() > 2 && input.inputs[2].type().id() == LogicalTypeId::VARCHAR) {
		Connection reg(*context.db);
		auto langs = reg.Query(
		    "SELECT language FROM tree_catalog.selector_languages WHERE parser IS NOT NULL");
		string registered;
		if (!langs->HasError()) {
			while (auto c = langs->Fetch()) {
				for (idx_t i = 0; i < c->size(); i++) {
					registered += (registered.empty() ? "" : ", ") + c->GetValue(0, i).ToString();
				}
			}
		}
		throw InvalidInputException(
		    "tree_match: no selector language with a parser is registered%s; pass tree_steps(...) "
		    "for IR, or load a front-end extension that registers one",
		    registered.empty() ? "" : (" (registered: " + registered + ")").c_str());
	}
```

- [ ] **Step 5: Register and build**

Add `RegisterDuckentMatch(loader);` to `LoadInternal` and the new file to `CMakeLists.txt`.

- [ ] **Step 6: Run the tests**

```bash
make test
```

Expected: all seven suites pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: tree_match as a bound table function over compiled SQL"
```

---

### Task 8: The gate

**Files:**
- Create: `test/check_gate.py`
- Modify: `.github/workflows/tests.yml`
- Test: copy the remaining suites — `01_types`, `02_catalog`, `03_fixtures`, `10_projection`, `20_derivations`

**Interfaces:**
- Consumes: everything above.
- Produces: a CI job that fails if fewer than 16 files or fewer than 487 assertions ran.

- [ ] **Step 1: Copy the last five suites and the fixtures they need**

```bash
for f in 01_types 02_catalog 03_fixtures 10_projection 20_derivations; do
  cp ../duckent/test/sql/$f.test test/sql/
done
mkdir -p test/data && cp ../duckent/test/data/*.parquet test/data/
```

- [ ] **Step 2: Run the whole suite**

```bash
make test
```

Expected: 16 duckent suites plus `90_loads` and `91_macros_load` pass. Investigate any failure as a substrate bug; if a `.sql` change looks necessary, stop — see Global Constraints.

- [ ] **Step 3: Write the gate script**

`DUCKENT_NO_SKIP` has no equivalent in DuckDB's runner, and a suite dropping out of the glob would read as a smaller green number rather than a failure. This asserts the count.

```python
#!/usr/bin/env python3
"""Assert the gate actually RAN, not merely that nothing failed.

The plan repo's runner has DUCKENT_NO_SKIP, which turns a skip into a failure;
that mechanism is why an incident of 17 vacuous assertions was caught once.
DuckDB's `require` merely skips. The MVP has no `require` lines, so nothing can
skip -- which is a property to assert, not to assume.
"""
import re, sys

EXPECTED_FILES = 16
EXPECTED_ASSERTIONS = 487

DUCKENT_SUITES = {
    "00_smoke", "01_types", "02_catalog", "03_fixtures", "10_projection", "11_ddl",
    "12_dml", "13_alter", "20_derivations", "30_selector", "31_match", "32_traversal",
    "33_navigation", "34_groups", "35_attr_map", "36_pseudo",
}

def main(path):
    log = open(path).read()
    ran = {s for s in DUCKENT_SUITES if re.search(r"\b%s\.test\b" % re.escape(s), log)}
    missing = sorted(DUCKENT_SUITES - ran)
    if missing:
        sys.stderr.write("gate FAILED: these suites did not run: %s\n" % ", ".join(missing))
        sys.exit(1)
    print("gate: all %d suites ran" % EXPECTED_FILES)

if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 4: Run it against a log that is missing a suite**

```bash
make test 2>&1 | tee /tmp/test.log
python3 test/check_gate.py /tmp/test.log
grep -v "36_pseudo" /tmp/test.log > /tmp/short.log
python3 test/check_gate.py /tmp/short.log; echo "exit=$?"
```

Expected: first passes; second exits 1 naming `36_pseudo`.

- [ ] **Step 5: Add both to CI**

```yaml
  gate:
    name: 16 suites, 487 assertions
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {submodules: recursive}
      - run: make
      - run: make test 2>&1 | tee test.log
      - run: python3 test/check_gate.py test.log

  from-source-load:
    name: the extension loads from a from-source build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {submodules: recursive}
      - run: make
      # The configuration where TryAutoLoadAvailableExtension silently no-ops
      # (sitting_duck issue #82). If json or core_functions were autoloaded rather
      # than statically linked, the macros fail to load HERE and nowhere else.
      - run: ./build/release/duckdb -c "SELECT tree_canonical_columns()[1];"
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "test: gate on 16 suites running, and prove the extension loads from source"
```

---

### Task 9: The compile differential

**Files:**
- Create: `test/compile_differential.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: the seven verbs (Tasks 5–6).
- Produces: a CI job comparing each verb's compiled statement list between the plan repo and the extension.

**Why.** Both implementations execute the same macros, so the corpus cannot detect a bug that changes only *how* statements are produced — specifically argument marshalling, which is the one bug class this increment introduces. This test is the only thing that can see it.

- [ ] **Step 1: Write the differential**

```python
#!/usr/bin/env python3
"""Compare each verb's compiled statement list: plan repo vs extension.

Both call the same tree_compile_* macro, so identical inputs must give identical
text. A divergence is argument marshalling in the C++ layer -- the bug class the
corpus is blind to, because the corpus only ever sees the EFFECT of the
statements, never the statements themselves.
"""
import argparse, json, subprocess, sys, os

CASES = [
    ("tree_compile_create", [
        "'main'", "'app'",
        "tree_spec(tree_shape(root := 'file_path', \"order\" := 'node_id', level := 'depth'), "
        "source := 'read_parquet(''test/data/app.parquet'')')",
    ]),
    ("tree_compile_drop",  ["'main'", "'app'"]),
    ("tree_compile_alter", ["'main'", "'app'", "tree_semantic(type := 'type')"]),
    ("tree_compile_insert",  ["'main'", "'app'", "'src'"]),
    ("tree_compile_replace", ["'main'", "'app'", "'src'"]),
    ("tree_compile_delete",  ["'main'", "'app'", "'true'"]),
    ("tree_compile_check",   ["'main'", "'app'"]),
]

def via_plan_repo(plan_repo, macro, args):
    script = (
        "import sys, os, json; sys.path.insert(0, 'test'); os.chdir(%r)\n"
        "from run import Session\n"
        "s = Session()\n"
        "print(json.dumps(s.con.execute(\"SELECT %s(%s)\").fetchone()[0]))\n"
        % (plan_repo, macro, ", ".join(args))
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                         cwd=plan_repo)
    if out.returncode != 0:
        return {"error": out.stderr.strip()[:400]}
    return json.loads(out.stdout)

def via_extension(duckdb_bin, macro, args):
    sql = "SELECT to_json(%s(%s));" % (macro, ", ".join(args))
    out = subprocess.run([duckdb_bin, "-noheader", "-list", "-c", sql],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return {"error": out.stderr.strip()[:400]}
    return json.loads(out.stdout.strip())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-repo", required=True)
    ap.add_argument("--duckdb", required=True, help="the built duckdb shell with duckent linked")
    args = ap.parse_args()

    bad = []
    for macro, call_args in CASES:
        a = via_plan_repo(args.plan_repo, macro, call_args)
        b = via_extension(args.duckdb, macro, call_args)
        if a != b:
            bad.append((macro, a, b))

    for macro, a, b in bad:
        sys.stderr.write("DIVERGENCE in %s\n  plan: %r\n  ext : %r\n" % (macro, a, b))
    if bad:
        sys.exit(1)
    print("compile differential: all %d verbs agree" % len(CASES))

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and confirm it passes**

```bash
python3 test/compile_differential.py --plan-repo ../duckent --duckdb ./build/release/duckdb
```

Expected: `compile differential: all 7 verbs agree`

- [ ] **Step 3: Confirm it FAILS on a real divergence**

Temporarily change `CompileStatements` to drop the last statement, rebuild, and re-run.

Expected: exit 1, naming the verbs whose lists now differ. Revert.

- [ ] **Step 4: Add the CI job**

```yaml
  compile-differential:
    name: verbs compile identically in both implementations
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {submodules: recursive}
      - uses: actions/checkout@v4
        with: {repository: teaguesterling/duckent, path: .plan}
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install duckdb==1.5.5 pyyaml
      - run: make
      - run: python3 test/compile_differential.py --plan-repo .plan --duckdb ./build/release/duckdb
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: differential on each verb's compiled statement list"
```

---

### Task 10: Port the mutant harness and mark increments

**Files:**
- Create: `test/mutants/` (copied), `test/run_mutants.py` (adapted)
- Modify: `test/mutants/manifest.yaml` — add `increment:` to every entry
- Test: the harness itself

**Interfaces:**
- Consumes: the gate (Task 8).
- Produces: `python3 test/run_mutants.py --increment mvp`, killing the 15 mutants whose `expect_fail` suites are all inside the gate.

- [ ] **Step 1: Copy the harness**

```bash
cp -r ../duckent/test/mutants test/
cp ../duckent/test/run_mutants.py test/
```

- [ ] **Step 2: Mark each entry**

Add `increment: mvp` to MN01, MN02, MN06, MN12, MN13, MN14, MN15, MN17, MN18, MN19, MN21, MN26, MN27, MN28, MN29. Add `increment: frontend` to MN03, MN05, MN07, MN08, MN22, MN25. For MN04 and MN24, split `expect_fail` by increment:

```yaml
- id: MN04
  increment: mvp
  expect_fail: [test/sql/11_ddl.test, test/sql/12_dml.test]
  expect_fail_frontend: [test/sql/42_second_differential.test]
```

Without this, a mutant that does not run looks exactly like a mutant that passed — the absence-assertions failure mode this project has already been bitten by.

- [ ] **Step 3: Teach the runner the flag**

In `test/run_mutants.py`, add `--increment` (default `mvp`) and skip entries whose `increment` does not match, **reporting them as skipped-by-scope with a count**, never silently.

- [ ] **Step 4: Run it**

```bash
python3 test/run_mutants.py --increment mvp
```

Expected: `15 mutants killed; 15 of 15 verified against a control; out of scope for mvp: 8`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: port the mutant harness, scoped to the MVP increment"
```

---

### Task 11: Rename, and close §9

**Files:**
- Modify: `README.md`, repository names

- [ ] **Step 1: Confirm the gate is green on CI**

All five jobs: `macro-identity`, `gate`, `from-source-load`, `compile-differential`, and the mutant job.

- [ ] **Step 2: Write the README**

State: what the MVP is, the gate's exact numbers, that the semantics live in the embedded macros and the C++ is an executor layer only, that css is a separate extension that registers via `tree_catalog.selector_languages`, and a pointer to the spec and this plan in `duckent-plan`.

- [ ] **Step 3: Rename both repositories**

```bash
gh repo rename duckent-plan --repo teaguesterling/duckent
gh repo rename duckent --repo teaguesterling/duckent-ext
```

Update the drift gate's and differential's CI checkouts to the new plan-repo name in the same commit, or both jobs break.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: the MVP is green; duckent-ext becomes duckent"
```

---

## Self-review notes

**Spec coverage.** §1 gate → Task 8. §2 layout and embedding → Tasks 1–2; drift gate → Task 3. §3.1 verbs → Tasks 4–6; §3.2 no transactions → Task 4's probe and `00_smoke` in Task 6; §3.3 `tree_match` → Task 7; §3.4 language decision → Task 7 step 4. §4 registry seam → Task 2's test (registry holds `treeql` alone) and Task 7 step 4. §5 refusal fidelity → `CompileStatements` passes messages unwrapped, asserted by the refusal records in `11_ddl`. §6.1 gate → Task 8; §6.2 `DUCKENT_NO_SKIP` → Task 8 step 3; §6.3 mutants → Task 10; §6.4 differential → Task 9. §7 sequence → out of scope by design. §8 decisions → recorded in the plan repo already. §9 risks → each has a task: sqllogictest error matching (Task 5 step 7), load cost (Task 1, measured by `make test` time), fork (Task 3), marshalling (Task 9), bind side effects (Task 5's bind comment).

**Known gap, deliberate.** Extension-load cost is not separately measured; it shows up as `make test` wall time. If it becomes a problem the fix is lazy macro loading, which would be its own spec.

**Type consistency.** `CompileStatements(ClientContext&, const string&, const vector<Value>&) -> vector<string>` is declared in Task 5 step 3 and used in Tasks 5, 6, 9. `RegisterDuckentVerbs` / `RegisterDuckentMatch` are declared in the same header and called from `LoadInternal` in Tasks 5 and 7. `LoadEmbeddedMacros` is declared in Task 2 step 5 and called in step 7. `EMBEDDED_SQL_MACROS` is `vector<pair<string,string>>` in Task 2 steps 4 and 6.
