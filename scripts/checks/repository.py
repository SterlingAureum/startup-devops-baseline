"""Syntax and entrypoint checks for active code; archives are historical inputs."""
import ast
from pathlib import Path
import re
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]


def check_job_checkout(job, location):
    checked_out = False
    for step in job.get("steps", []):
        if step.get("uses", "").startswith("actions/checkout@"):
            checked_out = True
        if re.search(r"scripts/[\w./-]+\.(?:py|sh)", step.get("run", "")) and not checked_out:
            raise ValueError("Repository script used before checkout: " + location)


def check():
    for folder in ("scripts", "tests", "apps/demo-api/src", "apps/demo-api/tests"):
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix == ".py":
                ast.parse(path.read_text(), filename=str(path))
            elif path.suffix == ".sh":
                subprocess.run(["bash", "-n", str(path)], check=True)
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        doc = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        if not isinstance(doc, dict) or not isinstance(doc.get("on"), dict) or not isinstance(doc.get("jobs"), dict):
            raise ValueError("Invalid workflow document: " + str(path.relative_to(ROOT)))
        for name, job in doc["jobs"].items():
            check_job_checkout(job, str(path.relative_to(ROOT)) + ":" + name)
            for item in [job, *job.get("steps", [])]:
                uses = item.get("uses", "")
                if uses.startswith("./"):
                    if not (ROOT / uses[2:]).is_file():
                        raise ValueError("Missing local workflow: " + uses)
                elif uses and not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", uses):
                    raise ValueError("External Action must use a full commit SHA: " + uses)
                script = item.get("run", "")
                if re.search(r"(?:python3?|bash|source|exec)\s+[^\n]*\barchive/", script):
                    raise ValueError("A current workflow executes an archive")
                for reference in re.findall(r"scripts/[\w./-]+\.(?:py|sh)", script):
                    if not (ROOT / reference).is_file():
                        raise ValueError("Missing active script: " + reference)
                if script:
                    snippet = re.sub(r"\$\{\{.*?\}\}", "FIXTURE", script)
                    subprocess.run(["bash", "-n"], input=snippet, text=True, check=True)
    print("PASS: current source syntax, pinned Actions and workflow entrypoints")


if __name__ == "__main__":
    check()
