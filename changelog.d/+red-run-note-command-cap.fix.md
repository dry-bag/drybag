The note after a failed test run reads no command longer than 64 KiB, as the other session hints already did, and a
`uv run` command with many words before its test runner no longer costs the hook seconds to read.
