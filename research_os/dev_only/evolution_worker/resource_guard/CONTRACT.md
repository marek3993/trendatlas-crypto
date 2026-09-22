# Process memory guard, observed-kernel correction 2026-09-22

The installed Pi kernel exposes cpuset/cpu/io/pids but no memory controller.
MemoryMax=384M and MemorySwapMax=0 remain configured, but cannot be claimed as
enforced cgroup limits on this host. Research was paused on discovery. Production
and boot/kernel configuration must not be changed to repair this research limit.

Add an independently pinned OS resource wrapper and research-only service drop-in:
LimitAS=384M bounds the entire interpreter virtual address space (stricter than
an RSS ceiling); LimitMEMLOCK=384M allows unprivileged mlockall(CURRENT|FUTURE).
The wrapper verifies both hard and soft bounds and successful mlockall BEFORE
running the original verified bootstrap in the same process. Failure blocks startup.
Memory locking prevents paging of current/future historical-computation memory.
The fixed read-only systemctl query helpers inherit the address-space limit, but
memory locks do not survive their exec; no claim of working cgroup swap accounting
is made. They process only service metadata, not historical simulations or secrets.
No capability, production change, swapoff, boot edit or reboot is needed.

Original release d534035a216a134cce610f80eec32afb8f0461bd remains byte-for-byte
immutable, as do accepted job release hashes, studies, seeds, input and SEALED files.
This is an external process-launch resource restriction, not a research-code update
or experiment restart. Record the wrapper/drop-in SHA256 separately in the deployment
audit. Resume only after a real same-sandbox probe reports VmLck >0 and VmSwap=0,
the original 384 MiB address-space hard limit, and the successful mlockall call.

Crash recovery addendum: a killed SQLite writer may leave a hot rollback journal.
The original ready/status readers open SQLite read-only, which cannot roll back
that journal. Before dispatcher admission, the pinned launch wrapper acquires
worker.lock non-blocking and asks SQLite to recover only existing hot journals in
queue.sqlite3 or unsealed jobs/*/research.sqlite3. Never open a SEALED job writable.
No custom SQL mutation, metadata rewrite or re-selection is allowed. The dispatcher
gets write access only to research state for this recovery, keeps its original
production/worker gates and runs only the original bootstrap ready command.
The status command remains read-only. This fixes restart recovery without editing
the immutable running research release or any accepted experiment/code hash.
