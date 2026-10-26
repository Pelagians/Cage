#!/bin/bash
# Disposable Ubuntu CI only. Keep apt's signed metadata/package verification;
# avoid the stalled Azure mirror observed in capability run 40295502219.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != true ]] || [[ ! -f /etc/apt/sources.list.d/ubuntu.sources ]]; then
  echo 'Capability prerequisite setup requires the disposable Ubuntu Actions runner' >&2
  exit 64
fi
sudo sed -i 's|http://azure.archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g; s|https://azure.archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources
apt_options=(-o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
sudo apt-get "${apt_options[@]}" update
sudo apt-get "${apt_options[@]}" install -y "$@"
