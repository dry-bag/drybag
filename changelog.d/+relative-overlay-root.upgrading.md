An `[overlay] root` in `~/.config/drybag/config.toml` must now be an absolute path or start with `~/`. A relative one
was read against whatever directory a command or hook ran from; it is now refused as a fault of that file, naming it.
Write the root out in full, or run `drybag setup --overlay PATH`, which records it resolved. With no root recorded, the
note store now names that command too, where it said only `drybag setup`, which records none.
