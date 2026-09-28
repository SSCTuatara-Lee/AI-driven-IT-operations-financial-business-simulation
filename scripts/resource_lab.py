"""Manage the isolated resource lab without touching the normal Compose project."""
import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['up', 'down', 'status'])
    args = parser.parse_args()
    config = ROOT/'.env.resources'
    if not config.exists():
        if args.action != 'up':
            raise SystemExit('Resource lab has not been initialized.')
        text = (ROOT/'resources.env.example').read_text(encoding='utf-8')
        for key in ['LAB_MYSQL_PASSWORD', 'LAB_MYSQL_ROOT_PASSWORD']:
            text = text.replace(key+'=\n', key+'='+secrets.token_hex(24)+'\n')
        config.write_text(text, encoding='utf-8')
        print('Created .env.resources; secret values are not printed.', flush=True)
    values = dict(line.split('=', 1) for line in config.read_text(encoding='utf-8').splitlines() if '=' in line and not line.startswith('#'))
    if args.action == 'up':
        for key in ['LAB_APP_CPUS', 'LAB_DB_CPUS']:
            if not 0.1 <= float(values[key]) <= 4:
                raise SystemExit(key+' must be between 0.1 and 4.')
        if not 192 <= int(values['LAB_APP_MEMORY_MB']) <= 2048:
            raise SystemExit('LAB_APP_MEMORY_MB must be 192..2048.')
        if not 16 <= int(values['LAB_CAPACITY_MB']) <= 128:
            raise SystemExit('LAB_CAPACITY_MB must be 16..128.')
        if int(values['LAB_APP_MEMORY_MB']) < int(values['LAB_CAPACITY_MB'])+192:
            raise SystemExit('Reserve at least 192MiB beyond tmpfs capacity for the app and load generator. Reduce LAB_CAPACITY_MB for a smaller memory experiment.')
        if not 512 <= int(values['LAB_DB_MEMORY_MB']) <= 2048:
            raise SystemExit('LAB_DB_MEMORY_MB must be 512..2048 for this MySQL lab.')
    docker = ROOT/'.tools/Docker/resources/bin/docker.exe'
    if not docker.exists():
        docker = shutil.which('docker')
    if not docker:
        raise SystemExit('Install/start Docker first.')
    # Keep lab configuration deterministic; ambient shell variables must not
    # override the dedicated file or accidentally target the normal project.
    env = {k: v for k, v in os.environ.items() if not k.startswith('LAB_')}
    command = [str(docker), 'compose', '--project-name', 'chengming-resources', '--env-file', str(config), '-f', str(ROOT/'compose.resources.yaml')]
    operation = {'up': ['up', '--build', '-d', '--wait', '--wait-timeout', '240'],
                 'down': ['down'], 'status': ['ps']}[args.action]
    subprocess.run(command+operation, cwd=ROOT, env=env, check=True)
    if args.action == 'up':
        print('Resource lab: http://127.0.0.1:'+values['LAB_APP_PORT']+'/#resources', flush=True)
        print('Prometheus: http://127.0.0.1:'+values['LAB_PROMETHEUS_PORT']+'/alerts', flush=True)

if __name__ == '__main__':
    main()
