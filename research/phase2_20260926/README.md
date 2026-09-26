# Phase 2 offline research

Read [RESULTS.md](RESULTS.md) for the completed experiment and [AUDIT.md](AUDIT.md)
for provenance, tests, changed files and git information.

The worktree is based on phase-1 commit
`9f3bed37ad47c5b952e170aea58671c66fb0c37f`. It preserves that engine, input ZIP,
legacy results and forward seal unchanged. `replay.py` reuses the event-accounting
primitives and exposes only a causal target/resize controller and explicit
diagnostic overrides. Default replay is checked against all 18 legacy policies.

The existing objectives JSON is loaded explicitly and hash checked. The phase-2
SSOT addendum describes sequencing and research scope; it does not reduce the
150–200% goal or authorize production changes.

Install the pinned dependencies in a separate environment if necessary:

```powershell
python -m venv scratch/phase2-venv
scratch/phase2-venv/Scripts/python.exe -m pip install -r research/phase2_20260926/requirements.txt
```

Run from the repository root:

```powershell
python -m unittest discover -s research/phase2_20260926 -p test_phase2.py -v
python research/phase2_20260926/diagnose.py run
python research/phase2_20260926/diagnostic_details.py
python research/phase2_20260926/search.py run --workers 6 --out scratch/phase2_fresh
python research/phase2_20260926/audit.py
python research/phase2_20260926/audit_high_lineage.py
python research/phase2_20260926/reproduce.py
python research/phase2_20260926/render.py
```

Use the environment's Python executable when dependencies are installed there.
The search writes only under this research directory or `scratch`. An empty
output directory recomputes all 396 variants and all grid scenarios. Existing
grid JSONs are reused only with the same frozen fingerprint. Audit/render read
the committed `results` folder; the independent fresh run is left in scratch.
`reproduce.py` replays all OOS/stress/neighbor policies from the frozen grid and
independently recomputes 54 full-history grid scenarios. Its scope is explicitly
smaller than repeating the exhaustive grid twice.

Do not call `freeze` again: these commands were used before the original runs
and intentionally reject existing freeze files. The preflight freeze retained
beside the accepted freeze was superseded before market search, solely because
two synthetic tests tried to mutate pandas read-only arrays. Copying the fixture
arrays fixed the tests; strategy parameters and market outcomes were unchanged.

Every CSV/JSON is committed with exact bytes (`-text`) to retain hash identity on
Windows and other platforms. There is no network client, order API, scheduler,
production adapter, promotion or deployment path in this research runner.

No historical data here are a scientific seal. The historical OOS policies were
frozen algorithmically using only prior validation years, but the history itself
was already seen in earlier research. The frozen A/B/C nominations precede OOS
metrics and are not replaced after failure. The observed best family is a
descriptive result, not a validated or automatically deployed finalist.
