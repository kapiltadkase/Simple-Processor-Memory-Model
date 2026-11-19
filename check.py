"""Check cache regressions and shared two-core backing memory."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

if not __debug__:
    raise RuntimeError('Run check.py without Python optimization so regression assertions are enabled')

os.environ.pop('SITAR_POLICY', None)  # Each regression selects its own policy.
os.environ.pop('SITAR_WRITE_POLICY', None)
os.environ.pop('SITAR_P_STORE', None)
shared_source = Path(__file__).with_name('main.sitar').read_text()
source = re.sub(r'procedure Processor\n.*?end procedure', lambda _: Path(__file__).with_name('mixed.sitar').read_text(), shared_source, flags=re.S)
source = re.sub(r'^.*processor\.peer = .*\n', '', source, flags=re.M)
source = source.replace('run processor;', 'if ($data_cache.core_id == 0$) then run processor; else $processor.done = true;$; end if;')

# Pause the processors so the test controls exactly when each cache asks for the bus.
snoop = Path(__file__).with_name('snoop.sitar').read_text()
model = shared_source.replace('run processor;', 'wait until (0);')
declarations, behavior = snoop.split('\nbehavior\n')
model = model.replace('    init $', declarations + '\n    init $', 1)
model = model.replace('wait until ($core.processor.done && core1.processor.done$);', behavior)
with tempfile.TemporaryDirectory() as directory:
    Path(directory, 'main.sitar').write_text(model)
    for command in [['sitar', 'translate', 'main.sitar'], ['sitar', 'compile'], ['./sitar_sim', '10000']]:
        result = subprocess.run(command, cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert result.returncode == 0 and 'FAILURE' not in result.stdout, result.stdout
    assert 'PASS snoop' in result.stdout, result.stdout
    print('PASS snoop: broadcast, arbitration and dirty intervention')
    rows = [line for line in result.stdout.splitlines() if line.startswith('DATA CACHE')]
    fields = ('hits', 'misses', 'BusRd', 'BusRdX', 'BusUpgr', 'invalidations', 'writebacks', 'coherence_misses', 'memory_write_bytes')
    expected = [(7,12,8,4,1,6,6,3,96), (1,9,4,5,1,4,4,4,64)]
    expected.append(tuple(map(sum, zip(*expected))))
    assert len(rows) == 3, rows
    for label, row, values in zip(('core=0', 'core=1', 'total'), rows, expected):
        assert row == 'DATA CACHE ' + label + ' ' + ' '.join(
            f'{name}={value}' for name, value in zip(fields, values)), row
    print('\n'.join(rows))

for sets, ways, block, cache_delay, memory_delay, mode in [
    (4, 1, 16, 0, 0, "mixed"), (2, 2, 16, 0, 0, "mixed"), (1, 4, 16, 0, 0, "mixed"),
    (2, 2, 16, 2, 0, "mixed"), (2, 2, 16, 0, 3, "mixed"), (2, 2, 16, 2, 3, "mixed"),
    (2, 2, 4, 0, 0, "mixed"), (1, 1, 256, 0, 0, "mixed"),
    (2, 2, 16, 0, 0, "reads"), (2, 2, 16, 0, 0, "local"),
    (2, 2, 16, 0, 0, "stream"), (2, 2, 16, 0, 0, "random"),
]:
    model = source.replace("replacement_policy = LRU", "replacement_policy = RANDOM") if mode == "random" else source
    for name, value in [('NUM_SETS', sets), ('NUM_WAYS', ways), ('BLOCK_SIZE', block)]:
        model = re.sub(rf'parameter int {name} = \d+', f'parameter int {name} = {value}', model)
    model = model.replace('.CACHE_DELAY = 0', f'.CACHE_DELAY = {cache_delay}')
    model = model.replace('.MEM_DELAY = 0', f'.MEM_DELAY = {memory_delay}')
    if mode == "reads":
        model = model.replace('index % 2 == 0', 'false')
    elif mode in ("local", "stream"):
        addresses = ([0, 4, 8, 12] * 5 if mode == "local" else
                     [0, 16, 32, 48, 64, 80, 96, 112, 128, 144, 160, 176, 192, 208, 224, 240, 0, 16, 32, 48])
        addresses[6:8] = [256, 2]
        model = re.sub(r'addresses\[20\] = \{[^}]+\}', 'addresses[20] = {' + ','.join(map(str, addresses)) + '}', model)
        model = model.replace('index % 2 == 0', 'true')
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, 'main.sitar').write_text(model)
        for command in [['sitar', 'translate', 'main.sitar'], ['sitar', 'compile'], ['./sitar_sim', '10000']]:
            result = subprocess.run(command, cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert result.returncode == 0 and 'FAILURE' not in result.stdout, result.stdout
        assert 'PASS two_cores=2' in result.stdout, result.stdout
        assert result.stdout.count('PASS requests_per_cache=20') == 1, result.stdout
        assert ' core=0 ' in result.stdout, result.stdout
        summary = next(line.split('PASS ')[1] for line in result.stdout.splitlines() if 'PASS ' in line)
        count = int(re.search(r' writebacks=(\d+)', summary)[1])
        assert 'instruction_writebacks=0' in summary
        if mode in ("reads", "local"):
            assert count == 0, summary
        if mode == "stream":
            assert count > 0, summary
        print(f'mode={mode} sets={sets} ways={ways} block={block} cache_delay={cache_delay} memory_delay={memory_delay}: {summary}')

# The same workload and memory schedule, with read bypass enabled or disabled.
fixture = Path(__file__).with_name('concurrent.sitar').read_text()
for delay in (0, 3):
    times = []
    for blocking in (True, False):
        model = re.sub(r'procedure Processor\n.*?end procedure', lambda _: fixture, source, flags=re.S)
        model = model.replace('parameter int NUM_WAYS = 2', 'parameter int NUM_WAYS = 1')
        model = model.replace('bool BLOCKING = false', f'bool BLOCKING = {str(blocking).lower()}')
        model = model.replace('.MEM_DELAY = 0', f'.MEM_DELAY = {delay}')
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'main.sitar').write_text(model)
            for command in [['sitar', 'translate', 'main.sitar'], ['sitar', 'compile'], ['./sitar_sim', '10000']]:
                result = subprocess.run(command, cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                assert result.returncode == 0 and 'FAILURE' not in result.stdout and 'error ' not in result.stdout, result.stdout
            assert 'PASS concurrent' in result.stdout, result.stdout
            times.append(int(re.search(r'COMPARE ticks=(\d+)', result.stdout)[1]))
            print(f'blocking={blocking} memory_delay={delay}: ' + next(line for line in result.stdout.splitlines() if 'COMPARE ' in line))
    assert times[1] < times[0], times
    print(f'Concurrent reads save {times[0]-times[1]} ticks with memory_delay={delay}')

# The same cache must honor access order for LRU and insertion order for FIFO.
for policy in ("LRU", "FIFO"):
    fixture = Path(__file__).with_name(f'{policy.lower()}.sitar').read_text()
    model = re.sub(r'procedure Processor\n.*?end procedure', lambda _: fixture, source, flags=re.S)
    model = model.replace('replacement_policy = LRU', f'replacement_policy = {policy}')
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, 'main.sitar').write_text(model)
        for command in [['sitar', 'translate', 'main.sitar'], ['sitar', 'compile'], ['./sitar_sim', '10000']]:
            result = subprocess.run(command, cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert result.returncode == 0 and 'FAILURE' not in result.stdout, result.stdout
        assert f'PASS {policy}' in result.stdout, result.stdout
        print(f'PASS {policy}: replacement order and dirty eviction')

# Four ways in one set: repeated peer invalidations and refills must leave C oldest.
ops = [(0, addr, 0) for addr in (0, 16, 32, 48)]
ops += [(1, 0, 1), (0, 0, 0)] + [(1, 16, 1), (0, 16, 0)] * 6 + [(0, 64, 0)]
steps = []
for core_id, addr, write in ops:
    cache = ('core1' if core_id else 'core') + '.data_cache'
    steps.append(f'${cache}.address={addr}; {cache}.write={write}; {cache}.request_id++;$;')
    steps.append(f'wait until (${cache}.response_id == {cache}.request_id$);')
steps.append('$assert(core.data_cache.find_way(32) < 0);'
             ' for (auto addr : {0, 16, 48, 64}) assert(core.data_cache.find_way(addr) >= 0);$;')
four_way = shared_source.replace('NUM_SETS = 2', 'NUM_SETS = 1').replace('NUM_WAYS = 2', 'NUM_WAYS = 4')
model = four_way.replace('run processor;', 'wait until (0);').replace(
    'wait until ($core.processor.done && core1.processor.done$);', '\n'.join(steps))
with tempfile.TemporaryDirectory() as directory:
    Path(directory, 'main.sitar').write_text(model)
    for command in [['sitar', 'translate', 'main.sitar'], ['sitar', 'compile']]:
        result = subprocess.run(command, cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert result.returncode == 0 and 'FAILURE' not in result.stdout, result.stdout
    for policy in ('lru', 'fifo'):
        result = subprocess.run(['./sitar_sim', '10000'], cwd=directory, text=True, capture_output=True,
                                env={**os.environ, 'SITAR_POLICY': policy})
        assert result.returncode == 0 and 'PASS two_cores=2' in result.stdout, result.stdout + result.stderr
        print(f'PASS {policy}: four-way invalidation and refill order')

# Run both processors against the same repeatable address streams for every policy.
for delay, ways, block in [(0, 2, 16), (3, 2, 16), (0, 4, 16), (0, 2, 256)]:
    with tempfile.TemporaryDirectory() as directory:
        model = shared_source.replace('.MEM_DELAY = 0', f'.MEM_DELAY = {delay}')
        model = model.replace('NUM_WAYS = 2', f'NUM_WAYS = {ways}').replace('BLOCK_SIZE = 16', f'BLOCK_SIZE = {block}')
        Path(directory, 'main.sitar').write_text(model)
        for command in [['sitar', 'translate', 'main.sitar'], ['sitar', 'compile']]:
            result = subprocess.run(command, cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert result.returncode == 0 and 'FAILURE' not in result.stdout, result.stdout
        for policy, workload in [('lru', 'fixed'), ('lru', 'locality'), ('fifo', 'locality'), ('random', 'locality')]:
            for write_policy in ('write-back', 'write-through'):
                result = subprocess.run(['./sitar_sim', '100000'], cwd=directory, text=True,
                                        capture_output=True, env={**os.environ, 'SITAR_POLICY': policy, 'SITAR_WRITE_POLICY': write_policy, 'SITAR_WORKLOAD': workload, 'SITAR_SEED': '42'})
                assert result.returncode == 0 and 'PASS two_cores=2' in result.stdout, result.stdout + result.stderr
                if workload == 'fixed':
                    if ways == 2 and block == 16:
                        row = next(r for r in result.stdout.splitlines() if r.startswith('DATA CACHE core=0 '))
                        assert f' writebacks={int(write_policy == "write-back")} ' in row, row
                    assert all(f'PASS shared core={i}' in result.stdout for i in (0, 1)), result.stdout
                else:
                    counts = re.findall(r'DATA CACHE core=[01] hits=(\d+) misses=(\d+)', result.stdout)
                    assert len(counts) == 2 and all(int(h) + int(m) == 256 for h, m in counts), counts
                if write_policy == 'write-through':
                    for core in (0, 1):
                        stores = len(re.findall(rf'ACCESS core={core} .*? write=1 error=0', result.stdout))
                        row = next(r for r in result.stdout.splitlines() if r.startswith(f'DATA CACHE core={core} '))
                        assert ' writebacks=0 ' in row and row.endswith(f' memory_write_bytes={4 * stores}'), row
                print(f'PASS two cores: write={write_policy} policy={policy} delay={delay} ways={ways} block={block} workload={workload}')

        if (delay, ways, block) == (0, 2, 16):
            for workload, probability, writes in [('fixed', '0', 1), ('uniform', '0', 0), ('locality', '1', 512)]:
                result = subprocess.run(['./sitar_sim', '100000'], cwd=directory, capture_output=True, text=True,
                                        env={**os.environ, 'SITAR_WORKLOAD': workload, 'SITAR_P_STORE': probability})
                assert result.returncode == 0 and 'PASS two_cores=2' in result.stdout, result.stderr
                assert result.stdout.count(' write=1 error=0') == writes, (workload, probability)
