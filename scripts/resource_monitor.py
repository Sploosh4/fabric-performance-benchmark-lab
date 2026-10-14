"""Read-only, PID-scoped Windows resource samples. Never controls the game."""
import ctypes as C
from ctypes import wintypes as W
import json
import math
import os
import re
import time
from pair_protocol import QpcClock


class Memory(C.Structure):
    _fields_ = [('cb', W.DWORD), ('PageFaultCount', W.DWORD)] + [
        (name, C.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
        'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
        'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]


class ValueUnion(C.Union):
    _fields_ = [('doubleValue', C.c_double), ('largeValue', C.c_longlong)]


class CounterValue(C.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('status', W.DWORD), ('value', ValueUnion)]


class CounterItem(C.Structure):
    _fields_ = [('name', W.LPWSTR), ('value', CounterValue)]


def cpu_rates(previous, current, processors):
    """Return whole-machine and one-core-equivalent percentages; prime with null."""
    if previous is None:
        return None, None
    elapsed, used = current[0] - previous[0], current[1] - previous[1]
    if elapsed <= 0 or used < 0 or processors < 1:
        raise ValueError('Invalid CPU sample interval')
    equivalent = 100 * used / elapsed
    return equivalent / processors, equivalent


def scoped_values(rows, pid):
    """Missing counters stay missing; never include another process or invalid data."""
    selected = {}
    for name, status, value in rows:
        match = re.match(r'^pid_(\d+)_', name)
        if match and int(match[1]) == pid and status in (0, 1) and math.isfinite(value) and value >= 0:
            selected[name] = value
    return selected


class GpuCounters:
    def __init__(self, pid):
        self.pid, self.query, self.counters, self.errors = pid, W.HANDLE(), {}, {}
        self.samples = 0
        self.pdh = C.WinDLL('pdh', use_last_error=True)
        signatures = {
            'PdhOpenQueryW': ([W.LPCWSTR, C.c_size_t, C.POINTER(W.HANDLE)], W.LONG),
            'PdhAddEnglishCounterW': ([W.HANDLE, W.LPCWSTR, C.c_size_t, C.POINTER(W.HANDLE)], W.LONG),
            'PdhCollectQueryData': ([W.HANDLE], W.LONG),
            'PdhGetFormattedCounterArrayW': ([W.HANDLE, W.DWORD, C.POINTER(W.DWORD), C.POINTER(W.DWORD), C.c_void_p], W.LONG),
            'PdhCloseQuery': ([W.HANDLE], W.LONG),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.pdh, name); fn.argtypes, fn.restype = args, result
        status = self.pdh.PdhOpenQueryW(None, 0, C.byref(self.query))
        if status:
            raise OSError('PDH query unavailable: ' + hex(status & 0xffffffff))
        try:
            for key, path, fmt in (
                ('engines', r'\GPU Engine(*)\Utilization Percentage', 0x200 | 0x8000),
                ('shared', r'\GPU Process Memory(*)\Shared Usage', 0x400),
                ('dedicated', r'\GPU Process Memory(*)\Dedicated Usage', 0x400)):
                handle = W.HANDLE()
                status = self.pdh.PdhAddEnglishCounterW(self.query, path, 0, C.byref(handle))
                if status:
                    self.errors[key] = hex(status & 0xffffffff)
                else:
                    self.counters[key] = (handle, fmt)
            self.pdh.PdhCollectQueryData(self.query)  # Prime rate counters.
        except Exception:
            self.close()
            raise

    def array(self, handle, fmt):
        # Instances may appear/disappear; retry a changed buffer size finitely.
        for _ in range(3):
            size, count = W.DWORD(), W.DWORD()
            status = self.pdh.PdhGetFormattedCounterArrayW(handle, fmt, C.byref(size), C.byref(count), None)
            if status == 0 and count.value == 0:
                return []
            if status & 0xffffffff != 0x800007d2 or not 0 < size.value <= 16 * 1024**2:
                raise OSError('PDH array unavailable: ' + hex(status & 0xffffffff))
            buffer = C.create_string_buffer(size.value)
            status = self.pdh.PdhGetFormattedCounterArrayW(handle, fmt, C.byref(size), C.byref(count), buffer)
            if status & 0xffffffff == 0x800007d2:
                continue
            if status:
                raise OSError('PDH array read failed: ' + hex(status & 0xffffffff))
            if count.value * C.sizeof(CounterItem) > len(buffer):
                raise OSError('PDH array exceeds buffer')
            items = C.cast(buffer, C.POINTER(CounterItem))
            return [(items[i].name, items[i].value.status,
                     items[i].value.largeValue if fmt == 0x400 else items[i].value.doubleValue)
                    for i in range(count.value)]
        raise OSError('GPU counter instances kept changing')

    def sample(self):
        status = self.pdh.PdhCollectQueryData(self.query)
        self.samples += 1
        values, issues = {}, dict(self.errors)
        if status:
            return {'gpu_engines_pct': None, 'gpu_busiest_engine_pct': None,
                    'gpu_shared_bytes': None, 'gpu_dedicated_bytes': None,
                    'gpu_issues': {'collect': hex(status & 0xffffffff)}}
        for key, (handle, fmt) in self.counters.items():
            if key == 'engines' and self.samples == 1:
                issues[key] = 'Rate counter priming; first reading excluded'
                continue
            try:
                values[key] = scoped_values(self.array(handle, fmt), self.pid)
                if not values[key]:
                    issues[key] = 'No valid matching process counter; not assumed zero'
            except Exception as error:
                issues[key] = str(error)
        engines = values.get('engines', {})
        return {'gpu_engines_pct': engines or None,
                'gpu_busiest_engine_pct': max(engines.values()) if engines else None,
                'gpu_shared_bytes': sum(values['shared'].values()) if values.get('shared') else None,
                'gpu_dedicated_bytes': sum(values['dedicated'].values()) if values.get('dedicated') else None,
                'gpu_issues': issues}

    def close(self):
        if self.query:
            self.pdh.PdhCloseQuery(self.query)
            self.query = W.HANDLE()


class WindowsResources:
    def __init__(self, pid):
        self.pid, self.previous, self.processors = pid, None, os.cpu_count() or 1
        self.k = C.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('OpenProcess', [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            ('CloseHandle', [W.HANDLE], W.BOOL),
            ('WaitForSingleObject', [W.HANDLE, W.DWORD], W.DWORD),
            ('GetProcessTimes', [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL),
            ('K32GetProcessMemoryInfo', [W.HANDLE, C.POINTER(Memory), W.DWORD], W.BOOL)):
            fn = getattr(self.k, name); fn.argtypes, fn.restype = args, result
        self.handle = self.k.OpenProcess(0x100000 | 0x1000 | 0x10, False, pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        self.gpu, self.gpu_error = None, None
        try:
            self.gpu = GpuCounters(pid)
        except Exception as error:
            self.gpu_error = str(error)

    def prime(self):
        # After an off interval, do not average CPU/GPU rates over that gap.
        self.previous = None
        if self.gpu is not None:
            self.gpu.samples = 0

    def sample(self):
        if self.k.WaitForSingleObject(self.handle, 0) != 258:
            raise RuntimeError('Original resource-monitor game process exited')
        creation, exit_time, kernel, user = (W.FILETIME() for _ in range(4))
        if not self.k.GetProcessTimes(self.handle, C.byref(creation), C.byref(exit_time), C.byref(kernel), C.byref(user)):
            raise C.WinError(C.get_last_error())
        cpu = sum((x.dwHighDateTime << 32) | x.dwLowDateTime for x in (kernel, user)) / 10**7
        current = (time.perf_counter(), cpu)
        total, equivalent = cpu_rates(self.previous, current, self.processors)
        self.previous = current
        memory = Memory(); memory.cb = C.sizeof(memory)
        if not self.k.K32GetProcessMemoryInfo(self.handle, C.byref(memory), memory.cb):
            raise C.WinError(C.get_last_error())
        record = {'game_pid': self.pid, 'logical_processors': self.processors,
                  'cpu_machine_pct': total, 'cpu_one_core_equivalent_pct': equivalent,
                  'cpu_total_seconds': cpu, 'working_set_bytes': memory.WorkingSetSize,
                  'private_committed_bytes': memory.PrivateUsage,
                  'process_lifetime_peak_working_set_bytes': memory.PeakWorkingSetSize}
        if self.gpu is not None:
            record.update(self.gpu.sample())
        else:
            record.update(gpu_engines_pct=None, gpu_busiest_engine_pct=None,
                          gpu_shared_bytes=None, gpu_dedicated_bytes=None,
                          gpu_issues={'initialization': self.gpu_error})
        return record

    def close(self):
        if self.gpu is not None:
            self.gpu.close()
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


class ResourceRecorder:
    """At most one sample per second, driven by existing controller health checks."""
    def __init__(self, pid, path):
        self.clock, self.next_due = QpcClock(), 0
        self.samples, self.failures, self.gpu_valid, self.costs = 0, 0, 0, []
        self.source = WindowsResources(pid)
        try:
            self.output = path.open('x', encoding='utf-8')
        except Exception:
            self.source.close()
            raise

    def prime(self):
        self.next_due = 0
        self.source.prime()

    def tick(self, context):
        now = time.monotonic()
        if now < self.next_due:
            return
        self.next_due = now + 1
        began = time.perf_counter()
        qpc = self.clock()
        try:
            data = self.source.sample()
            self.gpu_valid += data.get('gpu_busiest_engine_pct') is not None
        except Exception as error:
            data = {'resource_error': str(error)}
            self.failures += 1
        cost = (time.perf_counter() - began) * 1000
        self.costs.append(cost); self.samples += 1
        self.output.write(json.dumps({'schema': 'modpack-resources-v1', 'benchmark_accepted': False,
            'qpc': qpc, 'qpc_frequency': self.clock.frequency, 'sample_cost_ms': cost,
            'context': dict(context), **data}) + '\n')
        self.output.flush()

    def close(self):
        self.source.close()
        self.output.close()
        return {'status': 'collected' if self.samples and not self.failures else 'partial_or_missing',
                'samples': self.samples, 'failed_samples': self.failures,
                'valid_gpu_samples': self.gpu_valid,
                'gpu_status': 'measured' if self.gpu_valid else 'unavailable_or_unverified',
                'maximum_sample_cost_ms': max(self.costs, default=None),
                'sample_interval_seconds': 1, 'sampling_overhead': 'untested',
                'missing': ['Continuous JVM heap and GC events', 'CPU per-thread load', 'GPU temperature/power/clocks']}
