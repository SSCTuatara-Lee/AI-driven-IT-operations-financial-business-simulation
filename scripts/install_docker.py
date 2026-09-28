import json, os, subprocess, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
root=Path(__file__).resolve().parents[1]
installer=root/".tools"/"installers"/"docker-desktop-installer.exe"
if not installer.exists(): raise SystemExit("Run download_docker.py first")
powershell=Path(os.environ.get("SystemRoot","C:/Windows"))/"System32"/"WindowsPowerShell"/"v1.0"/"powershell.exe"
command="$s=Get-AuthenticodeSignature -LiteralPath '"+str(installer).replace("'","''")+"'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; @{Status=$s.Status.ToString();Signer=$s.SignerCertificate.Subject} | ConvertTo-Json -Compress"
verification=subprocess.run([str(powershell),"-NoProfile","-Command",command],capture_output=True,timeout=60)
if verification.returncode: raise SystemExit("Cannot verify installer signature: "+verification.stderr.decode("utf-8",errors="replace"))
signature=json.loads(verification.stdout.decode("utf-8-sig"))
print(json.dumps(signature),flush=True)
if signature.get("Status")!="Valid" or "Docker" not in signature.get("Signer",""):
    raise SystemExit("Docker installer signature validation failed; nothing installed")
args=[str(installer),"install","--quiet","--accept-license","--backend=wsl-2","--no-windows-containers","--installation-dir="+str(root/".tools"/"Docker"),"--wsl-default-data-root="+str(root/".tools"/"docker-data")]
print("Installing Docker Desktop into project .tools folder. No reboot will be requested by this script.",flush=True)
process=subprocess.run(args,creationflags=subprocess.CREATE_NO_WINDOW)
(root/"data"/"docker-install-result.json").write_text(json.dumps({"exit_code":process.returncode,"signature":signature,"target":str(root/".tools"/"Docker")},indent=2),encoding="utf-8")
print("Installer exit code:",process.returncode,flush=True)
raise SystemExit(process.returncode)
