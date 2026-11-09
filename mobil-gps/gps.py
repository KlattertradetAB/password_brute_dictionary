#!/usr/bin/env python3
"""
mobil-gps — läs GPS-position från din egen Android-telefon via USB-kabel.

Verktyget pratar med telefonen över ADB (Android Debug Bridge). Telefonen måste
vara ansluten med kabel och själv godkänna anslutningen (USB-felsökning), så det
fungerar bara på en telefon du fysiskt har och säger "ja" på.

Användning:
    python3 gps.py              # läs positionen en gång
    python3 gps.py --watch      # läs om positionen var 5:e sekund
    python3 gps.py --watch -i 2 # läs var 2:a sekund
    python3 gps.py --json       # skriv ut som JSON
    python3 gps.py --check      # kontrollera bara att telefonen är ansluten

Ingen rot (root) på telefonen behövs. Inga data skickas någonstans — allt sker
lokalt mellan din dator och din telefon.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone


def _run(args, timeout=15):
    """Kör ett adb-kommando och returnera (returkod, stdout, stderr)."""
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        print(
            "Fel: 'adb' hittades inte. Installera Android Platform Tools:\n"
            "  • Windows/macOS/Linux: https://developer.android.com/tools/releases/platform-tools\n"
            "  • macOS (Homebrew):   brew install android-platform-tools\n"
            "  • Debian/Ubuntu:      sudo apt install android-tools-adb\n"
            "  • Arch:               sudo pacman -S android-tools",
            file=sys.stderr,
        )
        sys.exit(2)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def check_adb():
    """Se till att adb finns i PATH."""
    if shutil.which("adb") is None:
        _run(["adb", "version"])  # skriver ut installationshjälpen och avslutar
    return True


def connected_devices():
    """Returnera en lista med (serienummer, status) för anslutna enheter."""
    rc, out, _ = _run(["adb", "devices"])
    devices = []
    for line in out.splitlines()[1:]:  # hoppa över rubrikraden
        line = line.strip()
        if not line or "\t" not in line:
            continue
        serial, status = line.split("\t", 1)
        devices.append((serial.strip(), status.strip()))
    return devices


def ensure_one_device():
    """Kontrollera att exakt en telefon är ansluten och godkänd. Avsluta annars."""
    devices = connected_devices()
    if not devices:
        print(
            "Ingen telefon hittades.\n"
            "  1. Anslut telefonen med USB-kabel.\n"
            "  2. Slå på Utvecklarläge: Inställningar → Om telefonen → tryck 7 gånger på 'Versionsnummer'.\n"
            "  3. Slå på 'USB-felsökning' under Inställningar → Utvecklaralternativ.\n"
            "  4. Lås upp telefonen och tryck 'Tillåt' på rutan om USB-felsökning.",
            file=sys.stderr,
        )
        sys.exit(1)

    unauthorized = [s for s, st in devices if st == "unauthorized"]
    if unauthorized:
        print(
            "Telefonen är ansluten men inte godkänd.\n"
            "Lås upp telefonen och tryck 'Tillåt' på rutan 'Tillåt USB-felsökning?'.\n"
            "Bocka gärna i 'Tillåt alltid från den här datorn'.",
            file=sys.stderr,
        )
        sys.exit(1)

    ok = [s for s, st in devices if st == "device"]
    if len(ok) == 0:
        statuses = ", ".join(f"{s} ({st})" for s, st in devices)
        print(f"Telefon hittad men inte klar: {statuses}", file=sys.stderr)
        sys.exit(1)
    if len(ok) > 1:
        print(
            "Flera enheter anslutna: " + ", ".join(ok) + "\n"
            "Koppla ur de du inte vill läsa från, eller sätt miljövariabeln "
            "ANDROID_SERIAL till rätt serienummer.",
            file=sys.stderr,
        )
        sys.exit(1)
    return ok[0]


def is_location_enabled():
    """True om platstjänster (GPS) är påslaget i telefonens inställningar."""
    rc, out, _ = _run(["adb", "shell", "settings", "get", "secure", "location_mode"])
    mode = out.strip()
    # 0 = av, 1/2/3 = olika lägen på. Null betyder att nyckeln inte finns (nyare Android).
    if mode in ("1", "2", "3"):
        return True
    if mode == "0":
        return False
    # Fallback för nyare Android: läs location_providers_allowed
    rc, out, _ = _run(
        ["adb", "shell", "settings", "get", "secure", "location_providers_allowed"]
    )
    return bool(out.strip()) and out.strip().lower() != "null"


def parse_location(dumpsys_text):
    """
    Plocka ut senaste kända position ur 'dumpsys location'.
    Returnerar en dict eller None.

    Formatet varierar mellan Android-versioner. Vi letar efter rader som:
      fused: Location[fused 59.329300,18.068600 hAcc=12 ...]
      gps:   Location[gps 59.329300,18.068600 ...]
    och tar den bästa (minst osäkerhet) vi hittar.
    """
    # Hitta alla Location[...]-block
    candidates = []
    pattern = re.compile(
        r"Location\[(?P<provider>\w+)\s+"
        r"(?P<lat>-?\d+\.\d+),(?P<lon>-?\d+\.\d+)"
        r"(?P<rest>[^\]]*)\]"
    )
    for m in pattern.finditer(dumpsys_text):
        rest = m.group("rest")
        acc_m = re.search(r"hAcc=(\d+(?:\.\d+)?)", rest)
        alt_m = re.search(r"alt=(-?\d+(?:\.\d+)?)", rest)
        et_m = re.search(r"et=([\w+smhd]+)", rest)
        candidates.append(
            {
                "provider": m.group("provider"),
                "lat": float(m.group("lat")),
                "lon": float(m.group("lon")),
                "accuracy_m": float(acc_m.group(1)) if acc_m else None,
                "altitude_m": float(alt_m.group(1)) if alt_m else None,
                "age": et_m.group(1) if et_m else None,
            }
        )

    if not candidates:
        return None

    # Föredra 'fused', annars 'gps', annars första. Inom samma typ: lägst osäkerhet.
    def rank(c):
        provider_rank = {"fused": 0, "gps": 1, "network": 2}.get(c["provider"], 3)
        acc = c["accuracy_m"] if c["accuracy_m"] is not None else 9999
        return (provider_rank, acc)

    candidates.sort(key=rank)
    return candidates[0]


def get_location():
    """Hämta senaste kända position från telefonen. Returnerar dict eller None."""
    rc, out, err = _run(["adb", "shell", "dumpsys", "location"], timeout=20)
    if rc != 0:
        print(f"adb-fel vid läsning av position: {err.strip()}", file=sys.stderr)
        return None
    return parse_location(out)


def format_human(loc):
    if loc is None:
        return "Ingen position tillgänglig ännu. Öppna en kart-app på telefonen " \
               "(t.ex. Google Maps) en stund så den får GPS-fix, och försök igen."
    lat, lon = loc["lat"], loc["lon"]
    maps = f"https://www.google.com/maps?q={lat},{lon}"
    lines = [
        f"Position:   {lat:.6f}, {lon:.6f}",
        f"Källa:      {loc['provider']}",
    ]
    if loc.get("accuracy_m") is not None:
        lines.append(f"Osäkerhet:  ±{loc['accuracy_m']:.0f} m")
    if loc.get("altitude_m") is not None:
        lines.append(f"Höjd:       {loc['altitude_m']:.0f} m")
    if loc.get("age"):
        lines.append(f"Ålder:      {loc['age']} sedan senaste fix")
    lines.append(f"Karta:      {maps}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="Läs GPS-position från din egen Android-telefon via USB-kabel.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--watch", action="store_true", help="Läs om positionen löpande.")
    ap.add_argument(
        "-i", "--interval", type=float, default=5.0,
        help="Sekunder mellan avläsningar i --watch-läge (standard: 5).",
    )
    ap.add_argument("--json", action="store_true", help="Skriv ut som JSON.")
    ap.add_argument(
        "--check", action="store_true",
        help="Kontrollera bara anslutning och platstjänster, läs ingen position.",
    )
    args = ap.parse_args()

    check_adb()
    _run(["adb", "start-server"], timeout=30)
    serial = ensure_one_device()
    loc_on = is_location_enabled()

    if args.check:
        print(f"OK: telefon ansluten och godkänd (serienummer: {serial}).")
        print("Platstjänster (GPS): " + ("PÅ" if loc_on else "AV — slå på i telefonens inställningar."))
        return

    if not loc_on:
        print(
            "Obs: platstjänster verkar vara avstängda på telefonen. "
            "Slå på GPS/plats i snabbinställningarna eller under "
            "Inställningar → Plats, annars finns ingen färsk position.",
            file=sys.stderr,
        )

    def emit(loc):
        if args.json:
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "device": serial,
                "location": loc,
            }
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(format_human(loc))

    if not args.watch:
        emit(get_location())
        return

    print(f"Läser position var {args.interval:g}:e sekund. Avbryt med Ctrl+C.\n",
          file=sys.stderr)
    try:
        while True:
            loc = get_location()
            if not args.json:
                print("—" * 40)
                print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            emit(loc)
            time.sleep(max(0.5, args.interval))
    except KeyboardInterrupt:
        print("\nAvslutar.", file=sys.stderr)


if __name__ == "__main__":
    main()
