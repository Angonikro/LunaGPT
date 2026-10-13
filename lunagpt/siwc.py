"""OpenAI Sign in with ChatGPT (open-source client flow).

Implements Authorization Code + PKCE, local loopback callback, ID-token
verification, refresh-token rotation, and streamed Responses API inference.
"""
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

AUTH_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _http_json(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
            detail = detail.get("error_description") or detail.get("error") or detail.get("message") or detail
        except Exception:
            detail = body
        raise RuntimeError(f"HTTP {exc.code}: {str(detail)[:900]}") from exc


def _verify_id_token(token, expected_client_id, expected_nonce):
    """Verify RS256 signature and the core OIDC claims before trusting identity."""
    try:
        head, body, signature = token.split(".")
        header = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    except Exception as exc:
        raise RuntimeError("OpenAI hat kein gültiges ID-Token zurückgegeben.") from exc
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise RuntimeError("Nicht unterstützter Signaturalgorithmus im ID-Token.")
    jwks = _http_json(JWKS_URL, timeout=20)
    jwk = next((k for k in jwks.get("keys", []) if k.get("kid") == header["kid"] and k.get("kty") == "RSA"), None)
    if not jwk:
        raise RuntimeError("OpenAI-Signaturschlüssel für das ID-Token wurde nicht gefunden.")
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        n = int.from_bytes(base64.urlsafe_b64decode(jwk["n"] + "=" * (-len(jwk["n"]) % 4)), "big")
        e = int.from_bytes(base64.urlsafe_b64decode(jwk["e"] + "=" * (-len(jwk["e"]) % 4)), "big")
        key = rsa.RSAPublicNumbers(e, n).public_key()
        key.verify(sig, (head + "." + body).encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise RuntimeError("Die Signatur des OpenAI-ID-Tokens konnte nicht verifiziert werden.") from exc
    now = int(time.time())
    aud = claims.get("aud")
    if claims.get("iss") != ISSUER:
        raise RuntimeError("Unerwarteter Aussteller im ID-Token.")
    if not (aud == expected_client_id or isinstance(aud, list) and expected_client_id in aud):
        raise RuntimeError("Die Zielgruppe des ID-Tokens passt nicht zur LunaGPT-Anmeldung.")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < now - 5:
        raise RuntimeError("Das ID-Token ist abgelaufen.")
    if claims.get("nonce") != expected_nonce:
        raise RuntimeError("Die Sicherheitsprüfung der Anmeldung (nonce) ist fehlgeschlagen.")
    if not claims.get("sub"):
        raise RuntimeError("Im ID-Token fehlt die Konto-ID.")
    return claims


def sign_in(config):
    """Complete official ChatGPT plan OAuth flow in the user's system browser."""
    host_id = config.get("ext_agent_host_id") or "urn:uuid:" + str(uuid.uuid4())
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    existing_client = config.get("siwc_client_id", "").strip()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_error(404)
                return
            self.server.callback_params = urllib.parse.parse_qs(parsed.query)
            page = ("<!doctype html><html><meta charset='utf-8'><title>LunaGPT</title>"
                    "<body style='font:18px sans-serif;padding:3em'>Anmeldung empfangen. "
                    "Du kannst dieses Browserfenster schließen und zu LunaGPT zurückkehren.</body></html>")
            data = page.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_port}/auth/callback"
    params = {
        "client_id": existing_client or "dynamic_agent_client",
        "response_type": "code", "redirect_uri": redirect_uri,
        "scope": SCOPES, "resource": RESOURCE, "state": state,
        "nonce": nonce, "code_challenge_method": "S256", "code_challenge": challenge,
        "ext_agent_host_id": host_id,
    }
    if not existing_client:
        params["agent_name_hint"] = "LunaGPT"
    elif config.get("siwc_id_token"):
        params["id_token_hint"] = config["siwc_id_token"]
        if config.get("siwc_email"):
            params["login_hint"] = config["siwc_email"]
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    try:
        if not webbrowser.open(url):
            # The browser opener may return False on some desktop environments despite launching.
            pass
        deadline = time.monotonic() + 300
        callback = None
        while time.monotonic() < deadline:
            server.handle_request()
            callback = getattr(server, "callback_params", None)
            if callback is not None:
                break
        if callback is None:
            raise RuntimeError("Zeitüberschreitung bei der Anmeldung. Bitte erneut versuchen.")
    finally:
        server.server_close()
    returned_state = (callback.get("state") or [""])[0]
    if not secrets.compare_digest(returned_state, state):
        raise RuntimeError("Die Anmeldung wurde wegen eines ungültigen state-Werts abgebrochen.")
    if (callback.get("error") or [None])[0]:
        err = callback["error"][0]
        desc = (callback.get("error_description") or [""])[0]
        raise RuntimeError(f"Anmeldung abgebrochen: {err} {desc}".strip())
    code = (callback.get("code") or [""])[0]
    issued_client = (callback.get("client_id") or [existing_client])[0]
    if not code:
        raise RuntimeError("OpenAI hat keinen Autorisierungscode zurückgegeben.")
    if existing_client and issued_client and issued_client != existing_client:
        raise RuntimeError("OpenAI hat eine andere Client-ID als erwartet zurückgegeben; Anmeldung aus Sicherheitsgründen abgebrochen.")
    if not issued_client or issued_client == "dynamic_agent_client":
        raise RuntimeError("Die Registrierung wurde nicht abgeschlossen: Es fehlt die ausgegebene Client-ID.")
    form = urllib.parse.urlencode({
        "grant_type": "authorization_code", "client_id": issued_client,
        "code": code, "code_verifier": verifier, "redirect_uri": redirect_uri,
        "resource": RESOURCE,
    }).encode()
    tokens = _http_json(TOKEN_URL, form, {"Content-Type": "application/x-www-form-urlencoded"}, timeout=40)
    id_token = tokens.get("id_token", "")
    if not id_token:
        raise RuntimeError("OpenAI hat kein ID-Token zurückgegeben; Anmeldung nicht gespeichert.")
    claims = _verify_id_token(id_token, issued_client, nonce)
    scopes = (tokens.get("scope") or (callback.get("scope") or [""])[0]).split()
    if "chatgpt.tokens.use.direct" not in scopes:
        raise RuntimeError("Die Anmeldung war erfolgreich, aber die Berechtigung zur Nutzung des ChatGPT-Tarifs wurde nicht erteilt. Bitte erneut anmelden und diese Berechtigung erlauben. LunaGPT verwendet sonst keinen ChatGPT-Tarif.")
    config.update({
        "auth_mode": "chatgpt", "ext_agent_host_id": host_id,
        "siwc_client_id": issued_client, "siwc_subject": claims["sub"],
        "siwc_email": claims.get("email", ""), "siwc_name": claims.get("name", ""),
        "siwc_id_token": id_token, "siwc_access_token": tokens.get("access_token", ""),
        "siwc_refresh_token": tokens.get("refresh_token", ""), "siwc_scopes": scopes,
        "siwc_expires_at": int(time.time()) + int(tokens.get("expires_in", 3600)),
    })
    return config


def refresh_if_needed(config, save_callback=None):
    if not config.get("siwc_access_token"):
        raise RuntimeError("Bitte zuerst über „Mit ChatGPT anmelden“ anmelden.")
    if int(config.get("siwc_expires_at", 0)) > int(time.time()) + 90:
        return config["siwc_access_token"]
    refresh = config.get("siwc_refresh_token", "")
    if not refresh:
        raise RuntimeError("Die ChatGPT-Anmeldung ist abgelaufen. Bitte erneut anmelden.")
    form = urllib.parse.urlencode({
        "grant_type": "refresh_token", "client_id": config["siwc_client_id"],
        "refresh_token": refresh, "resource": RESOURCE,
    }).encode()
    tokens = _http_json(TOKEN_URL, form, {"Content-Type": "application/x-www-form-urlencoded"}, timeout=40)
    config["siwc_access_token"] = tokens.get("access_token", "")
    config["siwc_refresh_token"] = tokens.get("refresh_token", refresh)
    config["siwc_expires_at"] = int(time.time()) + int(tokens.get("expires_in", 3600))
    if tokens.get("scope"):
        config["siwc_scopes"] = tokens["scope"].split()
    if save_callback:
        save_callback(config)
    return config["siwc_access_token"]


def list_models(access_token):
    data = _http_json(RESOURCE + "/models", headers={"Authorization": "Bearer " + access_token}, timeout=30)
    models = data.get("models", [])
    return [(m.get("slug"), m.get("display_name") or m.get("slug")) for m in models if m.get("visibility") == "list" and m.get("slug")]


def responses_request(access_token, model, messages, use_web=False):
    instructions = ""
    inputs = []
    for item in messages:
        if item.get("role") == "system":
            instructions = item.get("content", "")
        else:
            inputs.append({"role": item["role"], "content": item["content"]})
    payload = {"model": model, "input": inputs, "instructions": instructions,
               "store": False, "stream": True}
    if use_web:
        payload["tools"] = [{"type": "web_search"}]
    req = urllib.request.Request(RESOURCE + "/responses", data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + access_token, "Content-Type": "application/json", "Accept": "text/event-stream"}, method="POST")
    pieces = []
    completed = False
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                datum = line[5:].strip()
                if not datum or datum == "[DONE]":
                    continue
                try: event = json.loads(datum)
                except json.JSONDecodeError: continue
                kind = event.get("type", "")
                if kind == "response.output_text.delta":
                    pieces.append(event.get("delta", ""))
                elif kind == "response.completed":
                    completed = True
                elif kind in ("response.failed", "error"):
                    err = event.get("response", {}).get("error") or event.get("error") or {}
                    code = err.get("code", "") if isinstance(err, dict) else ""
                    message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    raise RuntimeError(f"ChatGPT-Anfrage fehlgeschlagen{(' ['+code+']') if code else ''}: {message}")
                elif kind == "response.incomplete":
                    raise RuntimeError("Die ChatGPT-Antwort wurde unvollständig beendet.")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
            detail = detail.get("error", {}).get("message") or detail.get("detail") or detail
        except Exception:
            detail = body
        raise RuntimeError(f"ChatGPT-Anfrage HTTP {exc.code}: {str(detail)[:900]}") from exc
    if not completed:
        raise RuntimeError("Der Antwortstream endete ohne bestätigtes response.completed-Ereignis.")
    return "".join(pieces).strip() or "(Keine Textantwort erhalten.)"
