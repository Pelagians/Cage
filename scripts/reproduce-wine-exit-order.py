#!/usr/bin/env python3
"""Apply the checked native exit-order change to the exact original RPM ELF.

The source change, original/derived ELF hashes, exact instruction edit and new
GNU build ID are recorded in runtime/vendor/wine-11.20-exit1/source.json.
The input is read only; the output must be new. No compiler or installed Wine
process is needed. This transformation never modifies an original runtime.
"""
from pathlib import Path
import argparse
import hashlib
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.arm64ec import native_exit_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    data = native_exit_payload(args.input.read_bytes())
    with args.output.open('xb') as output:output.write(data)
    args.output.chmod(args.input.stat().st_mode & 0o777)
    print(hashlib.sha256(data).hexdigest())


if __name__ == '__main__':main()
