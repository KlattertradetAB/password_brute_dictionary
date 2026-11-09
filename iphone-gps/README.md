# iphone-gps (för Mac + iPhone)

Läs GPS-positionen från **din egen iPhone** på din **Mac**.

## Varför det ser ut så här

Till skillnad från Android finns det **ingen** väg för en dator att läsa iPhonens
GPS direkt via kabeln — Apple tillåter det helt enkelt inte. iOS ger bara platsen
till appar, och bara med din tillåtelse.

Den väg som **fungerar**, och som matchar idén "ett script på datorn som jag går in
i från mobilen": Macen startar en liten **webbserver** som du öppnar i **Safari** på
iPhonen. Du trycker på en knapp, Safari frågar om platstillåtelse, och telefonens
**riktiga GPS-position** skickas tillbaka och visas live på Macen. Det använder
telefonens egen GPS via webbläsarens Geolocation-API.

Inget skickas utanför din Mac. Allt sker mellan din iPhone och din dator.

## Kom igång

Du behöver bara det som redan finns på en Mac (Python 3 + openssl).

### 1. Starta servern på Macen

```bash
cd iphone-gps
python3 gps_server.py
```

Första gången skapas ett självsignerat certifikat (engångs). Servern skriver ut en
eller flera adresser, t.ex.:

```
Öppna EN av dessa adresser i Safari på iPhonen:

    https://172.20.10.1:8443      (iPhone USB-kabel)
    https://192.168.1.42:8443     (nätverk (wifi/ethernet))
```

### 2. Anslut iPhonen och öppna adressen

- **Via kabel:** koppla in iPhonen i Macen. Då skapas ett "iPhone USB"-nätverk och
  adressen som är märkt **iPhone USB-kabel** fungerar.
- **Via wifi:** se till att iPhone och Mac är på samma nät och använd nätverks­adressen.

Öppna adressen i **Safari** på iPhonen.

### 3. Godkänn certifikatet (en gång)

Safari varnar för "osäker anslutning" (det är det självsignerade certet).
Tryck **Visa detaljer → besök denna webbplats**. Det behövs bara första gången.

### 4. Tryck "Starta GPS" och tillåt plats

Positionen uppdateras live på sidan — och skrivs ut på Macen i terminalen, med en
färdig Apple Maps-länk.

## Val

```bash
python3 gps_server.py                 # standardport 8443
python3 gps_server.py -p 9000         # annan port
python3 gps_server.py --log           # spara varje position till positioner.jsonl
python3 gps_server.py --log mina.jsonl   # egen loggfil
```

Terminalen visar varje uppdatering:

```
[14:03:21]  59.329301, 18.068599  ±8 m   https://maps.apple.com/?ll=59.329301,18.068599
```

## Felsökning

| Problem | Lösning |
|---|---|
| Safari säger bara "osäker anslutning" | Tryck **Visa detaljer → besök denna webbplats**. Certet är självsignerat, det är väntat. |
| Knappen gör inget / "Du nekade platsåtkomst" | Tillåt plats när Safari frågar. Annars: iPhone → Inställningar → Safari → rensa och försök igen, och kontrollera Inställningar → Integritet → Platstjänster → Safari. |
| iPhonen når inte adressen | Prova den andra adressen (USB vs wifi). Via kabel: använd `172.20.10.x`-adressen. Kontrollera att Macens brandvägg inte blockerar Python. |
| "±stor osäkerhet" / ingen fix | Gå nära ett fönster eller ut. GPS tar några sekunder att få fix. Sidan uppdateras automatiskt när den blir bättre. |
| Positionen uppdateras inte | Lämna skärmen på och Safari i förgrunden — iOS pausar GPS i bakgrunden. |

## Alternativ, om du hellre vill (utan webbserver)

**iOS Genväg (Shortcut):** skapa en genväg med *Hämta aktuell plats* → *Spara fil* till
iCloud Drive. Macen läser sedan filen från `~/Library/Mobile Documents/...`. Säg till
om du vill ha hjälp att sätta upp den varianten istället.

## Och Android?

Mappen `../mobil-gps/` innehåller motsvarande verktyg för Android, som läser GPS direkt
över USB via ADB.
