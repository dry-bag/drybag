The hook wrapper now falls back to uv's Python when there is no `python3` of 3.11 or newer on `PATH`. uv is asked from `/`, so no file in the repository can choose the program every hook starts.
