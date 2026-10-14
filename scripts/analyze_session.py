"""Verify and segment no-inventory sessions; never accept a mod benchmark."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
from capture_headless import check_csv
from session_protocol import OWNER, ROUTE_BATCH, batch_protocol, schedule
from validate_capture import percentile
from frame_csv import csv_encoding
from room_route_protocol import WORKLOAD as ROOM_WORKLOAD
from rooms_analysis import scene_evidence


def segmented_intervals(rows, start, end, frequency):
    """Keep an interval only when BOTH endpoints belong to the action window."""
    if frequency <= 0 or end <= start:
        raise ValueError('Invalid QPC window')
    intervals = []
    previous = None
    for row in rows:
        current = int(row['QPCTime'])
        if previous is not None:
            if current <= previous:
                raise ValueError('Frame timestamps are not increasing')
            value = float(row['msBetweenPresents'])
            delta = (current-previous)*1000/frequency
            if not math.isfinite(value) or value <= 0 or abs(value-delta)>max(0.05,delta*0.005):
                raise ValueError('Frame interval disagrees with QPC timestamps')
            if previous >= start and current <= end:
                intervals.append(value)
        previous = current
    if not intervals:
        raise ValueError('No complete frame intervals inside window')
    return intervals


def frame_metrics(intervals):
    if not intervals or any(not math.isfinite(v) or v <= 0 for v in intervals):
        raise ValueError('Invalid frame intervals')
    tail_count=max(1,math.ceil(len(intervals)*0.01))
    slowest=sorted(intervals,reverse=True)[:tail_count]
    spikes=[v for v in intervals if v>50]
    seconds=sum(intervals)/1000
    return {'interval_count':len(intervals),'analyzed_seconds':sum(intervals)/1000,
            'average_presented_fps':1000/statistics.mean(intervals),
            'one_percent_low_presented_fps':1000/statistics.mean(slowest),
            'one_percent_low_tail_interval_count':tail_count,
            'one_percent_low_definition':'1000 / mean of slowest ceil(N*0.01) complete intervals in milliseconds',
            'p50_ms':percentile(intervals,0.5),'p95_ms':percentile(intervals,0.95),
            'p99_ms':percentile(intervals,0.99),'stutters_over_50ms':len(spikes),
            'stutters_over_50ms_per_minute':len(spikes)*60/seconds,
            'worst_frame_ms':max(intervals),'worst_stutter_over_50ms_ms':max(spikes) if spikes else None,
            'total_stutter_over_50ms_time_ms':sum(spikes)}


def resource_summary(resources, phase, start, end):
    # CPU/GPU are interval rates. Exclude samples whose earlier endpoint is
    # outside the frame/action window, including the initial priming sample.
    selected=[]
    for previous,current in zip(resources,resources[1:]):
        if previous['qpc'] >= start and current['qpc'] <= end and current['context'].get('phase')==phase:
            selected.append(current)
    if not selected:
        return {'status':'missing','samples':0}
    result={'status':'sampled','samples':len(selected),'interval_endpoint_policy':'Both resource endpoints inside analyzed window'}
    for key in ('working_set_bytes','private_committed_bytes','cpu_machine_pct',
                'cpu_one_core_equivalent_pct','gpu_busiest_engine_pct','gpu_shared_bytes','gpu_dedicated_bytes'):
        values=[r[key] for r in selected if r.get(key) is not None and math.isfinite(r[key])]
        result[key]={'valid_samples':len(values),'minimum':min(values) if values else None,
                     'median':statistics.median(values) if values else None,'maximum':max(values) if values else None}
    return result


def analyze(suite):
    suite=Path(suite).resolve(strict=True)
    result=json.loads((suite/'session-result.json').read_text())
    arm=json.loads((suite/'session-arm.json').read_text())
    done=json.loads((suite/'game-done.json').read_text())
    diagnostic=arm.get('diagnostic_only',False)
    if type(diagnostic) is not bool or result.get('diagnostic_only',False)!=diagnostic:
        raise ValueError('Diagnostic analysis policy differs between session and arm')
    if arm.get('owner')!=OWNER or arm.get('movement_workload') not in ('mob_display_loop_v2',ROOM_WORKLOAD):
        raise ValueError('Requires the current no-inventory workload')
    protocol=batch_protocol(arm)
    expected=schedule(arm['repeats'],protocol)
    if result['status']!='session_validation_passed' or done['status']!='session_validation_passed' or done.get('cleanup_error'):
        raise ValueError('Session or cleanup failed')
    if done['completed_phases']!=len(expected) or len(result['phases'])!=len(expected):
        raise ValueError('Phase count differs')
    if any(v.get('benchmark_accepted') is not False for v in (arm,result,done)):
        raise ValueError('Unexpected benchmark acceptance')
    if arm.get('initial_issues') or done['nonce']!=arm['nonce'] or done['game_pid']!=arm['game_pid']:
        raise ValueError('Session identity/initial conditions differ')
    pid=arm['game_pid']
    game=[json.loads(line) for line in (suite/'game-samples.jsonl').read_text().splitlines()]
    if any(r['nonce']!=arm['nonce'] or r.get('benchmark_accepted') is not False for r in game):
        raise ValueError('Game event identity differs')
    frequencies={r['qpc_frequency'] for r in game}
    if len(frequencies)!=1:
        raise ValueError('Mixed QPC frequencies')
    frequency=frequencies.pop()
    if any(b['qpc']<=a['qpc'] for a,b in zip(game,game[1:])):
        raise ValueError('Game event timestamps are not increasing')
    if any(r['event'].startswith('inventory_') or r.get('action')=='inventory' for r in game):
        raise ValueError('Inventory unexpectedly opened in no-inventory workload')
    resource_file=suite/'resource-samples.jsonl'
    resources=[json.loads(line) for line in resource_file.read_text().splitlines()] if resource_file.exists() else []
    if any(r.get('game_pid',pid)!=pid or r['qpc_frequency']!=frequency for r in resources):
        raise ValueError('Resource process/clock differs')
    if any(b['qpc']<=a['qpc'] for a,b in zip(resources,resources[1:])):
        raise ValueError('Resource timestamps are not increasing')
    starts=[i for i,r in enumerate(game) if r['event']=='action_start']
    if len(starts)!=len(expected):
        raise ValueError('Missing or duplicate action start markers')
    phases=[]
    for index,(phase,scenario) in enumerate(zip(result['phases'],expected)):
        if phase['phase']!=index or phase['scenario']!=scenario or phase['nonce']!=arm['nonce'] or phase['game_pid']!=pid:
            raise ValueError('Phase order/identity differs')
        # Do not allow returned directory metadata to escape the local run root.
        root=(suite/'runs').resolve()
        folder=(root/phase['run_directory']).resolve(strict=True)
        if not folder.is_relative_to(root):
            raise ValueError('Run directory escapes suite')
        capture=json.loads((folder/'result.json').read_text())
        raw=folder/'frames.csv'
        digest=hashlib.sha256(raw.read_bytes()).hexdigest()
        if capture['status']!='tool_check_passed' or digest!=capture['csv_sha256'] or capture['game']['pid']!=pid:
            raise ValueError('Capture status/process/hash differs')
        check_csv(raw,pid,seconds=capture['duration_seconds'])
        if protocol==ROUTE_BATCH:
            from capture_headless import verify_route_capture
            from session_protocol import validate_phase
            if capture.get('capture_policy')!='verified-route-completion-plus-two-second-drain-v1' or capture.get('owned_session_stop_exit_code')!=0 or capture.get('cli_exit_code')!=0 or not 0<capture['duration_seconds']<180:
                raise ValueError('Route capture did not complete and drain cleanly')
            action=capture['route_completion']
            validate_phase(action,arm,index,scenario)
            if action.get('status')!='action_verified' or action.get('qpc_frequency')!=frequency:
                raise ValueError('Route completion identity/clock differs')
            verify_route_capture(raw,action)
        telemetry_path=folder/'focus-process.jsonl'
        if not telemetry_path.exists():telemetry_path=folder/'power-focus.jsonl' # Historical evidence only.
        focus=[json.loads(line) for line in telemetry_path.read_text().splitlines()]
        diagnostic=arm.get('diagnostic_only',False)
        if not focus or not all(r['original_game_alive'] and (diagnostic or r['minecraft_foreground']) for r in focus):
            raise ValueError('Capture focus/lifetime check failed')
        with raw.open(newline='',encoding=csv_encoding(raw)) as stream:
            frames=list(csv.DictReader(stream))
        start,end=int(frames[0]['QPCTime']),int(frames[-1]['QPCTime'])
        raw_start,raw_end=start,end
        scope='Full stationary recording, following controller warmup'
        room_sections=None
        if scenario=='movement' and arm['movement_workload']==ROOM_WORKLOAD:
            events=game[starts[index]:starts[index+1] if index+1<len(starts) else len(game)]
            from rooms_analysis import scored_action_events
            events=scored_action_events(events)
            room_sections=scene_evidence(events,frequency)
            if protocol==ROUTE_BATCH:
                complete=[e for e in events if e['event']=='player_actions_complete']
                if not complete[0]['qpc']<=action['completed_qpc'] or (action['completed_qpc']-complete[0]['qpc'])/frequency>2:
                    raise ValueError('Action completion does not follow the full route')
            start,end=room_sections[0]['start_qpc'],room_sections[-1]['end_qpc']
            if not raw_start<=start<end<=raw_end:raise ValueError('Recording does not contain all three rooms')
            scope='Short mob sprint/walk with two sprint-jumps, paintings and redstone displays; transitions excluded'
        elif scenario=='movement':
            events=game[starts[index]:starts[index+1] if index+1<len(starts) else len(game)]
            markers=[r for r in events if r['event']=='player_actions_complete']
            segments=[r for r in events if r['event']=='mob_route_segment_start']
            if len(markers)!=1 or markers[0].get('workload')!='mob_display_loop_v2' or len(segments)!=7:
                raise ValueError('Action-window markers differ')
            actions=[r for r in events if r['event']=='player_action_verified']
            if Counter(r['action'] for r in actions)!={'walk':5,'sprint':2,'jump':3,'punch':5}:
                raise ValueError('Player action counts differ')
            if any(not r['sprinting_observed'] for r in actions if r['action']=='sprint'):
                raise ValueError('Sprint state did not verify')
            waypoints=[r for r in events if r['event']=='mob_area_waypoint']
            if len(waypoints)!=6 or any(r['nearby_display_entities']<10 for r in waypoints):
                raise ValueError('Mob display population did not verify')
            start,end=segments[0]['qpc'],markers[0]['qpc']
            if not raw_start<=start<end<=raw_end:
                raise ValueError('Recording does not contain complete actions')
            scope='Mob route, camera looks, jumps and air punches; startup/idle tail excluded'
        intervals=([v for scene in room_sections for v in segmented_intervals(frames,scene['start_qpc'],scene['end_qpc'],frequency)]
                   if room_sections else segmented_intervals(frames,start,end,frequency))
        enabled=phase.get('resources_enabled',True)
        if not enabled and any(start<=r['qpc']<=end and r['context'].get('phase')==index for r in resources):
            raise ValueError('Resources sampled during an OFF control')
        phases.append({'phase':index,'scenario':scenario,'scope':scope,'csv_sha256':digest,
            'resources_enabled':enabled,
            'window_start_qpc':start,'window_end_qpc':end,'window_seconds':(end-start)/frequency,
            'excluded_leading_seconds':(start-raw_start)/frequency,'excluded_trailing_seconds':(raw_end-end)/frequency,
            'frame_metrics':frame_metrics(intervals),'resources':resource_summary(resources,index,start,end) if enabled else {'status':'disabled_for_control','samples':0}})
        if room_sections:
            phases[-1]['scene_windows']=room_sections
            phases[-1]['excluded_internal_transition_seconds']=((end-start)-sum(s['end_qpc']-s['start_qpc'] for s in room_sections))/frequency
            phases[-1]['resource_scope']='Descriptive full scene span, including transitions; frame metrics exclude transitions'
    analysis={'schema':'modpack-action-window-analysis-v1','status':'action_windows_verified',
            'benchmark_accepted':False,'suite':str(suite),'game_pid':pid,'nonce':arm['nonce'],
            'diagnostic_only':diagnostic,'purpose':'diagnostic_integration' if diagnostic else result.get('purpose','validation'),
            'movement_workload':arm['movement_workload'],'qpc_frequency':frequency,'phases':phases,
            'notes':['Presented-frame metrics; not displayed FPS or input latency',
                     'Resource rates are descriptive samples, not per-frame values',
                     'Reset occurs after capture; idle tail is explicitly excluded',
                     'Capture/resource overhead and matched mod comparisons remain pending']}
    if diagnostic:
        analysis['notes'].insert(0,'Diagnostic integration only: frame values must not be used for performance comparisons')
    if result.get('purpose')=='resource_sampling_overhead':
        order=result.get('resource_sampling_order')
        if order!=[True,False,False,True] or len(phases)!=8 or any(p['resources_enabled']!=order[p['phase']//2] for p in phases):
            raise ValueError('Overhead ON/OFF/OFF/ON order differs')
        for phase in phases:
            if phase['resources_enabled'] and any(phase['resources'].get(metric,{}).get('valid_samples',0)<2
                                                  for metric in ('working_set_bytes','cpu_machine_pct')):
                raise ValueError('Insufficient valid resource samples during an ON condition')
        contrasts=[]
        for scenario in ('stationary','movement'):
            selected=[p for p in phases if p['scenario']==scenario]
            for pair in ((selected[0],selected[1]),(selected[3],selected[2])):
                on,off=pair
                a,b=on['frame_metrics'],off['frame_metrics']
                contrasts.append({'scenario':scenario,'on_phase':on['phase'],'off_phase':off['phase'],
                    'presented_fps_change_on_vs_off_pct':100*(a['average_presented_fps']/b['average_presented_fps']-1),
                    'p95_frame_time_change_on_vs_off_pct':100*(a['p95_ms']/b['p95_ms']-1),
                    'p99_frame_time_change_on_vs_off_pct':100*(a['p99_ms']/b['p99_ms']-1)})
        analysis['resource_overhead_pilot']={'order':order,'paired_contrasts':contrasts,
            'scope':'Incremental Windows resource sampling/logging; query initialization, Java snapshots and PresentMon stay common',
            'conclusion':'Exploratory two-pair comparison per scene; no significance or negligible-overhead claim'}
    return analysis


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite',type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    target=args.report or args.suite/'action-window-analysis.json'
    result=analyze(args.suite)
    with target.open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(result,indent=2)+'\n')
    print(str(target))


if __name__=='__main__':
    main()
