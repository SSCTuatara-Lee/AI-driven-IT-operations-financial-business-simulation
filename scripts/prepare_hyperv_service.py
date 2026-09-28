import subprocess
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
root=Path(__file__).resolve().parents[1]
powershell="C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
copy_storage="--copy-storage" in sys.argv
script=root/("scripts/copy_docker_hyperv_storage.ps1" if copy_storage else "scripts/enable_docker_hyperv.ps1")
command="$p=Start-Process -FilePath '"+powershell+"' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','"+str(script)+"') -Verb RunAs -WindowStyle Hidden -PassThru -Wait; exit $p.ExitCode"
print("Windows administrator consent is required for Docker's Hyper-V configuration. No Windows updates or reboot will be performed.",flush=True)
result=subprocess.run([powershell,"-NoProfile","-Command",command],creationflags=subprocess.CREATE_NO_WINDOW)
report=root/("data/docker-hyperv-storage.json" if copy_storage else "data/docker-hyperv-service.json")
if report.exists():print(report.read_text(encoding="utf-8-sig"),flush=True)
raise SystemExit(result.returncode)
