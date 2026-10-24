#!/usr/bin/env python3
"""Collect proof records without traversing Wine drives or uploading user state."""
from pathlib import Path
import argparse
import os
import shutil


def collect(source, destination):
    if source.is_symlink():raise ValueError('evidence root must not be a symlink')
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('evidence destination must be outside the source tree')
    for directory, folders, files in os.walk(source, followlinks=False):
        root = Path(directory)
        folders[:] = [name for name in folders if name not in {'state', 'data', 'package-cache', 'documents'}
                      and not (root / name).is_symlink()]
        for name in files:
            path = root / name
            if path.is_symlink() or not path.is_file():continue
            if path.suffix not in {'.json', '.log', '.png', '.sig'} and path.name != 'publisher-public.pem':continue
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('dist/onboarding-evidence'))
    parser.add_argument('--destination', type=Path, default=Path('dist/onboarding-ci-evidence'))
    args = parser.parse_args()
    collect(args.source, args.destination)


if __name__ == '__main__':main()
