"""Record exact wheel hashes for the pinned Python/platform acceptance stack."""

import argparse
from email.parser import Parser
import hashlib
from pathlib import Path
import re
import zipfile


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", required=True)
    parser.add_argument("--requirements", default="requirements-week1.in")
    parser.add_argument("--output", default="requirements-week1.lock")
    args = parser.parse_args()
    wheels = {}
    for path in sorted(Path(args.wheelhouse).glob("*.whl")):
        with zipfile.ZipFile(path) as archive:
            name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
            metadata = Parser().parsestr(archive.read(name).decode())
        key = (normalized(metadata["Name"]), metadata["Version"])
        wheels.setdefault(key, []).append(hashlib.sha256(path.read_bytes()).hexdigest())
    lines = ["# Acceptance lock: CPython 3.12, Linux x86_64; includes transitive dependencies.",
             "# Other Python/platform combinations require separately verified wheels.", "--only-binary=:all:"]
    for requirement in Path(args.requirements).read_text().splitlines():
        if not requirement.strip() or requirement.startswith("#"):
            continue
        name, version = requirement.strip().split("==")
        digests = wheels.get((normalized(name), version))
        if not digests:
            raise ValueError(f"missing pinned wheel: {requirement}")
        lines.append(requirement + " " + " ".join("--hash=sha256:" + digest for digest in sorted(set(digests))))
    Path(args.output).write_text("\n".join(lines) + "\n")
    print(f"Locked {len(lines) - 3} requirements to {args.output}")


if __name__ == "__main__":
    main()
