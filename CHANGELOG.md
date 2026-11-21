## 1.11.6

- `mbrola` und `mbrola-de4` als verbindliche Debian-Abhängigkeiten ergänzt.
- MBROLA `de4` in der README als vorgesehene deutsche Sprachausgabe dokumentiert.
- eSpeak-NG bleibt als technische Schnittstelle zur Ansteuerung der MBROLA-Stimme enthalten.
- ZIP- und DEB-Versionsangaben auf 1.11.6 aktualisiert.

## 1.11.5

- Vorbereitende MBROLA-Dokumentation ergänzt; die Pakete waren zunächst nur empfohlen.

## 1.11.4
- Build-Werkzeuge akzeptieren freigegebene Buildskripte jetzt auch in sicheren Unterordnern des ausgewählten Projektordners (z. B. `gluecksrad/build_release.sh`). Das Skript läuft im eigenen Unterordner; absolute Pfade, `..` und Symlink-Ausbrüche bleiben gesperrt.

- Hilfe-Schaltfläche aus der linken Seitenleiste in die obere Leiste verschoben: direkt links neben der Versionsanzeige.
- Integrierte Schritt-für-Schritt-Anleitung korrigiert: neuer Hilfe-Aufruf oben rechts beschrieben.
- Neues Kapitel erklärt die separate Build-Ausführungsfreigabe, erforderliche Lese-/Schreibrechte, ausdrückliche Build-Aufträge, unterstützte Skripte und Sicherheitsgrenzen.
- README, Paketversion und Release-Dateinamen auf 1.11.4 aktualisiert.
- Build-Ausführungsfunktion aus 1.11.3 unverändert beibehalten.

## 1.11.3

- Versionsnummer auf 1.11.3 erhöht.
- Build-Ausführungsfreigabe und lokale Projekt-Buildfunktion aus 1.11.2 beibehalten.



- Lokale Build-Ausführung für den ausdrücklich ausgewählten Projektordner ergänzt.
- Neue separate Freigabe „KI darf Build-Befehle ausführen“; sie setzt aktivierte Lese- und Schreibfreigabe voraus und wird beim Wechsel des Projektordners zurückgesetzt.
- `run_project_command` führt begrenzte Prüf- und Build-Befehle direkt im ausgewählten Projektordner aus: freigegebene Buildskripte, Python-Syntaxprüfung, dpkg-deb sowie ZIP-Prüfungen.
- Buildskripte erhalten ein Zeitlimit, Ausgaben werden begrenzt; Shell-Verkettungen, Umleitungen, `sudo`, absolute Pfade und Zugriffe außerhalb des Projekts sind gesperrt.
- Keine Build-Ausführung ohne gesonderte Freigabe und konkreten Auftrag in der aktuellen Nachricht.
- Versionsnummer bleibt unverändert.

## 1.11.1\n\n- Neue Schaltfläche „Hilfe & Anleitung“ in der linken Seitenleiste.\n- Ausführliche deutschsprachige Schritt-für-Schritt-Anleitung zu Chatbedienung, Anhängen, Arbeitsbereich, Projektordner-Auswahl, Lese-/Schreibfreigaben, Projektanalyse, Änderungsplan und Sicherungsverwaltung.\n- Anleitung direkt in einem scrollbaren Dialog mit Hinweisen zu sicherem Arbeiten und Fehlerbehebung.\n\n## 1.11.0

- Versionsnummer in `lunagpt/version.py` zentralisiert; Bildgenerator-Header und Debian-Build lesen dieselbe Versionsquelle.
- Spracheingabe in einen QThread verlegt: Mikrofonaufnahme und Online-Erkennung laufen außerhalb des GUI-Threads; Ergebnisse und Fehlermeldungen werden sicher an die Oberfläche zurückgegeben.
- Installationsanleitung für DEB und ZIP überarbeitet und Python-Kernabhängigkeiten, Systempakete sowie optionale Spracheingabe klar getrennt.
- `build_deb.sh` ermittelt die Paketversion automatisch aus der zentralen Versionsdatei.

## 1.10.9
- Projekt-Arbeitsablauf erweitert: lesende Projektanalyse mit Dateitypen, wichtigen Projektdateien und Python-Einstiegspunkten.
- Neue Python-Syntaxprüfung über AST; Projektcode wird dabei nicht ausgeführt und keine Datei verändert.
- Arbeitsmodus-Anweisungen ergänzt: Analyse, Änderungsplan, ausdrückliche Freigabe, Umsetzung und anschließende Prüfung.
- Größere Projektänderungen sollen vor dem Schreiben mit betroffenen Dateien, Zweck und Risiken geplant werden.

