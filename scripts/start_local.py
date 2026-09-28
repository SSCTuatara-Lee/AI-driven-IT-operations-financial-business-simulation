import os
from pathlib import Path
import uvicorn
root=Path(__file__).resolve().parents[1]
os.chdir(root)
import sys
sys.path.insert(0,str(root))
sys.stdout.reconfigure(encoding="utf-8")
path=root/".env"
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key,value=line.split("=",1)
            os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
os.environ.setdefault("DATA_DIR",str(root/"data"))
if __name__=="__main__":
    uvicorn.run("app.main:app",host="127.0.0.1",port=8000,workers=1)
