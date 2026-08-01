# Confirmed Bugs

Audit date: 2026-08-01
Resolution review: 2026-08-01

## Resolution checklist

- [x] A live state-file lock cannot be revoked by elapsed time.
- [x] Hook discovery follows Git's effective path in linked worktrees and with
  `core.hooksPath`.
- [x] A newly installed hook can create its receipt before any prior scan.
- [x] Ephemeral-port serving reports and opens the actual bound URL.

All four findings are fixed and covered by adversarial regression tests. The
post-fix repository suite passes (`1060 passed, 124 subtests passed`), and Ruff
passes on every touched Python file. These were operating-system and Git
contract questions rather than unresolved algorithmic questions, so primary
Python and Git documentation was a stronger source than secondary or academic
literature.

The standard test suite passes (`1050 passed, 4 skipped, 124 subtests passed`),
but the following edge cases were reproduced independently. The three Ruff
findings under `docs/findings/fixtures/` are fixture-formatting issues and are
not included here as program defects.

## 1. A live state-file lock can be stolen after 120 seconds

- **Severity:** High
- **Location:** `src/graphgraph/runtime/state.py:15-65`
- **Affected callers:** atomic state writes, memory, temporal data, evidence,
  cache updates, delta appends, graph compaction, and incremental graph saves.

`file_lock()` treats any lock file older than `stale_seconds` (120 seconds by
default) as abandoned. It unlinks that file without checking whether its owner
process is still alive. A second writer can therefore enter the critical
section while a slow first writer is still active. Both writers then believe
they hold the lock, allowing lost updates or corrupted state.

Minimal reproduction (the shorter threshold demonstrates the same production
code path without waiting two minutes):

```python
import tempfile
import threading
import time
from pathlib import Path

from graphgraph.runtime.state import file_lock

path = Path(tempfile.mkdtemp()) / "state.json"
inside = []
overlap = []
barrier = threading.Barrier(2)

def holder():
    with file_lock(path, stale_seconds=0.01):
        inside.append("holder")
        barrier.wait()
        time.sleep(0.12)
        inside.remove("holder")

def waiter():
    barrier.wait()
    time.sleep(0.03)
    with file_lock(path, stale_seconds=0.01):
        overlap.extend(inside)

a = threading.Thread(target=holder)
b = threading.Thread(target=waiter)
a.start(); b.start(); a.join(); b.join()
print(overlap)
```

Actual result: `['holder']`, proving that both threads were inside the protected
section simultaneously. Expected result: `[]`.

**Suggested correction:** use an operating-system lock where possible, or
verify that the recorded owner PID is dead before breaking a stale lock. An
age threshold alone must not revoke a live owner's lock.

### Resolution: fixed

`file_lock()` now holds a nonblocking operating-system advisory lock for the
entire critical section: `fcntl.flock()` on POSIX and `msvcrt.locking()` on
Windows. The OS releases the lock when a process exits, eliminating both live
lease theft and PID-reuse ambiguity. `stale_seconds` remains accepted for API
compatibility but no longer grants revocation authority.

The `.lock` file intentionally remains as a stable rendezvous inode. Deleting
it during release would allow one waiter to lock the unlinked inode while a
third process creates and locks a different inode at the same path.

Regression coverage:

- `FileLockTest.test_live_lock_is_not_stolen_when_age_threshold_expires`
- `FileLockTest.test_lock_is_recoverable_after_owner_process_exits_without_cleanup`
- Existing timeout, transient/persistent permission, concurrent-write, and
  atomic-replace tests

