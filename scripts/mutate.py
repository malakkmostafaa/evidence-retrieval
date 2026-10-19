"""Mutation check helper: python scripts/mutate.py FILE TEST 'old=>new' ['old=>new' ...]
Applies each replacement in turn to FILE (restored afterwards), runs pytest on TEST, and prints whether the suite FAILED (= mutation caught)."""
import subprocess
import sys

path, test, *muts = sys.argv[1:]
orig = open(path, encoding="utf-8", newline="").read()
bad = 0
for m in muts:
    old, new = m.split("=>", 1)
    if old not in orig:
        print("NOT FOUND:", old)
        bad += 1
        continue
    open(path, "w", encoding="utf-8", newline="").write(orig.replace(old, new, 1))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", test, "-q", "-x", "-p", "no:cacheprovider"], capture_output=True, text=True)
    finally:
        open(path, "w", encoding="utf-8", newline="").write(orig)
    caught = r.returncode != 0
    bad += not caught
    print(("CAUGHT   " if caught else "SURVIVED ") + m)
sys.exit(1 if bad else 0)
