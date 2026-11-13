---
description: Check that a forked skill does not see the conversation of the invoking session
context: fork
agent: reviewer
background: false
disable-model-invocation: true
---

Look at everything you received before this task. If it contains a codeword, write it with `printf '%s\n' '<codeword>' > .pipeline/fork-check.txt`; otherwise write `NONE` the same way. Then answer with the content you wrote.
