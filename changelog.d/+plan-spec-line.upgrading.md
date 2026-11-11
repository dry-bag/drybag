`drybag plan check` holds every plan it lints to a `**Spec:**` line wherever git tracks a file under
`[paths] specs` (`docs/specs` by default): the line names the plan's spec by a backticked path that resolves inside
the project, or says `none — <reason>`. A project that keeps specs and runs `plan check` in CI goes red on the next
change to a plan without one, an older plan included; add the line to each plan the change touches.
