#!/usr/bin/env python3
"""
iphone-gps — läs GPS-position från din egen iPhone via din Mac.

Apple låter inte en dator läsa iPhonens GPS direkt över kabeln. Den väg som
*fungerar* är den här: Macen startar en liten webbserver som du öppnar i Safari
på iPhonen. Du trycker på en knapp, Safari frågar om platstillåtelse, och
telefonens riktiga GPS-position skickas tillbaka och visas live här på Macen.

Kör på Macen:
    python3 gps_server.py

Öppna sedan adressen som skrivs ut i Safari på iPhonen (anslut gärna med kabel —
då får du ett "iPhone USB"-nätverk — eller använd samma wifi).

Safari kräver HTTPS för GPS, så scriptet skapar ett eget (självsignerat)
certifikat första gången. På iPhonen får du en varning om "osäker anslutning" —
tryck "Visa detaljer" → "besök denna webbplats" en gång, sen funkar det.

Inga data skickas utanför din Mac. Positionen loggas valfritt till en lokal fil.
"""

import argparse
import datetime as dt
import http.server
import json
import os
import socket
import ssl
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(HERE, ".cert", "cert.pem")
KEY = os.path.join(HERE, ".cert", "key.pem")

# Senaste positionen (delas mellan trådar) så terminalen kan visa den.
_latest = {"value": None}
_log_path = None


# -----------------------------------------------------------------------------
# Certifikat
# -----------------------------------------------------------------------------
def ensure_cert():
    """Skapa ett självsignerat certifikat om det inte redan finns."""
    if os.path.exists(CERT) and os.path.exists(KEY):
        return
    os.makedirs(os.path.dirname(CERT), exist_ok=True)
    print("Skapar ett självsignerat certifikat (engångs) ...", file=sys.stderr)
    rc = subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", KEY, "-out", CERT,
            "-days", "3650", "-nodes",
            "-subj", "/CN=iphone-gps.local",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        capture_output=True, text=True,
    )
    if rc.returncode != 0:
        print("Kunde inte skapa certifikat:\n" + rc.stderr, file=sys.stderr)
        sys.exit(2)


# -----------------------------------------------------------------------------
# Nätverk — hitta vilka adresser iPhonen kan nå Macen på
# -----------------------------------------------------------------------------
def local_ipv4_addresses():
    """Returnera en lista med (etikett, ip) för Macens IPv4-adresser."""
    addrs = []
    # Primär utgående adress (oftast wifi)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary = s.getsockname()[0]
        s.close()
        addrs.append(("nätverk (wifi/ethernet)", primary))
    except OSError:
        primary = None

    # Alla adresser via ifconfig (macOS) — fångar även iPhone-USB-länken
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "127.0.0.1" not in line:
                ip = line.split()[1]
                if ip not in [a for _, a in addrs]:
                    # iPhone-USB brukar ligga på 172.20.10.x
                    label = "iPhone USB-kabel" if ip.startswith("172.20.10.") else "nätverk"
                    addrs.append((label, ip))
    except FileNotFoundError:
        pass
    return addrs


