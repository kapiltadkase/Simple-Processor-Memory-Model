# Two-core MESI cache simulator in Sitar

Two simulated processors read and write the same 256 bytes of data memory. Each has a private cache, so both can hold a copy of the same address. If core 0 changes its copy, how does core 1 get the new value? The model implements **MESI cache coherence** to keep those copies consistent. It also lets you measure how often each core hits in its cache, goes to memory, or asks the other core to give up a block.

The original A1 assignment starts with one processor talking to memory. Its bonus questions introduce caches, concurrency, set associativity, and write-back. This project extends that work with a second core, shared data memory, multiple replacement policies, and MESI. The processors in this version generate memory requests from a workload. The simulator models exactly two cores.

## Build and run

From this directory, with the Sitar toolchain on your PATH (including its SCons and C++ build dependencies), run:

```sh
sitar translate main.sitar
sitar compile
./sitar_sim 1000
```

Translation generates C++ in `Output/`. Compilation builds `sitar_sim`. Rebuild after editing the model. The number after the executable is the **maximum simulated cycles**. The default fixed workload should finish with `PASS shared core=0`, `PASS shared core=1`, and `PASS two_cores=2`.

For a longer workload, choose the settings at launch. For example, run the same address stream with three replacement policies:

```sh
SITAR_WORKLOAD=locality SITAR_SEED=42 SITAR_POLICY=lru    ./sitar_sim 100000
SITAR_WORKLOAD=locality SITAR_SEED=42 SITAR_POLICY=fifo   ./sitar_sim 100000
SITAR_WORKLOAD=locality SITAR_SEED=42 SITAR_POLICY=random ./sitar_sim 100000
```

To compare write policies on the same workload and replacement policy:

```sh
SITAR_WRITE_POLICY=write-back    SITAR_POLICY=lru SITAR_WORKLOAD=locality SITAR_SEED=42 ./sitar_sim 100000
SITAR_WRITE_POLICY=write-through SITAR_POLICY=lru SITAR_WORKLOAD=locality SITAR_SEED=42 ./sitar_sim 100000
```

To compare address patterns, keep the policy and seed fixed and change `SITAR_WORKLOAD=locality` to `SITAR_WORKLOAD=uniform`. These settings use the same binary.

| Setting | Choices and meaning |
|---|---|
| `SITAR_WORKLOAD` | `fixed` (default) runs eight predictable data accesses per core. `uniform` samples all 64 words. `locality` chooses from the first eight words with 75% probability and from all 64 otherwise. Both cores use the same hot region. |
| `SITAR_POLICY` | `lru` (default), `fifo`, or `random`. Applies to both **data** caches. |
| `SITAR_WRITE_POLICY` | `write-back` (default) or `write-through`. Both data caches use the same mode, with write-allocate and coherence in either mode. |
| `SITAR_SEED` | Unsigned 32-bit workload seed, default 42. Each core gets its own repeatable stream. Random replacement uses a separate, fixed generator seed. |

Uniform and locality each issue 256 accesses per core, with a 25% chance of a store per access. The current locality generator uses a fixed hot region; it has no separate spatial and temporal locality settings. At the cycle limit, the simulator prints statistics even if the workload is unfinished. For a complete generated workload look for `PASS two_cores=2` and 512 total hits plus misses.

## Follow one request

Using the default write-back mode, start with a cold cache and a read of byte address 44. Memory starts with word 0 equal to 0, word 1 equal to 1, and so on. Address 44 therefore contains word 11.

1. **The processor asks its data cache for address 44.** It sets the address and operation, increments the request ID, and waits for the matching response ID. The cache looks for the 16-byte block starting at address 32. Neither cache holds it yet.
2. **Core 0 gets the block.** Its cache issues `BusRd` to check the peer. The peer has no copy, so core 0 fetches the words at addresses 32, 36, 40, and 44 through the memory arbiter. It marks the line Exclusive and returns 11. This is one processor miss, even though four words were fetched.
3. **Core 1 reads address 44.** It also issues `BusRd`. Both copies become Shared. Now either core can read the block locally.
4. **Core 0 writes 101 to address 44.** Its copy is present, so this is a hit. It still needs permission to write. Its `BusUpgr` invalidates core 1’s copy, then core 0 stores 101 and marks its own line Modified. Memory can still contain 11.
5. **Core 1 reads again.** Its copy is invalid, so it misses. Core 0 writes the modified block to shared memory before core 1 fetches it. Core 1 receives **101**, and both copies are Shared again.

