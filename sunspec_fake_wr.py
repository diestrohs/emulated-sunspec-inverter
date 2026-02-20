#!/usr/bin/env python3
"""
SunSpec Fake WR (Wechselrichter) für EME20 / NIBE
Basierend auf echten Fronius Modbus-Traces

REGISTER-MAPPING (Gefunden durch systematisches Testen):
- 0x9C44: Manufacturer "Fronius" (FEST)
- 0x9C74: Serial Number (FEST)
- 0x9CAB: Status (0x0002 = RUNNING, FEST)
- 0x9C93[0]: Total Power (AC Watt) ⭐ DYNAMISCH - später von EVCC gridPower
- 0x9C9D[0-1]: Total Energy (Wh) als 32-bit ⭐ DYNAMISCH - akkumuliert
- 0x9CA2[0]: VPV1 (DC Voltage in V) - OPTIONAL dynamisch
- 0x9CA7[0]: Temperatur (in 0.1°C) - STATISCH oder dynamisch
- 0x9CA2[1]: VPV2 - NOCH NICHT GEFUNDEN (nicht in EME20-Abfrage enthalten)

ARCHITEKTUR:
┌──────────────────────────────────────────────────────────────┐
│ EVCC (PV-Erzeugung, Batterie, Netz)                          │
│   └─ WebSocket ws://IP:7070/api/ws                           │
│         └─ pvPower, gridPower, pvEnergy                       │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
                  Fake WR Python Server
                  (dein Script, LIVE=True/False)
                           │
                           ▼
                  SunSpec Register (Modbus TCP)
                           │
                           ▼
┌──────────────────────────┬───────────────────────────────────┐
│ NIBE EME20 (Modbus Master)                                   │
│   └─ liest: Power, Energy, Status                            │
│   └─ aktiviert PV-Modus / Belüftung                          │
└──────────────────────────────────────────────────────────────┘

Port: 5202 (Modbus TCP)
Version: v0.0.5 - EVCC WebSocket Integration
"""

import asyncio
import json
import threading
import time
import websockets
from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock

# ====================================================
# Konfiguration
# ====================================================

# ========== MODE SWITCH ==========
LIVE = True   # True = EVCC Live Daten (WebSocket)
              # False = statische Demo-Werte

# ========== EVCC VERBINDUNG ==========
EVCC_HOST = "evcc.local"    # oder: "192.168.x.x"
EVCC_WS_PORT = 7070         # WebSocket Port
EVCC_WS_URI = f"ws://{EVCC_HOST}:{EVCC_WS_PORT}/api/ws"

# ========== FESTE WERTE (WR-Identität) ==========
MANUFACTURER = "Fronius"           # Hersteller (bleibt immer gleich)
SERIAL_NUMBER = "34110779"         # Seriennummer (statisch)
MODEL = "Symo 10.0-3-M"            # Modell (optional, statisch)
FIRMWARE_VERSION = "1.20.3-1"      # Firmware (statisch)

# ========== STATISCHE KONFIGURATION ==========
WR_STATUS = 0x0002                 # 0x0002 = RUNNING, 0x0001 = IDLE
WR_TEMPERATURE = 45                # °C (statisch)

# ========== STATISCHE FALLBACK-WERTE (wenn LIVE=False oder EVCC offline) ==========
STATIC_VALUES = {
    "power_w": 4000,               # W - Netz-Überschuss
    "energy_kwh": 58940.909        # kWh - Gesamtenergie (wie EVCC liefert)
}

# ========== DYNAMISCHE WERTE (zur Laufzeit aktualisiert) ==========
# Diese Variablen werden von EVCC WebSocket gefüllt
current_power_w = STATIC_VALUES["power_w"]      # aktuelle Leistung
current_energy_kwh = STATIC_VALUES["energy_kwh"]  # Gesamtenergie
evcc_connected = False                           # Status EVCC Verbindung

# ====================================================
# Konfiguration - Hier alle Werte anpassen!
# ====================================================

# ====================================================
# Hilfsfunktionen
# ====================================================

def str_to_regs(s, num_regs):
    """String → SunSpec Register (2 Bytes pro Register, Big Endian)"""
    regs = []
    s_padded = s.ljust(num_regs * 2, '\x00')
    for i in range(num_regs):
        hi = ord(s_padded[i * 2])
        lo = ord(s_padded[i * 2 + 1])
        regs.append((hi << 8) | lo)
    return regs

# ====================================================
# Register-Update Funktionen (dynamische Werte)
# ====================================================

def update_power_register(power_w):
    """Update SunSpec AC Power Register (0x9C93)"""
    global sunspec_registers, holding
    
    # 16-bit signed integer (für negative Werte)
    if power_w < 0:
        power_w = (1 << 16) + int(power_w)
    else:
        power_w = int(power_w) & 0xFFFF
    
    sunspec_registers[0x9C93] = power_w
    sunspec_registers[0x9C94] = 0x0000  # Scale Factor
    
    # Auch in Holding-Array aktualisieren (mit +1 Offset)
    holding[0x9C93 + 1] = power_w
    holding[0x9C94 + 1] = 0x0000

