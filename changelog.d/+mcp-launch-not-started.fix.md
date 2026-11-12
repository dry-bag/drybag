`drybag attach` no longer stops installing the overlay's other MCP servers when one server's definition cannot be
passed to `claude` (a definition past the system's argument limit, say): that server is listed as `MCP server
failed` with the reason, and the rest are installed. Only a `claude` that is not on `PATH`, or that hangs, still
stops the run.
