# EuroLeague Analytics — agent instructions

**The instructions for this repository are in [`CLAUDE.md`](./CLAUDE.md).
Read that file in full before doing anything, including before asking
clarifying questions.**

It is the single source of truth for this project: scope, hard rules on event
ordering and data handling, validation requirements, architecture, and the
workflow rules. Nothing in this project should be built without it.

---

## Why this file is a pointer and not a copy

This file deliberately contains **no rules of its own**. A second copy of the
rules is a copy that will silently fall out of date, and this project has
already been bitten once by a rule that stayed wrong after the evidence changed.

A symlink would be the natural way to do this, but this repository lives on
Windows, where creating one requires Developer Mode or an elevated shell. A
hard link was tested and rejected: the editors used here write via
temp-file-and-rename, which severs the link and leaves a stale duplicate behind
with no error. A pointer is the only form that cannot desync.

**Do not paste the contents of `CLAUDE.md` into this file.** If you want the
two genuinely unified, enable Windows Developer Mode and replace this file with
a real symlink:

```sh
rm AGENTS.md
MSYS=winsymlinks:nativestrict ln -s CLAUDE.md AGENTS.md
```