def update_energy_register(energy_kwh):
    """Update SunSpec Total Energy Register (0x9C9D) - 32-bit"""
    global sunspec_registers, holding
    
    # kWh → Wh (1:1 Mapping ohne Berechnungen)
    energy_wh = int(energy_kwh * 1000)
    
    # 32-bit in zwei 16-bit Register aufteilen (Big Endian)
    high = (energy_wh >> 16) & 0xFFFF
    low = energy_wh & 0xFFFF
    
    sunspec_registers[0x9C9D] = high
    sunspec_registers[0x9C9E] = low
    sunspec_registers[0x9C9F] = 0x0000  # Scale Factor
    
    # Auch in Holding-Array aktualisieren (mit +1 Offset)
    holding[0x9C9D + 1] = high
    holding[0x9C9E + 1] = low
    holding[0x9C9F + 1] = 0x0000

def update_registers_from_values():
    """Update alle dynamischen Register basierend auf current_* Variablen"""
    global current_power_w, current_energy_kwh
    
    update_power_register(current_power_w)
    update_energy_register(current_energy_kwh)

# ====================================================
# SunSpec Register Dictionary definieren
# ====================================================

register_data = {}

# ====================================================
# EVCC WebSocket Integration
# ====================================================

async def evcc_websocket_worker():
    """Asynchroner WebSocket-Client für EVCC Live-Daten"""
    global current_power_w, current_energy_kwh, evcc_connected
    
    while True:
        try:
            print(f"[EVCC] Verbinde zu {EVCC_WS_URI}...")
            async with websockets.connect(EVCC_WS_URI, ping_interval=10) as websocket:
                evcc_connected = True
                print("[EVCC] ✅ WebSocket verbunden!")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        
                        # Extrahiere EVCC-Daten
                        if "site" in data:
                            site = data["site"]
                            
                            # Leistung (grid > 0 = Einspeisung)
                            if "gridPower" in site:
                                grid_power = site["gridPower"]
                                current_power_w = max(0, int(grid_power))
                            
                            # Energie (kWh)
                            if "pvEnergy" in site:
                                current_energy_kwh = float(site["pvEnergy"])
                            
                            update_registers_from_values()
                            
                    except json.JSONDecodeError:
                        pass  # Ignore parsing errors
                    except Exception as e:
                        print(f"[EVCC] Fehler bei Datenprozessierung: {e}")
                        
        except websockets.exceptions.WebSocketException as e:
            evcc_connected = False
            print(f"[EVCC] ❌ WebSocket Fehler: {e}")
            print(f"[EVCC] Versuche in 5 Sekunden erneut...")
            await asyncio.sleep(5)
        except Exception as e:
            evcc_connected = False
            print(f"[EVCC] ❌ Unexpected error: {e}")
            await asyncio.sleep(5)