## How the model is organized

All simulator components live in [main.sitar](main.sitar). Read them in this order to follow the example above.

| Component | Responsibility |
|---|---|
| `Top` | Connects cores and memories, grants coherence requests, checks coherence, and prints totals. |
| `Core` | Runs three procedures concurrently: the processor, instruction cache, and data cache. Instruction fetches use a private instruction memory. Both data caches use the same physical data addresses. |
| `Processor` | Generates the chosen access sequence and waits for each response. In the default trace both cores visit addresses 0, 32, and 64. Core 0 writes 12345 to address 0; core 1 later reads it. |
| `Cache` | Looks up blocks, counts hits and misses, chooses victims, handles MESI requests, and transfers data. The instruction and data caches share this implementation; coherence is enabled on the data caches. |
| `Arbiter` | Accepts one data-memory word transaction at a time and returns the reply only to the requesting core. |
| `Memory` | Holds 64 four-byte words. Valid word addresses are 0, 4, …, 252. Checks the operation, alignment, and bounds before accessing data. |

There are two paths to follow in the source. **Coherence** asks who holds a block and who can write it. The bus logic in `Top` gives simultaneous requests round-robin priority, initially favoring core 0. It lets the granted access finish before granting the next one. If two sharers request upgrades, the losing core may have lost its copy and must retry with `BusRdX`.

**Memory traffic** carries the actual fills and dirty evictions through `data cache → arbiter → shared memory`. The arbiter also uses round-robin priority. It handles individual words, so a whole block transfer is not atomic at this interface. A request occupies 10 bytes (core ID, operation, address, value); a reply occupies 5 bytes (error, value). Error 0 means success, 1 out of bounds, 2 misaligned, and 3 invalid operation. Sitar nets are read in phase 0 and written in phase 1. In the source, `||` runs workers concurrently, `wait` pauses a worker, and code inside dollar signs is C++.

## Cache organization, replacement, and writes

By default each cache has **2 sets × 2 ways × 16 bytes = 64 bytes**, enough for four of the 16 data-memory blocks. A set is the group where a block is allowed to live; a way is one slot in that group. The set index is `(address / BLOCK_SIZE) % NUM_SETS` using integer division. For example, blocks starting at 0, 32, and 64 all compete for the same two slots.

On a miss the cache uses an invalid slot in the target set first. If the set is full, LRU removes the least recently accessed block, FIFO removes the earliest inserted block, and Random chooses a way in that set. On a write miss, the cache fetches the block and then writes into it (**write-allocate**).

| MESI state | Meaning and behavior |
|---|---|
| Invalid (I) | No usable copy. A read miss issues `BusRd`; a write miss issues `BusRdX` to obtain ownership and invalidate peer copies. |
| Exclusive (E) | The only cached copy, matching memory. A local store needs no coherence transaction. It ends in M for write-back or E for write-through. |
| Shared (S) | Clean copy that another cache may hold. Before writing, issue `BusUpgr` to invalidate the peer. |
| Modified (M) | The sole owner of the latest data. Local reads and writes stay in M. Before giving the block to a peer or evicting it, preserve its latest contents in memory. |

**Write-back** means a store can finish before main memory receives the new value. A dirty eviction writes each word and waits for its acknowledgement before reusing the line. A clean E or S line can be discarded. When a peer requests modified data, the snoop handler copies the entire block to shared memory atomically in this model. Dirty lines can remain cached when simulation ends.

**Write-through** obtains the same ownership permissions and invalidates peer copies before writing. Every successful store sends one four-byte word through the memory arbiter and waits for acknowledgement before completing. The writer keeps a clean Exclusive copy, so its eviction needs no dirty write-back. There is no write buffer.

The cache also supports one extra read. During dirty eviction it can serve a hit on a different resident block. A read of the victim or a miss needing memory must wait. The concurrent-read fixture compares this behavior with blocking enabled.

