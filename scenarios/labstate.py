"""Finite readiness probe: Minecraft graphics setup/state logging, no desktop control."""
import json
from pathlib import Path
import time
import uuid

destination = Path(__file__).resolve().parent / 'lab-results'
destination.mkdir(parents=True, exist_ok=True)
report_path = destination / ('readiness-' + uuid.uuid4().hex + '.jsonl')
started = time.monotonic()

with report_path.open('x', encoding='utf-8') as output:
    try:
        import minescript as ms
        from lab_common import apply_graphics_conditions, sample_state, condition_issues
        apply_graphics_conditions()
        for sample in range(30):
            tick = time.monotonic()
            record = sample_state()
            record.update(sample=sample, elapsed_seconds=time.monotonic() - started)
            record['condition_issues'] = condition_issues(record)
            output.write(json.dumps(record) + '\n')
            output.flush()
            time.sleep(max(0, 1 - (time.monotonic() - tick)))
    except Exception as error:
        output.write(json.dumps({'status': 'readiness rejected', 'error': str(error),
                                 'benchmark_accepted': False}) + '\n')
        output.flush()
        raise
ms.echo('Lab readiness probe complete; no benchmark accepted.')
