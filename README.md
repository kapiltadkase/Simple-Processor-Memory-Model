# Two-core shared data memory

Build with `sitar translate main.sitar`, then `sitar compile`; run
`./sitar_sim 1000`. Expect `PASS shared core=0`, `PASS shared core=1`,
and `PASS two_cores=2`. Run `python3 check.py` for regressions.

To compare address patterns, run the same binary twice:

```sh
SITAR_WORKLOAD=uniform SITAR_SEED=42 ./sitar_sim 100000
SITAR_WORKLOAD=locality SITAR_SEED=42 ./sitar_sim 100000
```

Each core issues 256 aligned data accesses, with a one-in-four chance of a store.
Uniform samples all 64 words. Locality samples the first eight words three
quarters of the time and all 64 otherwise. Both cores share that hot region.
The seed defaults to 42. Each core has its own repeatable stream. Divide total
hits by 512 to get the combined hit rate. The default workload is fixed.

Each core has private instruction and data caches. Both data caches use exactly
one `data_memory : Memory`, containing 64 four-byte words. Instruction memories
remain private and separate from the shared data address space.

Request flow:

```text
core.data_cache  -> data_request  -> arbiter.request0 ─┐
                                                    ├-> shared_request -> data_memory
core1.data_cache -> data_request1 -> arbiter.request1 ─┘
```

Both cores use identical physical byte addresses (0 through 255), without any
core-specific translation or offset. Aligned word addresses range from 0 to 252.
Requests carry core ID, operation, address and value in 10 bytes. Memory validates
operation, alignment and bounds and returns a 5-byte error/value response.

The arbiter samples available requests in phase 0. If both are ready, it grants
round-robin priority, initially core 0; after each grant priority switches to the
other core. It forwards the unchanged request in phase 1 and waits for memory's
reply before accepting another request. It remembers the owner and routes the
reply from `shared_response` to only `data_response` or `data_response1`.
Full output nets are retried. This serializes individual word transactions,
including write acknowledgments and errors, with deterministic arbitration.
A whole block transfer is not atomic: words from different cores may interleave.

Caches retain write-back/write-allocate behavior and LRU, FIFO and RANDOM
replacement. A dirty eviction writes all words of the victim block before filling
the new block. Each word waits for its response. Cache hits remain private;
shared memory arbitration only applies to fills and write-backs. Configure cache
and memory delays in Top. NUM_SETS, NUM_WAYS and BLOCK_SIZE are structural
parameters; defaults are two sets, two ways and 16-byte blocks.

Inspect a private cache line with `data_cache.mesi_state(set, way)`. The shared
Cache implementation initializes every line to I (Invalid). A data read miss issues BusRd. The new line
is Exclusive when the peer has no copy and Shared otherwise. A read hit
keeps its state. Stores to Exclusive or Modified lines complete locally in
Modified. A store to a Shared line issues BusUpgr. A write miss issues BusRdX.

The bus broadcasts the requester ID and aligned block address to the peer.
BusRd downgrades a present peer to Shared. BusRdX and BusUpgr invalidate
its copy. A Modified peer writes the entire block to shared memory before
downgrading or invalidating it. This intervention is atomic in the simulator.

Simultaneous requests use round-robin priority, initially core 0. The bus
waits for each granted processor access to finish before the next grant.
A competing upgrade that lost its shared copy retries with BusRdX. Dirty
evictions still use the ordinary word-by-word write-back path.
Dirty lines are not automatically flushed at termination.

## Tests

Each core finishes with two reads of address 0. The first brings the block into
its cache and the second hits, giving one hit and seven misses per core.

The default two-core driver first reads address 0 from both caches, then evicts
that clean line using addresses 32 and 64. Core 0 stores 12345 at address 0 and
forces a dirty eviction. Core 1 waits for core 0 to finish and reads address 0
again through a cache miss, asserting that it sees 12345. Both processors check
every returned value and error, including different word values from the same
shared memory. This demonstrates shared backing storage without assuming
coherence. The test uses the default cache geometry and LRU policy.

`check.py` runs this shared test with zero and nonzero memory delays. It also
retains the earlier mixed, locality, streaming, replacement-policy and concurrent
read tests, using only core 0 for those independent-memory oracle workloads.
Those regressions exercise multiple cache geometries and delays, invalid inputs,
dirty eviction, read bypass and exact hit latency. Assertions must stay enabled.
