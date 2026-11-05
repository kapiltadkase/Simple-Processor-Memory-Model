"""Compare equal-capacity caches and check independent processing delays."""
from pathlib import Path
import re
import subprocess
import tempfile

source = Path(__file__).with_name('main.sitar').read_text()
for sets, ways, block, cache_delay, memory_delay in [
    (4, 1, 16, 0, 0), (2, 2, 16, 0, 0), (1, 4, 16, 0, 0),
    (2, 2, 16, 2, 0), (2, 2, 16, 0, 3), (2, 2, 16, 2, 3),
    (2, 2, 4, 0, 0), (1, 1, 256, 0, 0),
]:
    model = source
    for name, value in [('NUM_SETS', sets), ('NUM_WAYS', ways), ('BLOCK_SIZE', block)]:
        model = re.sub(rf'parameter int {name} = \d+', f'parameter int {name} = {value}', model)
    model = model.replace('.CACHE_DELAY = 0', f'.CACHE_DELAY = {cache_delay}')
    model = model.replace('.MEM_DELAY = 0', f'.MEM_DELAY = {memory_delay}')
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, 'main.sitar').write_text(model)
        for command in [['sitar', 'translate', 'main.sitar'], ['sitar', 'compile'], ['./sitar_sim', '10000']]:
            result = subprocess.run(command, cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert result.returncode == 0 and 'FAILURE' not in result.stdout, result.stdout
        assert 'PASS requests_per_cache=20' in result.stdout, result.stdout
        summary = next(line.split('PASS ')[1] for line in result.stdout.splitlines() if 'PASS ' in line)
        print(f'sets={sets} ways={ways} block={block} cache_delay={cache_delay} memory_delay={memory_delay}: {summary}')
