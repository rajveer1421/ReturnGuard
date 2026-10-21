"""Build a ready-to-upload Hugging Face Space folder in build/hf_space.

Only files staged or committed in git are included (via `git archive` of the index), so .env, data/, caches and private notes can't leak.
Then the Space files are laid on top: README.md with the Space settings, space_app.py and packages.txt.

    python deploy/huggingface/prepare_space.py
    hf upload <your-username>/returnguard build/hf_space . --repo-type space
"""
import io
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "build" / "hf_space"

# The Space also installs Gradio, which pins some of the same libraries. Leave these unpinned there so pip can
# pick versions that suit both; the exact versions used for the evaluation stay in the repo's requirements.txt.
UNPIN = {"pillow", "numpy", "pydantic"}
# torch is preinstalled on ZeroGPU (which only accepts a few versions); gunicorn and pytest aren't used there.
DROP = {"pytest", "gunicorn", "torch"}
ADD = ["a2wsgi==1.10.10"]  # serves the Flask app inside Gradio's server (space_app.py)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    tree = subprocess.run(["git", "write-tree"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    archive = subprocess.run(["git", "archive", "--format=tar", tree], cwd=ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(OUT, filter="data")

    for name in ("README.md", "space_app.py", "packages.txt"):
        shutil.copy(HERE / name, OUT / name)
    for extra in ("Dockerfile", ".dockerignore", ".github", "deploy", "tests"):
        path = OUT / extra
        shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)

    lines = []
    for line in (OUT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        name = re.split(r"[=<>\[ ]", line.strip(), maxsplit=1)[0].lower()
        if name in DROP:
            continue
        lines.append(name if name in UNPIN else line)
    lines = [line for line in lines if line.strip() and not line.startswith("# development")] + ADD
    (OUT / "requirements.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    files = sum(1 for p in OUT.rglob("*") if p.is_file())
    print(f"Space folder ready: {OUT} ({files} files)")
    print("Upload with:  hf upload <your-username>/returnguard build/hf_space . --repo-type space")


if __name__ == "__main__":
    main()