## 1.10.8
- Sicherungsverwaltung optisch überarbeitet: breitere Liste und größere, mehrzeilige Sicherungseinträge.
- Zeitstempel werden als Datum und Uhrzeit lesbar formatiert.
- Datei und Größe stehen getrennt und übersichtlich im Listeneintrag.
- Detailkopf nutzt klar getrennte Angaben; Vergleichsergebnis wird deutlich als identisch oder abweichend gekennzeichnet.
- Zeilenumbrüche in Sicherungsdetails werden korrekt dargestellt.

## 1.10.7
- Neue grafische Sicherungsverwaltung direkt in der Seitenleiste.
- Sicherungen des ausgewählten Projekts können angezeigt und ihr Inhalt eingesehen werden.
- Direkter Vergleich einer Sicherung mit dem aktuellen Original inklusive Unterschiede.
- Wiederherstellung per Schaltfläche mit ausdrücklicher Sicherheitsabfrage.
- Vor jeder Wiederherstellung wird der aktuelle Dateistand zusätzlich gesichert und die Sicherung auf Integrität geprüft.
- Backup-Ordner bleibt für gewöhnliche KI-Dateioperationen geschützt.

## 1.10.6

- Eigene, geschützte Backup-Verwaltung für den KI-Projektzugriff ergänzt.
- Sicherungen können gezielt aufgelistet, gelesen und mit dem aktuellen Original verglichen werden.
- Ausdrücklich angeforderte Wiederherstellung erstellt zuerst eine zusätzliche, verifizierte Sicherung des aktuellen Stands.
- Der interne Sicherungsordner bleibt für normale Dateioperationen weiterhin gesperrt.

## 1.10.5
- Korrigiert: Worker-Signal `done` übergibt jetzt Antwort und ursprüngliche Chat-ID mit passender Qt-Signatur.
- Behebt den Laufzeitfehler „done(QString) only accepts 1 argument(s), 2 given“.

# Changelog

## 1.10.4
- Sichere, exklusiv erzeugte temporäre Dateien für Projektänderungen und Editor-Speicherungen.
- Backup-Kopien vor dem Überschreiben werden auf Dateiintegrität geprüft.
- Zugriff auf den internen Backup-Ordner wird auch nach Pfadauflösung/Symlink-Prüfung blockiert.
- Chat-Antworten werden stets dem ursprünglichen Chat zugeordnet, auch nach einem Chatwechsel.
- SQLite-Verbindungen werden auch bei Fehlern zuverlässig geschlossen und Transaktionen zurückgerollt.

# Changelog

## 1.10.3
- Startfehler behoben: `QDir` wird korrekt aus `PySide6.QtCore` statt `PySide6.QtWidgets` importiert.
- Lokaler Projektmanager mit Dateibaum und Texteditor für einen ausdrücklich ausgewählten Projektordner.
- LunaGPT kann freigegebene Projektdateien auflisten und lesen; der Zugriff ist standardmäßig deaktiviert.
- Optionaler Schreibzugriff für die KI mit separater Freigabe und automatischen Sicherungskopien vor dem Überschreiben.
- Projektdateien können im integrierten Editor bearbeitet und mit vorheriger Bestätigung gespeichert werden.
- Pfadprüfung verhindert Zugriffe über absolute Pfade, `..` und Symlinks außerhalb des ausgewählten Projektordners.
- Interne Sicherungen liegen im Projektordner unter `.lunagpt-backups/`.


## 1.10.2
- Speicherort für KI-erstellte Dateien in der Seitenleiste sichtbar gemacht.
- Arbeitsbereich kann direkt im Dateimanager geöffnet und über „Speicherort ändern …“ frei gewählt werden.
- Alle Dateiwerkzeuge verwenden den gewählten Arbeitsbereich; Dateiergebnisse liefern absolute Pfade zurück.
- LunaGPT soll nach jeder Dateierstellung den vollständigen Speicherpfad in der Chatantwort nennen.
- Standard-Arbeitsbereich bleibt `~/Documents/LunaGPT-Arbeitsbereich/`; bestehende Chat-Unterordner bleiben erhalten.


## 1.10.1
- Chat-Ansicht scrollt nach dem Laden einer Unterhaltung und nach Lunas Antwort zuverlässiger bis zum Ende.
- Mehrere kurze Scroll-Nachläufe fangen verzögert berechnete Qt-Dokumenthöhen ab.
- Funktionen aus 1.10.0 bleiben erhalten.

