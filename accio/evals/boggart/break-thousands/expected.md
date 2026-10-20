Planted break: a regression. Thousands commas no longer parse.
Claim: "Thousands commas are allowed: '1,234.50' is 1234.5." (price.py:2; also S-903/2 "as before")
Repro: `parse_price("1,234.50")` should be `1234.5`; it passed on the base and now raises `ValueError`, because the
comma is replaced by a dot. Both story tests use a price with no comma.
