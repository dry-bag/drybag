The note sync no longer writes over an ignored file where a note another machine pushed lands: unless the file
already holds that note's content, the job stops with `waiting_clean_tree`, names the file and writes nothing, and
the next job goes on once the file is moved aside.