## 1.10.0
- `QImage` wird explizit aus `PySide6.QtGui` importiert.
- AI-Horde-Bildantworten werden validiert und als temporäres PNG für Vorschau und manuelles Speichern bereitgestellt.
- Keine lokale Bildgenerierung und kein kostenpflichtiger Fallback.

## 1.9.9
- AI-Horde-Bildantworten werden sowohl als Base64-WebP als auch über Ergebnis-URLs verarbeitet.
- Ergebnisbilder werden validiert, dekodiert und temporär als PNG abgelegt.
- Robustere HTTP-Fehlerdiagnose.

## 1.9.8
- Ungültiger Seed `-1` und fest codierter Modellname entfernt.
- AI Horde kann ein verfügbares Modell auswählen.
- Die sichtbare Auswahl 621 × 621 wird API-konform als 576 × 576 angefordert.

## 1.9.7
- Hinweise auf lokale/offline Bildgenerierung entfernt.
- AI Horde ist der einzige Bildgenerierungsdienst; kein kostenpflichtiger Fallback.
- Bilder werden nur temporär zur Vorschau gehalten und nicht automatisch dauerhaft gespeichert.
- Deutsches Kontextmenü im Bild-Prompt ergänzt.

## 1.9.6
- Bildgenerierung auf die kostenlose, anonyme AI-Horde-Schnittstelle umgestellt.
- Bildgrößen 256 × 256, 512 × 512 und 621 × 621; 768 × 768 entfernt.
- Bilder werden nicht automatisch dauerhaft gespeichert.

## 1.9.3
- Robuster AI-Horde-Anfrage-/Antwortablauf wiederhergestellt.
- Keine lokale Bildgenerierung und kein kostenpflichtiger Fallback.

## 1.9.0
- Verstrichene Generierungszeit wird während und nach der Bildgenerierung angezeigt.
- Die gewählte Auflösung wird an den Generator übergeben.

## 1.8.9
- Fortschrittsanzeige, Bildvorschau und „Bild speichern unter …“ ergänzt.
- Bildgenerierung bleibt optional.

## 1.8.8
- Release-Prüfung akzeptiert DEB-Ausgaben im Projektstamm und in `dist/`.
- Release-Ordner enthält nach erfolgreicher Prüfung nur die aktuellen Release-Dateien.

## 1.8.7
- Version und Architektur des frisch gebauten DEB werden getrennt geprüft.

## 1.8.6
- Begrenzte Build- und Prüfwerkzeuge für ausdrückliche Datei-Aufträge ergänzt.

## 1.8.4
- ZIP- und Debian-Paketierung für saubere Release-Ausgaben verbessert.
- Build-Pakete werden mit `dpkg-deb --build --root-owner-group` erstellt.

## 1.8.2
- ZIP-Extraktion stellt gespeicherte Unix-Dateirechte wieder her.
- Release-Prüfung entpackt ZIP-Dateien mit `unzip`.

## 1.8.1
- POSIX-Dateirechte werden beim Erstellen des Quellarchivs explizit gespeichert.
- Release-Prüfung bricht bei fehlenden Ausführungsrechten klar ab.

## 1.7.3
- Build-Werkzeug unterstützt `build_deb.sh` in Projekt-Unterordnern.
- Löschen eines Chats aktualisiert Chatliste und Unterhaltung sofort.

## 1.7.1
- Begrenzte Build- und Testbefehle innerhalb des Arbeitsbereichs ergänzt.
- Anzeige „🐭 Luna überlegt“ während einer KI-Anfrage ergänzt.
- Normales Senden erstellt weiterhin keine Dateien automatisch.

## 1.6.10
- Dateiwerkzeuge können angehängte Originaldateien unverändert in den Arbeitsbereich kopieren.
- ZIP- und DEB-Archive werden mit Pfad-, Mengen- und Größenprüfungen extrahiert.
- Datenbank-Fix und Streaming-Responses-API bleiben erhalten.


### Korrektur zu 1.11.2 – Paketierungsfunktion

- Regression behoben: Die zusätzliche build_release.sh-Pflicht und das dafür eingeführte build_project_release-Werkzeug wurden entfernt.
- Der bisherige Projekt-/Release-Arbeitsablauf aus 1.11.1 bleibt erhalten; vorhandene Werkzeuge zum Erstellen, Schreiben, Prüfen und Packen von Projektdateien stehen wieder wie zuvor zur Verfügung.
- Versionsnummer bleibt unverändert bei 1.11.2.