To change cache geometry, edit the structural parameters `NUM_SETS`, `NUM_WAYS`, and `BLOCK_SIZE` in `Cache` and rebuild. They must be powers of two; block size is 4–256 bytes. Edit `CACHE_DELAY` and `MEM_DELAY` assignments in `Top` to change timing. The default gives core 0 zero cache delay and core 1 one cycle, so identical hits can have different latencies. Phase and bus waits can still take time when a configured delay is zero.

## Read the trace and statistics

An entry such as `ACCESS core=0 id=3 address=152 hit=1 write=0 error=0 ticks=0` is core 0’s third completed request: a successful read hit at byte address 152. `ticks` measures latency in simulator ticks (two per cycle). `WRITEBACK_START` and `WRITEBACK` bracket a dirty eviction. At exit, `DATA CACHE` rows report each core and their sum.

| Counter | What counts |
|---|---|
| `hits`, `misses` | Successful data accesses, including extra reads. An upgrade that retains its copy is a hit. Hit rate = hits / (hits + misses). |
| `BusRd`, `BusRdX`, `BusUpgr` | Granted coherence transactions for a read, a write needing a copy, or a write upgrading a shared copy. A canceled upgrade is excluded; its granted retry counts. |
| `invalidations` | Valid copies lost to a peer’s request, charged to the core that lost the copy. |
| `writebacks` | Whole dirty blocks written to memory on eviction or intervention, charged to the core supplying the data. |
| `memory_write_bytes` | Data bytes written to shared memory, attributed to the writing core. Includes dirty evictions, snoop interventions, and individual write-through stores. Compare this counter and the simulation stop time on completed runs. |
| `coherence_misses` | First successful miss on a block since a peer invalidated this core’s copy. This is a subset of misses. Cold misses and ordinary replacement misses do not qualify. |

For a partial run, use the completed hits and misses as the denominator. A granted bus request may still be in progress at the cutoff. The fixed trace with default geometry and LRU expects one hit and seven misses per core; generated workloads and other policies can give different results.

## Automated verification

Run from this directory with Python 3 and the Sitar toolchain available. Keep assertions enabled.

```sh
python3 check.py
```

The checker builds temporary variants of the model, compiles them, and runs controlled workloads. Some replace the normal processor with a test processor; the snoop test drives the two caches directly. The source in your project directory stays intact. During simulation, completed data operations check valid cached words against an independent record of stores. If both cores hold a block, both must be Shared. Memory must match the reference unless a Modified owner exists.

## File guide

| File | What you use it for |
|---|---|
| [main.sitar](main.sitar) | The complete model, default workloads, actual replacement policies, and statistics. Build this file for a normal run. |
| [check.py](check.py) | Runs regressions for coherence, cache geometry, delays, errors, locality, replacement, read overlap, and counter totals. |
| [mixed.sitar](mixed.sitar) | Test processor that issues instruction and data requests together and checks data, errors, and timing. |
| [lru.sitar](lru.sitar), [fifo.sitar](fifo.sitar) | Test processors that exercise the expected replacement order and dirty eviction. The policy implementations themselves are in the cache. |
| [concurrent.sitar](concurrent.sitar) | Exercises an extra read during write-back and measures execution time with and without read overlap. |
| [snoop.sitar](snoop.sitar) | Deterministic two-core trace for shared reads, intervention, alternating writes, simultaneous requests, and eviction or reuse of lines in all four MESI states. |
| [Assignment handout](<A1 Proc-Mem Models (Sitar Users’ Group).pdf>) | Original requirements. Q1–Q4 are compulsory and Q5–Q10 are bonus work. |
| [Simulation notes](<Sitar Cache Simulation Notes.docx>) | Worked examples and notes on the two-core extension. Both documents are local reference files ignored by Git. |
| `Output/`, `sitar_sim` | Generated C++ headers, sources, object files, and the compiled executable. Edit the Sitar source and rebuild to change the simulator. |
| `sitar_scons_config.txt`, `.sconsign.dblite`, `.gitignore` | Local build configuration, SCons build records, and Git’s list of files to exclude. |
