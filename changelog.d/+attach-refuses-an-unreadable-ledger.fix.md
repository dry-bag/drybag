`drybag attach` and `attach --check` refuse a ledger they cannot read, as `drybag detach` does,
naming the file: one that is damaged or another drybag's `format` is no longer written over, which
left the allow rules and rule copies it recorded with nothing to take them back.
