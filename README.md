# Blocking write-back caches

Build with `sitar translate main.sitar`, then `sitar compile`.
Run `./sitar_sim 1000`; require `PASS requests_per_cache=20`.
Run `python3 check.py` for the configuration and workload checks.

Core runs the processor and two Cache procedures concurrently. Each cache has
its own external memory. Shared request/response sequence numbers allow one
outstanding request per cache and same-phase completion for zero-delay hits.
External memory reads occur in phase 0 and writes in phase 1.

NUM_SETS, NUM_WAYS, and BLOCK_SIZE are structural template parameters; edit
their defaults in main.sitar and rebuild. All must be powers of two. The default
is two sets, two ways, and 16-byte blocks. Aligned 32-bit accesses and a 256-byte
memory limit supported block sizes to 4 through 256 bytes.

For address a, offset = a % BLOCK_SIZE, set = (a / BLOCK_SIZE) % NUM_SETS,
and tag = a / BLOCK_SIZE / NUM_SETS. Lookup searches only the selected set.
A miss uses an invalid way first, otherwise a uniformly random victim from
that set. A fixed seed makes the replacement sequence reproducible.

Each block holds bytes, a tag, a valid bit, and a dirty bit. A store hit updates
cached bytes and sets dirty without accessing memory. A miss first writes a
valid dirty victim's entire block to its original memory address. Only after
all writes succeed does it clear dirty and increment writebacks. It then
fetches the requested block, installs it clean, and performs the original
load or store. A store miss therefore leaves the newly allocated block dirty.
Data words are assembled and split in big-endian order.

Write-back and fill use serialized word transfers through the existing memory
interface. Each word incurs MEM_DELAY plus net transport delay; writing a full
block costs the same transfer time as reading a full block. Every cache request
also pays CACHE_DELAY. Both delays are initialized independently in Top.
The cache blocks during eviction and fill. The other cache can still proceed.
Failed write-back preserves the victim's valid and dirty state; failed fills
are never installed as valid.

## Validation

The 20-request mixed trace uses an independent array of expected data. It checks
loads and stores, dirty-data persistence across eviction/reload, instruction
memory isolation, invalid addresses, request accounting, concurrent start
and completion, and exact hit latency for both loads and stores. Store values
change with each request, making stale data visible. The final log reports
hits, misses, and block write-backs. Assertions must remain enabled.

check.py runs the mixed trace with direct-mapped, two-way, and fully associative
layouts, independent zero/nonzero delays, and block sizes 4 and 256. It also
runs three controlled workload boundaries with the default layout:

- No stores: write-backs must remain zero.
- Frequent stores within one block: high temporal and spatial locality keep
  dirty data resident, so eviction write-backs remain zero.
- Frequent stores across the memory: low locality exceeds cache capacity,
  forcing dirty evictions. This trace also accesses different sets; the mixed
  trace checks stored-value persistence with subsequent loads.

These deterministic workloads represent store-frequency and locality extremes;
they do not implement a probabilistic P_STORE or locality sweep. More stores
can create more dirty victims, but repeated stores to a resident block combine
into one eventual block write-back. Low locality causes more evictions and
therefore more write-backs when the evicted blocks are dirty.

Dirty resident blocks are not flushed when simulation stops. Reported counts
measure eviction write-backs only; memory can legitimately lag cached data at
termination. No coherence or non-blocking requests are modeled.

All 11 checks pass. With the default layout and zero processing delays:

| Workload | Data hits | Data misses | Write-backs | Completion cycle |
| --- | --- | --- | --- | --- |
| No stores | 7 | 11 | 0 | 88 |
| Local stores | 17 | 1 | 0 | 8 |
| Streaming stores | 0 | 18 | 14 | 256 |
| Mixed | 7 | 11 | 6 | 136 |

The mixed trace takes 168 cycles with 7 write-backs for four sets/one way,
and 32 cycles with no write-backs for one set/four ways. For the default
layout, delay pairs (2,0), (0,3), and (2,3) finish at cycles 176, 340, and
380, all with six write-backs. Instruction-cache write-backs are zero in
every run because instruction requests are reads only.
