# Set-associative processor caches

Build with `sitar translate main.sitar`, then `sitar compile`. Run
`./sitar_sim 1000`; success prints `PASS requests_per_cache=20`.
Run `python3 check.py` for configuration and delay checks.

Top connects Core to separate instruction and data memories. Core runs the
processor and two instances of the same Cache procedure concurrently, using
shared request/response sequence numbers. External memory uses phase-0 reads
and phase-1 writes. One request per cache may be outstanding.

Cache has structural template parameters NUM_SETS, NUM_WAYS, and BLOCK_SIZE.
Change their defaults in `main.sitar` to configure both caches and rebuild.
Each must be a positive power of two. This word-access model supports block
sizes from 4 through 256 bytes, matching its aligned 32-bit accesses and 256-byte
memory. The default is two sets, two ways, and 16 bytes per block (64 bytes total).
Each block contains byte data, a tag, and a valid bit.

For address a, offset = a % BLOCK_SIZE, set = (a / BLOCK_SIZE) % NUM_SETS,
and tag = a / BLOCK_SIZE / NUM_SETS. Lookup examines all ways in that set.
A miss uses an invalid way first; a full set evicts a uniformly selected random
way. A fixed seed makes runs reproducible. Block fills read consecutive words
from external memory and install the block only after successful completion.
Words are stored in cache bytes in big-endian order. Stores remain write-through
and write-allocate: memory is updated before a missing block is fetched.

CACHE_DELAY and MEM_DELAY are independent whole-cycle parameters initialized
in Top. Every cache access pays CACHE_DELAY; a miss additionally pays for each
word fetched, including net transport. A zero-delay hit completes in the same
phase. Block transfers are serialized words, so a larger block costs more to
fill. There are no dirty bits or write-back behavior.

## Validation and comparison

The processor uses general names such as addresses, index, slot, way, and tag.
Its 20-request trace checks returned data, stored-value persistence, instruction
and data isolation, invalid alignment and range, hit/miss accounting, spatial
hits, repeated hits, and exact hit delay. Both caches must start each pair at
the issue timestamp; completion must equal the later cache completion time.
Assertions must stay enabled, and a run must reach PASS.

The comparison holds capacity at four 16-byte blocks and varies the layout:
4 sets x 1 way (direct-mapped), 2 sets x 2 ways, and 1 set x 4 ways (fully
associative). Addresses 0, 64, 128, and 192 intentionally map to one set in
all three configurations. Greater associativity can retain more of those
blocks, reducing conflict misses. This is a conflict-heavy trace, not a claim
that every workload benefits equally. Random eviction results depend on the
seed and request sequence.

The check script also tests cache/memory delays (2,0), (0,3), and (2,3),
and block sizes 4 and 256. It builds temporary copies without modifying the
working model and fails if compilation, assertions, or the PASS marker fail.

Measured results with both configured delays zero (hits/misses per cache;
two invalid requests excluded):

| Sets | Ways | Hits | Misses | Completion cycle |
| --- | --- | --- | --- | --- |
| 4 | 1 | 4 | 14 | 114 |
| 2 | 2 | 7 | 11 | 90 |
| 1 | 4 | 14 | 4 | 34 |

For the default two-way layout, delay pairs (2,0), (0,3), and (2,3)
finish at cycles 130, 225, and 265 respectively, with unchanged hit counts.
All eight tested configurations pass.