def run_evcc_websocket():
    """Starte WebSocket-Worker in eigenem Event Loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(evcc_websocket_worker())

# ====================================================
# SunSpec Register Dictionary definieren
# ====================================================

register_data = {}
sunspec_registers = {}  # Globales Register-Dict (für Updates)

# ========== FESTE WR-IDENTITÄT ==========
# Diese Register bleiben immer konstant

# ---- 0x9C40: SunSpec Identifier ("SunS") - CRITICAL!
register_data[0x9C40] = [0x5375, 0x6E53]  # "Su" + "nS"

# ---- 0x9C44 (40004): Manufacturer = "Fronius"
register_data[0x9C44] = str_to_regs(MANUFACTURER, 5)

# ---- 0x9C74 (40148): Serial Number (16 Register = 32 Bytes)
register_data[0x9C74] = str_to_regs(SERIAL_NUMBER, 16)

# ---- 0x9CAB (40235): Inverter Status
register_data[0x9CAB] = [WR_STATUS]  # 0x0002 = RUNNING

# ========== DYNAMISCHE WERTE (Später von EVCC) ==========
# Diese Register werden dynamisch aktualisiert

# ---- 0x9C93 (40179): AC Total Power (dynamisch aus EVCC)
power_w = int(current_power_w) & 0xFFFF
register_data[0x9C93] = [power_w, 0x0000]

# ---- 0x9C9D (40189): Total Energy 32-bit (dynamisch aus EVCC)
energy_wh = int(current_energy_kwh * 1000)
energy_hi = (energy_wh >> 16) & 0xFFFF
energy_lo = energy_wh & 0xFFFF
register_data[0x9C9D] = [energy_hi, energy_lo, 0x0000]

# ---- 0x9CA2 (40167): VPV1 (DC Voltage)
register_data[0x9CA2] = [600, 0x0000]

# ---- 0x9CA7 (40199): Temperatur + Scale Factors
register_data[0x9CA7] = [WR_TEMPERATURE * 10, 0x8000, 0x8000, 0xFFFF]

# ====================================================
# Holding Register Array bauen
# ====================================================

# Das größte Register bestimmen
max_reg_addr = max(register_data.keys())
max_length = max(len(v) for v in register_data.values())
max_addr = max_reg_addr + max_length + 10

# Array mit Nullen initialisieren
# pymodbus ModbusSequentialDataBlock(0, values): values[i] = Modbus-Register i
# ABER: Beim Lesen gibt es einen OFF-BY-ONE Bug in pymodbus!
# Lösung: Wir schreiben mit +1 Offset
holding = [0] * (max_addr + 2)

# Register eintragen (mit +1 Offset für pymodbus-Kompatibilität)
for addr, values in register_data.items():
    for idx, val in enumerate(values):
        target_addr = addr + idx + 1  # +1 Offset NOTWENDIG!
        if target_addr < len(holding):
            holding[target_addr] = val
            sunspec_registers[addr + idx] = val  # Auch ins globale Dict

# Debug: Prüfe ob Werte richtig geschrieben wurden
print(f"[INIT] SunSpec Identifier (0x9C40) = 0x{holding[0x9C40+1]:04X} 0x{holding[0x9C41+1]:04X} (sollte 0x5375 0x6E53)")
print(f"[INIT] Manufacturer (0x9C44) = 0x{holding[0x9C44+1]:04X}")
print(f"[INIT] Status (0x9CAB) = 0x{holding[0x9CAB+1]:04X}")

# ====================================================
# Fallback-Werte laden wenn LIVE=False
# ====================================================

if not LIVE:
    print("[INIT] 🔧 STATIC MODE - Verwende feste Demo-Werte")
    update_registers_from_values()
else:
    print("[INIT] 🔌 LIVE MODE - Warte auf EVCC WebSocket...")

# ====================================================
# Modbus Slave Context erstellen
# ====================================================

store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0] * 100),
    co=ModbusSequentialDataBlock(0, [0] * 100),
    hr=ModbusSequentialDataBlock(0, holding),  # Holding Registers
    ir=ModbusSequentialDataBlock(0, holding)   # Input Registers (kopiert HR)
)

context = ModbusServerContext(slaves=store, single=True)

# ====================================================
# TCP Server starten mit WebSocket-Worker (optional)
# ====================================================

try:
    print("\n" + "="*70)
    print("🚀 SunSpec Fake WR (Fronius Simulation) — v0.0.5")
    print("="*70)
    print(f"📡 Modbus TCP Port: 5202")
    print(f"")
    print(f"🏭 WR-Identität:")
    print(f"   Manufacturer: {MANUFACTURER}")
    print(f"   Model: {MODEL}")
    print(f"   Serial: {SERIAL_NUMBER}")
    print(f"   Firmware: {FIRMWARE_VERSION}")
    print(f"   Status: {'RUNNING' if WR_STATUS == 0x0002 else 'IDLE'}")
    print(f"")
    print(f"⚡ Aktuelle Werte:")
    print(f"   Total Power: {current_power_w} W")
    print(f"   Total Energy: {current_energy_kwh:.2f} kWh")
    print(f"   Temperatur: {WR_TEMPERATURE}°C")
    print(f"")
    
    if LIVE:
        print(f"🌐 EVCC WebSocket Connection:")
        print(f"   URI: {EVCC_WS_URI}")
        print(f"   Status: {'🟢 Connected' if evcc_connected else '🔴 Disconnected (connecting...)'}")
    else:
        print(f"📋 Mode: STATIC (Demo-Werte)")
    
    print(f"")
    print(f"📝 SunSpec Register:")
    print(f"   0x9C40 = Identifier ('SunS')")
    print(f"   0x9C44 = Manufacturer")
    print(f"   0x9C74 = Serial Number")
    print(f"   0x9C93 = AC Total Power (dynamisch)")
    print(f"   0x9C9D = Total Energy (dynamisch)")
    print(f"   0x9CAB = Status")
    print("="*70 + "\n")
    
    # Starte WebSocket-Worker wenn LIVE=True
    if LIVE:
        ws_thread = threading.Thread(target=run_evcc_websocket, daemon=True)
        ws_thread.start()
        print("[MAIN] ✅ EVCC WebSocket-Worker gestartet\n")
    
    # Starte Modbus Server (blockierend)
    StartTcpServer(context, address=("0.0.0.0", 5202))
    
except KeyboardInterrupt:
    print("\n\n[INFO] Server gestoppt (CTRL+C).")
except Exception as e:
    print(f"\n[ERROR] Server-Fehler: {e}")
