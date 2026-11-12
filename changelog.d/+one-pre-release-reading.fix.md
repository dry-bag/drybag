`drybag doctor`'s `versions` row and a session's note on a newer configuration now read a pre-release as an overlay's
`requires` floor reads it, so a recorded `1.0.0rc1+local`, `1.0.0.0rc1` or `1.0.0rc1.post2` orders before `1.0.0` there
too, where it was left unordered.
