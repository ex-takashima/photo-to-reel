#!/bin/sh
# 使い方: ./build.sh  → dist/photo-to-reel.zip
set -e
cd "$(dirname "$0")"
mkdir -p dist && rm -f dist/photo-to-reel.zip
zip -qr dist/photo-to-reel.zip photo-to-reel -x "*.DS_Store" "*__pycache__*"
unzip -l dist/photo-to-reel.zip
