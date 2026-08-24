import os
from pathlib import Path

modules_dir = Path(r"c:\Users\User\Desktop\sollus_connected\modules")

for root, _, files in os.walk(modules_dir):
    for file in files:
        if file.endswith(".py"):
            path = Path(root) / file
            try:
                content = path.read_text(encoding="utf-8")
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if ".before_request" in line and "@" in line:
                        print(f"--- {path.name}:{i+1} ---")
                        for j in range(i, min(i+5, len(lines))):
                            print(lines[j])
            except Exception as e:
                pass
