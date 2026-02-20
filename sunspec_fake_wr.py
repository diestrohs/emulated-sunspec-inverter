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

WICHTIG für EVCC-Integration:
- Total Power sollte GRID POWER (Überschuss) sein, nicht PV Power!
- Grund: Batterie-Ladung muss abgezogen werden
- Formel: max(0, gridPower) → nur positive Werte (Einspeisung)

Port: 5202 (Modbus TCP)
Version: v0.0.4
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

# ========== FESTE WERTE (WR-Identität) ==========
MANUFACTURER = "Fronius"           # Hersteller (bleibt immer gleich)
SERIAL_NUMBER = "34110779"        # Seriennummer (statisch)
MODEL = "Symo 10.0-3-M"           # Modell (optional, statisch)
FIRMWARE_VERSION = "1.20.3-1"     # Firmware (statisch)

# ========== STATISCHE KONFIGURATION ==========
WR_STATUS = 0x0002                # 0x0002 = RUNNING, 0x0001 = IDLE
WR_TEMPERATURE = 45               # °C (statisch, später evtl. dynamisch)

# ========== DYNAMISCHE WERTE (später von EVCC) ==========
# Diese Werte sollten später aus EVCC gridPower/pvPower kommen
TOTAL_POWER_WATTS = 4000          # W - Grid Überschuss (positiv = Export)
TOTAL_ENERGY_WH = 29286700        # Wh - Lifetime Energy (akkumuliert)
VPV1_VOLTAGE = 600                # V - DC Voltage String 1 (optional aus pvPower)
VPV2_VOLTAGE = 500                # V - DC Voltage String 2 (noch nicht gefunden)

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
# SunSpec Register definieren
# ====================================================

register_data = {}

# ========== FESTE WR-IDENTITÄT ==========
# Diese Register bleiben immer konstant

# ---- 0x9C44 (40004): Manufacturer = "Fronius"
register_data[0x9C44] = str_to_regs(MANUFACTURER, 5)

# ---- 0x9C74 (40148): Serial Number (16 Register = 32 Bytes)
register_data[0x9C74] = str_to_regs(SERIAL_NUMBER, 16)

# ---- 0x9CAB (40235): Inverter Status
register_data[0x9CAB] = [WR_STATUS]  # 0x0002 = RUNNING

# ========== DYNAMISCHE WERTE (Später von EVCC) ==========
# Diese Register ändern sich basierend auf aktuellen PV/Grid-Werten

# ---- 0x9C93 (40179): AC TOTAL POWER ⭐⭐⭐
# Wichtig: Hier sollte gridPower (Überschuss) rein, nicht pvPower!
# Positiver Wert = Einspeisung ins Netz = verfügbar für NIBE
# Bei EVCC Integration: max(0, gridPower) verwenden
register_data[0x9C93] = [TOTAL_POWER_WATTS, 0x0000]  # AC Power (W), Scale Factor = 0

# ---- 0x9CA2 (40167): VPV1 (DC Voltage String 1)
# Direkte Spannung in Volt (KEINE Multiplikation mit 10!)
# Optional: Später aus pvPower berechnen (pvPower / Strom)
register_data[0x9CA2] = [VPV1_VOLTAGE, 0x0000]  # VPV1 (V), Scale Factor

# ---- 0x9CA7 (40199): Temperatur + Scale Factors
# Temperatur * 10 für 0.1°C Auflösung
# 45°C → 450 im Register → Display zeigt 45,0°C
register_data[0x9CA7] = [WR_TEMPERATURE * 10, 0x8000, 0x8000, 0xFFFF]  # Temp, Rest N/A

# ---- 0x9C9D (40189): TOTAL ENERGY (WH) ⭐⭐⭐ 
# Lifetime Energy in Wh (32-bit)
# Könnte später akkumuliert werden (jede Stunde PV-Produktion addieren)
energy_high = (TOTAL_ENERGY_WH >> 16) & 0xFFFF
energy_low = TOTAL_ENERGY_WH & 0xFFFF
register_data[0x9C9D] = [energy_high, energy_low, 0x0000]  # High, Low, Scale Factor

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
    print("🚀 SunSpec Fake WR (Fronius Simulation) — v0.0.4")
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
    print(f"⚡ Aktuelle Werte (statisch, später dynamisch von EVCC):")
    print(f"   Total Power: {TOTAL_POWER_WATTS} W (Grid Überschuss)")
    print(f"   Total Energy: {TOTAL_ENERGY_WH/1000:.2f} kWh (Lifetime)")
    print(f"   VPV1: {VPV1_VOLTAGE} V (DC String 1)")
    print(f"   Temperatur: {WR_TEMPERATURE}°C")
    print(f"")
    print(f"📝 Register-Mapping:")
    print(f"   0x9C93 = Total Power (später von EVCC gridPower)")
    print(f"   0x9C9D = Total Energy")
    print(f"   0x9CA2 = VPV1")
    print(f"   0x9CA7 = Temperature")
    print("="*70 + "\n")
    
    StartTcpServer(context, address=("0.0.0.0", 5202))
    
except KeyboardInterrupt:
    print("\n\n[INFO] Server gestoppt (CTRL+C).")
except Exception as e:
    print(f"\n[ERROR] Server-Fehler: {e}")
