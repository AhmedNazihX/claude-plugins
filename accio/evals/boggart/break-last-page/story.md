---
id: S-901
title: Paginate a list
track: story
status: review
---
# S-901 Paginate a list

## Context
Callers show a long list a page at a time.

## Definition of Done
- [ ] S-901/1 WHEN `paginate(items, page, size)` is called THE SYSTEM SHALL return the items of that page, pages counted from 1
- [ ] S-901/2 WHEN the last page has fewer than `size` items THE SYSTEM SHALL return the remainder
