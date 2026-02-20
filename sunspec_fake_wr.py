#!/usr/bin/env python3
"""
SunSpec Fake WR (Wechselrichter) für EME20 / NIBE
Basierend auf echten Fronius Modbus-Traces

REGISTER-MAPPING (EME20):
- 0x9CA2[0]: VPV1 (DC Voltage Panel 1) in 0.1V
- 0x9CA2[1]: VPV2 (DC Voltage Panel 2) in 0.1V
- 0x9C93[0]: Total Power (AC Watt)
- 0x9CA7[0]: Temperatur in 0.1°C
- 0x9C44: Manufacturer "Fronius"
- 0x9CAB: Status (0x0002 = RUNNING)
- 0x9C9D: Firmware
- 0x9C74: Serial Number

Port: 5202 (Modbus TCP)
"""

from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock

# ====================================================
# Konfiguration
# ====================================================

# ====================================================
# Konfiguration - Hier alle Werte anpassen!
# ====================================================

# Gesamtleistung (AC Power - das sieht der EME20 als "Total Power")
TOTAL_POWER_WATTS = 4000  # W

# Gesamtenergie (kumuliert - das sieht der EME20 als "Total Energy")
TOTAL_ENERGY_WH = 29286700  # Wh (= 29286,70 kWh im Display)

# DC-Spannungen
VPV1_VOLTAGE = 600  # V (String 1)
VPV2_VOLTAGE = 500  # V (String 2)

# WR-Temperatur
WR_TEMPERATURE = 45  # °C

# Slave ID (für Multi-WR Setup)
SLAVE_ID = 1

# Slave ID (1 oder 2, je nachdem welchen WR du simulieren willst)
SLAVE_ID = 1

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
# SunSpec Register definieren (100% wie Original Fronius WR)
# ====================================================

register_data = {}

# ====================================================
# LÖSUNG GEFUNDEN! ⭐
# 0x9CA2[0] = VPV1 (DC Voltage Panel 1) - DIREKT in 0.1V
# 0x9CA2[1] = Scale Factor oder N/A  
# 0x9C93[0] = TOTAL POWER (AC Power in Watt)
# 0x9CA7[0] = Temperatur (WR) - mit * 10 für 0.1°C
# ====================================================

# VPV1: DC Voltage OHNE Multiplikation!
# 600V → 600 im Register (nicht 6000!)
# EME20 zeigt es als XXX,X V (mit Dezimalstelle)
register_data[0x9CA2] = [VPV1_VOLTAGE, 0x0000]  # VPV1 DIREKT, kein *10!

# ---- 0x9C44 (40004): Manufacturer = "Fronius"
register_data[0x9C44] = str_to_regs("Fronius", 5)

# ---- 0x9C93 (40179): AC TOTAL POWER ⭐⭐⭐
# DAS IST DAS REGISTER FÜR "TOTAL POWER"!
# Zweites Register MUSS 0x0000 sein!
register_data[0x9C93] = [TOTAL_POWER_WATTS, 0x0000]  # AC Power (W), MUSS 0 sein!

# ---- 0x9CAB (40235): Inverter Status
register_data[0x9CAB] = [0x0002]  # RUNNING

# ---- 0x9CA7 (40199): Temperatur + Scale Factors
# Register 0: Temperatur (BESTÄTIGT!)
# Scale Factor -1 → 450 = 45,0°C
register_data[0x9CA7] = [WR_TEMPERATURE * 10, 0x8000, 0x8000, 0xFFFF]  # Temp, Rest N/A

# ---- 0x9C9D (40189): Firmware
# Original Werte wiederherstellen (nicht Total Energy!)
register_data[0x9C9D] = [0xAE90, 0x0E12, 0xFFFE]  # Original Firmware-Werte
# WR1: AE 90 0E 12 FF FE
# WR2: 01 D0 43 90 00 00
register_data[0x9C9D] = [0xAE90, 0x0E12, 0xFFFE]

# ---- 0x9C74 (40148): Serial Number (16 Register = 32 Bytes)
# WR1: "34110779"
# WR2: "34521519"
register_data[0x9C74] = str_to_regs("34110779", 16)

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

# Debug: Prüfe ob Werte richtig geschrieben wurden
print(f"[DEBUG] VPV1 (0x9CA2+1) = holding[{0x9CA2+1}] = {holding[0x9CA2+1]} (sollte {VPV1_VOLTAGE} sein)")
print(f"[DEBUG] VPV2 (0x9CA3+1) = holding[{0x9CA3+1}] = {holding[0x9CA3+1]} (sollte {VPV2_VOLTAGE} sein)")
print(f"[DEBUG] Fronius = holding[{0x9C44+1}] = {holding[0x9C44+1]:04X} (sollte 0x4672 sein)")

print("[INFO] SunSpec Fake WR starten...")
print(f"[INFO] Holding Register Array gebaut (max addr: {max_addr})")
print(f"[INFO] Total Power (0x9C93) = {TOTAL_POWER_WATTS}W (hex: 0x{TOTAL_POWER_WATTS:04X})")
print(f"[INFO] Manufacturer (0x9C44) = Fronius")
print(f"[INFO] Status (0x9CAB) = RUNNING (0x0002)")

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
# TCP Server starten
# ====================================================

try:
    print("\n" + "="*70)
    print("🚀 SunSpec Fake WR (Fronius Simulation) — v0.1.0")
    print("="*70)
    print(f"📡 Modbus TCP Port: 5202")
    print(f"🔌 Slave ID: {SLAVE_ID}")
    print(f"⚡ Total Power (AC): {TOTAL_POWER_WATTS}W")
    print(f"🔋 VPV1: {VPV1_VOLTAGE}V | VPV2: {VPV2_VOLTAGE}V")
    print(f"🌡️  Temperatur: {WR_TEMPERATURE}°C")
    print(f"🏭 Manufacturer: Fronius")
    print(f"📟 Serial: 34110779")
    print(f"✅ Status: RUNNING")
    print("="*70 + "\n")
    
    StartTcpServer(context, address=("0.0.0.0", 5202))
    
except KeyboardInterrupt:
    print("\n\n[INFO] Server gestoppt (CTRL+C).")
except Exception as e:
    print(f"\n[ERROR] Server-Fehler: {e}")
