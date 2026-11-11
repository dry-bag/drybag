`drybag plan check` run from a project root below the top of its git work tree now lints the plans the change
touches and lists its uncommitted ones. It used to read the paths git printed as the root's own, find no plan, and
report `OK: linted 0 plan(s)`.
