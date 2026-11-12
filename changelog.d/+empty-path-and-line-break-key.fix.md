A `PATH` with no absolute entry no longer reaches `git` empty, which would run a `git` from the directory a command runs
in: drybag hands `git` the system default search path instead. `drybag setup` now refuses, naming the key, a machine
file key that ends in a line break, where it wrote the key raw and left a file that no longer loaded.
