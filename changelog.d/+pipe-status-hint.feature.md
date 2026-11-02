A shell call that pipes a test run into `tail`, `head` or `grep` without `pipefail` now gets a
one-time hint that the pipeline's exit status is the reader's, so a failing run looks green, and
that `set -o pipefail;` in front of the command keeps it. The hint never refuses the command.
