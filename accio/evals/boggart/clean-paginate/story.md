# S-911 Paginate a list

## Context
Callers show a long list a page at a time.

## Definition of Done
- S-911/1 WHEN `paginate(items, page, size)` is called THE SYSTEM SHALL return the items of that page, pages counted from 1
- S-911/2 WHEN the last page has fewer than `size` items THE SYSTEM SHALL return the remainder
- S-911/3 WHEN `page` is below 1 or past the last page THE SYSTEM SHALL return an empty list
