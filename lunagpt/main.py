#!/usr/bin/env python3
import os, sys, json, base64, mimetypes, sqlite3, urllib.request, urllib.error, uuid, subprocess, tempfile, time, queue, threading, re, zipfile, shutil, shlex, stat
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer
from PySide6.QtGui import QFont, QAction, QPixmap, QImage, QTextCursor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QTextBrowser, QTextEdit, QPushButton, QLabel, QLineEdit,
    QFileDialog, QMessageBox, QComboBox, QCheckBox, QSplitter, QInputDialog, QDialog,
    QFormLayout, QDialogButtonBox, QPlainTextEdit, QProgressBar, QMenu, QSlider)

def frage_de(parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No, defaultButton=QMessageBox.NoButton):
    """Fragedialog mit deutschen Beschriftungen, unabhängig von der Systemsprache."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    labels = {
        QMessageBox.Yes: "Ja",
        QMessageBox.No: "Nein",
        QMessageBox.Cancel: "Abbrechen",
        QMessageBox.Ok: "OK",
        QMessageBox.Close: "Schließen",
        QMessageBox.Save: "Speichern",
        QMessageBox.Discard: "Verwerfen",
        QMessageBox.Apply: "Übernehmen",
        QMessageBox.Reset: "Zurücksetzen",
        QMessageBox.Retry: "Erneut versuchen",
        QMessageBox.Ignore: "Ignorieren",
    }
    for standard, label in labels.items():
        button = box.button(standard)
        if button is not None:
            button.setText(label)
    if defaultButton != QMessageBox.NoButton:
        box.setDefaultButton(defaultButton)
    return box.exec()

class AttachmentTextEdit(QTextEdit):
    """Eingabefeld für Datei-Drops."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setAcceptDrops(True)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()): event.acceptProposedAction()
        else: super().dragEnterEvent(event)
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()): event.acceptProposedAction()
        else: super().dragMoveEvent(event)
    def dropEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            self.owner.add_dropped_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()
        else: super().dropEvent(event)

# Gemeinsame, abbrechbare TTS-Wiedergabe.
tts_queue = queue.Queue()
_tts_process_lock = threading.Lock()
_tts_active_process = None
_tts_generation = 0

