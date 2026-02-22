# Emulation eines SunSpec Wechselrichters für EME20 / NIBE auf Basis EVCC-Daten über Websockets

**Version:** v0.1.0 - Thread-Safe Register Updates, Code Cleanup & Konsistenz

## 💡 Changelog (v0.1.0)

### ✨ Verbesserungen
- **Thread-Safety:** Alle dynamischen Register-Updates laufen über sichere Wrapper (`update_power_register()`, `update_energy_register()`)
- **Code-Cleanup:** Doppelte Initialisierungen entfernt, Formatierung bereinigt
- **Konsistenz:** Docstrings und Kommentare auf aktuelle README abgestimmt
- **Naming:** Hersteller auf "OpenSource" standardisiert statt "Fronius"
- **Testing:** Validiert mit echten NIBE EME20 Modbus-Traces

### 🔧 Interne Änderungen
- `update_registers_from_values()` nutzt jetzt immer thread-sichere Wrapper
- Interne Helper (`_update_power_register()`, `_update_energy_register()`) dokumentiert
- Modbus-Datastore wird konsistent aktualisiert (globales Dict + Holding-Array + Store)

---

Ein Python-basierter SunSpec Modbus TCP Server, der die von NIBE EME20 erwarteten Register eines Wechselrichters (WR) emuliert. Wurde entwickelt, um eine NIBE Wärmepumpe (WP) mit EME20 mit Live-Daten von EVCC (PV-Management-System) zu versorgen.

---

## 📋 Inhaltsverzeichnis

