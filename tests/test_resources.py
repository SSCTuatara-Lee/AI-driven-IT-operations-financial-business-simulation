import json
import asyncio
from pathlib import Path
import httpx
import pytest
from app import resources
from app.domain import BusinessError


def test_cgroup_limited_and_unlimited(tmp_path):
    for name, text in {'cpu.stat': 'usage_usec 2000000\nthrottled_usec 500000\n',
                       'cpu.max': '50000 100000\n', 'memory.current': '900\n',
                       'memory.max': '1000\n', 'memory.events': 'oom_kill 2\n'}.items():
        (tmp_path/name).write_text(text)
    result = resources.read_cgroup(tmp_path)
    assert result['available'] and result['cpu_seconds'] == 2
    assert result['cpu_limit_cores'] == .5 and result['throttled_seconds'] == .5
    assert result['memory_bytes'] == 900 and result['oom_kills'] == 2
    (tmp_path/'cpu.max').write_text('max 100000\n')
    (tmp_path/'memory.max').write_text('max\n')
    result = resources.read_cgroup(tmp_path)
    assert result['cpu_limit_cores'] is None and result['memory_limit_bytes'] is None


def test_missing_cgroup_is_unavailable(tmp_path):
    result = resources.read_cgroup(tmp_path)
    assert not result['available'] and result['memory_bytes'] is None


def test_capacity_refuses_normal_directory(monkeypatch):
    monkeypatch.setattr(resources, 'DRILLS_ENABLED', True)
    monkeypatch.setattr(Path, 'read_text', lambda *a, **k: '/dev/sda /capacity-test ext4 rw 0 0\n')
    # The validation must fail before creating or truncating any file.
    with pytest.raises(BusinessError) as exc:
        resources.fill_capacity(85, 30)
    assert exc.value.code == 'INVALID_CAPACITY_MOUNT'


def test_resource_api_and_disabled_mutations(client, monkeypatch):
    monkeypatch.setattr(resources, 'DRILLS_ENABLED', False)
    result = client.get('/api/resources')
    assert result.status_code == 200
    assert 'container' in result.json() and not result.json()['capacity_drill_enabled']
    assert client.post('/api/resources/capacity', json={'percent': 85, 'duration_seconds': 30}).status_code == 409
    assert client.post('/api/resources/capacity', json={'percent': 100}).status_code == 422
    assert client.delete('/api/resources/capacity').status_code == 409
    assert 'finops_container_metrics_available' in client.get('/metrics').text


def test_prometheus_states_and_health_preserved():
    data = {'status': 'success', 'data': {'groups': [{'rules': [
        {'type': 'alerting', 'name': 'Cpu', 'state': 'pending', 'health': 'ok', 'duration': 20,
         'annotations': {'summary': 'CPU high'}, 'alerts': [{'state': 'pending', 'value': '0.9', 'labels': {'instance': 'app:8000'}}]},
        {'type': 'alerting', 'name': 'Memory', 'state': 'inactive', 'health': 'err', 'alerts': []}
    ]}]}}
    result = resources.normalize_rules(data)
    assert result[0]['state'] == 'pending' and result[0]['alerts'][0]['value'] == '0.9'
    assert result[1]['health'] == 'err'
    with pytest.raises(ValueError):
        resources.normalize_rules({'status': 'error'})


def test_alert_connection_failure_does_not_invent_recovery(monkeypatch):
    recorded = []
    iterations = 0
    def respond(request):
        if iterations == 1:
            return httpx.Response(503)
        firing = iterations == 0
        return httpx.Response(200, json={'status': 'success', 'data': {'groups': [{'rules': [
            {'type': 'alerting', 'name': 'CPU', 'health': 'ok', 'state': 'firing' if firing else 'inactive',
             'alerts': [{'state': 'firing', 'value': '0.95', 'labels': {'alertname': 'CPU'}}] if firing else []}
        ]}]}})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(resources, 'PROMETHEUS_URL', 'http://monitor.test')
    monkeypatch.setattr(resources.httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(resources, 'emit', lambda trace, code, message, **kw: recorded.append((iterations, code)))
    monkeypatch.setattr(resources, '_alerts', {})
    async def tick(_):
        nonlocal iterations
        iterations += 1
        if iterations == 3:
            raise asyncio.CancelledError()
    monkeypatch.setattr(resources.asyncio, 'sleep', tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(resources.watch_alerts())
    assert recorded == [(0, 'RESOURCE_ALERT_FIRING'), (2, 'RESOURCE_ALERT_RESOLVED')]
