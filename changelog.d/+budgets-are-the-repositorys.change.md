The documentation no longer says the base branch's `drybag.toml` sets a documentation budget: every command reads
`[budgets]` from the `drybag.toml` in the checkout it runs in, so a pull request can raise a budget and that change is
for review to catch.
A documentation budget in the machine file is still ignored, and the note now says so in the words used for every key
a layer may not set.
