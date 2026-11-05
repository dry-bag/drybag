The note sync's secret scan is now the `gitleaks` on `PATH`, the `PATH` your sessions run with,
less its relative entries. It no longer reads pre-commit's build of the overlay's hook, nor a
`PRE_COMMIT_HOME` or `XDG_CACHE_HOME` a session sets. A machine whose only gitleaks is
pre-commit's build syncs nothing, and the job records `scan_unavailable`, until gitleaks is
installed on that `PATH` (for example `brew install gitleaks`); `stayfixed doctor` says so.
