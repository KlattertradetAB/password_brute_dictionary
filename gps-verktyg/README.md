# gps-verktyg

Verktyg för att läsa GPS-position från din egen mobiltelefon på din dator.
Allt sker lokalt — inga positionsdata skickas någonstans.

## Mappar

| Mapp | För | Hur det fungerar |
|---|---|---|
| [`iphone-mac/`](iphone-mac/) | **iPhone + Mac** | Liten webbserver på Macen som du öppnar i Safari på iPhonen. Telefonens riktiga GPS läses via webbläsaren och visas live på Macen. |
| [`android/`](android/) | **Android + dator** | Läser GPS direkt över USB-kabeln via ADB (`dumpsys location`). |

## Vilken ska jag använda?

- Har du **iPhone** → gå till [`iphone-mac/`](iphone-mac/README.md).
- Har du **Android** → gå till [`android/`](android/README.md).

Varje mapp har en egen README med steg-för-steg-instruktioner.

## Snabbstart

**iPhone + Mac:**
```bash
cd iphone-mac
python3 gps_server.py
```
Öppna sedan den utskrivna adressen i Safari på iPhonen.

**Android:**
```bash
cd android
python3 gps.py
```
Anslut telefonen med USB och godkänn USB-felsökning.

## Viktigt om iPhone

Apple tillåter inte att en dator läser iPhonens GPS direkt över kabeln (ingen
ADB-motsvarighet finns). Därför använder iPhone-verktyget webbläsarens
Geolocation-API — den enda väg Apple tillåter. Se [`iphone-mac/README.md`](iphone-mac/README.md)
för detaljer.