Design evidence: Python documents nonblocking exclusive `flock` and its
portable contention errors in [`fcntl`](https://docs.python.org/3/library/fcntl.html),
and documents the equivalent nonblocking byte-range lock in
[`msvcrt`](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking).

## 2. Git-hook installation does not support linked worktrees or `core.hooksPath`

- **Severity:** Medium
- **Location:** `src/graphgraph/platform/service.py:402-408`

`install_git_hooks()` hard-codes `<root>/.git/hooks` and requires `.git` to be a
directory. In a linked Git worktree, `.git` is a file that points at the real
per-worktree Git directory, so the command rejects a valid repository:

```text
ValueError: not a Git repository: /tmp/.../linked
```

The same assumption silently installs unused hooks when the repository has a
custom `core.hooksPath`. In a reproduction with `core.hooksPath=.custom-hooks`,
GraphGraph reported installation under `.git/hooks`, while
`git rev-parse --git-path hooks` returned `.custom-hooks`.

**Suggested correction:** ask Git for the effective hooks directory (for
example, via `git rev-parse --git-path hooks`) instead of deriving it from the
working-tree layout.

### Resolution: fixed

The installer now asks Git for both the canonical worktree root and the
effective hooks path. Relative hook paths are resolved from that canonical
root, so calling from a subdirectory cannot place receipts or hooks in the
wrong directory. Invalid repositories, missing Git, and configured hook paths
that resolve to non-directories produce explicit errors.

Regression coverage:

- `PlatformTest.test_git_hook_install_uses_custom_hooks_path_and_linked_worktree`
- `PlatformTest.test_git_hook_install_is_idempotent_and_preserves_existing_hook`

Design evidence: Git's worktree documentation says callers should not assume
the physical `$GIT_DIR` layout and should use `git rev-parse --git-path`; the
[`git-rev-parse`](https://git-scm.com/docs/git-rev-parse) and
[`githooks`](https://git-scm.com/docs/githooks) manuals define the effective
path and `core.hooksPath` behavior.

## 3. Newly installed hooks fail if `.graphgraph/` does not already exist

- **Severity:** Medium
- **Location:** `src/graphgraph/platform/service.py:412-415`

The generated hook redirects command output directly to
`.graphgraph/hook-receipt.json`, but the installer does not create that
directory. Shell redirection happens before `graphgraph` starts, so a hook
installed before the first scan never runs the refresh command.

Reproduction result from executing a newly installed hook in a repository
without `.graphgraph/`:

```text
return code: 2
cannot create .graphgraph/hook-receipt.json: Directory nonexistent
```

**Suggested correction:** create the directory during installation and/or add
`mkdir -p .graphgraph` to the managed hook before the redirect. The installer
should also report clearly if a refresh graph has not been initialized.

### Resolution: fixed

Installation creates `<worktree>/.graphgraph`, and the managed block also runs
`mkdir -p .graphgraph` immediately before redirection. The second guard matters
if a user removes the state directory after installation. The executable is
shell-quoted before insertion into the hook.

Regression coverage:

- `PlatformTest.test_new_hook_recreates_receipt_directory_before_redirect`

That test removes the directory after installation, performs a real Git
commit, and verifies that the actual `post-commit` hook recreates the directory
and writes parseable JSON to `hook-receipt.json`.

## 4. `platform serve --port 0 --open` opens the wrong browser URL

- **Severity:** Low
- **Locations:** `src/graphgraph/platform/service.py:354-368` and
  `src/graphgraph/cli/platform.py:436-445`

Port `0` asks the operating system to choose an available port. The bound port
is available as `server.server_address[1]`, but `serve_graph()` constructs the
browser URL from the original `port` argument. The CLI also prints that
original value before the server binds.

A focused reproduction with a fake server assigned port `43123` recorded the
browser target as:

```text
actual listener: 43123
opened URL: http://127.0.0.1:0
```

**Suggested correction:** after creating the server, use its bound address and
port for both the displayed console URL and `webbrowser.open()`.

### Resolution: fixed

`serve_graph()` now derives one URL from `server.server_address[1]` after the
bind. It passes that URL to an `on_ready` callback and to the delayed browser
launch. The CLI prints only from `on_ready`, so it cannot announce port `0`
before the listener exists. IPv6 hosts are bracketed when forming the URL.

Regression coverage:

- `PlatformTest.test_serve_graph_uses_bound_port_for_ready_and_browser_urls`
- `PlatformTest.test_platform_serve_announces_only_the_post_bind_url`
