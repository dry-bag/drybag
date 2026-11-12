The commit-message hook `drybag setup --git-hooks` installs runs only the `drybag` executable on `PATH`. Without one it
no longer falls back to `python3 -m drybag`, which imported a `drybag.py` or `drybag/` the repository commits ahead of the
installed package; it says that trailers are not stripped locally and lets the commit through. Run `drybag setup
--git-hooks` again to replace a hook an earlier release installed.
