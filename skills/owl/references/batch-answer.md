# The batch answer

owl asks once, for everything, and the user answers once. Ask so they can answer without asking back: say what
each choice does, in plain words, the first time it comes up.

## What each answer does
- **Accept:** the story is merged into the base branch with the others, after all the checks pass on the result.
- **Reject (with a reason):** the reason goes into the story's Review notes, and the story goes back to Ready to be
  built again. Stories stacked on it go back with it.
- **Drop (with a reason):** the story leaves the backlog for good (the user can bring it back). Its work stays on
  its branch. Stories stacked on it go back to Ready, and the next plan asks about them.
- **Answer a question:** the answer goes into the story, which goes back to Ready.
- **Allow a command once:** this story's next build may run it (no other story, no later build). **From now on:** every build may (it is added to
  `agent_allow` in `.accio/config.json`). Either way the story that asked goes back to Ready. **No:** it goes back
  too, with a note to find another way.
- **Push:** after the merge, the base branch is pushed to `origin`. accio's push guard lets exactly that commit
  through, once.

## Example: how to ask

> The build finished 3 stories and has 1 question.
>
> *(owl.md as it is)*
>
> **What I need from you, in one answer:**
> 1. **S-012 Password reset email** and **S-013 Reset token expiry** (built on S-012): accept, reject or drop each.
>    Accepting S-013 needs S-012 accepted too.
> 2. **S-015 Profile photo upload:** accept, reject or drop.
> 3. **S-014 asks:** "Email or SMS for the reset?"
> 4. **Push** to main after the merge: yes or no?
>
> For example: "accept S-012 and S-013, reject S-015: the photo isn't cropped, S-014: email only, push yes".

## Example: turning an answer into flags

"accept 12 and 13, drop 15 we don't need it, 14 email only, S-016 may run `docker compose up` from now on, push"
becomes one command (push is step 6, not a flag):

```
${CLAUDE_PLUGIN_ROOT}/bin/accio-owl check --accept S-012 --accept S-013 --drop S-015 'we don’t need it' --answer S-014 'email only' --allow S-016 'docker compose up'
```

Keep the user's own words for reasons and answers, each in single quotes (an apostrophe becomes `’`). If an
answer is ambiguous ("looks fine" for two stories, one of them blocked), ask about just that part.
