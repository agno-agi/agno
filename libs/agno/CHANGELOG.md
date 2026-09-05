# Unreleased

## Knowledge constructor

All `Knowledge` constructor arguments are now keyword-only. This intentionally
breaks positional construction; use `Knowledge(name="docs", content_db=db,
vector_db=vectors, max_results=10)` instead of positional arguments.

`content_db` is the preferred spelling. The existing `contents_db` keyword remains
supported without a deprecation warning, and both attributes read and write the
same database value. Supplying both keywords requires the same object; distinct
objects (including explicit `None` versus a database) raise `ValueError`.

Dataclass inspection, serialization, reconstruction and replacement retain the
single legacy field spelling, `contents_db`. Use
`dataclasses.replace(knowledge, contents_db=new_db)`; replacement through the new
`content_db` alias is not supported. Copy behavior is unchanged.
