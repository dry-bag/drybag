`examples/demo/demo.py` builds a small repository in a scratch directory and runs a `stayfixed`
you name against it in seven acts, each passing only on `stayfixed`'s own exit code and `--json`
answer: a green run proved, text that only looks like a report, an all-skipped run, a variable that
switches assertions off, a fixed bug's regression failing the change that brings it back, an
overlay attached with one project's skill and not another's, and the `Stop`-hook recipe on a red
tree and a green one. One command runs it, `python3 -I examples/demo/demo.py "$(command -v stayfixed)"`, and it
makes no model call and reaches no network.
