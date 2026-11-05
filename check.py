"""Compare equal-capacity caches and check independent processing delays."""
from pathlib import Path
import re
import subprocess
import tempfile

source = Path(__file__).with_name('main.sitar').read_text()
for sets, ways, block, cache_delay, memory_delay, mode in [
    (4, 1, 16, 0, 0, "mixed"), (2, 2, 16, 0, 0, "mixed"), (1, 4, 16, 0, 0, "mixed"),
    (2, 2, 16, 2, 0, "mixed"), (2, 2, 16, 0, 3, "mixed"), (2, 2, 16, 2, 3, "mixed"),
    (2, 2, 4, 0, 0, "mixed"), (1, 1, 256, 0, 0, "mixed"),
    (2, 2, 16, 0, 0, "reads"), (2, 2, 16, 0, 0, "local"),
    (2, 2, 16, 0, 0, "stream"),
]:
    model = source
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
        assert 'PASS requests_per_cache=20' in result.stdout, result.stdout
        summary = next(line.split('PASS ')[1] for line in result.stdout.splitlines() if 'PASS ' in line)
        count = int(re.search(r' writebacks=(\d+)', summary)[1])
        assert 'instruction_writebacks=0' in summary
        if mode in ("reads", "local"):
            assert count == 0, summary
        if mode == "stream":
            assert count > 0, summary
        print(f'mode={mode} sets={sets} ways={ways} block={block} cache_delay={cache_delay} memory_delay={memory_delay}: {summary}')
