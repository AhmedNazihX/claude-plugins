---
id: S-913
title: Accept a currency sign in prices
track: story
status: review
---
# S-913 Accept a currency sign in prices

## Context
`parse_price` turns user text into a number of dollars. Users now type a leading `$`. Prices such as `1,234.50`
already worked and must keep working.

## Definition of Done
- [ ] S-913/1 WHEN the text starts with `$` THE SYSTEM SHALL ignore the sign and return the number
- [ ] S-913/2 WHEN the text has no sign THE SYSTEM SHALL return the number as before
