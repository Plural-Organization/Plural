#!/bin/zsh
# Eval runs one after another, each given as: harness preset model. Usage:
#   benchmarks/runs/matrix.sh <log name> plural claude_code claude-sonnet-5-5 claude claude_code ...
cd "$(dirname "$0")/../.."
family=$1; shift
log=benchmarks/runs/$family.log
: > $log
while (( $# >= 3 )); do
  harness=$1 preset=$2 model=$3; shift 3
  echo "=== $harness $preset $model $(date +%H:%M:%S)" >> $log
  uv run python -m benchmarks.evals --harness $harness --preset $preset --model $model --jobs 3 >> $log 2>&1
done
echo "=== done $(date +%H:%M:%S)" >> $log
