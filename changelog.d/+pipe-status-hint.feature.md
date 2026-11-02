A shell call that pipes a test run into `tail`, `head` or `grep` without `pipefail` now gets a
one-time hint that the pipeline's exit status is the reader's, so a failing run looks green, and
that `set -o pipefail;` in front of the command keeps it. The hint reads only a plain list of
pipelines, stays silent for a command with a substitution, parenthesis, brace or heredoc, and never
refuses the command.
