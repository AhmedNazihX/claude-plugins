# Data migration

- Read the migration against realistic data: what happens to existing rows, nulls, duplicates and very large
  tables? Find the test that runs it on such data.
- Check there is a way back (a down migration or a documented restore), and find the test that runs it.
- Check the old and new code can both run while the migration is in progress, if deploys overlap.
- Look for locks on big tables and for long transactions.
- Check data is copied before it is dropped, and that counts are compared after a copy.
