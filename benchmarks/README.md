# Benchmarks

## Speed

How fast the harness is with an instant fake model. No network and no cost; CI runs it.

    uv run python -m benchmarks.speed           # print the numbers
    uv run python -m benchmarks.speed --check   # fail on a slowdown
    uv run python -m benchmarks.speed --save    # make these numbers the baseline

Each case keeps the best of five rounds. `--check` scales `baseline.json` by a short calibration
run, so another machine compares fairly, and allows 2.5 times the baseline. Save a new baseline in
the PR that makes something slower on purpose.

## Evals

How well the harness solves real tasks on a real model. Every run spends tokens, so CI does not
run these.

    uv run python -m benchmarks.evals                       # the plural window's agent
    uv run python -m benchmarks.evals --preset codex_cli --model gpt-6.1-sol
    uv run python -m benchmarks.evals --task large_log --repeat 3
    uv run python -m benchmarks.evals --compare benchmarks/results/<earlier>.json
    uv run python -m benchmarks.evals --harness codex       # the same tasks through codex exec

Each task gets a fresh git repository and a full host in `auto` permission mode, so the agent's
commands run on this machine without approval, inside the temporary folder by convention only.
Run tasks you trust.

The results go to `benchmarks/results/`, per task and in total: pass or fail, time, model turns,
tool calls and failures, input, output and cache tokens, the context's peak, the model's window,
compactions and what filled the context at its peak. Tokens include sub-agents and
compaction. A run the runner could not drive (`error`: the host did not start, the connection
dropped) is left out of the pass rate; a run the harness ended with an error counts as failed, and
its reason is in the results, so a spent usage limit shows there and the run is worth repeating.

`--harness codex` runs each task through `codex exec` with the same model, medium effort and a
workspace-write sandbox, for comparison. Codex reports neither its model requests nor its context,
so those stay empty for it. Plural reaches Codex through its app server, which reads
`$CODEX_HOME/config.toml`: keep the effort there at medium for a fair comparison.

Runs use an empty home folder, because skills found there go into every prompt and would make
numbers differ per person. `--keep-home` measures your own setup instead. Codex finds its sign-in
through `CODEX_HOME`; a preset that signs in another way may need `--keep-home`.

### Adding a task

    benchmarks/evals/tasks/<id>/
      task.toml   prompt, and timeout_s if 600 is not enough
      repo/       the repository the agent starts in
      setup.py    optional: generates large files, run inside the repository
      check.py    exits 0 when solved; gets the path of the agent's last reply as its argument

`check.py` runs in the finished repository and is not copied into it, so the agent does not come
across it. Check
behaviour the prompt asks for with inputs the repository does not show, and confirm it fails on the
untouched repository.