# -----------------------------------------------------------------------------
# HTML-sidan som iPhonen öppnar
# -----------------------------------------------------------------------------
PAGE = """<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>GPS → Mac</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, system-ui, sans-serif; margin: 0;
         padding: max(24px, env(safe-area-inset-top)) 20px 40px;
         display: flex; flex-direction: column; gap: 18px; max-width: 520px;
         margin-inline: auto; }
  h1 { font-size: 20px; margin: 4px 0; }
  button { font-size: 18px; padding: 16px; border-radius: 14px; border: none;
           background: #0a84ff; color: #fff; font-weight: 600; }
  button.stop { background: #ff3b30; }
  button:disabled { opacity: .4; }
  .card { background: color-mix(in srgb, Canvas 90%, CanvasText 10%);
          border-radius: 14px; padding: 16px; }
  .row { display: flex; justify-content: space-between; padding: 6px 0;
         border-bottom: 1px solid color-mix(in srgb, Canvas 70%, CanvasText 30%); }
  .row:last-child { border-bottom: none; }
  .k { opacity: .6; }
  .v { font-variant-numeric: tabular-nums; font-weight: 600; }
  a { color: #0a84ff; }
  #status { opacity: .7; font-size: 14px; }
</style>
</head>
<body>
  <h1>📍 GPS → Mac</h1>
  <p id="status">Tryck på knappen och tillåt platsåtkomst.</p>
  <button id="start">Starta GPS</button>
  <button id="stop" class="stop" hidden>Stoppa</button>
  <div class="card" id="out" hidden>
    <div class="row"><span class="k">Latitud</span><span class="v" id="lat">–</span></div>
    <div class="row"><span class="k">Longitud</span><span class="v" id="lon">–</span></div>
    <div class="row"><span class="k">Osäkerhet</span><span class="v" id="acc">–</span></div>
    <div class="row"><span class="k">Höjd</span><span class="v" id="alt">–</span></div>
    <div class="row"><span class="k">Hastighet</span><span class="v" id="spd">–</span></div>
    <div class="row"><span class="k">Uppdaterad</span><span class="v" id="ts">–</span></div>
    <div class="row"><span class="k">Karta</span><span class="v"><a id="map" target="_blank">öppna</a></span></div>
  </div>
<script>
let watchId = null;
const $ = id => document.getElementById(id);

function show(p) {
  const c = p.coords;
  $('out').hidden = false;
  $('lat').textContent = c.latitude.toFixed(6);
  $('lon').textContent = c.longitude.toFixed(6);
  $('acc').textContent = c.accuracy != null ? '±' + Math.round(c.accuracy) + ' m' : '–';
  $('alt').textContent = c.altitude != null ? Math.round(c.altitude) + ' m' : '–';
  $('spd').textContent = c.speed != null ? (c.speed * 3.6).toFixed(1) + ' km/h' : '–';
  $('ts').textContent = new Date(p.timestamp).toLocaleTimeString();
  $('map').href = 'https://maps.apple.com/?ll=' + c.latitude + ',' + c.longitude;
  $('status').textContent = 'Skickar position till din Mac …';

  fetch('/loc', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      lat: c.latitude, lon: c.longitude, accuracy: c.accuracy,
      altitude: c.altitude, speed: c.speed, heading: c.heading,
      timestamp: p.timestamp
    })
  }).catch(() => { $('status').textContent = 'Kunde inte nå Macen (nätverk?).'; });
}

function fail(e) {
  const msg = {1:'Du nekade platsåtkomst.',2:'Positionen gick inte att hämta.',3:'Tog för lång tid.'};
  $('status').textContent = 'Fel: ' + (msg[e.code] || e.message);
}

$('start').onclick = () => {
  if (!navigator.geolocation) { $('status').textContent = 'Geolocation stöds inte.'; return; }
  $('start').hidden = true; $('stop').hidden = false;
  watchId = navigator.geolocation.watchPosition(show, fail,
    { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
};
$('stop').onclick = () => {
  if (watchId != null) navigator.geolocation.clearWatch(watchId);
  $('start').hidden = false; $('stop').hidden = true;
  $('status').textContent = 'Stoppad.';
};
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/favicon.ico":
            self._send(204, b"")
        else:
            self._send(404, "not found")

    def do_POST(self):
        if self.path != "/loc":
            self._send(404, "not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, "bad json")
            return

        _latest["value"] = data
        lat, lon = data.get("lat"), data.get("lon")
        acc = data.get("accuracy")
        now = dt.datetime.now().strftime("%H:%M:%S")
        acc_s = f"  ±{acc:.0f} m" if isinstance(acc, (int, float)) else ""
        print(f"[{now}]  {lat:.6f}, {lon:.6f}{acc_s}"
              f"   https://maps.apple.com/?ll={lat},{lon}")

        if _log_path:
            rec = {"received": dt.datetime.now().isoformat(), **data}
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        self._send(200, "ok")

    def log_message(self, *args):  # tysta standardloggen
        pass


def main():
    global _log_path
    ap = argparse.ArgumentParser(
        description="Läs iPhonens GPS via en liten webbserver på din Mac.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("-p", "--port", type=int, default=8443, help="Port (standard: 8443).")
    ap.add_argument("--log", metavar="FIL", nargs="?", const="positioner.jsonl",
                    help="Spara varje position till en JSONL-fil (standard: positioner.jsonl).")
    args = ap.parse_args()

    if args.log:
        _log_path = args.log if os.path.isabs(args.log) else os.path.join(HERE, args.log)

    ensure_cert()

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)

    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    print("=" * 60)
    print("  iphone-gps — servern körs på din Mac")
    print("=" * 60)
    print("\nÖppna EN av dessa adresser i Safari på iPhonen:\n")
    for label, ip in local_ipv4_addresses():
        print(f"    https://{ip}:{args.port}      ({label})")
    print(f"\n  (Testa på Macen själv: https://localhost:{args.port} )")
    print("\n  På iPhonen: anslut gärna med kabel, öppna adressen, godkänn")
    print("  certifikatvarningen en gång, tryck 'Starta GPS' och tillåt plats.")
    if _log_path:
        print(f"\n  Loggar till: {_log_path}")
    print("\n  Positioner visas här nedan. Avbryt med Ctrl+C.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nAvslutar.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
