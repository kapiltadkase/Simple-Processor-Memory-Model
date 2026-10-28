# Concurrent processor and caches

Build with `sitar translate main.sitar`, then `sitar compile`. Run
`./sitar_sim 1000`. Success prints `PASS requests_per_cache=10`.

Top contains one Core compute module and two external Memory modules. Core runs
`processor`, `instruction_cache`, and `data_cache` in a parallel block. Both
caches are instances of the same Cache procedure class. Change CACHE_DELAY and
MEM_DELAY independently in Top's init block; zero and positive cycle delays are
supported.

The processor sets each cache's address, write flag, and write_data, then
increments request_id. The cache snapshots those fields and publishes read_data
and error before updating response_id. One request may be outstanding per cache.
Sequence numbers allow consecutive same-phase requests without losing a brief
boolean handshake transition.

Sitar interleaves parallel branches and re-executes them until no branch can
advance in the current phase. A wait-until condition can become true through
another branch without advancing time. Thus a zero-delay cache hit returns in
the same cycle and phase. These procedures share one module's state; they are
not independent operating-system threads. The installed examples
`/home/kapil/sitar/examples/7_Parallel.sitar` and `8_Procedures.sitar` illustrate
these constructs.

Only external memory uses nets. Even MEM_DELAY=0 leaves request/response
transport delay: cold reads issued at (0,0) return at (2,0). The next pair of
cached reads starts and finishes at (2,0), demonstrating actual zero latency.

## Validation

The finite processor trace checks returned values and error codes with asserts.
Both requests are issued before either response is awaited. Both caches must
start at the issue timestamp; the pair finishes at the maximum of the two
completion timestamps. The initial cold reads overlap rather than execute one
after another. Read-hit latency must equal exactly CACHE_DELAY, including zero.

The trace tests repeated hits, a store followed by a load, a conflicting address
that evicts the stored word, and a reload that verifies persistence in memory.
Instruction reads must remain unchanged by data stores. Out-of-range and
unaligned addresses must report errors. Consecutive zero-delay requests expose
lost handshakes and stale responses. A finite trace avoids an infinite zero-time
request loop. Keep assertions enabled and require the final PASS marker;
reaching the simulator's time limit alone is not success.

Test zero and nonzero delays independently, especially unequal cache and memory
delays, to expose unintended coupling. The model uses four direct-mapped word
lines and write-through, write-allocate stores. It intentionally omits block
fills, dirty lines, coherence, and full instruction execution. Each pair waits
for both results before issuing the next pair; concurrency is demonstrated
within each pair. Configured processing delays are whole cycles, while shared
communication can complete within one phase.
