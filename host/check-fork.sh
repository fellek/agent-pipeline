#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
mkdir -p .pipeline
out=.pipeline/fork-check.txt
codeword="fork-check-$RANDOM$RANDOM"
run() {
  : > "$out"
  claude -p "$1" --append-system-prompt "The codeword is $codeword." \
    --permission-mode acceptEdits --allowedTools "Bash(printf *)" >/dev/null
  cat "$out"
}

# Control run: proves the main session sees the codeword, so NONE from the fork means isolation.
control=$(run "Write the codeword with: printf '%s\n' '<codeword>' > $out")
[ "$control" = "$codeword" ] || { echo "FAIL: control run wrote '$control'"; exit 1; }

case "$(run /fork-check)" in
  "$codeword") echo "FAIL: forked skill sees the conversation"; exit 1 ;;
  NONE) echo "OK: forked skill is isolated" ;;
  *) echo "FAIL: unexpected result in $out"; exit 1 ;;
esac
