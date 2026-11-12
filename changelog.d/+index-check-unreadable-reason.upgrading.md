`drybag memory index --json` now gives each entry of `unreadable` as an object with the store-relative `path` and
the `reason` the note could not be read, where it was a list of paths; read `path` where a script read the string.
