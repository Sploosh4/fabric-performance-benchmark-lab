"""A receipted, closed-client option update for the dedicated diagnostic profile."""
from datetime import datetime
import json
import uuid
from world_restore import plain
from experiment_protocol import file_hash


def prepare(settings):
    from manage_experiment import closed
    closed()
    target=settings.profile/'options.txt';plain(target)
    before=target.read_bytes() if target.exists() else None
    lines=(before or b'').decode('utf-8-sig').splitlines()
    matching=[i for i,line in enumerate(lines) if line.startswith('pauseOnLostFocus:')]
    if len(matching)>1:raise ValueError('Duplicate pause-on-lost-focus option; inspect it before changing')
    if matching and lines[matching[0]]=='pauseOnLostFocus:false':return {'status':'already_disabled'}
    recovery=settings.state/'diagnostic-options'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    plain(recovery);recovery.mkdir(parents=True,exist_ok=False)
    if before is not None:(recovery/'options.before.txt').write_bytes(before)
    if matching:lines[matching[0]]='pauseOnLostFocus:false'
    else:lines.append('pauseOnLostFocus:false')
    closed()
    if (target.read_bytes() if target.exists() else None)!=before:raise ValueError('Options changed while planning')
    target.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    receipt={'status':'pause_on_lost_focus_disabled','profile':str(settings.profile),'option':'pauseOnLostFocus',
             'after_sha256':file_hash(target),'previous_existed':before is not None}
    (recovery/'receipt.json').write_text(json.dumps(receipt,indent=2))
    return receipt
