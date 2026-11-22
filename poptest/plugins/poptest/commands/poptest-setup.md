---
description: Set up a poptest project for a system: connect the target, build the fake world and fake tools, write the rules
argument-hint: <path to the system and its spec / API docs>
---

Set up poptest for:

$ARGUMENTS

Follow the plugin's skills in order: `connect-target`, then `build-world`, then `write-rules`. Finish when `poptest validate` says OK and `poptest say` shows a real reply with the system's actions listed. Then summarise what was built and ask whether to go on to `/poptest-cases`.