def _tts_run(command, input_data=None, timeout=180):
    """Führt einen TTS-Prozess so aus, dass der Stop-Knopf ihn beenden kann."""
    global _tts_active_process
    proc = subprocess.Popen(command, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with _tts_process_lock:
        _tts_active_process = proc
    try:
        out, err = proc.communicate(input=input_data, timeout=timeout)
        return subprocess.CompletedProcess(command, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return subprocess.CompletedProcess(command, 124, out, err or "TTS-Zeitüberschreitung".encode("utf-8"))
    finally:
        with _tts_process_lock:
            if _tts_active_process is proc:
                _tts_active_process = None

def stop_tts_playback():
    """Bricht aktuelle Sprachausgabe ab und leert ausstehende Ansagen."""
    global _tts_generation, _tts_active_process
    with _tts_process_lock:
        _tts_generation += 1
        proc = _tts_active_process
        _tts_active_process = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
    while True:
        try:
            tts_queue.get_nowait()
            tts_queue.task_done()
        except queue.Empty:
            break

def _tts_worker():
    """Spielt Sprache aus der Warteschlange ab und unterstützt Abbruch."""
    global _tts_generation
    while True:
        item = tts_queue.get()
        if item is None:
            tts_queue.task_done()
            return
        text, voice, speed, pitch, volume, output_device, generation = item
        try:
            with _tts_process_lock:
                cancelled = generation != _tts_generation
            if cancelled:
                continue
            voices_to_try = [voice]
            if voice != "de":
                voices_to_try.append("de")
            audio = None
            last_error = ""
            for selected_voice in dict.fromkeys(voices_to_try):
                with _tts_process_lock:
                    if generation != _tts_generation:
                        break
                try:
                    command = ["espeak-ng", "-v", selected_voice, "-s", str(speed),
                               "-p", str(pitch), "-a", str(volume), "--stdout", text]
                    generated = _tts_run(command, timeout=180)
                    with _tts_process_lock:
                        if generation != _tts_generation:
                            break
                    if generated.returncode == 0 and generated.stdout:
                        audio = generated.stdout
                        break
                    last_error = (generated.stderr or b"Keine Audiodaten erzeugt.").decode("utf-8", errors="replace")
                except (OSError, subprocess.SubprocessError) as exc:
                    last_error = str(exc)
            with _tts_process_lock:
                if generation != _tts_generation:
                    continue
            if not audio:
                print(f"LunaGPT TTS: Spracherzeugung fehlgeschlagen: {last_error}", file=sys.stderr, flush=True)
                continue
            play_command = ["aplay", "-q"]
            if output_device and str(output_device).startswith("alsa:"):
                play_command += ["-D", str(output_device).split(":", 1)[1]]
            played = _tts_run(play_command, input_data=audio, timeout=180)
            with _tts_process_lock:
                if generation != _tts_generation:
                    continue
            if played.returncode != 0:
                if len(play_command) > 2:
                    fallback = _tts_run(["aplay", "-q"], input_data=audio, timeout=180)
                    if fallback.returncode != 0:
                        detail = (fallback.stderr or played.stderr or b"").decode("utf-8", errors="replace").strip()
                        print(f"LunaGPT TTS: Audiowiedergabe fehlgeschlagen: {detail}", file=sys.stderr, flush=True)
                else:
                    detail = (played.stderr or b"").decode("utf-8", errors="replace").strip()
                    print(f"LunaGPT TTS: Audiowiedergabe fehlgeschlagen: {detail}", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"LunaGPT TTS: Unerwarteter Fehler: {exc}", file=sys.stderr, flush=True)
        finally:
            tts_queue.task_done()

threading.Thread(target=_tts_worker, name="LunaGPT-TTS", daemon=True).start()

APP_NAME = "LunaGPT"
APP_VERSION = "1.10.1"
CONFIG_DIR = Path.home()/".config"/"lunagpt"
DATA_DIR = Path.home()/".local"/"share"/"lunagpt"
CONFIG = CONFIG_DIR/"config.json"
DB = DATA_DIR/"chats.sqlite3"
DEFAULT_MODEL = "gpt-4.1-mini"
from siwc import sign_in as siwc_sign_in, refresh_if_needed, responses_request, list_models
SYSTEM_PROMPT = """Du bist LunaGPT, ein sorgfältiger, freundlicher deutschsprachiger KI-Assistent.
Antworte standardmäßig auf Deutsch, außer der Nutzer wünscht ausdrücklich eine andere Sprache.
Beantworte zuerst die konkrete Frage und passe Länge und Fachsprache an den Nutzer an.
Erkläre schwierige Themen verständlich und Schritt für Schritt, wenn das hilfreich ist.
Erfinde keine Fakten, Quellen, Testergebnisse oder Fähigkeiten. Wenn du etwas nicht sicher weißt, sage das offen und trenne gesicherte Fakten von Vermutungen.
Frage nur nach, wenn eine fehlende Information wirklich nötig ist; andernfalls nenne deine Annahme kurz und fahre fort.
Wenn Dateianhänge mit Dateiinhalt-Markierungen übergeben wurden, analysiere den tatsächlich mitgesendeten Inhalt. Bitte nicht erneut um dieselben Dateien, wenn deren Inhalt bereits im Kontext steht; sage transparent, falls nur Dateiliste oder gekürzte Inhalte verfügbar sind.\nWenn die Websuche verfügbar und aktiviert ist, nutze sie für aktuelle oder veränderliche Informationen und stütze Aussagen auf tatsächlich gefundene Ergebnisse. Behaupte nicht, gesucht oder etwas geprüft zu haben, wenn das nicht geschehen ist.
Bei praktischen Anleitungen gib konkrete, geordnete Schritte. Weise bei riskanten oder zerstörerischen Befehlen auf mögliche Folgen hin.
Formatiere Code in Markdown-Codeblöcken und bewahre korrekte Einrückungen. Bleibe respektvoll, ehrlich und auf die Aufgabe konzentriert."""
CODE_PROMPT = """Du bist LunaGPT im Programmiermodus: ein sorgfältiger, pragmatischer Entwicklungshelfer.
Antworte standardmäßig auf Deutsch und erkläre technische Begriffe passend zum Kenntnisstand des Nutzers.
Bei Code-Aufgaben:
1. Verstehe zuerst das gewünschte Verhalten und untersuche den gesamten bereitgestellten Code, nicht nur die erste auffällige Zeile.
2. Benenne konkrete Fehler und erkläre jeweils Ursache und Auswirkung. Unterscheide sichere Befunde von möglichen Ursachen.
3. Wenn du Code korrigierst, liefere bei überschaubaren Beispielen den vollständigen, direkt nutzbaren Code. Achte auf Syntax, Einrückung, Imports, Namen, Rückgabewerte und relevante Randfälle.
4. Erkläre kurz, was geändert wurde und welche Ausgabe bzw. welches Verhalten zu erwarten ist.
5. Behaupte niemals, Code ausgeführt, getestet, gebaut oder auf einem Gerät geprüft zu haben, wenn das nicht tatsächlich geschehen ist. Wenn du ihn nur gedanklich geprüft hast, sage das.
6. Bei Änderungen an bestehenden Projekten: bewahre vorhandene Funktionen, halte Änderungen eng am Auftrag und fordere fehlende Dateien an, statt deren Inhalt zu erfinden.
7. Bei Shell-Befehlen oder Änderungen an Dateien erkläre mögliche Risiken und vermeide unnötig zerstörerische Schritte.
Wenn mehrere Lösungen möglich sind, nenne kurz die Vor- und Nachteile und empfehle eine passende Lösung. Erfinde keine APIs, Fehlermeldungen, Testergebnisse oder Dokumentationsquellen."""

def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try: CONFIG_DIR.chmod(0o700)
    except OSError: pass

def load_config():
    ensure_dirs()
    try:
        cfg = json.loads(CONFIG.read_text())
    except Exception:
        cfg = {}
    defaults = {
        "api_key": "", "model": DEFAULT_MODEL, "speak": True, "auth_mode": "api",
        "tts_voice": "mb-de4", "tts_speed": 165, "tts_pitch": 45, "tts_volume": 185,
        "ui_mode": "Allgemein", "web_search": False
    }
    defaults.update(cfg)
    return defaults

def save_config(c):
    ensure_dirs()
    temp = CONFIG.with_suffix(".tmp")
    temp.write_text(json.dumps(c, indent=2))
    temp.chmod(0o600)
    temp.replace(CONFIG)
    CONFIG.chmod(0o600)

def init_db():
    ensure_dirs()
    con=sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, title TEXT, created TEXT)")
    cols=[row[1] for row in con.execute("PRAGMA table_info(chats)").fetchall()]
    if "archived" not in cols: con.execute("ALTER TABLE chats ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    con.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT, content TEXT, created TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS knowledge (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT, created TEXT)")
    n=con.execute("SELECT count(*) FROM chats").fetchone()[0]
    if not n: con.execute("INSERT INTO chats (id, title, created) VALUES(?,?,?)", (str(uuid.uuid4()),"Neuer Chat",datetime.now().isoformat()))
    con.commit(); con.close()

def dball(sql,args=(),fetch=True):
    con=sqlite3.connect(DB); cur=con.execute(sql,args)
    result=cur.fetchall() if fetch else None
    con.commit(); con.close(); return result

def extract_file(path):
    p=Path(path); ext=p.suffix.lower()
    if p.stat().st_size > 25*1024*1024:
        raise ValueError("Datei ist größer als 25 MB.")
    if ext in (".png",".jpg",".jpeg",".webp",".gif"):
        mime=mimetypes.guess_type(str(p))[0] or "image/png"
        if p.stat().st_size > 12*1024*1024: raise ValueError("Bild ist größer als 12 MB.")
        return {"image":f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}", "text":f"[Bild angehängt: {p.name}]"}
    if ext == ".pdf":
        proc=subprocess.run(["pdftotext","-layout",str(p),"-"],capture_output=True,text=True,timeout=20)
        if proc.returncode == 0: return {"text":f"[PDF: {p.name}]\n{proc.stdout[:60000]}"}
        raise ValueError("PDF-Text konnte nicht gelesen werden. Bitte installiere poppler-utils.")
    if ext in (".txt",".md",".py",".js",".json",".html",".css",".xml",".csv",".ini",".log",".sh",".c",".cpp",".h",".yml",".yaml",".toml",".sql"):
        return {"text":f"[Datei: {p.name}]\n{p.read_text(errors='replace')[:60000]}"}
    if ext == ".zip":
        import zipfile
        chunks=[f"[ZIP-Archiv: {p.name}]"]
        try:
            with zipfile.ZipFile(p) as archive:
                members=[m for m in archive.infolist() if not m.is_dir()]
                chunks.append(f"Dateien im Archiv: {len(members)}")
                for m in members[:300]:
                    chunks.append(f"- {m.filename} ({m.file_size} Bytes)")
                allowed={".txt",".md",".py",".js",".json",".html",".css",".xml",".csv",".ini",".log",".sh",".c",".cpp",".h",".yml",".yaml",".toml",".sql"}
                total=0
                for m in members:
                    if Path(m.filename).suffix.lower() not in allowed or m.file_size > 180000 or total >= 220000:
                        continue
                    try:
                        data=archive.read(m)
                        text=data.decode("utf-8",errors="replace")
                        text=text[:max(0,220000-total)]
                        if text:
                            chunks.append(f"\n--- DATEIINHALT: {m.filename} ---\n{text}\n--- ENDE DATEI ---")
                            total += len(text)
                    except Exception:
                        pass
        except Exception as e:
            raise ValueError(f"ZIP-Archiv konnte nicht gelesen werden: {e}")
        return {"text":"\n".join(chunks)[:250000]}
    if ext == ".deb":
        # Metadaten und relevante Text-/Quellcodedateien lesen, ohne das Paket zu installieren.
        info=subprocess.run(["dpkg-deb","-I",str(p)],capture_output=True,text=True,timeout=15)
        listing=subprocess.run(["dpkg-deb","-c",str(p)],capture_output=True,text=True,timeout=20)
        if info.returncode != 0 or listing.returncode != 0:
            raise ValueError("Debian-Paket konnte nicht gelesen werden. Bitte prüfe, ob dpkg-deb installiert ist.")
        chunks=[f"[Debian-Paket: {p.name}]\nPaketinformationen:\n{info.stdout[:12000]}\nDateiliste:\n{listing.stdout[:22000]}"]
        # Do not unpack unexpectedly huge packages.
        sizes=[]
        for line in listing.stdout.splitlines():
            m=re.match(r"^\S+\s+\S+\s+(\d+)\s+\S+\s+\S+\s+(.+)$", line)
            if m: sizes.append(int(m.group(1)))
        if sum(sizes) <= 100*1024*1024:
            try:
                with tempfile.TemporaryDirectory(prefix="lunagpt-deb-read-") as tmp:
                    extracted=subprocess.run(["dpkg-deb","-x",str(p),tmp],capture_output=True,text=True,timeout=30)
                    if extracted.returncode == 0:
                        allowed={".txt",".md",".py",".js",".json",".html",".css",".xml",".csv",".ini",".log",".sh",".c",".cpp",".h",".yml",".yaml",".toml",".sql"}
                        total=0
                        for file in sorted(Path(tmp).rglob("*")):
                            if not file.is_file() or file.suffix.lower() not in allowed or file.stat().st_size > 180000 or total >= 180000:
                                continue
                            try:
                                text=file.read_text(errors="replace")[:max(0,180000-total)]
                                if text:
                                    rel=file.relative_to(tmp)
                                    chunks.append(f"\n--- DATEIINHALT AUS DEB: {rel} ---\n{text}\n--- ENDE DATEI ---")
                                    total += len(text)
                            except Exception:
                                pass
            except Exception as e:
                chunks.append(f"\nHinweis: Quelltext aus dem Paket konnte nicht zusätzlich gelesen werden: {e}")
        else:
            chunks.append("\nHinweis: Das entpackte Paket wäre größer als 100 MB; aus Sicherheitsgründen wurde nur die Dateiliste übernommen.")
        chunks.append("\nHinweis: Das Paket wurde nicht installiert oder ausgeführt.")
        return {"text":"\n".join(chunks)[:250000]}
    raise ValueError("Dieses Dateiformat wird nicht unterstützt. Unterstützt: Bilder, PDF, TXT/MD/Code/JSON/CSV, ZIP-Archive und Debian-Pakete (.deb).")

def api_request(key, model, messages, use_web=False):
    content=[]
    for m in messages:
        role=m["role"]
        if role=="system": content.append({"role":"system","content":m["content"]})
        else: content.append({"role":role,"content":m["content"]})
    payload={"model":model,"input":content}
    if use_web: payload["tools"]=[{"type":"web_search"}]
    req=urllib.request.Request("https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode(), headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req,timeout=150) as r: data=json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body=e.read().decode(errors="replace")
        try: msg=json.loads(body).get("error",{}).get("message",body)
        except Exception: msg=body
        raise RuntimeError(f"OpenAI API HTTP {e.code}: {msg[:900]}")
    except Exception as e: raise RuntimeError(str(e))
    chunks=[]
    for item in data.get("output",[]):
        if item.get("type")=="message":
            for part in item.get("content",[]):
                if part.get("type")=="output_text": chunks.append(part.get("text",""))
    return "\n".join(chunks).strip() or "(Keine Textantwort erhalten.)"

# Werkzeuge, die die KI bei ausdrücklich passenden Aufgaben selbst aufrufen kann.
AGENT_TOOLS = [
 {"type":"function","name":"list_attachments","description":"Zeigt Namen und Typ der aktuell angehängten Dateien.","parameters":{"type":"object","properties":{},"additionalProperties":False}},
 {"type":"function","name":"read_attachment","description":"Liest den verfügbaren Textinhalt eines angehängten Textdokuments, ZIP-Archivs oder Debian-Pakets. Für ZIP-Dateien kann ein interner Dateiname angegeben werden.","parameters":{"type":"object","properties":{"name":{"type":"string","description":"Exakter Name des Anhangs"},"member":{"type":"string","description":"Optionaler Pfad einer Datei innerhalb eines ZIP-Archivs"}},"required":["name"],"additionalProperties":False}},
 {"type":"function","name":"copy_attachment_to_workspace","description":"Kopiert einen angehängten Originaldatei-Binärinhalt unverändert in den Arbeitsbereich. Verwende dies, um vollständige ZIP- und DEB-Dateien in ein Projekt aufzunehmen.","parameters":{"type":"object","properties":{"name":{"type":"string","description":"Exakter Name des Anhangs"},"destination":{"type":"string","description":"Zielpfad relativ zum Arbeitsbereich"}},"required":["name","destination"],"additionalProperties":False}},
 {"type":"function","name":"extract_attachment_to_workspace","description":"Entpackt ein angehängtes ZIP-Quellarchiv sicher in einen Unterordner des Arbeitsbereichs oder extrahiert den Inhalt eines Debian-Pakets (.deb), ohne es zu installieren oder auszuführen. Nutze dies, um echten Quellcode zu übernehmen, nicht nur Dokumente zu schreiben.","parameters":{"type":"object","properties":{"name":{"type":"string","description":"Exakter Name des ZIP- oder DEB-Anhangs"},"destination":{"type":"string","description":"Zielordner relativ zum Arbeitsbereich"}},"required":["name","destination"],"additionalProperties":False}},
 {"type":"function","name":"list_workspace_files","description":"Listet die bisher im Arbeitsbereich erstellten Dateien auf.","parameters":{"type":"object","properties":{},"additionalProperties":False}},
 {"type":"function","name":"write_workspace_file","description":"Erstellt oder aktualisiert eine Datei im LunaGPT-Arbeitsbereich. Verwende relative Pfade, z.B. Projekt/README.md.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"],"additionalProperties":False}},
 {"type":"function","name":"set_workspace_executable","description":"Setzt bei einer ausdrücklich angeforderten Projektaufgabe das Ausführungsrecht für ein vorhandenes Shell-Skript im LunaGPT-Arbeitsbereich. Nur Dateien mit der Endung .sh innerhalb des Arbeitsbereichs sind erlaubt; es werden keine Dateien außerhalb des Arbeitsbereichs verändert.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"Relativer Pfad zu einer vorhandenen .sh-Datei im Arbeitsbereich"}},"required":["path"],"additionalProperties":False}},
 {"type":"function","name":"create_zip","description":"Packt ein Projektverzeichnis oder ausgewählte Dateien aus dem LunaGPT-Arbeitsbereich in eine ZIP-Datei. Der Ausgabe-ZIP-Pfad ist relativ zum Arbeitsbereich.","parameters":{"type":"object","properties":{"output":{"type":"string"},"paths":{"type":"array","items":{"type":"string"},"description":"Zu packende Dateien/Verzeichnisse, relativ zum Arbeitsbereich"},"top_level_folder":{"type":"string","description":"Optionaler Ordnername, unter dem die Inhalte im ZIP liegen"}},"required":["output","paths"],"additionalProperties":False}},
 {"type":"function","name":"run_workspace_command","description":"Führt einen begrenzten Build- oder Testbefehl im Arbeitsbereich aus. Kein Shell-Parsing, keine Pipes, Umleitungen oder sudo. Ein vorhandenes build_deb.sh darf auch in einem Projekt-Unterordner ausgeführt werden; das Skript läuft dann in seinem eigenen Projektordner. Zulässig sind Python-Syntaxprüfung, dpkg-deb, zip/unzip-Prüfung und vorhandene Buildskripte.","parameters":{"type":"object","properties":{"command":{"type":"string","description":"Ein einzelner Befehl, z.B. python3 -m py_compile Projekt/lunagpt/main.py, ./Projekt/build_deb.sh oder dpkg-deb --info Projekt/dist/lunagpt.deb"}},"required":["command"],"additionalProperties":False}}
 ,{"type":"function","name":"prepare_github_release","description":"Bereitet nach ausdrücklichem Nutzerauftrag ein sauberes GitHub-Repository und ein separates, neu gebautes DEB vor; unterstützt sowohl LunaGPT-Repositories als auch normale Testprojekte mit main.py im Projektstamm; die Ausgabe wird als zwei einzelne Dateien im release/-Ordner abgelegt, nicht als Gesamtarchiv des Arbeitsbereichs. Entfernt nur generierte build/dist/Cache-Dateien innerhalb des angegebenen Projektordners, führt build_deb.sh aus, prüft Syntax und Paketversion, erstellt eine saubere Repository-ZIP ohne alte DEBs/Builddateien und kopiert das neu gebaute DEB als separates Ergebnis. Der Ausgabeordner release/ enthält danach ausschließlich die aktuelle GitHub-ZIP und das dazugehörige DEB; alte Release-Ausgaben werden vorab entfernt. Verwende dies bei Aufträgen wie 'GitHub-fertig machen, saubere ZIP und DEB geben'. Es lädt nichts zu GitHub hoch.","parameters":{"type":"object","properties":{"project":{"type":"string","description":"Relativer Pfad zum entpackten Projektordner im Arbeitsbereich"},"version":{"type":"string","description":"Erwartete Versionsnummer, z.B. 1.7.4"},"zip_name":{"type":"string","description":"Dateiname der Repository-ZIP, z.B. LunaGPT-1.7.4-GitHub.zip"}},"required":["project","version","zip_name"],"additionalProperties":False}}

]

class AgentTools:
    def __init__(self, attachments, chat_id=None):
        self.attachments = list(attachments or [])
        base = Path.home() / "Documents" / "LunaGPT-Arbeitsbereich"
        # Workspace is stable per chat, so a follow-up can continue prior file work.
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(chat_id or ""))[:80]
        if not safe_id:
            safe_id = "legacy-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.root = (base / ("Chat-" + safe_id)).resolve()
        # Create the folder lazily only when a file tool is used.

    def _safe(self, rel):
        rel = str(rel or "").strip()
        if not rel or Path(rel).is_absolute(): raise ValueError("Bitte einen relativen Dateipfad verwenden.")
        target=(self.root / rel).resolve()
        if target != self.root and self.root not in target.parents: raise ValueError("Pfad außerhalb des Arbeitsbereichs ist nicht erlaubt.")
        self.root.mkdir(parents=True, exist_ok=True)
        return target

    def call(self, name, args):
        if name == "list_attachments":
            return {"attachments":[{"name":a.get("name","Datei"),"path":a.get("path",""),"has_extracted_text":bool(a.get("text")),"is_image":bool(a.get("image"))} for a in self.attachments]}
        if name == "read_attachment":
            wanted=str(args.get("name","")); a=next((x for x in self.attachments if x.get("name")==wanted),None)
            if not a: return {"error":f"Anhang nicht gefunden: {wanted}"}
            path=Path(a.get("path","")) if a.get("path") else None
            member=args.get("member")
            if path and path.is_file() and path.suffix.lower()==".zip" and member:
                with zipfile.ZipFile(path) as z:
                    info=z.getinfo(member)
                    if info.file_size>500000: return {"error":"Datei im ZIP ist größer als 500 KB."}
                    data=z.read(member)
                return {"name":wanted,"member":member,"content":data.decode("utf-8",errors="replace")[:500000]}
            if path and path.is_file() and path.suffix.lower()==".zip":
                with zipfile.ZipFile(path) as z:
                    return {"name":wanted,"members":[{"name":i.filename,"size":i.file_size} for i in z.infolist()[:1000] if not i.is_dir()]}
            if a.get("text"): return {"name":wanted,"content":a["text"][:250000]}
            return {"name":wanted,"note":"Für diesen Anhang steht kein extrahierter Text zur Verfügung."}
        if name == "copy_attachment_to_workspace":
            wanted=str(args.get("name", "")); a=next((x for x in self.attachments if x.get("name")==wanted),None)
            if not a: return {"error":f"Anhang nicht gefunden: {wanted}"}
            source=Path(a.get("path", "")) if a.get("path") else None
            if not source or not source.is_file(): return {"error":"Die Originaldatei ist lokal nicht verfügbar; Kopieren ist nicht möglich."}
            target=self._safe(args.get("destination")); target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
            return {"copied":str(target.relative_to(self.root)),"bytes":target.stat().st_size,"workspace":str(self.root)}
        if name == "extract_attachment_to_workspace":
            wanted=str(args.get("name", "")); a=next((x for x in self.attachments if x.get("name")==wanted),None)
            if not a: return {"error":f"Anhang nicht gefunden: {wanted}"}
            source=Path(a.get("path", "")) if a.get("path") else None
            if not source or not source.is_file(): return {"error":"Die Originaldatei ist lokal nicht verfügbar; Extrahieren ist nicht möglich."}
            target=self._safe(args.get("destination")); target.mkdir(parents=True,exist_ok=True)
            ext=source.suffix.lower(); count=0; total=0
            if ext == ".zip":
                with zipfile.ZipFile(source) as z:
                    members=[m for m in z.infolist() if not m.is_dir()]
                    if len(members)>5000: raise ValueError("Archiv enthält mehr als 5000 Dateien; aus Sicherheitsgründen abgebrochen.")
                    for info in members:
                        rel=Path(info.filename)
                        if rel.is_absolute() or ".." in rel.parts: raise ValueError("Unsicherer Pfad im ZIP-Archiv erkannt.")
                        if info.file_size>50*1024*1024: raise ValueError(f"Datei im Archiv zu groß: {info.filename}")
                        total += info.file_size
                        if total>300*1024*1024: raise ValueError("Archiv überschreitet das Entpack-Limit von 300 MB.")
                        out=(target/rel).resolve()
                        if target.resolve() not in out.parents and out != target.resolve(): raise ValueError("Unsicherer Zielpfad im Archiv erkannt.")
                        out.parent.mkdir(parents=True,exist_ok=True)
                        with z.open(info) as src, out.open("wb") as dst: shutil.copyfileobj(src,dst)
                        # Restore Unix permission bits from the ZIP entry. Writing the
                        # file contents alone silently turns executable scripts into 0644.
                        if info.create_system == 3:
                            archived_mode=(info.external_attr >> 16) & 0o777
                            if archived_mode:
                                out.chmod(archived_mode)
                        count += 1
            elif ext == ".deb":
                if shutil.which("dpkg-deb") is None: raise ValueError("dpkg-deb ist nicht installiert.")
                proc=subprocess.run(["dpkg-deb","-x",str(source),str(target)],capture_output=True,text=True,timeout=60)
                if proc.returncode: raise ValueError("DEB konnte nicht extrahiert werden: "+(proc.stderr or proc.stdout)[:500])
                count=sum(1 for x in target.rglob("*") if x.is_file())
                total=sum(x.stat().st_size for x in target.rglob("*") if x.is_file())
            else: raise ValueError("Nur ZIP- und DEB-Anhänge können hier extrahiert werden.")
            return {"extracted_to":str(target.relative_to(self.root)),"files":count,"bytes":total,"workspace":str(self.root),"note":"Dateien wurden nur extrahiert, nicht installiert oder ausgeführt."}
        if name == "list_workspace_files":
            if not self.root.exists():
                return {"workspace":str(self.root),"files":[]}
            return {"workspace":str(self.root),"files":[str(x.relative_to(self.root)) for x in sorted(self.root.rglob('*')) if x.is_file()]}
        if name == "write_workspace_file":
            target=self._safe(args.get("path")); content=args.get("content","")
            if not isinstance(content,str): raise ValueError("Dateiinhalt muss Text sein.")
            if len(content)>2_000_000: raise ValueError("Einzeldateien sind auf 2 MB begrenzt.")
            target.parent.mkdir(parents=True,exist_ok=True); target.write_text(content,encoding="utf-8")
            return {"created":str(target.relative_to(self.root)),"bytes":target.stat().st_size,"workspace":str(self.root)}
        if name == "run_workspace_command":
            command=str(args.get("command", "")).strip()
            if not command or len(command)>1000: raise ValueError("Befehl fehlt oder ist zu lang.")
            if any(x in command for x in ("|", ";", "&&", "||", ">", "<", "`", "$(", "\n", "\r")):
                raise ValueError("Nur ein einzelner Befehl ohne Shell-Operatoren ist erlaubt.")
            parts=shlex.split(command)
            if not parts: raise ValueError("Leerer Befehl.")
            executable=parts[0]
            allowed=("python3", "dpkg-deb", "zip", "unzip")
            script_path = None
            command_cwd = self.root
            is_build_script = executable.endswith("build_deb.sh") and not Path(executable).is_absolute()
            if executable not in allowed and not is_build_script:
                raise ValueError("Dieser Befehl ist nicht freigegeben. Zulässig: python3, dpkg-deb, zip, unzip oder ein vorhandenes build_deb.sh innerhalb des Arbeitsbereichs.")
            if is_build_script:
                if len(parts)!=1 or ".." in Path(executable).parts:
                    raise ValueError("Ein Buildskript darf ohne Zusatzargumente nur über einen sicheren relativen Pfad aufgerufen werden.")
                script=(self.root/executable).resolve()
                if self.root not in script.parents or not script.is_file() or script.name != "build_deb.sh":
                    raise ValueError("Das angegebene build_deb.sh muss im Arbeitsbereich vorhanden sein.")
                # Skripte dürfen nur den eigenen Projektordner als Arbeitsverzeichnis verwenden.
                command_cwd=script.parent
                if not (script.stat().st_mode & 0o100):
                    raise ValueError("build_deb.sh hat kein Ausführungsrecht. Bitte die Projektdatei bzw. ZIP korrekt erstellen; das Werkzeug repariert Rechte nicht automatisch.")
                parts=[str(script)]
            elif executable == "python3":
                # Syntax checks and explicit, no-argument execution of a Python file
                # inside this chat's workspace are permitted. Never allow -c, stdin,
                # arbitrary interpreter switches, or paths outside the workspace.
                if len(parts) >= 4 and parts[1:3] == ["-m", "py_compile"]:
                    py_args=parts[3:]
                    if not py_args: raise ValueError("Bitte mindestens eine Python-Datei zur Syntaxprüfung angeben.")
                    for arg in py_args:
                        candidate=(self.root/arg).resolve()
                        if Path(arg).is_absolute() or (candidate!=self.root and self.root not in candidate.parents) or not candidate.is_file() or candidate.suffix != ".py":
                            raise ValueError("Syntaxprüfung darf nur vorhandene .py-Dateien innerhalb des Arbeitsbereichs prüfen.")
                elif len(parts) == 2 and not parts[1].startswith("-"):
                    candidate=(self.root/parts[1]).resolve()
                    if Path(parts[1]).is_absolute() or self.root not in candidate.parents or not candidate.is_file() or candidate.suffix != ".py":
                        raise ValueError("Python-Programmstart ist nur für eine vorhandene .py-Datei innerhalb des Arbeitsbereichs freigegeben.")
                else:
                    raise ValueError("python3 ist nur für Syntaxprüfungen oder den explizit angeforderten Start einer vorhandenen .py-Datei im Arbeitsbereich freigegeben.")
            elif executable == "dpkg-deb":
                # Read-only inspection plus a build into the workspace are supported.
                if len(parts)==3 and parts[1] in ("--info", "--contents"):
                    target=(self.root/parts[2]).resolve()
                    if Path(parts[2]).is_absolute() or self.root not in target.parents or not target.is_file():
                        raise ValueError("dpkg-deb darf nur Dateien innerhalb des Arbeitsbereichs prüfen.")
                elif len(parts) in (4,5) and parts[1:3] == ["--build", "--root-owner-group"]:
                    target=(self.root/parts[3]).resolve()
                    if Path(parts[3]).is_absolute() or self.root not in target.parents or not target.is_dir():
                        raise ValueError("dpkg-deb darf nur einen Build-Ordner innerhalb des Arbeitsbereichs paketieren.")
                    if len(parts)==5:
                        output=(self.root/parts[4]).resolve()
                        if Path(parts[4]).is_absolute() or self.root not in output.parents:
                            raise ValueError("DEB-Ausgabepfad muss innerhalb des Arbeitsbereichs liegen.")
                elif len(parts) in (3,4) and parts[1] == "--build":
                    target=(self.root/parts[2]).resolve()
                    if Path(parts[2]).is_absolute() or self.root not in target.parents or not target.is_dir():
                        raise ValueError("dpkg-deb darf nur einen Build-Ordner innerhalb des Arbeitsbereichs paketieren.")
                    if len(parts)==4:
                        output=(self.root/parts[3]).resolve()
                        if Path(parts[3]).is_absolute() or self.root not in output.parents:
                            raise ValueError("DEB-Ausgabepfad muss innerhalb des Arbeitsbereichs liegen.")
                else:
                    raise ValueError("dpkg-deb ist nur für --info, --contents oder --build innerhalb des Arbeitsbereichs freigegeben.")
            elif executable in ("zip", "unzip"):
                if any(Path(a).is_absolute() or ".." in Path(a).parts for a in parts[1:] if not a.startswith("-")):
                    raise ValueError("ZIP-Befehle dürfen nur relative Pfade im Arbeitsbereich verwenden.")
                if executable == "unzip":
                    # Support normal extraction only when both the archive and target
                    # are within the workspace; no overwrite confirmation can hang.
                    archive_args=[a for a in parts[1:] if not a.startswith("-")]
                    for a in archive_args:
                        candidate=(self.root/a).resolve()
                        if self.root not in candidate.parents or (candidate.suffix.lower()==".zip" and not candidate.is_file()):
                            raise ValueError("unzip darf nur ZIP-Dateien und Ziele innerhalb des Arbeitsbereichs verwenden.")
            # Kommandos laufen nur im aktuellen Projekt-Arbeitsordner und mit Zeit-/Ausgabelimit.
            self.root.mkdir(parents=True, exist_ok=True)
            proc=subprocess.run(parts, cwd=str(command_cwd), capture_output=True, text=True, timeout=300,
                                env={"PATH":os.environ.get("PATH","/usr/bin:/bin"),"HOME":str(self.root),"LANG":"C.UTF-8","LC_ALL":"C.UTF-8"})
            out=(proc.stdout or "")[-12000:]; err=(proc.stderr or "")[-12000:]
            return {"command":command,"returncode":proc.returncode,"success":proc.returncode==0,"stdout":out,"stderr":err,"workspace":str(self.root),"working_directory":str(command_cwd)}
        if name == "set_workspace_executable":
            target=self._safe(args.get("path"))
            if target.suffix != ".sh" or not target.is_file():
                raise ValueError("Nur eine vorhandene .sh-Datei im Arbeitsbereich darf ausführbar gemacht werden.")
            if target.resolve() == self.root or self.root not in target.resolve().parents:
                raise ValueError("Datei muss innerhalb des Arbeitsbereichs liegen.")
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            mode=stat.S_IMODE(target.stat().st_mode)
            return {"path":str(target.relative_to(self.root)),"mode":format(mode,"04o"),"executable":bool(mode & stat.S_IXUSR),"workspace":str(self.root)}
        if name == "create_zip":
            output=self._safe(args.get("output")); paths=args.get("paths") or []
            if not paths: raise ValueError("Bitte mindestens eine Datei oder einen Ordner zum Packen angeben.")
            output.parent.mkdir(parents=True,exist_ok=True); top=str(args.get("top_level_folder") or "").strip().strip('/')
            count=0
            with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as z:
                for rel in paths:
                    src=self._safe(rel)
                    if not src.exists(): raise ValueError(f"Datei/Ordner nicht gefunden: {rel}")
                    candidates=[src] if src.is_file() else sorted(x for x in src.rglob('*') if x.is_file())
                    for file in candidates:
                        if file == output: continue
                        arc=Path(top)/file.relative_to(src.parent if src.is_file() else src) if top else (Path(rel)/file.relative_to(src) if src.is_dir() else Path(rel))
                        # Store POSIX permission bits explicitly; ZipFile.write() can
                        # otherwise produce entries without usable executable bits.
                        info=zipfile.ZipInfo.from_file(file, arc.as_posix())
                        info.compress_type=zipfile.ZIP_DEFLATED
                        info.external_attr=(stat.S_IMODE(file.stat().st_mode) & 0xFFFF) << 16
                        with file.open("rb") as source:
                            z.writestr(info, source.read())
                        count+=1
            return {"created":str(output),"workspace":str(self.root),"files_packed":count,"bytes":output.stat().st_size}
        if name == "prepare_github_release":
            rel=str(args.get("project", "")).strip()
            project=self._safe(rel)
            if not project.is_dir(): raise ValueError("Projektordner nicht gefunden.")
            version=str(args.get("version", "")).strip()
            if not re.fullmatch(r"\d+\.\d+\.\d+", version): raise ValueError("Versionsnummer muss z.B. 1.7.4 lauten.")
            if not (project/"build_deb.sh").is_file(): raise ValueError("Im Projektordner fehlt build_deb.sh.")
            # Support both the full LunaGPT repository and ordinary test projects.
            # Full LunaGPT projects require consistent app-version references; generic
            # projects are validated against the resulting Debian metadata instead.
            is_lunagpt_project=(project/"lunagpt"/"main.py").is_file()
            if not is_lunagpt_project and not (project/"main.py").is_file():
                raise ValueError("Weder lunagpt/main.py noch main.py im Projektstamm gefunden.")
            if is_lunagpt_project:
                version_files=[project/"lunagpt"/"__init__.py", project/"lunagpt"/"main.py", project/"debian"/"control", project/"build_deb.sh"]
                missing=[str(x.relative_to(project)) for x in version_files if not x.is_file()]
                if missing: raise ValueError("Versionsdateien fehlen: "+", ".join(missing))
                for vf in version_files:
                    txt=vf.read_text(errors="replace")
                    if version not in txt: raise ValueError(f"Versionsprüfung fehlgeschlagen: {vf.relative_to(project)} enthält nicht {version}. Bitte Quellcode/Metadaten zuerst konsistent aktualisieren.")
            # Drop only reproducible local build products/caches inside the selected project.
            for folder in ("build", "dist", "__pycache__"):
                target=project/folder
                if target.exists(): shutil.rmtree(target)
            for cache in project.rglob("__pycache__"):
                if cache.is_dir(): shutil.rmtree(cache, ignore_errors=True)
            for pyc in project.rglob("*.pyc"):
                try: pyc.unlink()
                except OSError: pass
            # Syntax-check source before invoking the project build script.
            pyfiles=[str(x) for x in project.rglob("*.py") if "build" not in x.parts and ".git" not in x.parts]
            if not pyfiles: raise ValueError("Keine Python-Dateien für Syntaxprüfung gefunden.")
            check=subprocess.run(["python3","-m","py_compile",*pyfiles],cwd=str(project),capture_output=True,text=True,timeout=90)
            if check.returncode: raise ValueError("Python-Syntaxprüfung fehlgeschlagen: "+(check.stderr or check.stdout)[-3000:])
            build_script=project/"build_deb.sh"
            if not (build_script.stat().st_mode & 0o100):
                raise ValueError("build_deb.sh ist im Quellprojekt nicht ausführbar. Bitte die Quelldatei korrekt mit Ausführungsrecht bereitstellen; LunaGPT repariert Dateirechte nicht stillschweigend.")
            env={"PATH":os.environ.get("PATH","/usr/bin:/bin"),"HOME":str(self.root),"LANG":"C.UTF-8","LC_ALL":"C.UTF-8"}
            build=subprocess.run([str(build_script)],cwd=str(project),capture_output=True,text=True,timeout=300,env=env)
            if build.returncode: raise ValueError("DEB-Build fehlgeschlagen (Exit "+str(build.returncode)+"): "+(build.stderr or build.stdout)[-5000:])
            # Build scripts differ: LunaGPT writes to dist/, while the fixed
            # Standard-Release-Test intentionally writes the DEB into the project root.
            # Search the selected project after cleaning old build outputs, but ignore
            # package staging trees so only the actual deliverable is considered.
            debs=sorted(d for d in project.rglob("*.deb") if not any(part in {"build", ".git"} for part in d.relative_to(project).parts))
            expected=[d for d in debs if version in d.name]
            if len(expected)!=1: raise ValueError(f"Erwartete genau ein DEB für Version {version}, gefunden: {[str(d.relative_to(project)) for d in debs]}")
            deb=expected[0]
            def read_deb_field(package, field):
                result=subprocess.run(["dpkg-deb","-f",str(package),field],capture_output=True,text=True,timeout=20)
                if result.returncode:
                    raise ValueError(f"DEB-Metadatenfeld {field} konnte nicht gelesen werden: {(result.stderr or result.stdout).strip()}")
                # dpkg-deb normally prints only the value. Also tolerate tools/wrappers
                # that prefix the field label, preventing a valid package from failing.
                value=result.stdout.strip()
                prefix=field+":"
                if value.lower().startswith(prefix.lower()): value=value[len(prefix):].strip()
                return value
            deb_version=read_deb_field(deb,"Version")
            deb_arch=read_deb_field(deb,"Architecture")
            if deb_version!=version: raise ValueError("DEB-Metadaten stimmen nicht mit Version "+version+" überein: "+deb_version)
            if deb_arch!="all": raise ValueError("DEB-Architektur muss all sein, gefunden: "+deb_arch)
            # Keep repository ZIP clean and put the DEB beside it as a separate deliverable.
            zip_name=Path(str(args.get("zip_name", ""))).name
            if not zip_name.lower().endswith(".zip"): raise ValueError("zip_name muss auf .zip enden.")
            release_dir=self._safe("release")
            release_dir.mkdir(parents=True,exist_ok=True)
            # Keep the release deliverable folder clean: remove only files directly
            # inside release/, never project sources or arbitrary workspace folders.
            for old in release_dir.iterdir():
                if old.is_file() or old.is_symlink():
                    old.unlink()
                elif old.is_dir():
                    shutil.rmtree(old)
            output=release_dir/zip_name
            deb_out=release_dir/deb.name
            excludes={".git","build","dist","__pycache__",".venv","venv"}
            count=0
            with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as z:
                for file in sorted(project.rglob("*")):
                    if not file.is_file(): continue
                    relpath=file.relative_to(project)
                    if any(part in excludes for part in relpath.parts) or file.suffix==".pyc" or file.suffix==".deb": continue
                    arcname=(project.name/relpath).as_posix()
                    # Preserve POSIX mode bits in the archive. ZIP's default write()
                    # does not reliably preserve executable permissions across platforms.
                    info=zipfile.ZipInfo.from_file(file, arcname)
                    mode=stat.S_IMODE(file.stat().st_mode)
                    info.external_attr=(mode & 0xFFFF) << 16
                    info.compress_type=zipfile.ZIP_DEFLATED
                    with file.open("rb") as source:
                        z.writestr(info, source.read())
                    count+=1
            with zipfile.ZipFile(output) as z:
                bad=z.testzip()
                if bad: raise ValueError("Repository-ZIP ist beschädigt: "+bad)
            contents=subprocess.run(["dpkg-deb","--contents",str(deb)],capture_output=True,text=True,timeout=20)
            if contents.returncode: raise ValueError("Das gebaute DEB lässt sich nicht lesen.")
            # Verify the deliverable, not merely the source folder: unpack the exact
            # repository ZIP into a fresh temporary directory and build from there.
            with tempfile.TemporaryDirectory(prefix="lunagpt-release-verify-") as verify_tmp:
                verify_root=Path(verify_tmp)
                with zipfile.ZipFile(output) as z:
                    names=z.namelist()
                    bad=z.testzip()
                    if bad: raise ValueError("Repository-ZIP ist beschädigt: "+bad)
                    roots={n.split("/",1)[0] for n in names if n.strip("/")}
                    if roots != {project.name}: raise ValueError("ZIP muss genau einen obersten Projektordner namens "+project.name+" enthalten; gefunden: "+repr(sorted(roots)))
                    forbidden={"build","dist","__pycache__",".venv","venv",".git"}
                    dirty=[n for n in names if any(part in forbidden for part in Path(n).parts) or n.endswith((".pyc",".deb"))]
                    if dirty: raise ValueError("ZIP enthält unerlaubte Build-/Cache-/DEB-Dateien: "+", ".join(dirty[:20]))
                # Use the platform unzip utility for a realistic fresh extraction; Python's
                # ZipFile.extractall() does not restore Unix executable permission bits.
                unzip_proc=subprocess.run(["unzip","-q",str(output),"-d",str(verify_root)],capture_output=True,text=True,timeout=60)
                if unzip_proc.returncode: raise ValueError("Frisches Entpacken der GitHub-ZIP fehlgeschlagen: "+(unzip_proc.stderr or unzip_proc.stdout)[-2000:])
                unpacked=verify_root/project.name
                if not (unpacked/"build_deb.sh").is_file(): raise ValueError("In der fertigen ZIP fehlt build_deb.sh.")
                expected_main=(unpacked/"lunagpt"/"main.py") if is_lunagpt_project else (unpacked/"main.py")
                if not expected_main.is_file(): raise ValueError("In der fertigen ZIP fehlt der erwartete Programm-Einstiegspunkt: "+str(expected_main.relative_to(unpacked)))
                # Do not chmod the extracted script here: that would mask a broken ZIP.
                script_mode=(unpacked/"build_deb.sh").stat().st_mode
                if not (script_mode & 0o100): raise ValueError("GitHub-ZIP verliert das Ausführungsrecht von build_deb.sh; Release abgebrochen.")
                verify_build=subprocess.run([str(unpacked/"build_deb.sh")],cwd=str(unpacked),capture_output=True,text=True,timeout=300,env=env)
                if verify_build.returncode: raise ValueError("Build aus frisch entpackter GitHub-ZIP fehlgeschlagen: "+(verify_build.stderr or verify_build.stdout)[-4000:])
                verify_debs=sorted(d for d in unpacked.rglob("*.deb") if not any(part in {"build", ".git"} for part in d.relative_to(unpacked).parts))
                if len(verify_debs)!=1: raise ValueError("Build aus ZIP muss genau ein DEB erzeugen; gefunden: "+repr([str(d.relative_to(unpacked)) for d in verify_debs]))
                verify_version=read_deb_field(verify_debs[0],"Version")
                verify_arch=read_deb_field(verify_debs[0],"Architecture")
                if verify_version != version or verify_arch != "all":
                    raise ValueError("DEB aus ZIP hat falsche Metadaten: Version="+verify_version+", Architecture="+verify_arch)
                # Deliver the DEB rebuilt from the exact, freshly extracted ZIP,
                # not merely the first build from the working source directory.
                shutil.copy2(verify_debs[0], deb_out)
            # The output directory must contain exactly these two deliverables.
            expected_outputs={output.name,deb_out.name}
            actual_outputs={x.name for x in release_dir.iterdir() if x.is_file()}
            if actual_outputs != expected_outputs:
                raise ValueError("Release-Ordner enthält unerwartete Dateien: "+repr(sorted(actual_outputs)))
            return {"success":True,"version":version,"repository_zip":str(output),"deb":str(deb_out),"repository_files":count,"zip_bytes":output.stat().st_size,"deb_bytes":deb_out.stat().st_size,"deb_version":deb_version,"python_files_syntax_checked":len(pyfiles),"zip_integrity":"ok","zip_structure":"ok","clean_zip_rebuild":"ok","rebuilt_deb_metadata":"version "+version+", architecture all","deb_metadata":"ok","build_stdout":build.stdout[-2500:],"workspace":str(self.root),"github_uploaded":False}
        raise ValueError("Unbekanntes Werkzeug")

