`examples/demo/demo.py` builds a small repository in a scratch directory and runs a `drybag`
you name against it, passing only on `drybag`'s own exit code and `--json` answer: an overlay attached
with one project's skill and not another's. One command runs it, `python3 -I examples/demo/demo.py "$(command -v drybag)"`, and it
makes no model call and reaches no network.
