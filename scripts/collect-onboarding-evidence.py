#!/usr/bin/env python3
"""Collect proof records without traversing Wine drives or uploading user state."""
from pathlib import Path
import os
import shutil

source = Path('dist/onboarding-evidence')
destination = Path('dist/onboarding-ci-evidence')
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
