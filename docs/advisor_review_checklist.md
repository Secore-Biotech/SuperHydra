# Advisor Review Checklist

## Test-stub leakage

For every script under `scripts/empirical_*.py`, no class beginning with
`_Noop`, `_Stub`, `_Fake`, `_Mock`, or `_Dummy` may be imported or
instantiated unless an explicit `--allow-*` CLI flag is set.

### Rationale

Test doubles that silently replace real venue adapters cause PAPER_RESEARCH
results to look valid while containing zero observed slippage data.  This
produces non-decision-grade memos that can be mistaken for real evidence.
The `--allow-*` gate makes the opt-in explicit and triggers the
`[MODELED-ONLY / NON-DECISION-GRADE]` labelling guard.

### CI enforcement

Add the following grep to CI (e.g. in `.github/workflows/ci.yml` or the
project's Makefile `lint` target):

```bash
# Fail if any scripts/empirical_*.py file imports or instantiates a
# test-double class without going through the --allow-* CLI gate.
#
# Allowed pattern:  conditional import inside a function gated by a CLI flag
# Disallowed pattern: top-level import or inline class definition

if grep -Pn '^\s*(class\s+_(Noop|Stub|Fake|Mock|Dummy)|from\s+\S+\s+import\s+_(Noop|Stub|Fake|Mock|Dummy))' scripts/empirical_*.py; then
  echo "FAIL: test-stub leakage detected in scripts/empirical_*.py"
  echo "Test doubles must live in tests/fixtures/ and be imported only"
  echo "behind an explicit --allow-* CLI flag."
  exit 1
fi
```

This grep catches:
- Inline class definitions like `class _NoopFetcher:` at module scope
- Top-level imports like `from tests.fixtures._noop_fetcher import _NoopFetcher`

It does **not** flag conditional imports inside functions (e.g. inside
`_build_fetcher(allow_noop=True)`), because those are gated by the CLI
flag and are the intended usage pattern.
