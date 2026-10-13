# Changelog

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
