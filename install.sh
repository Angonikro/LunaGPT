#!/bin/sh
set -eu
sudo apt update
sudo apt install python3 python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore python3-cryptography poppler-utils alsa-utils espeak-ng python3-pyaudio
python3 lunagpt/main.py
