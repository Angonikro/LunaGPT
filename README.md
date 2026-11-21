# LunaGPT 1.11.6

Deutschsprachiger Desktop-Chatclient für Linux und Raspberry Pi. LunaGPT bietet ChatGPT-Anmeldung, lokale Chat-Historie, Datei-Anhänge, Sprachein- und -ausgabe, Themes sowie KI-gestützte Dateiwerkzeuge.

![LunaGPT](lunagpt1.png)

[Github Seite](https://github.com/Angonikro/LunaGPT/)

## Funktionen

- Ausführliche integrierte Hilfe mit Schritt-für-Schritt-Anleitung für Chats, Arbeitsbereich, Projektstart und Paketierung\n- Projektpaketierung direkt im ausgewählten Projektordner: vorhandenes build_release.sh ohne sudo ausführen und ZIP/DEB anschließend prüfen

- Interne Projektsicherungen auflisten, lesen, vergleichen und nach Bestätigung wiederherstellen
- Lokaler Projekt-Arbeitsmodus mit Analyse, Änderungsplan und Syntaxprüfung
- Anmeldung über „Mit ChatGPT anmelden“ im Browser
- Lokale Chat-Historie und Datei-Anhänge
- Sprachein- und -ausgabe; die Mikrofonaufnahme und Spracherkennung laufen in einem Hintergrundthread
- KI-Dateiwerkzeuge im lokalen Arbeitsbereich `~/Documents/LunaGPT-Arbeitsbereich/`
- Integrierter Projektmanager mit Dateibaum und Editor
- Optionaler KI-Lesezugriff und separat freischaltbarer Schreibzugriff auf ausgewählte Projektordner
- Automatische Sicherung vorhandener Dateien vor Änderungen
- Online-Bildgenerierung über AI Horde

## Datenschutz und Dateiarbeit

Chat-Verlauf und Einstellungen werden lokal verwaltet. Normale Dateiwerkzeuge arbeiten im eingestellten LunaGPT-Arbeitsbereich. Ein Projektordner wird im Projektmanager ausdrücklich ausgewählt. Lese- und Schreibzugriff müssen separat freigegeben werden. Vorhandene Projektdateien werden vor dem Überschreiben unter `.lunagpt-backups/` gesichert. Pfade außerhalb des ausgewählten Projektordners werden abgewiesen.

## Build-Befehle im ausgewählten Projektordner

LunaGPT kann auf ausdrücklichen Auftrag Build- und Prüfskripte direkt im aktuell ausgewählten Projektordner ausführen. Dafür müssen Lese-, Schreib- und die separate Build-Ausführungsfreigabe aktiviert sein. Die Build-Freigabe ist standardmäßig ausgeschaltet und wird beim Wechsel des Projektordners zurückgesetzt. Unterstützt werden `build_deb.sh`, `build_release.sh` und `release.sh` im Projektstamm sowie begrenzte Prüfungen mit Python `py_compile`, `dpkg-deb`, `zip` und `unzip`. Befehle laufen ohne `sudo`, ohne Shell-Verkettung und mit Zeitlimit. Buildskripte sind ausführbarer Projektcode; aktiviere die Freigabe nur für vertrauenswürdige Projekte.

### Buildskripte in Projekt-Unterordnern

Die Projekt-Buildwerkzeuge unterstützen freigegebene Skripte `build_deb.sh`, `build_release.sh` und `release.sh` auch in Unterordnern des ausdrücklich ausgewählten Projektordners. Beispiel: `gluecksrad/build_release.sh`. Das Skript wird im eigenen Verzeichnis ausgeführt, sodass relative Pfade wie `release/` korrekt auf den Unterordner zeigen. Absolute Pfade, Pfadaufstiege (`..`) und Symlinks außerhalb des Projektordners werden weiterhin abgewiesen.


## Installation mit Debian-Paket (empfohlen)

Benötigt wird Debian 13 / Raspberry Pi OS mit ARM64 oder eine kompatible Debian-Umgebung.

```bash
sudo apt update
sudo apt install ./lunagpt_1.11.6_all.deb
# Benötigte MBROLA-Sprachausgabe:
sudo apt install mbrola mbrola-de4
```

Falls `apt` fehlende Abhängigkeiten meldet, installiert es diese normalerweise automatisch. Alternativ können die Laufzeitpakete vorab installiert werden:

```bash
sudo apt install python3 python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore python3-cryptography python3-pyaudio poppler-utils alsa-utils espeak-ng mbrola mbrola-de4
```

Start über das Anwendungsmenü oder im Terminal:

```bash
lunagpt
```

Das DEB installiert den Starter nach `/usr/bin/lunagpt` und die Anwendung nach `/usr/share/lunagpt/`. Es wird keine virtuelle Python-Umgebung angelegt.

## Start aus dem ZIP-Archiv

1. ZIP-Datei entpacken.
2. In das entpackte Verzeichnis `LunaGPT` wechseln.
3. Systemabhängigkeiten installieren und das Startskript ausführen:

```bash
cd LunaGPT
sudo apt update
sudo apt install python3 python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore python3-cryptography python3-pyaudio poppler-utils alsa-utils espeak-ng mbrola mbrola-de4
python3 lunagpt/main.py
```

Alternativ kann `./install.sh` verwendet werden. Das Skript installiert die Systempakete und startet LunaGPT. Es benötigt `sudo` für `apt`.

## MBROLA-Sprachausgabe (Standard)

LunaGPT verwendet die deutsche MBROLA-Stimme `de4` als vorgesehene Sprachausgabe. Dafür müssen `mbrola` und `mbrola-de4` installiert sein. eSpeak-NG bleibt als technische Schnittstelle erhalten, über die LunaGPT die MBROLA-Stimme ansteuert:

```bash
sudo apt install mbrola mbrola-de4
```

MBROLA ist für die vorgesehene deutsche Sprachausgabe erforderlich. Die eigentliche Stimme ist MBROLA `de4`; eSpeak-NG dient lediglich als technische Ansteuerung. Falls `apt` `mbrola-de4` nicht findet, prüfe, ob die Debian-Paketquelle `contrib` aktiviert ist. Die Stimme wird lokal installiert und benötigt zur Wiedergabe keine Internetverbindung.

## Spracheingabe (optional)

Die Spracheingabe benötigt zusätzlich das Python-Modul `SpeechRecognition`. Mikrofonzugriff benötigt außerdem `python3-pyaudio` und `alsa-utils`, die oben über `apt` installiert werden.

```bash
python3 -m pip install --user --break-system-packages SpeechRecognition
```

Debian schützt die systemweite Python-Installation vor pip-Änderungen. Der Befehl verwendet deshalb ausdrücklich die Benutzerinstallation. Die eigentliche Aufnahme und Online-Spracherkennung blockiert die Programmoberfläche nicht. Für die Online-Erkennung ist eine Internetverbindung erforderlich.

## Abhängigkeiten

| Komponente | Zweck | Installation |
|---|---|---|
| Python 3 | Laufzeit | `python3` |
| PySide6 | Grafische Oberfläche | `python3-pyside6.qtwidgets`, `qtgui`, `qtcore` |
| cryptography | Verschlüsselungsfunktionen | `python3-cryptography` |
| PyAudio | Mikrofonzugriff | `python3-pyaudio` |
| SpeechRecognition | Optionale Spracheingabe | Benutzerinstallation über pip |
| poppler-utils | PDF-Textausgabe | `poppler-utils` |
| alsa-utils | Audio-Werkzeuge | `alsa-utils` |
| espeak-ng | Technische Schnittstelle zur Ansteuerung der MBROLA-Stimme | `espeak-ng` |
| MBROLA | Sprachausgabe-Engine | `mbrola` |
| MBROLA Deutsch (de4) | Deutsche MBROLA-Stimme (vorgesehen) | `mbrola-de4` |

`requirements.txt` enthält die Python-Kernabhängigkeiten für eine pip-basierte Entwicklungsumgebung. Für Debian wird die Installation der Systempakete über `apt` bevorzugt.

## Debian-Paket selbst bauen

Im Projektverzeichnis:

```bash
./build_deb.sh
```

Benötigt wird `dpkg-deb`. Die Paketversion wird automatisch aus `lunagpt/version.py` gelesen; die Versionsnummer muss im Build-Skript nicht separat gepflegt werden. Das fertige Paket liegt unter `dist/lunagpt_1.11.6_all.deb`.

## Prüfen

```bash
python3 -m py_compile lunagpt/main.py lunagpt/siwc.py lunagpt/version.py
dpkg-deb -I dist/lunagpt_1.11.6_all.deb
dpkg-deb -c dist/lunagpt_1.11.6_all.deb
```

## Projektstruktur

- `lunagpt/` – Python-Quellcode einschließlich zentraler `version.py`
- `bin/lunagpt` – Programmstarter
- `share/` – Desktop-Eintrag und Anwendungssymbol
- `debian/control` – Paketmetadaten
- `build_deb.sh` – Build-Skript
- `requirements.txt` – Python-Kernabhängigkeiten
- `CHANGELOG.md` – Versionshistorie

73 de DO2QG Andreas