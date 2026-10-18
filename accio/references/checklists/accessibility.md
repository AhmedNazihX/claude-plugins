# Accessibility

- Every interactive element can be reached and used with the keyboard alone, in a sensible order, with a visible
  focus.
- Every control has a name a screen reader announces (label, aria-label), and images have alt text (or alt="" when
  decorative).
- Text and controls meet contrast (4.5:1 for text), and nothing relies on colour alone.
- Errors and status changes are announced (aria-live) and say how to fix the problem.
- Check the tests or checks that cover these, such as an axe run in the test suite, if the project has one.