def _response_json(url, token, model, conversation, use_web=False):
    # Die verwendete Responses-API erwartet hier einen SSE-Stream. Ohne stream=true
    # antwortet der Dienst mit HTTP 400: "Stream must be set to true".
    payload={"model":model,"input":conversation,"tools":AGENT_TOOLS,"tool_choice":"auto","store":False,"stream":True}
    if use_web: payload["tools"] += [{"type":"web_search"}]
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json","Accept":"text/event-stream"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=180) as r:
            completed=None
            stream_error=None
            output_items=[]
            text_deltas=[]
            # SSE kann neben dem abschließenden response.completed auch einzelne
            # Text-Deltas und fertige Output-Items liefern. Sammle sie robust ein,
            # damit eine gültige Antwort nicht als leer verworfen wird.
            for raw in r:
                line=raw.decode("utf-8",errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                datum=line[5:].strip()
                if not datum or datum == "[DONE]":
                    continue
                try:
                    event=json.loads(datum)
                except json.JSONDecodeError:
                    continue
                event_type=event.get("type","")
                if event_type == "response.output_text.delta":
                    delta=event.get("delta","")
                    if isinstance(delta,str): text_deltas.append(delta)
                elif event_type == "response.output_item.done":
                    item=event.get("item")
                    if isinstance(item,dict): output_items.append(item)
                elif event_type == "response.completed":
                    completed=event.get("response")
                elif event_type in ("response.failed", "response.incomplete"):
                    detail=event.get("response",{}).get("error") or event.get("response",{}).get("incomplete_details") or event.get("error") or event
                    stream_error=detail
                elif event_type == "error":
                    stream_error=event.get("error") or event
            if stream_error:
                raise RuntimeError("KI-Streamfehler: " + str(stream_error)[:900])
            if completed is None:
                raise RuntimeError("Der KI-Antwortstream endete ohne Abschlussereignis. Bitte erneut versuchen; falls es wieder passiert, den Status/Fehlertext mitteilen.")
            if not isinstance(completed,dict): completed={}
            if not completed.get("output") and output_items:
                completed["output"]=output_items
            if not completed.get("output") and text_deltas:
                completed["output"]=[{"type":"message","content":[{"type":"output_text","text":"".join(text_deltas)}]}]
            return completed
    except urllib.error.HTTPError as e:
        body=e.read().decode(errors="replace")
        try: msg=json.loads(body).get("error",{}).get("message",body)
        except Exception: msg=body
        raise RuntimeError(f"KI-Anfrage HTTP {e.code}: {msg[:900]}")

def _agent_run(url, token, model, messages, use_web, attachments, chat_id=None):
    tools=AgentTools(attachments, chat_id)
    conversation=[]
    instructions=""
    for m in messages:
        if m.get("role")=="system": instructions=m.get("content","")
        else: conversation.append({"role":m["role"],"content":m["content"]})
    instructions += "\n\nDu hast Werkzeuge für echte Dateiarbeit. Entscheide anhand der aktuellen Nutzeranweisung in natürlicher Sprache, ob Dateiarbeit ausdrücklich beauftragt wurde. Eine normale Nachricht, ein bloßer Klick auf Senden, ein Anhang allein oder ein früherer Auftrag sind KEINE Erlaubnis, jetzt Dateien zu erstellen. Rufe Dateiwerkzeuge nur auf, wenn die aktuelle Nachricht konkret verlangt, Anhänge zu untersuchen, Dateien/Code zu erstellen oder zu ändern, ein Projekt vorzubereiten oder eine ZIP zu erzeugen. Verwende keine starren Schlüsselwortregeln; verstehe den Sinn des aktuellen Auftrags. Wenn ein neu erstelltes Shell-Skript wie build_deb.sh vor dem Packen ausführbar sein muss, verwende set_workspace_executable auf die konkrete .sh-Datei im Arbeitsbereich, bevor du create_zip oder prepare_github_release ausführst; ändere Rechte nur im Rahmen des ausdrücklich angeforderten Projektauftrags und prüfe danach die ZIP-Metadaten. Wenn kein solcher Auftrag vorliegt, antworte normal im Chat und erstelle nichts. Bei einem konkreten Projekt-/GitHub-Archivauftrag: Rufe zuerst list_attachments auf, extrahiere angehängte Quell-ZIPs mit extract_attachment_to_workspace und kopiere angehängte DEBs mit copy_attachment_to_workspace. Untersuche danach die vollständigen extrahierten Dateien und Paketdateien. Erstelle ein vollständiges Repository mit dem echten Quellcode und allen erforderlichen Dateien; schreibe NICHT nur README/CHANGELOG/Lizenz und behaupte dann, das Projekt sei fertig. Wenn Quellcode geändert wurde und der Nutzer ein lauffähiges Paket verlangt, nutze run_workspace_command für Syntaxprüfungen und zum Ausführen eines vorhandenen build_deb.sh, auch wenn es in einem Projekt-Unterordner liegt (z.B. Projekt/build_deb.sh); baue DEBs nicht nur durch Kopieren eines alten Pakets. Führe Befehle nur im Arbeitsbereich aus und melde fehlgeschlagene Tests ehrlich. Für ausdrücklich angeforderte Funktionsprüfungen darfst du `python3 Projekt/main.py` verwenden, sofern die .py-Datei im Arbeitsbereich liegt; `dpkg-deb --build --root-owner-group` ist ebenfalls für Build-Ordner innerhalb des Arbeitsbereichs erlaubt. Packe niemals den gesamten Chat-Arbeitsbereich als äußeres ZIP. Gib ausschließlich die beiden Dateien aus `release/` getrennt aus und nenne ihre exakten Pfade. Bei selbst erzeugten Debian-Buildskripten verwende `dpkg-deb --build --root-owner-group` (sofern vom installierten dpkg-deb unterstützt), damit Eigentümer und Gruppe im Paket reproduzierbar root:root sind; behandle Warnungen nicht als erfolgreich bereinigt, sondern prüfe den Build-Ausgang. Der dedizierte release/-Ordner muss nach erfolgreicher Release-Vorbereitung nur die aktuelle GitHub-ZIP und das frisch aus genau dieser ZIP gebaute DEB enthalten; gib diese zwei Dateien getrennt aus, nicht den kompletten Arbeitsordner. Erstelle eine ZIP mit dem kompletten Repository einschließlich Quellcode und bei explizitem Wunsch auch die originale oder neu gebaute DEB-Datei. Wenn der Nutzer ein GitHub-fertiges Projekt mit sauberer ZIP und neu gebautem DEB verlangt, nutze nach den notwendigen Codeänderungen bevorzugt prepare_github_release; gib niemals alte DEBs als neu gebaut aus und prüfe die zurückgegebenen success-/Versions-/Pfadangaben. Prüfe vor Abschluss mit list_workspace_files, dass Quellcode, README, CHANGELOG und gewünschte Pakete wirklich enthalten sind. Sage niemals, etwas erstellt zu haben, bevor das Werkzeug Erfolg gemeldet hat. Nenne am Ende die vollständigen Ausgabe-Pfade. GitHub-Upload/Push ist nicht verfügbar; erstelle stattdessen ein GitHub-fertiges lokales Projekt/ZIP, wenn das gemeint ist."
    conversation=[{"role":"system","content":instructions}]+conversation
    for _ in range(30):
        data=_response_json(url,token,model,conversation,use_web)
        output=data.get("output",[])
        if not output:
            return "(Keine Antwort erhalten.)"
        calls=[x for x in output if x.get("type")=="function_call"]
        # Preserve the model's output items so function_call_output call_ids match.
        conversation.extend(output)
        if not calls:
            texts=[]
            for item in output:
                if item.get("type")=="message":
                    for part in item.get("content",[]):
                        if part.get("type")=="output_text": texts.append(part.get("text",""))
            return "\n".join(texts).strip() or "(Keine Textantwort erhalten.)"
        for call in calls:
            try:
                args=json.loads(call.get("arguments") or "{}")
                result=tools.call(call.get("name",""),args)
            except Exception as e: result={"error":str(e)}
            conversation.append({"type":"function_call_output","call_id":call.get("call_id"),"output":json.dumps(result,ensure_ascii=False)})
    return "Die KI hat das Werkzeug-Limit von 30 Schritten erreicht. Der Arbeitsbereich bleibt für diesen Chat erhalten: " + str(tools.root) + ". Sende eine Folgeanweisung in diesem Chat, um dort fortzufahren."

class Worker(QThread):
    done=Signal(str); failed=Signal(str)
    def __init__(self, config, model, messages, web=False, attachments=None, chat_id=None):
        super().__init__(); self.config=config.copy(); self.model=model; self.messages=messages; self.web=web; self.attachments=attachments or []; self.chat_id=chat_id
    def run(self):
        try:
            if self.config.get("auth_mode") == "chatgpt":
                token=refresh_if_needed(self.config, save_config)
                answer=_agent_run("https://api.openai.com/v1/responses",token,self.model,self.messages,self.web,self.attachments,self.chat_id)
            else:
                answer=_agent_run("https://api.openai.com/v1/responses",self.config.get("api_key",""),self.model,self.messages,self.web,self.attachments,self.chat_id)
            self.done.emit(answer)
        except Exception as e: self.failed.emit(str(e))

class AuthWorker(QThread):
    done=Signal(object); failed=Signal(str)
    def __init__(self, config):
        super().__init__(); self.config=config.copy()
    def run(self):
        try:
            if not self.config.get("ext_agent_host_id"):
                self.config["ext_agent_host_id"] = "urn:uuid:" + str(uuid.uuid4())
                save_config(self.config)
            updated=siwc_sign_in(self.config)
            token=updated.get("siwc_access_token","")
            try:
                available=list_models(token)
            except Exception:
                # Authentication remains useful even if the model catalog is temporarily unavailable.
                available=[]
            if available:
                slugs=[x[0] for x in available]
                if updated.get("model") not in slugs:
                    updated["model"]=slugs[0]
            save_config(updated)
            self.done.emit(updated)
        except Exception as e: self.failed.emit(str(e))

class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LunaGPT – Einstellungen")
        self.setMinimumWidth(470)
        self.config = config.copy()
        layout = QFormLayout(self)

        self.key = QLineEdit(config.get("api_key", ""))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("sk-… (bleibt lokal auf diesem Rechner)")
        self.reveal = QCheckBox("Schlüssel anzeigen")
        self.reveal.toggled.connect(lambda v: self.key.setEchoMode(QLineEdit.Normal if v else QLineEdit.Password))
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.key)
        row.addWidget(self.reveal)

        self.model = QLineEdit(config.get("model", DEFAULT_MODEL))
        self.speak = QCheckBox("Antworten automatisch vorlesen")
        self.speak.setChecked(config.get("speak", True))

        self.voice = QComboBox()
        self._populate_voices()
        saved_voice = config.get("tts_voice", "de")
        idx = self.voice.findData(saved_voice)
        self.voice.setCurrentIndex(idx if idx >= 0 else 0)
        self.refresh_voices_btn = QPushButton("Sprachmodule neu erkennen")
        self.refresh_voices_btn.clicked.connect(self.refresh_voices)
        voice_wrap = QWidget(); voice_row = QHBoxLayout(voice_wrap)
        voice_row.setContentsMargins(0, 0, 0, 0)
        voice_row.addWidget(self.voice, 1); voice_row.addWidget(self.refresh_voices_btn)

        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(100, 220)
        self.speed.setValue(int(config.get("tts_speed", 145)))
        self.speed_label = QLabel(str(self.speed.value()))
        speed_wrap = QWidget()
        speed_row = QHBoxLayout(speed_wrap); speed_row.setContentsMargins(0, 0, 0, 0)
        speed_row.addWidget(self.speed, 1); speed_row.addWidget(self.speed_label)
        self.speed.valueChanged.connect(lambda v: self.speed_label.setText(str(v)))

        self.pitch = QSlider(Qt.Horizontal)
        self.pitch.setRange(0, 99)
        self.pitch.setValue(int(config.get("tts_pitch", 45)))
        self.pitch_label = QLabel(str(self.pitch.value()))
        pitch_wrap = QWidget()
        pitch_row = QHBoxLayout(pitch_wrap); pitch_row.setContentsMargins(0, 0, 0, 0)
        pitch_row.addWidget(self.pitch, 1); pitch_row.addWidget(self.pitch_label)
        self.pitch.valueChanged.connect(lambda v: self.pitch_label.setText(str(v)))

        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(50, 200)
        self.volume.setValue(int(config.get("tts_volume", 120)))
        self.volume_label = QLabel(str(self.volume.value()))
        volume_wrap = QWidget()
        volume_row = QHBoxLayout(volume_wrap); volume_row.setContentsMargins(0, 0, 0, 0)
        volume_row.addWidget(self.volume, 1); volume_row.addWidget(self.volume_label)
        self.volume.valueChanged.connect(lambda v: self.volume_label.setText(str(v)))

        layout.addRow("OpenAI-API-Schlüssel", wrap)
        layout.addRow("", QLabel("Der Schlüssel wird lokal mit Dateirechten 600 gespeichert."))
        layout.addRow("Modell", self.model)
        layout.addRow("", self.speak)
        layout.addRow("Stimme", voice_wrap)
        layout.addRow("Sprechtempo", speed_wrap)
        layout.addRow("Tonhöhe", pitch_wrap)
        layout.addRow("Sprachlautstärke", volume_wrap)

        self.output_device = QComboBox()
        output_devices = self._list_output_devices()
        for dev_id, dev_name in output_devices:
            self.output_device.addItem(dev_name, dev_id)
        saved_device = config.get("tts_output_device", "default")
        saved_idx = self.output_device.findData(saved_device)
        self.output_device.setCurrentIndex(saved_idx if saved_idx >= 0 else 0)

        # Schmale Auswahl: nur Systemstandard und erkannte physische USB-/HDMI-Ausgänge.
        self.output_device.setMaximumWidth(220)
        self.output_device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.output_device.setMinimumContentsLength(12)
        layout.addRow("Soundkarte für Luna", self.output_device)
        test_row = QWidget()
        test_layout = QHBoxLayout(test_row)
        test_layout.setContentsMargins(0, 0, 0, 0)
        self.test_sound_btn = QPushButton("🔊 Testton / Stimme testen")
        self.test_sound_btn.clicked.connect(self.test_sound)
        test_layout.addWidget(self.test_sound_btn)
        test_layout.addStretch(1)
        layout.addRow("", test_row)
        layout.addRow("", QLabel("Wählt das ALSA-Ausgabegerät für Lunas Sprachausgabe."))
        layout.addRow("", QLabel("Die Liste wird aus den installierten eSpeak-NG- und MBROLA-Stimmen ermittelt."))

        self.input_device = QComboBox()
        self.input_devices = self._list_input_devices()
        for device_index, device_name in self.input_devices:
            self.input_device.addItem(device_name, device_index)
        saved_mic = config.get("mic_device_index", None)
        saved_mic_idx = self.input_device.findData(saved_mic)
        self.input_device.setCurrentIndex(saved_mic_idx if saved_mic_idx >= 0 else 0)
        self.input_device.setMinimumContentsLength(22)
        self.input_device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        layout.addRow("Mikrofon für Spracheingabe", self.input_device)
        layout.addRow("", QLabel("Die Auswahl wird gespeichert. Der Spracheingabe-Knopf startet die Aufnahme direkt."))

        buttons = QDialogButtonBox()
        self.savebtn = buttons.addButton("Speichern", QDialogButtonBox.AcceptRole)
        self.cancelbtn = buttons.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        self.savebtn.clicked.connect(self.accept)
        self.cancelbtn.clicked.connect(self.reject)
        layout.addRow(buttons)

    def _populate_voices(self):
        """List voices detected from installed eSpeak NG and MBROLA data."""
        self.voice.clear()
        voices = []
        try:
            proc = subprocess.run(["espeak-ng", "--voices=all"], capture_output=True, text=True, timeout=8)
            for line in (proc.stdout or "").splitlines():
                parts = line.split()
                if len(parts) < 5 or parts[0].lower() in ("pty", "language"):
                    continue
                lang, name = parts[1], parts[4]
                if not re.match(r"^[a-z]{2,3}([_-][A-Za-z0-9]+)?$", lang):
                    continue
                # Skip language aliases that are not actual voice IDs where possible.
                if name and name not in {v[0] for v in voices}:
                    language_name = {"de":"Deutsch", "en":"Englisch", "fr":"Französisch", "es":"Spanisch", "it":"Italienisch", "nl":"Niederländisch", "pt":"Portugiesisch", "ru":"Russisch", "pl":"Polnisch", "zh":"Chinesisch"}.get(lang.split("-")[0].split("_")[0], lang)
                    voices.append((name, f"{language_name} – {name} ({lang})"))
        except (OSError, subprocess.SubprocessError):
            pass
        # MBROLA data packages may be installed even when espeak-ng doesn't list them
        # as a normal voice. Only offer them if the actual voice data file exists.
        roots = [Path("/usr/share/mbrola"), Path("/usr/share/espeak-ng-data/voices/mb")]
        for root in roots:
            if not root.exists():
                continue
            for f in root.iterdir():
                if not f.is_file() and not f.is_dir():
                    continue
                code = f.name
                if re.fullmatch(r"[a-z]{2,3}[0-9]", code, re.I):
                    voice_id = "mb-" + code.lower()
                    if not any(v[0] == voice_id for v in voices):
                        lang = "Deutsch" if code.lower().startswith("de") else "MBROLA"
                        voices.append((voice_id, f"{lang} – MBROLA {code.lower()}"))
        # Put a sane German default first, followed by detected voices.
        preferred = [("de", "Deutsch – eSpeak NG Standard"), ("de+f3", "Deutsch – weibliche Variante (de+f3)"), ("de+m3", "Deutsch – männliche Variante (de+m3)")]
        all_items = preferred + sorted(voices, key=lambda x: (x[1].casefold(), x[0]))
        seen = set()
        for voice_id, label in all_items:
            if voice_id not in seen:
                self.voice.addItem(label, voice_id); seen.add(voice_id)
        if not self.voice.count():
            self.voice.addItem("Deutsch – eSpeak NG Standard", "de")

    def refresh_voices(self):
        previous = self.voice.currentData()
        self._populate_voices()
        idx = self.voice.findData(previous)
        if idx >= 0:
            self.voice.setCurrentIndex(idx)
        QMessageBox.information(self, "Sprachmodule", f"Erkennung abgeschlossen. {self.voice.count()} Stimmen gefunden. Nicht jede gelistete Stimme ist automatisch abspielbar; nutze zum Prüfen den Soundtest.")

    def _list_input_devices(self):
        # SpeechRecognition/PyAudio-Indexliste; der Index wird dauerhaft gespeichert.
        devices = []
        try:
            import speech_recognition as sr
            for index, name in enumerate(sr.Microphone.list_microphone_names()):
                devices.append((index, f"{index}: {name}"))
        except Exception:
            pass
        if not devices:
            devices.append((None, "Systemstandard (Mikrofonliste nicht verfügbar)"))
        return devices

    def _list_output_devices(self):
        # Kurze Liste echter Hardware-Ausgänge. IDs sind die von ALSA unterstützten
        # plughw-Kennungen und nicht die Anzeigenamen.
        devices = [("default", "Systemstandard")]
        try:
            proc = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=4)
            for line in (proc.stdout or "").splitlines():
                match = re.match(r"^(?:card|karte)\s+(\d+):\s*([^\s,]+).*?,.*?(?:device|gerät|geraet)\s+(\d+):", line, re.IGNORECASE)
                if not match:
                    continue
                card_no, card_id, dev_no = match.groups()
                low = (card_id + " " + line).lower()
                alsa_id = f"alsa:plughw:CARD={card_id},DEV={dev_no}"
                if "usb" in low or "device" == card_id.lower():
                    label = "USB-Soundkarte"
                elif "vc4hdmi0" in low or "hdmi-0" in low:
                    label = "HDMI 1"
                elif "vc4hdmi1" in low or "hdmi-1" in low:
                    label = "HDMI 2"
                elif "hdmi" in low or "vc4" in low:
                    label = f"HDMI (Karte {card_no})"
                else:
                    label = f"Audio (Karte {card_no})"
                if not any(existing_id == alsa_id for existing_id, _ in devices):
                    devices.append((alsa_id, label))
        except Exception:
            pass
        return devices

    def test_sound(self):
        self.test_sound_btn.setEnabled(False)
        self.test_sound_btn.setText("Teste Audio …")
        QApplication.processEvents()
        try:
            voice = self.voice.currentData() or "de"
            selected_voice = voice
            if voice.startswith("mb-"):
                code = voice[3:]
                candidates = [Path("/usr/share/mbrola") / code, Path("/usr/share/mbrola") / (code + ".mbrola"), Path("/usr/share/espeak-ng-data/voices/mb") / code]
                if not any(candidate.exists() for candidate in candidates):
                    selected_voice = "de"
            command = ["espeak-ng", "-v", selected_voice, "-s", str(self.speed.value()),
                       "-p", str(self.pitch.value()), "-a", str(self.volume.value()),
                       "--stdout", "Hallo, hier ist Luna. Dies ist ein kurzer Test meiner Sprachausgabe."]
            generated = subprocess.run(command, capture_output=True, timeout=20, check=True)
            play_command = ["aplay", "-q"]
            output_device = self.output_device.currentData()
            if output_device and str(output_device).startswith("alsa:"):
                play_command += ["-D", str(output_device).split(":", 1)[1]]
            subprocess.run(play_command, input=generated.stdout, capture_output=True, timeout=30, check=True)
            QMessageBox.information(self, "Soundtest", "Der Audiotest wurde erfolgreich abgespielt.")
        except FileNotFoundError as exc:
            QMessageBox.critical(self, "Soundtest fehlgeschlagen", f"Programm nicht gefunden: {exc.filename}\n\nBitte installiere es mit: sudo apt install espeak-ng alsa-utils")
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
            QMessageBox.critical(self, "Soundtest fehlgeschlagen", "Die Sprachausgabe konnte nicht abgespielt werden.\n\n" + (details or "Bitte prüfe die ausgewählte Soundkarte und die Lautstärke."))
        except Exception as exc:
            QMessageBox.critical(self, "Soundtest fehlgeschlagen", str(exc))
        finally:
            self.test_sound_btn.setEnabled(True)
            self.test_sound_btn.setText("🔊 Testton / Stimme testen")

    def values(self):
        return {
            "api_key": self.key.text().strip(),
            "model": self.model.text().strip() or DEFAULT_MODEL,
            "speak": self.speak.isChecked(),
            "tts_voice": self.voice.currentData(),
            "tts_speed": self.speed.value(),
            "tts_pitch": self.pitch.value(),
            "tts_volume": self.volume.value(),
            "tts_output_device": self.output_device.currentData(),
            "mic_device_index": self.input_device.currentData()
        }

