The commit-message hook leaves alone a message git hands it as `message` while a cherry-pick or a rebase is under way:
a `cherry-pick` or a rebase's pick, so a human's `Signed-off-by` at a vendor's mail domain survives it, and a `commit -m`
made while a rebase is stopped at `edit`. A cherry-pick continued after a conflict, any other `commit -m`, an editor
commit and `git commit --amend` are stripped as before. Run `drybag setup --git-hooks` again to install the new hook.
