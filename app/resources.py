"""Read this container's cgroup v2 and filesystem counters; no Docker socket access."""
import asyncio
import contextlib
import json
import os
import shutil
import threading
import time
from pathlib import Path

import httpx
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, REGISTRY
from .db import DATA_DIR
from .domain import BusinessError
from .observability import emit, now, uid

CGROUP = Path('/sys/fs/cgroup')
CAPACITY_DIR = Path('/capacity-test')
PROMETHEUS_URL = os.getenv('PROMETHEUS_URL', '').rstrip('/')
DRILLS_ENABLED = os.getenv('RESOURCE_DRILLS_ENABLED', '') == 'true'
_cpu_previous = None
_sample_lock = threading.Lock()
_capacity_lock = threading.Lock()
_capacity_timer = None
_capacity_expires = None
_capacity_generation = 0
_alerts = {'available': False, 'rules': [], 'error': '等待 Prometheus' if PROMETHEUS_URL else '未配置 Prometheus', 'updated_at': None}


def read_cgroup(root=CGROUP):
    result = {'available': False, 'cpu_limit_cores': None, 'cpu_seconds': None,
              'throttled_seconds': None, 'memory_bytes': None, 'memory_limit_bytes': None,
              'oom_kills': None, 'error': None}
    try:
        cpu = dict(line.split() for line in (root/'cpu.stat').read_text().splitlines())
        quota, period = (root/'cpu.max').read_text().split()
        memory_limit = (root/'memory.max').read_text().strip()
        events = dict(line.split() for line in (root/'memory.events').read_text().splitlines())
        result.update(available=True, cpu_seconds=int(cpu['usage_usec'])/1e6,
                      throttled_seconds=int(cpu.get('throttled_usec', 0))/1e6,
                      cpu_limit_cores=int(quota)/int(period) if quota != 'max' else None,
                      memory_bytes=int((root/'memory.current').read_text()),
                      memory_limit_bytes=int(memory_limit) if memory_limit != 'max' else None,
                      oom_kills=int(events.get('oom_kill', 0)))
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        result['error'] = '未读到完整 cgroup v2 指标；本机非容器模式或旧 cgroup 环境不提供容器用量。'
    return result


def filesystems():
    values = []
    for name, path in [('data', DATA_DIR), ('capacity', CAPACITY_DIR)]:
        if not path.exists():
            continue
        try:
            usage = shutil.disk_usage(path)
            values.append({'name': name, 'total_bytes': usage.total, 'used_bytes': usage.used,
                           'free_bytes': usage.free, 'used_ratio': usage.used/usage.total if usage.total else 0,
                           'description': '限额临时区（tmpfs，占用内存）' if name == 'capacity' else '数据所在文件系统（共享容量，非容器独占配额）'})
        except OSError:
            pass
    return values


def snapshot():
    global _cpu_previous
    value = read_cgroup()
    value['cpu_used_ratio'] = None
    with _sample_lock:
        timestamp = time.monotonic()
        if value['available'] and value['cpu_limit_cores']:
            if _cpu_previous:
                previous_time, previous_cpu = _cpu_previous
                if timestamp > previous_time and value['cpu_seconds'] >= previous_cpu:
                    value['cpu_used_ratio'] = (value['cpu_seconds']-previous_cpu)/(timestamp-previous_time)/value['cpu_limit_cores']
            _cpu_previous = (timestamp, value['cpu_seconds'])
    value['memory_used_ratio'] = value['memory_bytes']/value['memory_limit_bytes'] if value['memory_limit_bytes'] else None
    return {'sampled_at': now(), 'container': value, 'filesystems': filesystems(),
            'capacity_drill_enabled': DRILLS_ENABLED, 'capacity_expires_at': _capacity_expires,
            'alerts': _alerts,
            'scope': 'CPU/内存为当前应用容器总量，包含压测子进程；不含 MySQL 或宿主机。'}


class ContainerCollector:
    def collect(self):
        resource = read_cgroup()
        available = GaugeMetricFamily('finops_container_metrics_available', 'Cgroup v2 counters are readable')
        available.add_metric([], int(resource['available']))
        yield available
        for name, field, kind in [
            ('finops_container_cpu_seconds', 'cpu_seconds', CounterMetricFamily),
            ('finops_container_cpu_throttled_seconds', 'throttled_seconds', CounterMetricFamily),
            ('finops_container_cpu_limit_cores', 'cpu_limit_cores', GaugeMetricFamily),
            ('finops_container_memory_bytes', 'memory_bytes', GaugeMetricFamily),
            ('finops_container_memory_limit_bytes', 'memory_limit_bytes', GaugeMetricFamily),
            ('finops_container_oom_kills', 'oom_kills', CounterMetricFamily),
        ]:
            if resource[field] is not None:
                metric = kind(name, field)
                metric.add_metric([], resource[field])
                yield metric
        for field in ['total_bytes', 'free_bytes', 'used_bytes']:
            metric = GaugeMetricFamily('finops_filesystem_'+field, 'Filesystem '+field, labels=['area'])
            for filesystem in filesystems():
                metric.add_metric([filesystem['name']], filesystem[field])
            yield metric


