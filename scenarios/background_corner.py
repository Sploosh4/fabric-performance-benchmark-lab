"""Physical diagnostic correction: release movement before slow background observations."""
import time
import minescript as ms


def settle(target,probe,write,segment):
    position,ground,sprint=probe.sample()
    write({'event':'corner_correction_start','segment':segment,'position':position,
           'control_policy':'diagnostic-released-input-pulses-v1'})
    try:
        ms.player_press_sprint(False)
        ms.player_press_jump(False)
        ms.player_press_sneak(True)
        for axis in (0,2):
            deadline=time.monotonic()+20
            for pulse in range(12):
                # The probe checks cancellation/menu/pause. Never leave forward held
                # while a minimized render bridge is assembling its observations.
                ms.player_press_forward(False)
                position,ground,sprint=probe.sample()
                if not ground or abs(position[1]-target[1])>.2:
                    raise RuntimeError('Background corner correction is not grounded')
                delta=target[axis]-position[axis]
                if abs(delta)<=.16:break
                if abs(delta)>2 or time.monotonic()>deadline:
                    raise RuntimeError('Background corner correction exceeded its bound')
                yaw=(-90 if delta>0 else 90) if axis==0 else (0 if delta>0 else 180)
                ms.player_set_orientation(yaw,6.5)
                try:
                    ms.player_press_forward(True)
                    # At least one simulation tick; scale longer corrections rather
                    # than exhausting tiny pulses after the normal early braking.
                    time.sleep(min(.35,max(.08,abs(delta)/1.3*.6)))
                finally:ms.player_press_forward(False)
                time.sleep(.2)
            else:raise RuntimeError('Background corner correction exhausted its pulses')
    finally:
        ms.player_press_forward(False)
        ms.player_press_sneak(False)
    final,ground,sprint=probe.sample()
    if not ground or max(abs(final[axis]-target[axis]) for axis in (0,1,2))>.2:
        raise RuntimeError('Background corner did not settle')
    write({'event':'corner_correction_end','segment':segment,'position':final,
           'control_policy':'diagnostic-released-input-pulses-v1'})
