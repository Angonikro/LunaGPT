#!/bin/sh
set -eu
sudo apt update
sudo apt install dpkg zip unzip python3 python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore python3-cryptography poppler-utils alsa-utils espeak-ng python3-pyaudio mbrola mbrola-de4
python3 lunagpt/main.py
