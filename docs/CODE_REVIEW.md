# Review of 024e3a5

Reviewed `git diff 8f1b94e...024e3a5` against the user BRD and the repository's
architecture/security contracts. Findings below refer to the original commit's line
numbers. Standards and specification reviews were independent. All findings below
have regression coverage and are fixed in the accompanying changes.

## Standards

1. **P1: deadlines stop after the first streamed chunk.** `backends/rpc_backend.py:61`
   creates an asyncio timeout across generator yields; `provider.py:104,116` uses a
   new task for each read. The timer cancels the already-completed first task.
   This violates the documented whole-request deadline. Fixed by assigning each
   stream a persistent producer task with a bounded output queue.
2. **P1: shutdown misses suspended streams.** `provider.py:133` closes clients before
   cancelling tasks; a generator paused between chunks has no task to cancel or
   run interrupt cleanup. Fixed by tracking producer tasks and cancelling/awaiting
   them before closing remaining clients. Closing a provider is now terminal.
3. **P2: write errors escape normalization.** `rpc/client.py:34` lets socket errors
   and WebSocket close reasons escape directly, violating the documented safe-error
   contract. Writes now normalize network errors and retain a terminal failure.
   RPC deadlines cover write-lock admission and sending as well as response waits.
4. **P2: dead readers accept new requests.** `rpc/client.py:50` fails current futures
   without retaining failure state; later requests can wait their full timeout on
   a client whose reader has exited. Failed clients now reject subsequent work
   immediately and safely.

No separate coding standards document was present. No cosmetic smell findings were
considered blocking; these are documented lifecycle/error-contract violations.

## Spec

1. **P1: stalled streaming is unbounded after a delta (FR-13/19/20).** Same deadline
   defect described above. Covered by a first-delta-then-stall regression.
2. **P1: disconnects discard received success (FR-13/20).** `rpc/client.py:50–57`
   empties pending notifications on EOF, deleting text and terminal events already
   received. The client now preserves ordered received events and exposes its
   retained failure after the queue drains.
3. **P2: unsupported options silently ignored (FR-11/12).** `provider.py:63–75`
   only rejects a short list; top_p, stop, seed and logprobs passed directly are
   ignored. Explicit framework-option allowlists now reject unsupported direct
   and optional parameters, including unimplemented stream options/extra headers.
4. **P2: invalid parameters reported as unavailable (FR-25).** `rpc/client.py:97–98`
   discards the RPC error code. Code -32602 now maps to a safe HTTP 400 error
   without reflecting server text.
5. **P2: malformed payloads leak Python exceptions (FR-06/25).**
   `backends/rpc_backend.py:88,96,102,130` indexes unvalidated results/events.
   Malformed envelopes, response IDs, thread/turn identifiers, deltas and token
   usage now produce safe protocol errors instead of raw tracebacks/data.

Explicitly deferred stateful sessions, legacy mode, dynamic tools and live completion
acceptance were not counted as defects in implemented behavior.

## Validation

The original three reproductions failed on the reviewed commit, then passed after
fixes. The full suite passes **39 tests**, including 20 added regressions for
stream deadlines, paused-stream interruption, direct backend shutdown, event
preservation, safe write failures, RPC deadlines, malformed protocol/usage and
unsupported options. Final re-review reproduced two further shutdown races: cancellation
before the producer starts and cancellation while publishing a terminal event to a full
queue. A task completion callback now signals both cases; three regressions cover them.
Existing Unix/WebSocket concurrency and real LiteLLM Proxy
HTTP/SSE tests remain enabled. Upstream dependency deprecation/serialization
warnings remain visible. Live authenticated model completion remains unverified;
this review does not establish production runtime isolation or subscription access.

Standards: **4 findings**, worst P1 streaming deadline/shutdown. Spec: **5 findings**,
worst P1 streaming deadline/event loss. Overlap is intentional; 8 distinct findings.