class ImageGenerationWorker(QThread):
    finished_image = Signal(str, str, float)

    def __init__(self, prompt, output_path, width, height, parent=None):
        super().__init__(parent)
        self.prompt = self.enhance_prompt(prompt)
        self.output_path = output_path
        requested_width = int(width)
        requested_height = int(height)
        # AI Horde requires width/height to be multiples of 64; 621 is a UI size tier.
        self.width = 576 if requested_width == 621 else requested_width
        self.height = 576 if requested_height == 621 else requested_height

    @staticmethod
    def enhance_prompt(user_prompt):
        """Improve the online image prompt without changing the requested subject."""
        import re
        prompt = " ".join(user_prompt.split())
        quality = ("high-quality image, clear main subject, coherent composition, "
                   "accurate object shape, realistic materials, detailed lighting, "
                   "sharp focus, complete subject visible")
        cola_terms = r"\b(coca[ -]?cola|cola|colaflasche|cola-flasche|cola flasche)\b"
        bottle_terms = r"\b(flasche|bottle)\b"
        if re.search(cola_terms, prompt, re.IGNORECASE) and re.search(bottle_terms, prompt, re.IGNORECASE):
            details = ("single small vintage Coca-Cola glass contour bottle, iconic curved waist, "
                       "dark brown cola visible through clear glass, red metal crown cap, "
                       "authentic red-and-white Coca-Cola script label on the front, "
                       "front three-quarter product view, entire bottle visible, "
                       "realistic glass reflections, simple uncluttered studio background")
            return f"{prompt}. {details}. {quality}"
        return f"{prompt}. {quality}"

    @classmethod
    def _request(cls, url, data=None, timeout=30):
        headers = {"apikey": "0000000000", "Client-Agent": "LunaGPT:1.10.1:anonymous-free-image-generation", "User-Agent": "LunaGPT/1.10.1", "Accept": "application/json"}
        payload = None
        if data is not None:
            payload = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST" if payload is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read(20 * 1024 * 1024 + 1)
                if len(raw) > 20 * 1024 * 1024:
                    raise RuntimeError("Die Antwort des Bilddienstes ist unerwartet groß.")
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read(2000).decode("utf-8", errors="replace")
            raise RuntimeError(f"AI Horde meldet HTTP {exc.code}: {details or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"AI Horde ist nicht erreichbar: {exc.reason}") from exc

    def run(self):
        started = time.monotonic()
        try:
            prompt = self.prompt.strip()
            if not prompt:
                raise ValueError("Bitte zuerst eine Bildbeschreibung eingeben.")
            request_data = {"prompt": prompt, "params": {"width": self.width, "height": self.height, "steps": 20, "n": 1, "cfg_scale": 7.0, "sampler_name": "k_euler"}, "nsfw": False, "censor_nsfw": True, "r2": True, "shared": False}
            submitted = self._request("https://aihorde.net/api/v2/generate/async", request_data)
            job_id = submitted.get("id")
            if not job_id:
                raise RuntimeError("AI Horde hat keine Auftragsnummer zurückgegeben: " + str(submitted))
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                time.sleep(5)
                check = self._request("https://aihorde.net/api/v2/generate/check/" + str(job_id))
                if check.get("fault"):
                    raise RuntimeError(str(check["fault"]))
                if check.get("faulted"):
                    raise RuntimeError("AI Horde konnte das Bild nicht erzeugen. Bitte später erneut versuchen.")
                if check.get("done"):
                    break
            else:
                raise TimeoutError("AI Horde hat nach 15 Minuten noch kein Bild geliefert. Es wurde kein anderer Dienst verwendet.")
            result = self._request("https://aihorde.net/api/v2/generate/status/" + str(job_id))
            generations = result.get("generations") or []
            if not generations:
                raise RuntimeError("AI Horde meldet den Auftrag als fertig, hat aber kein Bild geliefert.")
            image_value = generations[0].get("img")
            if not image_value:
                raise RuntimeError("Die Bildantwort von AI Horde enthält keine Bilddaten.")
            if isinstance(image_value, str) and image_value.startswith(("http://", "https://")):
                req = urllib.request.Request(image_value, headers={"User-Agent": "LunaGPT/1.10.1"})
                with urllib.request.urlopen(req, timeout=60) as response:
                    image_bytes = response.read(20 * 1024 * 1024 + 1)
            else:
                if isinstance(image_value, str) and image_value.startswith("data:") and "," in image_value:
                    image_value = image_value.split(",", 1)[1]
                image_bytes = base64.b64decode(image_value, validate=True)
            if not image_bytes or len(image_bytes) > 20 * 1024 * 1024:
                raise RuntimeError("Das erzeugte Bild ist leer oder größer als 20 MB.")
            image = QImage.fromData(image_bytes)
            if image.isNull():
                raise RuntimeError("AI Horde hat keine lesbare Bilddatei geliefert.")
            if not image.save(self.output_path, "PNG"):
                raise RuntimeError("Das temporäre Vorschaubild konnte nicht vorbereitet werden.")
            self.finished_image.emit(self.output_path, "", time.monotonic() - started)
        except Exception as exc:
            try:
                Path(self.output_path).unlink(missing_ok=True)
            except OSError:
                pass
            self.finished_image.emit("", str(exc), time.monotonic() - started)


class ImageGenerationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LunaGPT – Kostenlose Online-Bildgenerierung")
        self.resize(650, 620)
        self.worker = None
        self.last_image = ""
        self.started_at = None
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(250)
        self.elapsed_timer.timeout.connect(self.update_elapsed)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Beschreibe das Bild, das kostenlos online erzeugt werden soll:"))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("Zum Beispiel: Ein rotes Haus auf einer grünen Wiese, sonniger Tag, digitale Malerei")
        self.prompt.setMinimumHeight(90)
        self.prompt.setContextMenuPolicy(Qt.CustomContextMenu)
        self.prompt.customContextMenuRequested.connect(self.prompt_context_menu)
        layout.addWidget(self.prompt)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Bildgröße:"))
        self.size_combo = QComboBox()
        for size in (256, 512, 621):
            self.size_combo.addItem(f"{size} × {size} Pixel", size)
        self.size_combo.currentIndexChanged.connect(self.update_size_info)
        size_row.addWidget(self.size_combo)
        size_row.addStretch(1)
        layout.addLayout(size_row)
        self.info = QLabel("AI Horde · anonym und kostenlos · 256 × 256 Pixel\nKein kostenpflichtiger Ersatzdienst. Bilder werden nicht automatisch gespeichert.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.preview = QLabel("Hier erscheint das erzeugte Bild.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(220, 220)
        self.preview.setStyleSheet("QLabel { border: 1px solid #555; border-radius: 8px; padding: 8px; }")
        layout.addWidget(self.preview, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel("Bereit · Verstrichene Zeit: 00:00")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.generate_btn = QPushButton("🎨 Bild erzeugen")
        self.generate_btn.clicked.connect(self.generate)
        buttons.addWidget(self.generate_btn)
        self.save_btn = QPushButton("Bild speichern unter …")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_image)
        buttons.addWidget(self.save_btn)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def prompt_context_menu(self, pos):
        """Deutsches Kontextmenü für das Bild-Promptfeld."""
        menu = QMenu(self)
        undo = menu.addAction("Rückgängig")
        redo = menu.addAction("Wiederholen")
        menu.addSeparator()
        cut = menu.addAction("Ausschneiden")
        copy = menu.addAction("Kopieren")
        paste = menu.addAction("Einfügen")
        menu.addSeparator()
        select = menu.addAction("Alles auswählen")
        cursor = self.prompt.textCursor()
        has_selection = cursor.hasSelection()
        undo.setEnabled(self.prompt.document().isUndoAvailable())
        redo.setEnabled(self.prompt.document().isRedoAvailable())
        cut.setEnabled(has_selection)
        copy.setEnabled(has_selection)
        paste.setEnabled(bool(QApplication.clipboard().mimeData().hasText()))
        select.setEnabled(bool(self.prompt.toPlainText()))
        chosen = menu.exec(self.prompt.mapToGlobal(pos))
        if chosen == undo: self.prompt.undo()
        elif chosen == redo: self.prompt.redo()
        elif chosen == cut: self.prompt.cut()
        elif chosen == copy: self.prompt.copy()
        elif chosen == paste: self.prompt.paste()
        elif chosen == select: self.prompt.selectAll()

    def update_size_info(self):
        size = int(self.size_combo.currentData())
        self.info.setText(f"AI Horde · anonym und kostenlos · {size} × {size} Pixel\nKein kostenpflichtiger Ersatzdienst. Bilder werden nicht automatisch gespeichert.")
        # Dialoggröße folgt der gewählten Bildauflösung. Auf kleinen Displays wird
        # die Fenstergröße auf den verfügbaren Platz begrenzt; die Vorschau zeigt
        # dann weiterhin das vollständige Bild proportional verkleinert.
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            margin = 32
            desired_width = max(650, size + 100)
            desired_height = size + 270
            width = min(desired_width, max(600, available.width() - margin))
            height = min(desired_height, max(560, available.height() - margin))
            self.resize(width, height)
            x = min(max(self.x(), available.left()), available.right() - width + 1)
            y = min(max(self.y(), available.top()), available.bottom() - height + 1)
            self.move(x, y)

    def update_elapsed(self):
        if self.started_at is not None:
            seconds = int(time.monotonic() - self.started_at)
            self.status.setText(f"Bild wird online erzeugt … · Verstrichene Zeit: {seconds // 60:02d}:{seconds % 60:02d} min")

    def generate(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "Bildbeschreibung fehlt", "Bitte gib zuerst eine Beschreibung ein.")
            return
        import tempfile
        # Vorschau nur temporär speichern; dauerhafte Speicherung nur über den Speichern-Dialog.
        fd, temp_name = tempfile.mkstemp(prefix="lunagpt_preview_", suffix=".png")
        import os
        os.close(fd)
        output = Path(temp_name)
        self.generate_btn.setEnabled(False)
        self.size_combo.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.started_at = time.monotonic()
        self.elapsed_timer.start()
        self.progress.show()
        self.status.setText("Bild wird online erzeugt … · Verstrichene Zeit: 00:00 min")
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Bild wird erzeugt …")
        size = int(self.size_combo.currentData())
        self.worker = ImageGenerationWorker(prompt, str(output), size, size, self)
        self.worker.finished_image.connect(self.generation_finished)
        self.worker.start()

    def generation_finished(self, path, error, elapsed):
        self.elapsed_timer.stop()
        self.progress.hide()
        self.generate_btn.setEnabled(True)
        self.size_combo.setEnabled(True)
        self.started_at = None
        elapsed_text = f"{int(elapsed) // 60:02d}:{int(elapsed) % 60:02d} min"
        if error:
            self.preview.setText("Die Bilderzeugung ist fehlgeschlagen.")
            self.status.setText(f"Fehler beim Bildgenerator · Verstrichene Zeit: {elapsed_text}")
            QMessageBox.critical(self, "Bildgenerierung fehlgeschlagen", error)
            return
        self.last_image = path
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview.setText("Das Bild konnte nicht angezeigt werden.")
        else:
            self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.status.setText(f"Fertig · Verstrichene Zeit: {elapsed_text}\nNicht dauerhaft gespeichert. Bei Bedarf auf ‚Bild speichern unter …‘ klicken.")
        self.save_btn.setEnabled(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.last_image and Path(self.last_image).is_file():
            pixmap = QPixmap(self.last_image)
            if not pixmap.isNull():
                self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Bild wird noch erzeugt", "Bitte warte, bis die laufende Bilderzeugung abgeschlossen ist.")
            event.ignore()
            return
        # Temporäre Vorschau nach dem Schließen entfernen; manuell gespeicherte Kopien bleiben erhalten.
        if self.last_image:
            try:
                Path(self.last_image).unlink(missing_ok=True)
            except OSError:
                pass
            self.last_image = ""
        event.accept()

    def save_image(self):
        if not self.last_image or not Path(self.last_image).is_file():
            return
        target, _ = QFileDialog.getSaveFileName(self, "Bild speichern", str(Path.home() / "Bild.png"), "PNG-Bilder (*.png)")
        if target:
            if not target.lower().endswith(".png"):
                target += ".png"
            try:
                shutil.copy2(self.last_image, target)
                self.status.setText(f"Bild manuell gespeichert: {target}")
            except OSError as exc:
                QMessageBox.critical(self, "Speichern fehlgeschlagen", str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.config=load_config(); init_db(); self.current_chat=None; self.attachments=[]; self.worker=None; self.authworker=None; self.dark_theme=bool(self.config.get("dark_theme", True))
        self.setWindowTitle("LunaGPT – dein KI-Client"); self.resize(1180,780); self.setMinimumSize(850,600)
        self.setAcceptDrops(True)
        root=QWidget(); outer=QHBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        self.sidebar=QWidget(); self.sidebar.setObjectName("sidebar"); self.sidebar.setMinimumWidth(225); self.sidebar.setMaximumWidth(280)
        sl=QVBoxLayout(self.sidebar); sl.setContentsMargins(12,16,12,12)
        logo=QLabel("🐭 LunaGPT"); logo.setObjectName("logo"); sl.addWidget(logo)
        self.newbtn=QPushButton("＋  Neuer Chat"); self.newbtn.clicked.connect(self.new_chat); sl.addWidget(self.newbtn)
        self.archiveviewbtn=QPushButton("🗃  Archivierte Chats anzeigen"); self.archiveviewbtn.clicked.connect(self.toggle_archived_view); sl.addWidget(self.archiveviewbtn)
        self.loginbtn=QPushButton("Mit ChatGPT anmelden"); self.loginbtn.setToolTip("Mit deinem ChatGPT-Konto anmelden; Google kann im Browser ausgewählt werden."); self.loginbtn.clicked.connect(self.chatgpt_login); sl.addWidget(self.loginbtn)
        self.show_archived=False; self.chats=QListWidget(); self.chats.currentItemChanged.connect(self.select_chat); self.chats.setContextMenuPolicy(Qt.CustomContextMenu); self.chats.customContextMenuRequested.connect(self.chat_context_menu); sl.addWidget(self.chats,1)
        self.knowledgebtn=QPushButton("📚  Wissenssammlung"); self.knowledgebtn.clicked.connect(self.manage_knowledge); sl.addWidget(self.knowledgebtn)
        self.exportbtn=QPushButton("📤  Chats exportieren"); self.exportbtn.clicked.connect(self.export_chats); sl.addWidget(self.exportbtn)
        self.importbtn=QPushButton("📥  Chats importieren"); self.importbtn.clicked.connect(self.import_chats); sl.addWidget(self.importbtn)
        self.themebtn=QPushButton("☀  Helles Design"); self.themebtn.clicked.connect(self.toggle_theme); sl.addWidget(self.themebtn)
        self.settingsbtn=QPushButton("⚙  Einstellungen"); self.settingsbtn.clicked.connect(self.settings); sl.addWidget(self.settingsbtn)
        self.status=QLabel("Bereit"); self.status.setObjectName("status"); sl.addWidget(self.status)
        main=QWidget(); ml=QVBoxLayout(main); ml.setContentsMargins(18,14,18,14); ml.setSpacing(10)
        top=QHBoxLayout(); self.title=QLabel("Wie kann ich helfen?"); self.title.setObjectName("heading"); top.addWidget(self.title); top.addStretch()
        self.mode=QComboBox(); self.mode.addItems(["Allgemein","Programmiermodus"]); top.addWidget(QLabel("Modus")); top.addWidget(self.mode)
        saved_mode = self.config.get("ui_mode", "Allgemein")
        self.mode.setCurrentText(saved_mode if saved_mode in ("Allgemein", "Programmiermodus") else "Allgemein")
        self.web=QCheckBox("Websuche"); self.web.setToolTip("Nutzt die Websuche der OpenAI API; kann zusätzliche API-Kosten verursachen.")
        self.web.setChecked(bool(self.config.get("web_search", False)))
        top.addWidget(self.web)
        # Speichere die Auswahl sofort, damit sie auch bei einem unerwarteten Beenden erhalten bleibt.
        self.mode.currentTextChanged.connect(self.save_ui_preferences)
        self.web.toggled.connect(self.save_ui_preferences)
        top.addStretch()
        self.version_label=QLabel(f"LunaGPT v{APP_VERSION}"); self.version_label.setObjectName("versionLabel"); self.version_label.setToolTip("Installierte Programmversion"); top.addWidget(self.version_label)
        ml.addLayout(top)
        self.transcript=QTextBrowser(); self.transcript.setOpenExternalLinks(True); self.transcript.setObjectName("transcript"); self.transcript.setContextMenuPolicy(Qt.CustomContextMenu); self.transcript.customContextMenuRequested.connect(self.transcript_context_menu); ml.addWidget(self.transcript,1)
        # Deutlich sichtbare, animierte Denk-Anzeige im Chatbereich. Sie wird nur
        # während einer laufenden Anfrage eingeblendet und erzeugt selbst keine Dateien.
        self.thinking_label=QLabel("🐭  Luna überlegt")
        self.thinking_label.setObjectName("thinkingIndicator")
        self.thinking_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.thinking_label.setMinimumHeight(34)
        self.thinking_label.setContentsMargins(12, 4, 12, 4)
        self.thinking_label.hide()
        ml.addWidget(self.thinking_label)
        self._thinking_frame = 0
        self.thinking_timer = QTimer(self)
        self.thinking_timer.setInterval(420)
        self.thinking_timer.timeout.connect(self._animate_thinking)
        self.attachlabel=QLabel("Keine Anhänge"); self.attachlabel.setObjectName("muted"); ml.addWidget(self.attachlabel)
        self.input=AttachmentTextEdit(self)
        self.input.setPlaceholderText("Schreibe Luna eine Nachricht …  (Enter = Senden, Umschalt+Enter = neue Zeile)")
        self.input.setFixedHeight(105)
        self.input.setContextMenuPolicy(Qt.CustomContextMenu)
        self.input.customContextMenuRequested.connect(self.input_context_menu)
        self.input.installEventFilter(self)
        ml.addWidget(self.input)
        bottom=QHBoxLayout()
        self.attachbtn=QPushButton("＋ Datei/Bild"); self.attachbtn.clicked.connect(self.add_file); bottom.addWidget(self.attachbtn)
        self.imagegenbtn=QPushButton("🎨 Bild erzeugen"); self.imagegenbtn.setToolTip("Ein Bild kostenlos und anonym online mit AI Horde erzeugen."); self.imagegenbtn.clicked.connect(self.open_image_generation); bottom.addWidget(self.imagegenbtn)
        self.micbtn=QPushButton("🎙 Spracheingabe"); self.micbtn.clicked.connect(self.voice_input); bottom.addWidget(self.micbtn)
        self.readbtn=QPushButton("🔊 Vorlesen"); self.readbtn.clicked.connect(self.read_last); bottom.addWidget(self.readbtn)
        self.stopreadbtn=QPushButton("⏹ Vorlesen beenden"); self.stopreadbtn.clicked.connect(self.stop_reading); bottom.addWidget(self.stopreadbtn)
        bottom.addStretch(); self.progress=QProgressBar(); self.progress.setMaximumWidth(110); self.progress.setRange(0,1); self.progress.hide(); bottom.addWidget(self.progress)
        self.sendbtn=QPushButton("Senden  ➤"); self.sendbtn.setObjectName("send"); self.sendbtn.clicked.connect(self.send); bottom.addWidget(self.sendbtn)
        ml.addLayout(bottom)
        splitter=QSplitter(); splitter.addWidget(self.sidebar); splitter.addWidget(main); splitter.setStretchFactor(1,1); outer.addWidget(splitter); self.setCentralWidget(root)
        self.apply_theme()
        self.refresh_chats()
        self.update_api_status()

    def open_image_generation(self):
        dialog = ImageGenerationDialog(self)
        dialog.exec()

    def save_ui_preferences(self, *_args):
        """Persist the selected mode and web-search state immediately."""
        self.config["ui_mode"] = self.mode.currentText()
        self.config["web_search"] = self.web.isChecked()
        save_config(self.config)

    def apply_theme(self):
        if self.dark_theme:
            stylesheet = """
            QWidget { background:#171923; color:#e8eaf0; font-size:14px; }
            #sidebar { background:#202330; border-right:1px solid #343849; }
            #logo {font-size:22px;font-weight:700;padding:8px 2px 14px;color:#ffffff;}
            #heading {font-size:20px;font-weight:600;color:#ffffff;}
            #versionLabel {font-size:12px;font-weight:700;color:#c9c2ff;background:#292e3d;border:1px solid #42495c;border-radius:7px;padding:5px 9px;}
            #status,#muted {color:#a7adbd;font-size:12px;}
            #thinkingIndicator {color:#d8ceff;background:#29243f;border:1px solid #514579;border-radius:10px;font-size:14px;font-weight:700;}
            QPushButton {background:#292e3d;border:1px solid #42495c;border-radius:9px;padding:9px 12px;text-align:left;color:#eef0f6;}
            QPushButton:hover {background:#363d50;} QPushButton:disabled {color:#777e90;}
            #send {background:#7055e8;color:#ffffff;border:0;font-weight:700;text-align:center;padding:10px 18px;}
            #send:hover {background:#8069ed;}
            QListWidget {background:transparent;border:0;outline:0;} QListWidget::item {padding:10px;border-radius:8px;margin:2px 0;} QListWidget::item:selected {background:#3c365d;color:#ffffff;}
            QTextBrowser {background:#202330;border:1px solid #343849;border-radius:12px;padding:12px;selection-background-color:#5544a8;}
            QTextEdit,QLineEdit {background:#202330;border:1px solid #42495c;border-radius:10px;padding:10px;color:#f0f1f6;selection-background-color:#5544a8;}
            QComboBox {background:#292e3d;border:1px solid #42495c;border-radius:8px;padding:6px;color:#eef0f6;}
            QComboBox QAbstractItemView {background:#292e3d;color:#eef0f6;selection-background-color:#5544a8;}
            QCheckBox {spacing:6px;color:#dce0eb;} QProgressBar {border:0;background:#343849;border-radius:4px;} QProgressBar::chunk {background:#7055e8;}
            QScrollBar:vertical {background:#202330;width:12px;} QScrollBar::handle:vertical {background:#454b60;border-radius:5px;min-height:24px;}
            """
        else:
            stylesheet = """
            QWidget { background:#f4f6fa; color:#202532; font-size:14px; }
            #sidebar { background:#e9edf5; border-right:1px solid #d1d7e2; }
            #logo {font-size:22px;font-weight:700;padding:8px 2px 14px;color:#202532;}
            #heading {font-size:20px;font-weight:600;}
            #status,#muted {color:#626b7a;font-size:12px;}
            #thinkingIndicator {color:#5540a5;background:#f0edff;border:1px solid #d2c8ff;border-radius:10px;font-size:14px;font-weight:700;}
            QPushButton {background:#ffffff;border:1px solid #cbd2df;border-radius:9px;padding:9px 12px;text-align:left;color:#202532;}
            QPushButton:hover {background:#e5e9f2;} QPushButton:disabled {color:#737985;}
            #send {background:#7055e8;color:#ffffff;border:0;font-weight:700;text-align:center;padding:10px 18px;}
            #send:hover {background:#8069ed;}
            QListWidget {background:transparent;border:0;outline:0;} QListWidget::item {padding:10px;border-radius:8px;margin:2px 0;} QListWidget::item:selected {background:#d9def0;}
            QTextBrowser {background:#ffffff;border:1px solid #d1d7e2;border-radius:12px;padding:12px;selection-background-color:#bdb0ff;}
            QTextEdit,QLineEdit {background:#ffffff;border:1px solid #cbd2df;border-radius:10px;padding:10px;color:#202532;selection-background-color:#bdb0ff;}
            QComboBox {background:#ffffff;border:1px solid #cbd2df;border-radius:8px;padding:6px;color:#202532;}
            QComboBox QAbstractItemView {background:#ffffff;color:#202532;selection-background-color:#d9def0;}
            QCheckBox {spacing:6px;color:#343b49;} QProgressBar {border:0;background:#e2e6ef;border-radius:4px;} QProgressBar::chunk {background:#7055e8;}
            QScrollBar:vertical {background:#e9edf5;width:12px;} QScrollBar::handle:vertical {background:#c5ccda;border-radius:5px;min-height:24px;}
            """
        self.setStyleSheet(stylesheet)
        self.themebtn.setText("☀  Helles Design" if self.dark_theme else "🌙  Dunkles Design")

    def toggle_theme(self):
        self.dark_theme = not self.dark_theme
        self.config["dark_theme"] = self.dark_theme
        save_config(self.config)
        self.apply_theme()

    def get_text_german(self, title, label, text=""):
        dlg=QDialog(self); dlg.setWindowTitle(title)
        layout=QVBoxLayout(dlg); layout.addWidget(QLabel(label))
        field=QLineEdit(text); layout.addWidget(field)
        buttons=QDialogButtonBox()
        ok=buttons.addButton("OK",QDialogButtonBox.AcceptRole)
        cancel=buttons.addButton("Abbrechen",QDialogButtonBox.RejectRole)
        ok.clicked.connect(dlg.accept); cancel.clicked.connect(dlg.reject); layout.addWidget(buttons)
        accepted=dlg.exec()==QDialog.Accepted
        return field.text(), accepted

    def get_multiline_german(self, title, label):
        dlg=QDialog(self); dlg.setWindowTitle(title); dlg.resize(500,300)
        layout=QVBoxLayout(dlg); layout.addWidget(QLabel(label))
        field=QPlainTextEdit(); layout.addWidget(field,1)
        buttons=QDialogButtonBox()
        ok=buttons.addButton("OK",QDialogButtonBox.AcceptRole)
        cancel=buttons.addButton("Abbrechen",QDialogButtonBox.RejectRole)
        ok.clicked.connect(dlg.accept); cancel.clicked.connect(dlg.reject); layout.addWidget(buttons)
        accepted=dlg.exec()==QDialog.Accepted
        return field.toPlainText(), accepted

    def manage_knowledge(self):
        dialog = QDialog(self); dialog.setWindowTitle("Wissenssammlung"); dialog.resize(640, 480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Speichere Hinweise, Projektnotizen oder bevorzugte Anweisungen. Passende Einträge werden bei jeder Anfrage als Kontext mitgesendet."))
        self.knowledge_list = QListWidget(); layout.addWidget(self.knowledge_list, 1)
        rows = dball("SELECT id,title FROM knowledge ORDER BY id DESC")
        for kid, title in rows:
            self.knowledge_list.addItem(QListWidgetItem(f"{kid} — {title}"))
        buttons = QHBoxLayout()
        add = QPushButton("＋ Eintrag hinzufügen"); delete = QPushButton("Ausgewählten löschen"); close = QPushButton("Schließen")
        buttons.addWidget(add); buttons.addWidget(delete); buttons.addStretch(); buttons.addWidget(close); layout.addLayout(buttons)
        def add_entry():
            title, ok = self.get_text_german("Wissen hinzufügen", "Titel:")
            if not ok or not title.strip(): return
            content, ok = self.get_multiline_german("Wissen hinzufügen", "Notiz / Wissen:")
            if not ok or not content.strip(): return
            dball("INSERT INTO knowledge(title,content,created) VALUES(?,?,?)", (title.strip(),content.strip(),datetime.now().isoformat()), False)
            self.knowledge_list.clear()
            for kid, saved_title in dball("SELECT id,title FROM knowledge ORDER BY id DESC"):
                self.knowledge_list.addItem(QListWidgetItem(f"{kid} — {saved_title}"))
        def delete_entry():
            item=self.knowledge_list.currentItem()
            if not item:return
            try: kid=int(item.text().split(" — ",1)[0])
            except Exception:return
            dball("DELETE FROM knowledge WHERE id=?",(kid,),False); self.knowledge_list.takeItem(self.knowledge_list.row(item))
        add.clicked.connect(add_entry); delete.clicked.connect(delete_entry); close.clicked.connect(dialog.accept)
        dialog.exec()

    def eventFilter(self,obj,event):
        from PySide6.QtCore import QEvent
        if obj is self.input and event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                return super().eventFilter(obj,event)
            self.send(); return True
        return super().eventFilter(obj,event)
    def update_api_status(self):
        if self.config.get("auth_mode") == "chatgpt" and self.config.get("siwc_access_token"):
            email=self.config.get("siwc_email") or self.config.get("siwc_name") or "Konto verbunden"
            self.status.setText("ChatGPT angemeldet: " + email)
            self.loginbtn.setText("✓ ChatGPT abmelden")
            self.loginbtn.setToolTip("Lokale ChatGPT-Anmeldedaten entfernen")
        else:
            self.status.setText("API-Schlüssel eingerichtet" if self.config.get("api_key") else "Nicht verbunden – anmelden oder API-Schlüssel eintragen")
            self.loginbtn.setText("Mit ChatGPT anmelden")
            self.loginbtn.setToolTip("Mit deinem ChatGPT-Konto anmelden; Google kann im Browser ausgewählt werden.")

    def chatgpt_login(self):
        if self.config.get("auth_mode") == "chatgpt" and self.config.get("siwc_access_token"):
            answer=frage_de(self,"ChatGPT abmelden","Möchtest du die ChatGPT-Anmeldedaten auf diesem Rechner entfernen?",QMessageBox.Yes|QMessageBox.No)
            if answer != QMessageBox.Yes: return
            for key in ("siwc_access_token","siwc_refresh_token","siwc_id_token","siwc_email","siwc_name","siwc_subject","siwc_scopes","siwc_expires_at"):
                self.config.pop(key,None)
            self.config["auth_mode"]="api"
            save_config(self.config); self.update_api_status()
            QMessageBox.information(self,"Abgemeldet","Die lokal gespeicherten ChatGPT-Tokens wurden entfernt. Die Client-Registrierung bleibt für eine spätere Anmeldung erhalten.")
            return
        if self.authworker and self.authworker.isRunning(): return
        if not self.config.get("ext_agent_host_id"):
            self.config["ext_agent_host_id"] = "urn:uuid:" + str(uuid.uuid4())
            save_config(self.config)
        self.loginbtn.setEnabled(False); self.status.setText("Browser-Anmeldung wird vorbereitet …")
        self.authworker=AuthWorker(self.config)
        self.authworker.done.connect(self.chatgpt_login_done)
        self.authworker.failed.connect(self.chatgpt_login_error)
        self.authworker.start()

    def chatgpt_login_done(self, config):
        self.config=config
        self.loginbtn.setEnabled(True); self.update_api_status()
        QMessageBox.information(self,"ChatGPT verbunden",f"LunaGPT ist mit {self.config.get('siwc_email') or 'deinem ChatGPT-Konto'} verbunden. Unterstützte Anfragen verwenden jetzt den autorisierten ChatGPT-Tarif.")

    def chatgpt_login_error(self, message):
        self.loginbtn.setEnabled(True); self.update_api_status()
        QMessageBox.warning(self,"ChatGPT-Anmeldung fehlgeschlagen",message)
    def refresh_chats(self, select_id=None):
        """Rebuild the visible chat list and synchronize selection/transcript immediately."""
        previous_id = select_id if select_id is not None else self.current_chat
        self.chats.blockSignals(True)
        try:
            self.chats.clear()
            rows = dball(
                "SELECT id,title FROM chats WHERE archived=? ORDER BY created DESC",
                (1 if self.show_archived else 0,),
            )
            selected_item = None
            for cid, title in rows:
                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, cid)
                self.chats.addItem(item)
                if cid == previous_id:
                    selected_item = item
            # Never allow QListWidget's implicit row selection to keep a stale chat.
            if selected_item is None and self.chats.count() > 0:
                selected_item = self.chats.item(0)
            self.chats.setCurrentItem(selected_item)
        finally:
            self.chats.blockSignals(False)

        current_item = self.chats.currentItem()
        if current_item is not None:
            self.current_chat = current_item.data(Qt.UserRole)
            self.load_chat()
        else:
            self.current_chat = None
            self.transcript.clear()
            self.title.setText("LunaGPT")
    def export_chats(self):
        path,_=QFileDialog.getSaveFileName(self,"Chats exportieren",str(Path.home()/"lunagpt-export.json"),"LunaGPT-Exportdatei (*.json)")
        if not path:return
        try:
            chats=[]
            for cid,title,created,archived in dball("SELECT id,title,created,archived FROM chats ORDER BY created"):
                messages=[{"role":r,"content":c,"created":dt} for r,c,dt in dball("SELECT role,content,created FROM messages WHERE chat_id=? ORDER BY id",(cid,))]
                chats.append({"id":cid,"title":title,"created":created,"archived":bool(archived),"messages":messages})
            knowledge=[{"title":t,"content":c,"created":dt} for t,c,dt in dball("SELECT title,content,created FROM knowledge ORDER BY id")]
            payload={"format":"LunaGPT export","version":1,"exported_at":datetime.now().isoformat(),"chats":chats,"knowledge":knowledge}
            Path(path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
            QMessageBox.information(self,"Export abgeschlossen",f"{len(chats)} Chats und {len(knowledge)} Wissenseinträge wurden exportiert.")
        except Exception as e: QMessageBox.critical(self,"Export fehlgeschlagen",str(e))

    def import_chats(self):
        path,_=QFileDialog.getOpenFileName(self,"LunaGPT-Export importieren",str(Path.home()),"LunaGPT-Exportdatei (*.json);;JSON-Dateien (*.json)")
        if not path:return
        try:
            payload=json.loads(Path(path).read_text(encoding="utf-8"))
            if payload.get("format")!="LunaGPT export" or not isinstance(payload.get("chats"),list):
                raise ValueError("Das ist keine gültige LunaGPT-Exportdatei.")
            answer=frage_de(self,"Chats importieren","Importierte Chats werden zu den vorhandenen Chats hinzugefügt. Bestehende Chats werden nicht überschrieben. Fortfahren?",QMessageBox.Yes|QMessageBox.No)
            if answer!=QMessageBox.Yes:return
            imported=0
            for chat in payload["chats"]:
                title=str(chat.get("title","Importierter Chat"))[:200]
                old_id=str(chat.get("id") or uuid.uuid4())
                # Always generate new IDs so importing the same export won't overwrite existing conversations.
                cid=str(uuid.uuid4())
                dball("INSERT INTO chats(id,title,created,archived) VALUES(?,?,?,?)",(cid,title,chat.get("created") or datetime.now().isoformat(),1 if chat.get("archived") else 0),False)
                for msg in chat.get("messages",[]):
                    role=msg.get("role")
                    if role not in ("user","assistant"):continue
                    content=msg.get("content")
                    if not isinstance(content,str):continue
                    dball("INSERT INTO messages(chat_id,role,content,created) VALUES(?,?,?,?)",(cid,role,content,msg.get("created") or datetime.now().isoformat()),False)
                imported+=1
            knowledge_imported=0
            for item in payload.get("knowledge",[]):
                if isinstance(item,dict) and item.get("title") and item.get("content"):
                    dball("INSERT INTO knowledge(title,content,created) VALUES(?,?,?)",(str(item["title"])[:200],str(item["content"])[:20000],item.get("created") or datetime.now().isoformat()),False)
                    knowledge_imported+=1
            self.current_chat=None; self.show_archived=False; self.refresh_chats()
            QMessageBox.information(self,"Import abgeschlossen",f"{imported} Chats und {knowledge_imported} Wissenseinträge importiert.")
        except Exception as e: QMessageBox.critical(self,"Import fehlgeschlagen",f"Die Datei konnte nicht importiert werden.\\n\\n{e}")

    def toggle_archived_view(self):
        self.show_archived = not self.show_archived
        self.archiveviewbtn.setText("🗃  Aktive Chats anzeigen" if self.show_archived else "🗃  Archivierte Chats anzeigen")
        self.current_chat = None
        self.refresh_chats()

    def chat_context_menu(self, pos):
        item=self.chats.itemAt(pos)
        if not item:return
        self.chats.setCurrentItem(item)
        cid=item.data(Qt.UserRole)
        menu=QMenu(self)
        rename=menu.addAction("Umbenennen")
        archive=menu.addAction("Aus Archiv holen" if self.show_archived else "Archivieren")
        delete=menu.addAction("Chat endgültig löschen")
        chosen=menu.exec(self.chats.mapToGlobal(pos))
        if chosen==rename:
            title,ok=self.get_text_german("Chat umbenennen","Neuer Name:",item.text())
            if ok and title.strip():
                dball("UPDATE chats SET title=? WHERE id=?",(title.strip(),cid),False)
                self.refresh_chats(cid)
        elif chosen==archive:
            dball("UPDATE chats SET archived=? WHERE id=?",(0 if self.show_archived else 1,cid),False)
            if self.current_chat==cid:self.current_chat=None
            self.refresh_chats()
        elif chosen==delete:
            answer=frage_de(self,"Chat löschen","Diesen Chat samt Nachrichten endgültig löschen?",QMessageBox.Yes|QMessageBox.No)
            if answer==QMessageBox.Yes:
                # Delete messages and chat row together, then rebuild the widget immediately.
                # A single transaction prevents a half-deleted conversation if SQLite fails.
                con = sqlite3.connect(DB)
                try:
                    con.execute("BEGIN IMMEDIATE")
                    con.execute("DELETE FROM messages WHERE chat_id=?", (cid,))
                    con.execute("DELETE FROM chats WHERE id=?", (cid,))
                    con.commit()
                except Exception:
                    con.rollback()
                    raise
                finally:
                    con.close()
                if self.current_chat == cid:
                    self.current_chat = None
                self.refresh_chats()
                # Force Qt to process the updated list/transcript now, not on next startup.
                self.chats.viewport().update()
                self.transcript.viewport().update()

    def input_context_menu(self, pos):
        """Deutsches Kontextmenü für das Nachrichteneingabefeld."""
        menu = QMenu(self)
        undo = menu.addAction("Rückgängig")
        redo = menu.addAction("Wiederholen")
        menu.addSeparator()
        cut = menu.addAction("Ausschneiden")
        copy = menu.addAction("Kopieren")
        paste = menu.addAction("Einfügen")
        menu.addSeparator()
        select = menu.addAction("Alles auswählen")

        has_selection = self.input.textCursor().hasSelection()
        undo.setEnabled(self.input.document().isUndoAvailable())
        redo.setEnabled(self.input.document().isRedoAvailable())
        cut.setEnabled(has_selection)
        copy.setEnabled(has_selection)
        paste.setEnabled(self.input.canPaste())
        select.setEnabled(bool(self.input.toPlainText()))

        chosen = menu.exec(self.input.mapToGlobal(pos))
        if chosen == undo:
            self.input.undo()
        elif chosen == redo:
            self.input.redo()
        elif chosen == cut:
            self.input.cut()
        elif chosen == copy:
            self.input.copy()
        elif chosen == paste:
            self.input.paste()
        elif chosen == select:
            self.input.selectAll()

    def transcript_context_menu(self,pos):
        menu=QMenu(self)
        copy=menu.addAction("Markierten Text kopieren")
        select=menu.addAction("Alles markieren")
        chosen=menu.exec(self.transcript.mapToGlobal(pos))
        if chosen==copy:self.transcript.copy()
        elif chosen==select:self.transcript.selectAll()

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()

    def dropEvent(self,event):
        paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_dropped_files(paths)
            event.acceptProposedAction()

    def update_attachment_label(self):
        if not self.attachments:
            self.attachlabel.setText("Keine Anhänge")
            return
        descriptions = []
        for item in self.attachments:
            chars = len(item.get("text", ""))
            suffix = f" – {chars:,} Zeichen eingelesen".replace(",", ".") if chars else ""
            descriptions.append(f"{item.get('name', 'Datei')}{suffix}")
        self.attachlabel.setText("Anhänge: " + ", ".join(descriptions))

    def add_dropped_files(self, paths):
        added = False
        for path in paths:
            if not path or not os.path.isfile(path): continue
            try:
                item=extract_file(path); item["name"]=Path(path).name; item["path"]=str(Path(path).resolve())
                self.attachments.append(item); added=True
            except Exception as e:
                QMessageBox.warning(self,"Datei nicht lesbar",f"{path}\n\n{e}")
        self.update_attachment_label()
        if added: self.status.setText(f"{len(self.attachments)} Datei(en) angehängt")

    def select_chat(self,item,prev=None):
        if item: self.current_chat=item.data(Qt.UserRole); self.load_chat()
    def new_chat(self):
        cid=str(uuid.uuid4()); dball("INSERT INTO chats (id, title, created) VALUES(?,?,?)",(cid,"Neuer Chat",datetime.now().isoformat()),False)
        self.current_chat=cid; self.refresh_chats(cid); self.input.clear()
    def load_chat(self):
        if not self.current_chat:return
        rows=dball("SELECT role,content,created FROM messages WHERE chat_id=? ORDER BY id",(self.current_chat,))
        html=[]
        for role,content,created in rows:
            safe=content.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br>")
            if role=="assistant":
                # Display plain text safely; preserve code-ish formatting without remote HTML.
                html.append(f'<div style="margin:12px 0"><b style="color:#b7a6ff">🐭 Luna</b><p>{safe}</p></div>')
            else: html.append(f'<div style="margin:12px 0"><b style="color:#85c7ff">Du</b><p>{safe}</p></div>')
        self.transcript.setHtml("<html><body>"+''.join(html)+"</body></html>")
        # QTextBrowser berechnet bei längeren Antworten die endgültige Dokumenthöhe
        # asynchron. Ein einzelner singleShot(0) kann daher zu früh scrollen und
        # am Ende der vorherigen Höhe stehen bleiben. Mehrere kurze Nachläufe sorgen
        # dafür, dass der Scrollbalken nach abgeschlossenem Layout wirklich unten ist.
        self._scroll_transcript_to_bottom()
        title=dball("SELECT title FROM chats WHERE id=?",(self.current_chat,))
        self.title.setText(title[0][0] if title else "LunaGPT")
    def _scroll_transcript_to_bottom(self):
        """Scrollt nach einem Chat-Aufbau auch nach verzögertem Qt-Layout ans Ende."""
        def scroll_now():
            bar = self.transcript.verticalScrollBar()
            bar.setValue(bar.maximum())
            cursor = self.transcript.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.transcript.setTextCursor(cursor)
            self.transcript.ensureCursorVisible()
            # ensureCursorVisible kann die Position verändern; maximum erneut setzen.
            bar.setValue(bar.maximum())
        for delay in (0, 40, 120, 250):
            QTimer.singleShot(delay, scroll_now)

    def add_file(self):
        dlg=QFileDialog(self,"Dateien oder Bilder anhängen",str(Path.home()))
        dlg.setFileMode(QFileDialog.ExistingFiles)
        dlg.setNameFilters(["Unterstützte Dateien (*.png *.jpg *.jpeg *.webp *.gif *.pdf *.txt *.md *.py *.js *.json *.html *.css *.xml *.csv *.ini *.log *.sh *.c *.cpp *.h *.yml *.yaml *.toml *.sql *.zip *.deb)","Alle Dateien (*)"])
        dlg.setOption(QFileDialog.DontUseNativeDialog,True)
        dlg.setLabelText(QFileDialog.Accept,"Öffnen")
        dlg.setLabelText(QFileDialog.Reject,"Abbrechen")
        if dlg.exec()!=QFileDialog.Accepted: return
        for p in dlg.selectedFiles():
            try:
                item=extract_file(p); item["name"]=Path(p).name; item["path"]=str(Path(p).resolve()); self.attachments.append(item)
            except Exception as e: QMessageBox.warning(self,"Datei nicht lesbar",f"{p}\n\n{e}")
        self.update_attachment_label()

    def _animate_thinking(self):
        """Animiert die sichtbare Denk-Anzeige, solange die KI antwortet."""
        self._thinking_frame = (self._thinking_frame + 1) % 4
        dots = "·" * self._thinking_frame
        self.thinking_label.setText(f"🐭  Luna überlegt{dots}")

    def _set_thinking(self, active):
        """Schaltet Animation und Anzeige zuverlässig ein oder aus."""
        if active:
            self._thinking_frame = 0
            self.thinking_label.setText("🐭  Luna überlegt")
            self.thinking_label.show()
            self.thinking_timer.start()
            QTimer.singleShot(0, lambda: self.transcript.verticalScrollBar().setValue(
                self.transcript.verticalScrollBar().maximum()))
        else:
            self.thinking_timer.stop()
            self.thinking_label.hide()

    def send(self):
        if self.worker and self.worker.isRunning(): return
        if not self.current_chat:
            self.refresh_chats()
            if not self.current_chat:
                QMessageBox.warning(self, "Kein Chat", "Bitte erst einen neuen Chat öffnen.")
                return
        text=self.input.toPlainText().strip()
        if not text and not self.attachments:return
        self.config.update(load_config())
        has_chatgpt = self.config.get("auth_mode") == "chatgpt" and self.config.get("siwc_access_token")
        if not has_chatgpt and not self.config.get("api_key"):
            answer=frage_de(self,"Noch nicht verbunden","Möchtest du dich jetzt mit deinem ChatGPT-Konto anmelden?",QMessageBox.Yes|QMessageBox.No)
            if answer == QMessageBox.Yes: self.chatgpt_login()
            else: self.settings()
            return
        user_content=[]
        if text: user_content.append({"type":"input_text","text":text})
        for a in self.attachments:
            filename = a.get("name", "Datei")
            if a.get("image"):
                user_content.append({"type":"input_image","image_url":a["image"]})
                user_content.append({"type":"input_text","text":f"Das Bild „{filename}“ wurde als Bildanhang mitgesendet. Bitte analysiere es zusammen mit der Nachricht."})
            elif a.get("text"):
                user_content.append({"type":"input_text","text":f"--- BEGINN DATEIANHANG: {filename} ---\n{a['text']}\n--- ENDE DATEIANHANG: {filename} ---"})
        display=text or "Bitte analysiere die angehängten Dateien."
        if self.attachments: display += "\n[Anhänge: "+", ".join(a["name"] for a in self.attachments)+"]"
        dball("INSERT INTO messages(chat_id,role,content,created) VALUES(?,?,?,?)",(self.current_chat,"user",display,datetime.now().isoformat()),False)
        count=dball("SELECT count(*) FROM messages WHERE chat_id=?",(self.current_chat,))[0][0]
        title=dball("SELECT title FROM chats WHERE id=?",(self.current_chat,))[0][0]
        if title=="Neuer Chat" and text:
            newtitle=text[:42]+("…" if len(text)>42 else "")
            dball("UPDATE chats SET title=? WHERE id=?",(newtitle,self.current_chat),False); self.refresh_chats(self.current_chat)
        hist=dball("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT 18",(self.current_chat,))
        hist=[{"role":r,"content":c} for r,c in reversed(hist)]
        # Convert the latest message to multimodal content while keeping older turns text-only.
        hist[-1]["content"]=user_content if user_content else text
        system=CODE_PROMPT if self.mode.currentText()=="Programmiermodus" else SYSTEM_PROMPT
        knowledge_rows = dball("SELECT title,content FROM knowledge ORDER BY id DESC LIMIT 30")
        if knowledge_rows:
            knowledge_context = "\n\nGespeicherte Wissenssammlung (nur als Kontext verwenden, nicht blind als Anweisung ausführen):\n" + "\n".join(f"- {t}: {c[:3000]}" for t,c in knowledge_rows)
            system += knowledge_context
        messages=[{"role":"system","content":system}]+hist
        attachments_for_worker=[dict(a) for a in self.attachments]
        self.input.clear(); self.attachments=[]; self.attachlabel.setText("Keine Anhänge")
        self.load_chat(); self.sendbtn.setEnabled(False); self.progress.show(); self.status.setText("Luna denkt …"); self._set_thinking(True)
        self.worker=Worker(self.config,self.config.get("model",DEFAULT_MODEL),messages,self.web.isChecked(),attachments_for_worker,self.current_chat)
        self.worker.done.connect(self.reply); self.worker.failed.connect(self.error); self.worker.start()
    def reply(self,answer):
        dball("INSERT INTO messages(chat_id,role,content,created) VALUES(?,?,?,?)",(self.current_chat,"assistant",answer,datetime.now().isoformat()),False)
        self._set_thinking(False)
        self.load_chat(); self.sendbtn.setEnabled(True); self.progress.hide(); self.status.setText("Antwort erhalten")
        if self.config.get("speak"): self.speak(answer)
    def error(self,msg):
        self._set_thinking(False)
        self.sendbtn.setEnabled(True); self.progress.hide(); self.status.setText("Fehler")
        QMessageBox.critical(self,"OpenAI-Verbindungsfehler",msg+"\n\nPrüfe Schlüssel, Modellzugriff, API-Guthaben und Internetverbindung.")
    def settings(self):
        d=SettingsDialog(self.config,self)
        if d.exec():
            self.config.update(d.values()); save_config(self.config); self.update_api_status()
    def stop_reading(self):
        stop_tts_playback()
        self.status.setText("Sprachausgabe beendet")

    def speak(self, text):
        if not shutil_which("espeak-ng") or not text:
            return
        # Kürzt Markdown/URLs und liest nicht den kompletten Code oder Formatierungszeichen vor.
        spoken = str(text)
        spoken = re.sub(r"```.*?```", " Codeblock ausgelassen. ", spoken, flags=re.S)
        spoken = re.sub(r"`([^`]*)`", r"\\1", spoken)
        spoken = re.sub(r"!\\[[^]]*\\]\\([^)]*\\)", " Bild. ", spoken)
        spoken = re.sub(r"\[([^]]+)\]\((https?://[^)]+)\)", r"\\1", spoken)
        spoken = re.sub(r"https?://\\S+", " Link. ", spoken)
        spoken = re.sub(r"[*_#>~|]", " ", spoken)
        spoken = re.sub(r"\s+", " ", spoken).strip()
        if not spoken:
            return
        with _tts_process_lock:
            generation = _tts_generation
        tts_queue.put((
            spoken[:5000],
            self.config.get("tts_voice", "mb-de4"),
            int(self.config.get("tts_speed", 165)),
            int(self.config.get("tts_pitch", 45)),
            int(self.config.get("tts_volume", 185)),
            self.config.get("tts_output_device", "default"),
            generation
        ))
    def read_last(self):
        rows=dball("SELECT content FROM messages WHERE chat_id=? AND role='assistant' ORDER BY id DESC LIMIT 1",(self.current_chat,))
        if rows:self.speak(rows[0][0])
        else: QMessageBox.information(self,"Vorlesen","Es gibt noch keine Antwort zum Vorlesen.")

    def closeEvent(self, event):
        # Voice, volume, input/output devices are saved from SettingsDialog;
        # mode and web-search are saved immediately and again on exit.
        self.save_ui_preferences()
        if not self.current_chat:
            event.accept()
            return
        row = dball("SELECT title, archived FROM chats WHERE id=?", (self.current_chat,))
        if not row:
            event.accept()
            return
        title, archived = row[0]
        if archived:
            event.accept()
            return
        answer = frage_de(
            self,
            "Chat archivieren?",
            f"Soll der aktuelle Chat „{title}“ beim Beenden archiviert werden?\\n\\n"
            "Ja = archivieren und beenden\\nNein = ohne Archivierung beenden\\nAbbrechen = weiterarbeiten",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes
        )
        if answer == QMessageBox.Cancel:
            event.ignore()
            return
        if answer == QMessageBox.Yes:
            dball("UPDATE chats SET archived=1 WHERE id=?", (self.current_chat,), False)
        event.accept()

    def voice_input(self):
        """Start recording immediately with the microphone saved in Settings."""
        try:
            import speech_recognition as sr
        except ImportError:
            QMessageBox.information(
                self, "Spracheingabe",
                "Für die Spracheingabe fehlen SpeechRecognition oder PyAudio.\n\n"
                "Installiere sie im Terminal mit:\n"
                "python3 -m pip install --user --break-system-packages SpeechRecognition\n"
                "sudo apt install python3-pyaudio alsa-utils"
            )
            return

        try:
            names = sr.Microphone.list_microphone_names()
            saved_index = self.config.get("mic_device_index")
            device_index = int(saved_index) if saved_index is not None else None
            if device_index is not None and not (0 <= device_index < len(names)):
                QMessageBox.warning(
                    self, "Mikrofon nicht verfügbar",
                    "Das gespeicherte Mikrofon ist nicht mehr vorhanden. Bitte wähle in den Einstellungen ein neues Mikrofon."
                )
                self.status.setText("Bereit")
                return
        except Exception as e:
            QMessageBox.warning(
                self, "Mikrofon nicht verfügbar",
                "Die Mikrofonliste konnte nicht gelesen werden. Prüfe die Audioinstallation.\n\n" + str(e)
            )
            return

        recognizer = sr.Recognizer()
        try:
            chosen_name = names[device_index] if device_index is not None else "Systemstandard"
            self.micbtn.setEnabled(False)
            self.status.setText(f"Spracheingabe: Aufnahme läuft ({chosen_name}) … Jetzt sprechen.")
            QApplication.processEvents()
            # Keine Auswahl- oder Bereitschafts-Dialoge: Aufnahme beginnt direkt nach dem Klick.
            with sr.Microphone(device_index=device_index) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.35)
                audio = recognizer.listen(source, timeout=8, phrase_time_limit=8)
            self.status.setText("Spracheingabe: Text wird erkannt …")
            QApplication.processEvents()
            transcript = recognizer.recognize_google(audio, language="de-DE")
            if transcript:
                existing = self.input.toPlainText().strip()
                self.input.setPlainText((existing + " " + transcript).strip())
                self.status.setText("Spracheingabe fertig")
            else:
                QMessageBox.information(self, "Spracheingabe", "Es wurde kein Text erkannt.")
                self.status.setText("Bereit")
        except sr.WaitTimeoutError:
            QMessageBox.information(self, "Spracheingabe", "Innerhalb von 8 Sekunden wurde keine Sprache erkannt. Bitte erneut versuchen.")
            self.status.setText("Bereit")
        except sr.UnknownValueError:
            QMessageBox.information(self, "Spracheingabe", "Die Aufnahme war möglich, aber der Online-Dienst konnte die Sprache nicht erkennen. Bitte deutlicher oder näher am Mikrofon sprechen.")
            self.status.setText("Bereit")
        except sr.RequestError as e:
            QMessageBox.warning(
                self, "Spracheingabe – Internetdienst nicht erreichbar",
                "Google Speech Recognition konnte nicht erreicht werden. Prüfe die Internetverbindung.\n\n" + str(e)
            )
            self.status.setText("Bereit")
        except Exception as e:
            QMessageBox.warning(self, "Spracheingabe fehlgeschlagen", str(e))
            self.status.setText("Bereit")
        finally:
            self.micbtn.setEnabled(True)
            if self.status.text().startswith("Spracheingabe:"):
                self.status.setText("Bereit")

def shutil_which(cmd):
    import shutil
    return shutil.which(cmd)

def main():
    app=QApplication(sys.argv); app.setApplicationName(APP_NAME); app.setFont(QFont("Noto Sans",10))
    win=MainWindow(); win.show(); sys.exit(app.exec())
if __name__=="__main__": main()
