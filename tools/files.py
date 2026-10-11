from pathlib import Path
def list_files(path='.'):
    p=Path(path).expanduser(); return [x.name for x in p.iterdir()][:100] if p.exists() else []
