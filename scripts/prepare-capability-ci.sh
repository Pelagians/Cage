#!/bin/bash
# Disposable Ubuntu CI only. Keep apt's signed metadata/package verification;
# avoid the stalled Azure mirror observed in capability runs 40295502219/40298530840.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != true ]] || [[ ! -f /etc/apt/sources.list.d/ubuntu.sources ]]; then
  echo 'Capability prerequisite setup requires the disposable Ubuntu Actions runner' >&2
  exit 64
fi
# Current runner images use a mirror+file URI whose first priority is Azure;
# replacing only a direct Azure URL leaves that selection unchanged.
sudo sed -i \
  -e 's|mirror+file:/etc/apt/apt-mirrors\.txt/*|https://archive.ubuntu.com/ubuntu/|g' \
  -e 's|https\?://azure\.archive\.ubuntu\.com/ubuntu/*|https://archive.ubuntu.com/ubuntu/|g' \
  /etc/apt/sources.list.d/ubuntu.sources
if grep -Eq '^URIs:.*(mirror\+file:|https?://azure\.archive\.ubuntu\.com/)' /etc/apt/sources.list.d/ubuntu.sources; then
  echo 'Capability prerequisite mirror selection was not replaced' >&2
  exit 64
fi
sed -n '/^URIs:/p' /etc/apt/sources.list.d/ubuntu.sources
apt_options=(-o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
sudo apt-get "${apt_options[@]}" update
sudo apt-get "${apt_options[@]}" install -y "$@"
