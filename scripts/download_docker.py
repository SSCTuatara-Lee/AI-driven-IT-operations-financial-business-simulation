import hashlib, json, sys, time, urllib.request
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
url="https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
folder=Path(__file__).resolve().parents[1]/".tools"/"installers"
folder.mkdir(parents=True,exist_ok=True)
path=folder/"docker-desktop-installer.exe"
part=folder/"docker-desktop-installer.part"
if path.exists():
    print("Installer already downloaded:",path,flush=True)
    sys.exit(0)
print("Downloading official Docker Desktop installer",flush=True)
with urllib.request.urlopen(url,timeout=60) as response, part.open("wb") as output:
    total=int(response.headers.get("Content-Length",0))
    copied=0
    last=time.monotonic()
    while block:=response.read(1024*1024):
        output.write(block)
        copied+=len(block)
        if time.monotonic()-last>30:
            print(f"Downloaded {copied//1048576} MiB / {total//1048576} MiB",flush=True)
            last=time.monotonic()
if total and copied!=total:
    raise RuntimeError("Incomplete download")
part.replace(path)
info={"source":url,"bytes":copied,"sha256":hashlib.file_digest(path.open("rb"),"sha256").hexdigest(),"signature":"must verify before installation"}
(folder/"docker-download.json").write_text(json.dumps(info,indent=2),encoding="utf-8")
print(json.dumps(info),flush=True)