REGISTRY.register(ContainerCollector())


def normalize_rules(payload):
    if payload.get('status') != 'success':
        raise ValueError('Prometheus API failed')
    rules = []
    for group in payload['data']['groups']:
        for rule in group['rules']:
            if rule.get('type') != 'alerting':
                continue
            rules.append({'name': rule['name'], 'state': rule['state'], 'health': rule.get('health'),
                          'summary': rule.get('annotations', {}).get('summary', rule['name']),
                          'duration_seconds': rule.get('duration', 0),
                          'alerts': [{'state': item['state'], 'active_at': item.get('activeAt'),
                                      'value': item.get('value'), 'labels': item.get('labels', {}),
                                      'summary': item.get('annotations', {}).get('summary', rule['name'])}
                                     for item in rule.get('alerts', [])]})
    return rules


async def watch_alerts():
    global _alerts
    if not PROMETHEUS_URL:
        return
    previous = None
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        while True:
            try:
                response = await client.get(PROMETHEUS_URL+'/api/v1/rules', params={'type': 'alert'})
                response.raise_for_status()
                rules = normalize_rules(response.json())
                current = {json.dumps(a['labels'], sort_keys=True): (rule['name'], a)
                           for rule in rules for a in rule['alerts'] if a['state'] == 'firing'}
                # Never invent recoveries while the monitoring service is unreachable.
                for key in current.keys() - (previous or {}).keys():
                    name, alert = current[key]
                    await asyncio.to_thread(emit, uid(), 'RESOURCE_ALERT_FIRING',
                        name+'：'+alert['summary']+'；value='+str(alert['value']), service='monitoring', level='WARN')
                if previous is not None:
                    for key in previous.keys() - current.keys():
                        await asyncio.to_thread(emit, uid(), 'RESOURCE_ALERT_RESOLVED',
                            previous[key][0]+'：Prometheus 告警已恢复', service='monitoring')
                previous = current
                _alerts = {'available': True, 'rules': rules, 'error': None, 'updated_at': now()}
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                _alerts = {**_alerts, 'available': False, 'error': '暂时无法获取 Prometheus 告警；上次结果可能已过期。'}
            await asyncio.sleep(5)


def _validated_capacity_path():
    if not DRILLS_ENABLED:
        raise BusinessError('RESOURCE_DRILL_DISABLED', '容量演练仅在独立资源实验环境启用', 409)
    path = CAPACITY_DIR.resolve()
    mounts = Path('/proc/mounts').read_text().splitlines()
    if path != CAPACITY_DIR or not any(line.split()[1:3] == [str(path), 'tmpfs'] for line in mounts):
        raise BusinessError('INVALID_CAPACITY_MOUNT', '容量区必须是独立的 tmpfs 挂载，拒绝向普通数据目录填充', 409)
    usage = shutil.disk_usage(path)
    if usage.total > 128*1024*1024:
        raise BusinessError('CAPACITY_LIMIT_TOO_LARGE', '容量演练区不得超过 128MiB', 409)
    return path/'finops-capacity-drill.bin'


def clear_capacity(expected_generation=None):
    global _capacity_timer, _capacity_expires, _capacity_generation
    with _capacity_lock:
        if expected_generation is not None and expected_generation != _capacity_generation:
            return
        _capacity_generation += 1
        if _capacity_timer:
            _capacity_timer.cancel()
        if DRILLS_ENABLED:
            with contextlib.suppress(FileNotFoundError):
                _validated_capacity_path().unlink()
        _capacity_timer = None
        _capacity_expires = None


def fill_capacity(percent, duration_seconds):
    global _capacity_timer, _capacity_expires, _capacity_generation
    path = _validated_capacity_path()
    if not _capacity_lock.acquire(blocking=False):
        raise BusinessError('CAPACITY_BUSY', '容量演练正在写入，请稍后重试', 409)
    try:
        _capacity_generation += 1
        if _capacity_timer:
            _capacity_timer.cancel()
        # O_NOFOLLOW prevents writing through a substituted symlink.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        target = int(shutil.disk_usage(CAPACITY_DIR).total*percent/100)
        with os.fdopen(fd, 'wb', buffering=0) as output:
            block = b'R'*(1024*1024)
            remaining = target
            while remaining:
                written = output.write(block[:min(remaining, len(block))])
                remaining -= written
        _capacity_expires = time.time()+duration_seconds
        _capacity_timer = threading.Timer(duration_seconds, clear_capacity, args=(_capacity_generation,))
        _capacity_timer.daemon = True
        _capacity_timer.start()
        return {'bytes_written': target, 'percent': percent, 'expires_at': _capacity_expires,
                'warning': '这是 tmpfs 临时容量演练，同时占用应用容器内存；到期自动清理。'}
    except OSError:
        with contextlib.suppress(OSError):
            path.unlink()
        _capacity_expires = None
        raise BusinessError('CAPACITY_WRITE_FAILED', '容量演练写入失败，已尝试清理专用文件', 503)
    finally:
        _capacity_lock.release()
