The commit-message hook leaves alone the message of a commit git replays, a `cherry-pick` or a rebase's pick, so a
human's `Signed-off-by` at a vendor's mail domain survives it; `commit -m`, an editor commit and `git commit --amend` are
stripped as before. Run `drybag setup --git-hooks` again to install the new hook.
