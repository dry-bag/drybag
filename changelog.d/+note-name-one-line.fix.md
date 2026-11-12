A note whose file name holds a line break is now reported as unreadable instead of being linked from `MEMORY.md`,
where its name could add lines of its own to the index. A `startup` value that is not an integer (`yes`, `true`, an
empty value, `1 # first`) now gives the note no rank, so it is not a standing rule; it used to rank the note last.