1. [Übersicht](#übersicht)
2. [Architektur](#architektur)
3. [Quick Start](#quick-start)
4. [Installation](#installation)
5. [Konfiguration](#konfiguration)
6. [Verwendung](#verwendung)
7. [Register-Mapping](#register-mapping)
8. [Modbus Protokoll](#modbus-protokoll)
9. [Docker Deployment](#docker-deployment)
10. [Troubleshooting](#troubleshooting)
11. [Getestete Werte](#getestete-werte)

---

## 📖 Übersicht

### Was macht dieses Script?

Dieses Python-Script emuliert eine kompatible Modbus-TCP Schnittstelle und antwortet auf die gleichen Register wie ein echter WR:

- **Statische Daten:** Geräte-ID, Seriennummer, Status
- **Dynamische Daten:** Aktuelle Netzleistung und kumulierte Energie von EVCC
- **Live-Updates:** Daten alle ~1 Sekunde von EVCC WebSocket

### Wofür?

Das **NIBE EME20** der WP ist ein **Modbus-Master** und liest folgende Register von einem **Modbus-Slave** WR:
- Power (W) → zur Regelung des PV-Modus
- Total Energy (kWh) → zur Statistik
- Device Status → Prüfung, ob WR aktiv ist

Da die Daten mit mehreren WR und einer Batterie zu falschen Werten führt (z.B. Batterie wird von beiden WR geladen), EVCC jedoch über das Gesamtsystem informiert ist, werden vom Script die Daten von EVCC herangezogen und über eine authentische Modbus-Schnittstelle an die WR übermittelt. Damit wird sichergestellt, dass die WP nur in einen Boost-Modus geht, wenn ein tatsächlicher Überschuss besteht.

---

## ⚡ Quick Start

### Lokal (Python)

```bash
pip install pymodbus==2.5.3 websockets
python emulated_sunspec_inverter.py
```

### Docker (Compose)

```bash
git clone https://github.com/diestrohs/emulated-sunspec-inverter.git
cd emulated-sunspec-inverter
docker-compose -f docker-compose-emulated-sunspec-inverter.yml up -d
```

**Hinweis:** Für Live-Daten `LIVE = True` setzen und `EVCC_HOST` in `const.py` anpassen.

---

## 🏗️ Architektur

```
┌──────────────────────────────────────────────────────────────┐
│ EVCC Container (PV-Erzeugung, Batterie, Netz)               │
│   └─ WebSocket ws://<host>:7070/ws       │
│         └─ Daten: grid.power, pvEnergy (30s Heartbeat)      │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
        ┌─ EvccWebsocketClient._run()
        │  ├─ Verbindet mit Timeouts (open_timeout=10s)
        │  ├─ Filtert relevante Updates
        │  ├─ Dedupliziert Nachrichten (Signature)
        │  └─ Exponential Backoff bei Fehlern (1s → 60s)
        │      └─ Schreibt in async Message Queue
        │
┌───────┴──────────────────────────────────────────────────────┐
│ SunSpec WR Container (Modbus TCP Server)               │
│   ├─ EvccWebsocketClient._consume_messages()                 │
│   │   └─ Verarbeitet Queue asynchron (non-blocking)         │
│   └─ Aktualisiert Modbus-Register in Echtzeit               │
│       └─ Port 5202 (Modbus TCP)                             │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ NIBE EME20 der Wärmepumpe (Modbus TCP Master)                   │
│   └─ liest mit ~4ms Abstand                                  │
│   └─ aktiviert PV-Modus / Belüftung basierend auf Power     │
└──────────────────────────────────────────────────────────────┘
```

**Datenfluss:**
1. EVCC sendet PV-Daten alle ~1-2 Sekunden via WebSocket
2. Emulated SunSpec Inverter empfängt, dedupliziert und aktualisiert Register
3. EME20 liest aktuelle Werte via Modbus-TCP (~4ms Zyklus)

---

## 🔒 WebSocket Features & Thread-Safety (v0.1.0+)

### Robuste Verbindung

| Feature | Beschreibung | Wert |
|---------|-------------|------|
| **Open Timeout** | Maximale Zeit zum Verbinden | 10s |
| **Ping Interval** | Heartbeat-Frequenz | 30s |
| **Ping Timeout** | Maximale Zeit auf Pong-Response | 10s |
| **Max Message Size** | Maximale Nachrichtengröße | 1 MB |
| **Queue Size** | Asynchrone Message Queue | 100 Messages |

### Exponential Backoff bei Fehlern

Bei Verbindungsfehlern nutzt das Script intelligentes Backoff mit Jitter:

```
Versuch 1: 1s Warten
Versuch 2: 2.5s (1s + Jitter)
Versuch 3: 4.2s (2.5s + Jitter)
...
Versuch N: max 60s (Plateau)
```

**Vorteile:**
- ✅ Verhindert Server-Overload bei Fehlern
- ✅ Unbegrenzte Reconnect-Versuche
- ✅ Smooth Wiederherstellung ohne Spam

### Message Deduplication

Das Script erkennt und filtert Duplicate-Nachrichten:

```python
# Beispiel: Wenn EVCC die gleichen Daten zweimal sendet
# → Wird erkannt durch Signature-Hash und übersprungen
```

### Asynchrone Message Queue

Empfangene Nachrichten werden in eine Warteschlange geschrieben und asynchron verarbeitet:

- ✅ **Non-blocking:** WebSocket wird nicht blockiert während Register aktualisiert werden
- ✅ **Pufferung:** Bis zu 100 Messages können gepuffert werden
- ✅ **Fehlertoleranz:** Fehlerhafte Nachrichten werden geloggt, blockieren aber nicht

---

## 🚀 Installation

### Anforderungen

- **Python 3.9+**
- Paket: `pymodbus` (2.5.3)
- Paket: `websockets`

### Lokal installieren

```bash
pip install pymodbus==2.5.3 websockets
python emulated_sunspec_inverter.py
```

---

## ⚙️ Konfiguration

Alle Einstellungen befinden sich in `const.py`:

### Mode: LIVE vs. STATIC

```python
LIVE = False   # True = EVCC Live Daten (WebSocket)
              # False = statische Demo-Werte
```

| Mode | Verhalten |
|------|-----------|
| `LIVE = True` | Socket verbindet sich zu EVCC und aktualisiert Register in Echtzeit |
| `LIVE = False` | Nutzt hardcodierte `STATIC_VALUES`, Fallback wenn EVCC offline ist |

### EVCC WebSocket Verbindung

```python
EVCC_HOST = "192.168.178.5"           # Host-IP (EVCC im host-mode)
EVCC_WS_PORT = 7070                   # Standard EVCC Port
EVCC_WS_URI = f"ws://{EVCC_HOST}:{EVCC_WS_PORT}/ws"
```

**Für verschiedene Umgebungen:**

| Umgebung | EVCC_HOST | Grund |
|----------|-----------|-------|
| Windows Docker | `host.docker.internal` | Bridge zu Host |
| Mac Docker | `host.docker.internal` | Bridge zu Host |
| Linux Docker | `192.168.x.x` oder Hostname | Direkte Adressierung |
| QNAP (EVCC im host-mode) | Host-IP | Direkte Adressierung |
| Bare Metal | `localhost` oder IP | Direkte Verbindung |

### WR-Identität (fest konfiguriert)

```python
MANUFACTURER = "OpenSource"        # Hersteller (10 Zeichen)
SERIAL_NUMBER = "12345678"         # Eindeutige Seriennummer
MODEL = "EVCC"                     # Modell
WR_STATUS = 0x0002                 # 0x0002 = RUNNING, 0x0001 = IDLE
WR_TEMPERATURE = 45                # Temperatur in °C
```

### Statische Fallback-Werte

Wenn `LIVE = False` oder EVCC offline ist:

```python
STATIC_VALUES = {
    "power_w": 4000,               # Aktuelle Leistung in Watt
    "energy_kwh": 58940.909        # Gesamtenergie in kWh
}
```

---

## 🎯 Verwendung

### Starten (lokal)

```bash
python emulated_sunspec_inverter.py
```

**Erwartete Ausgabe:**

```
======================================================================
🚀 Emulated SunSpec WR (OpenSource Simulation) — v0.1.0
======================================================================
📡 Modbus TCP Port: 5202

🏭 WR-Identität:
  Manufacturer: OpenSource
  Model: EVCC
  Serial: 12345678
   Status: RUNNING

⚡ Aktuelle Werte:
   Total Power: 4000 W
   Total Energy: 58940.91 kWh
   Temperatur: 45°C

📋 Mode: STATIC (Demo-Werte)

📝 SunSpec Register:
   0x9C40 = Identifier ('SunS')
   0x9C44 = Manufacturer
   0x9C74 = Serial Number
   0x9C93 = AC Total Power (dynamisch)
   0x9C9D = Total Energy (dynamisch)
   0x9CAB = Status
======================================================================
```

### Mit LIVE-Modus aktivieren

1. Ändere `LIVE = True` im Script
2. Stelle sicher, dass `EVCC_HOST` korrekt ist
3. Starte das Script

**LIVE-Ausgabe Beispiel:**

```
[INFO] WebSocket-Client gestartet
[INFO] Verbinde zu EVCC WebSocket: ws://192.168.178.5:7070/ws
[INFO] ✅ EVCC WebSocket verbunden!
[INFO] Power aktualisiert: 4000 W → 0 W
[DEBUG] Energy aktualisiert: 58940.91 kWh
[MAIN] ✅ EVCC WebSocket-Worker gestartet (mit Reconnect & Message Queue)
```

### WebSocket Features (v0.1.0+)

**Robuste Verbindung:**
- ✅ **Timeouts:** `open_timeout=10s`, `ping_interval=30s`, `ping_timeout=10s`
- ✅ **Exponential Backoff:** Bei Fehlern 1s → 2.5s → 5s → ... → 60s (mit Jitter)
- ✅ **Automatische Reconnects:** Unbegrenzte Reconnect-Versuche
- ✅ **Message Queue:** Asynchrone Verarbeitung (non-blocking), max 100 Messages
- ✅ **Deduplication:** Duplikate werden durch Signatur-Check gefiltert
- ✅ **Logging:** Debug-Logs für alle wichtigen Events

### Modbus TCP Client testen

Mit `nc` (Windows/Linux) oder Modbus-Client-Tool:

```bash
# Beispiel: Register 0x9C93 (Power) lesen
# Modbus TCP Request: Unit=1, Function=3 (Read), Start=0x9C93, Count=2
```

---

## 📝 Register-Mapping

Detailliertes SunSpec-Register-Mapping für Fronius-kompatible Geräte:

| Hex-Adresse | Dezimal | Register | Datentyp | Länge | Wert | Status | Beschreibung |
|-------------|---------|----------|----------|-------|------|--------|-------------|
| 0x9C40 | 40000 | SunSpec ID | String | 2 | `0x5375 0x6E53` | ✅ FIX | Identifier "SunS" (CRITICAL!) |
| 0x9C42 | 40002 | Type | Int16 | 1 | `0x0001` | ✅ FIX | Type 1 = Single Phase |
| 0x9C44 | 40004 | Manufacturer | String | 5 | `OpenSource` | ✅ FIX | Hersteller |
| 0x9C7A | 40122 | Model | String | 8 | `EVCC` | ⚠️ OPT | Modell (optional) |
| 0x9C74 | 40148 | Serial | String | 16 | `12345678` | ✅ FIX | Seriennummer |
| **0x9C93** | **40179** | **AC Power** | **Int16** | **2** | **0 W** | **✅ LIVE** | **Aktuell: -grid.power von EVCC (Einspeisung als positiv)** |
| **0x9C9D** | **40189** | **Total Energy** | **Int32** | **3** | **58.940.910 Wh** | **✅ LIVE** | **Akkumuliert: pvEnergy von EVCC (kWh → Wh)** |
| 0x9CA2 | 40194 | VPV1 (DC) | Int16 | 2 | 600 V | ⚠️ OPT | DC Spannung Phase 1 |
| **0x9CAB** | **40235** | **Device Status** | **Int16** | **1** | **0x0002** | **✅ FIX** | **0x0002=RUNNING, 0x0001=IDLE** |
| 0x9CA7 | 40199 | Temperatur | Int16 | 1 | 450 (=45°C) | ⚠️ OPT | Wärmekühler-Temperatur |

**Legende:**
- ✅ **FIX** = Fest konfiguriert, ändert sich nicht
- ✅ **LIVE** = Wird in Echtzeit von EVCC aktualisiert
- ⚠️ **OPT** = Optional, wird von EME20 nicht gelesen

---

## 📡 Modbus Protokoll

### Supported Functions

Das Script implementiert die minimalen **Modbus Function Codes** für EME20:

| Function | Code | Beschreibung | Unterstützt |
|----------|------|-------------|-------------|
| Read Input Registers | 0x04 | Liest Input Register | ✅ Ja |
| Read Holding Registers | 0x03 | Liest Holding Register | ✅ Ja |

### Request/Response Format

**Standard Modbus TCP Frame:**

```
[TxID] [ProtocolID] [Length] [UnitID] [FunctionCode] [RegisterAddress] [Count] [CRC]
```

**Beispiel: Register 0x9C93 lesen (Power)**

*Request:*
```
00 DE 00 00 00 06 01 03 9C 93 00 02
         └─┘ └─┘ └─┘ └─┘ └──┘ └──┘
         Len  ID  Func Addr   Count
```

*Response:*
```
00 DE 00 00 00 07 01 03 04 0F A0 00 00
         └─┘ └─┘ └─┘ └──┘ └─────────┘
         Len  ID  Func Bytes  Data (4000 W)
```

---

## 🐳 Docker Deployment

### docker-compose-emulated-sunspec-inverter.yml

```yaml
version: "3.9"

services:
  emulated-sunspec-inverter:
    image: python:3.11-slim
    container_name: emulated-sunspec-inverter
    restart: unless-stopped

    volumes:
      - /share/Container/EmulatedSunSpecInverter:/app
    working_dir: /app

    command: >
      sh -c "pip install pymodbus==2.5.3 websockets &&
             python emulated_sunspec_inverter.py"

    ports:
      - "5202:5202"

    network_mode: bridge
```

### Volume anlegen (Host-Verzeichnis)

Die Compose-Datei nutzt ein Bind-Mount als Volume. Lege das Verzeichnis an und lege dort die Dateien ab:

```bash
mkdir -p /share/Container/EmulatedSunSpecInverter
cd /share/Container/EmulatedSunSpecInverter
git clone <REPO_URL> .
```

### Container erstellen und starten

```bash
docker-compose -f docker-compose-emulated-sunspec-inverter.yml up -d
```

### Logs prüfen

```bash
docker logs emulated-sunspec-inverter
```

### Container neu starten

```bash
docker-compose -f docker-compose-emulated-sunspec-inverter.yml restart emulated-sunspec-inverter
```

### Wichtige Docker-Konfiguration

1. **Port-Mapping:** `5202:5202` → Modbus TCP
2. **Netzwerk:** `bridge` für Zugriff auf EVCC-Container
3. **Volume:** `/share/Container/EmulatedSunSpecInverter:/app` → Persist und Änderungen
4. **Dependencies:** Bei separaten Compose-Files ggf. externe Netzwerke konfigurieren

---

## 🔧 Troubleshooting

### 1. EVCC WebSocket verbindet sich nicht

**Problem:** 
```
[WARNING] ❌ WS-Fehler: Cannot connect to host
[DEBUG] Backoff nach WS-Fehler: 1.23s
```

**Häufige Ursachen + Lösungen:**

1. **Falsche EVCC_HOST**
  - Windows/Mac Docker: `host.docker.internal` ✅
  - Linux Docker: IP des Host-Systems oder Hostname ✅
  - QNAP (EVCC im host-mode): Host-IP ✅
   
   **Test:** 
   ```bash
   ping <EVCC_HOST>
   ```

2. **Falscher Port**
   - Standard EVCC Port: `7070` ✅
   
   **Test:**
   ```bash
  curl http://<EVCC_HOST>:7070/api/state | jq '.site'
   ```

3. **EVCC offline oder nicht erreichbar**
   - Script vertraut auf Exponential Backoff (5s → 60s)
   - Fallback zu `STATIC_VALUES` wenn `LIVE=True` aber keine Verbindung
   
   **Logs prüfen:**
   ```bash
   # Im Docker-Container:
  docker logs emulated-sunspec-inverter | grep -i evcc
   ```

4. **Firewall/Netzwerk blockiert**
   - Docker-Netzwerk überprüfen
   - Ggfs. externe Netzwerk-Konfiguration in docker-compose
   
   **QNAP-Specific:** Container müssen im gleichen Docker-Netzwerk sein

### 2. WebSocket-Verbindung wird ständig getrennt

**Problem:** Logs zeigen ständige Reconnects

```
[INFO] Verbinde zu EVCC WebSocket...
[WARNING] ❌ WS-Fehler: connection closed
[DEBUG] Backoff nach WS-Fehler: 2.45s
```

**Lösungen:**

- ✅ EVCC-Stabilität prüfen
- ✅ Netzwerk-Latenz überprüfen (sollte < 100ms sein)
- ✅ EVCC Logs überprüfen (Version 0.210.2+?)
- ✅ Script-Logs mit Debug-Level:
  ```bash
  # Log-Level bereits auf DEBUG gesetzt in v0.1.0
  # Suche nach "relevant" oder "duplicate" in den Logs
  ```

### 3. EME20 kann Modbus TCP nicht erreichen

**Problem:** EME20 zeigt "WR offline"

**Lösungen:**

- ✅ Prüfe Port `5202` ist offen:
  ```bash
  netstat -an | grep 5202
  # oder
  ss -an | grep 5202
  ```

- ✅ EME20 IP-Adresse korrekt?
  ```bash
  ping <QNAP-IP>
  ```

- ✅ Modbus TCP Client-Test:
  ```bash
  nc -zv 192.168.x.x 5202
  ```

### 4. Register-Werte stimmen nicht

**Problem:** EME20 liest falsche oder fehlende Daten

**Überprüfung:**

```bash
# Logs anschauen
docker logs emulated-sunspec-inverter

# Oder direkt im Container:
docker exec emulated-sunspec-inverter python -c "
import sys
sys.path.insert(0, '.')
from emulated_sunspec_inverter import holding
print(f'0x9C93: {hex(holding[0x9C93+1])}')  # Power
print(f'0x9CAB: {hex(holding[0x9CAB+1])}')  # Status
"
```

### 5. Statische Werte ändern

**Lösung:** Bearbeite `STATIC_VALUES` im Script:

```python
STATIC_VALUES = {
    "power_w": 5000,        # erhöht von 4000
    "energy_kwh": 60000.0   # erhöht
}
```

Dann Container neu starten:
```bash
docker-compose -f docker-compose-emulated-sunspec-inverter.yml restart emulated-sunspec-inverter
```

### 6. Debug-Logs verstehen

**Log-Ausgaben in v0.1.0:**

```
[INFO] WebSocket-Client gestartet
  ✓ WebSocket Worker wurde erfolgreich gestartet

[INFO] Verbinde zu EVCC WebSocket: ws://...
  ✓ Versucht eine Verbindung aufzubauen

[INFO] ✅ EVCC WebSocket verbunden!
  ✓ Verbindung erfolgreich, Daten werden empfangen

[DEBUG] Relevante WS-Nachricht empfangen
  ✓ Neue EVCC-Daten (grid.power, pvEnergy) verarbeitet

[DEBUG] Power aktualisiert: 4000 W → 5250 W
  ✓ Leistungswert hat sich geändert, Register aktualisiert

[DEBUG] Duplicate WS-Nachricht ignoriert
  ✓ Gleiche Daten wie zuletzt, wurde übersprungen (Deduplication)

[WARNING] WS-Message Queue voll; Nachricht wird verworfen
  ✗ Queue-Overflow (selten). Zeichen für Performance-Problem

[WARNING] ❌ WS-Fehler: connection reset by peer
  ✗ Verbindungsfehler, Script startet Reconnect mit Backoff

[DEBUG] Backoff nach WS-Fehler: 2.45s
  ✓ Wartet 2.45s bis zur nächsten Reconnect-Versuch
```

---

## ✅ Getestete Werte

Diese Werte wurden mit echter **NIBE EME20** Hardware validiert (Feb 2026):

### Register 0x9CA2 (VPV1 DC Voltage)
```
Request:  00 DB 00 00 00 06 01 03 9C A2 00 02
Response: 00 DB 00 00 00 07 01 03 04 02 58 00 00
Dekodiert: 0x0258 = 600 V ✅
```

### Register 0x9C44 (Manufacturer)
```
Request:  00 DC 00 00 00 06 01 03 9C 44 00 05
Response: 00 DC 00 00 00 0D 01 03 0A 4F 70 65 6E 53 6F 75 72 63 65
Dekodiert: "OpenSource" ✅
```

### Register 0x9CAB (Status)
```
Request:  00 DD 00 00 00 06 01 03 9C AB 00 01
Response: 00 DD 00 00 00 05 01 03 02 00 02
Dekodiert: 0x0002 = RUNNING ✅
```

### Register 0x9C93 (Power)
```
Request:  00 DE 00 00 00 06 01 03 9C 93 00 02
Response: 00 DE 00 00 00 07 01 03 04 00 00 00 00
Dekodiert: 0x0000 = 0 W ✅
```

### Register 0x9CA7 (Temperatur)
```
Request:  00 DF 00 00 00 06 01 03 9C A7 00 04
Response: 00 DF 00 00 00 0B 01 03 08 01 C2 80 00 80 00 FF FF
Dekodiert: 0x01C2 = 450 (45°C × 10) ✅
```

### Register 0x9C9D (Total Energy)
```
Request:  00 E0 00 00 00 06 01 03 9C 9D 00 03
Response: 00 E0 00 00 00 09 01 03 06 03 83 5D EE 00 00
Dekodiert: 0x03835DEE = 58.940.910 Wh = 58.940,910 kWh ✅
```

### Register 0x9C74 (Serial Number)
```
Request:  00 E1 00 00 00 06 01 03 9C 74 00 10
Response: 00 E1 00 00 00 23 01 03 20 31 32 33 34 35 36 37 38 00 00 00 00 ...
Dekodiert: "12345678" ✅
```

---

## 📚 Referenzen

- **SunSpec Alliance:** https://www.sunspec.org/
- **Fronius Modbus Specification:** Basierend auf echten Traces
- **NIBE EME20 Handbuch:** Modbus Register-Definitionen
- **pymodbus Library:** https://github.com/riptideio/pymodbus

---

## 📄 Lizenz

Dieses Projekt ist für Privat-/Testgebrauch gedacht.

---

## ✍️ Autor & Versionsverlauf

| Version | Datum | Änderung |
|---------|-------|----------|
| **v0.1.0** | **2026-02-22** | **Thread-Safe Updates:** Wrapper-Funktionen, Cleanup, Konsistenz |
| v0.0.6 | 2026-02-20 | Production-Grade WebSocket: Exponential Backoff, Message Queue, Deduplication, Timeouts |
| v0.0.5 | 2026-02-20 | EVCC WebSocket Integration, Docker-Support |
| v0.0.4 | 2026-02-19 | Modbus Register durchgetestet |
| v0.0.1 | 2026-02-15 | Initiale Version |

