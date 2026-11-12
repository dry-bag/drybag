The note sync no longer writes over a file of yours where a note another machine pushed lands: an ignored file at the
note's path, at a directory above it, or under a name this volume takes for the note's (a case or
Unicode-normalisation variant). Unless the file already holds that note's content, the job stops with
`waiting_clean_tree`, names the file and writes nothing. An incoming note this volume takes for a tracked one holds
upstream, naming both, rather than writing one over the other.
