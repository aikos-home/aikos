"""Privacy scan: run before every push.

    python tools/privacy_scan.py --denylist PATH
    (or set KLINGELBOX_DENYLIST=PATH)

The denylist is a private text file that is never committed. One term per line:
  - plain words match case-insensitively as whole words ("anna" does not hit "Johanna");
  - terms with punctuation (".lan", "10.0.") match as plain substrings;
  - lines starting with "!" are allowed phrases that are blanked out before matching
    (e.g. a public repository URL that contains a name);
  - "#" starts a comment.

Built-in checks, no denylist needed: private IPv4 addresses, MAC addresses, e-mail
addresses and Home Assistant entity ids. Binary files are scanned as Latin-1 text, so
names inside STL/STEP headers or PNG metadata are found too.

Exit code 1 if anything is found.
"""
import argparse
import os
import re
import subprocess
import sys

BUILTIN = {
    "private IPv4": re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    "MAC address": re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b"),
    "e-mail address": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "HA entity id": re.compile(r"\b(?:binary_sensor|input_boolean|input_text|input_number|input_select|"
                               r"automation|device_tracker|person|zone|notify)\.[a-z0-9_]{3,}\b"),
}
ALLOWED_EMAILS = {"noreply@anthropic.com"}


def repo_files(root):
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=root, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def load_denylist(path):
    terms, allowed = [], []
    for line in open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("!"):
            allowed.append(line[1:].strip().lower())
        else:
            terms.append(line.lower())
    return terms, allowed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--denylist", default=os.environ.get("KLINGELBOX_DENYLIST"))
    args = ap.parse_args()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    terms, allowed = ([], [])
    if args.denylist:
        terms, allowed = load_denylist(args.denylist)
    else:
        print("warning: no denylist given, running the built-in checks only")
    patterns = []
    for t in terms:
        if re.fullmatch(r"[\wÀ-ɏ]+", t):
            patterns.append((t, re.compile(r"(?<![\wÀ-ɏ])" + re.escape(t) + r"(?![\wÀ-ɏ])")))
        else:
            patterns.append((t, re.compile(re.escape(t))))
    hits = 0
    for rel in repo_files(root):
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        raw = open(path, "rb").read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        low = text.lower()
        for a in allowed:
            low = low.replace(a, " " * len(a))
        for t, rx in patterns:
            for m in rx.finditer(low):
                line = low.count("\n", 0, m.start()) + 1
                print(f"{rel}:{line}: denylisted term '{t}'")
                hits += 1
        for name, rx in BUILTIN.items():
            for m in rx.finditer(text):
                if name == "e-mail address" and m.group(0).lower() in ALLOWED_EMAILS:
                    continue
                line = text.count("\n", 0, m.start()) + 1
                print(f"{rel}:{line}: {name}: {m.group(0)}")
                hits += 1
    print(f"{hits} finding(s)" if hits else "clean")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
