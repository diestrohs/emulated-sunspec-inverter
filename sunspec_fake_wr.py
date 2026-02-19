#!/usr/bin/env python3
"""
SunSpec Fake WR (Wechselrichter) für EME20 / NIBE
Basierend auf echten Fronius Modbus-Traces (Slave ID 01 & 02)

WICHTIG: EME20 fragt diese Register-Sequenz ab:
- 9CA2: AC Power (W)
- 9C44: Manufacturer  
- 9CAB: Status
- 9C93: Options
- 9CA7: Scale Factors
- 9C9D: Firmware/Version
- 9C74: Serial Number

Port: 5202 (Modbus TCP)
"""

from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock

# ====================================================
# Konfiguration
# ====================================================

# PV-Überschuss in Watt (wird später dynamisch aus EVCC gelesen)
PV_POWER_WATTS = 4000

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

# ---- 0x9CA2 (40194): AC Power (W) + Scale Factor
# Original bei keiner Produktion: FF FF 80 00
# Mit 4000W Produktion: 0F A0 80 00
register_data[0x9CA2] = [PV_POWER_WATTS, 0x8000]

# ---- 0x9C44 (40004): Manufacturer = "Fronius" (5 Register = 10 Bytes)
# Original Response: 46 72 6F 6E 69 75 73 00 00 00
register_data[0x9C44] = str_to_regs("Fronius", 5)

# ---- 0x9CAB (40235): Inverter Status
# 0x0002 = RUNNING (produziert)
# 0x0007 = anderer Status (WR 2 im Trace)
register_data[0x9CAB] = [0x0002]

# ---- 0x9C93 (40179): Options / Reserved (2 Register)
# WR1: 00 00 00 00
# WR2: 00 00 FF FE
register_data[0x9C93] = [0x0000, 0x0000]

# ---- 0x9CA7 (40199): Scale Factors (4 Register)
# WR1: 80 00 80 00 80 00 FF FF
# WR2: 80 00 80 00 80 00 80 00
# Wir nutzen WR1 als Basis
register_data[0x9CA7] = [0x8000, 0x8000, 0x8000, 0xFFFF]

# ---- 0x9C9D (40189): Firmware / Version (3 Register)
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
# WICHTIG: pymodbus verwendet 1-basierte Adressierung, wir müssen +1 offset verwenden
holding = [0] * (max_addr + 2)

# Register eintragen (mit +1 Offset für pymodbus 1-basierte Adressierung)
for addr, values in register_data.items():
    for idx, val in enumerate(values):
        target_addr = addr + idx + 1  # +1 für pymodbus Offset-Korrektur
        if target_addr < len(holding):
            holding[target_addr] = val

print("[INFO] SunSpec Fake WR starten...")
print(f"[INFO] Holding Register Array gebaut (max addr: {max_addr})")
print(f"[INFO] AC Power (0x9CA2) = {PV_POWER_WATTS}W (hex: 0x{PV_POWER_WATTS:04X})")
print(f"[INFO] Manufacturer (0x9C44) = Fronius")
print(f"[INFO] Status (0x9CAB) = RUNNING (0x0002)")
print(f"[DEBUG] Register 0x9CA2+1 = {holding[0x9CA2+1]:04X}, 0x9CA3+1 = {holding[0x9CA3+1]:04X}")

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
    print("🚀 SunSpec Fake WR (Fronius Simulation) — Original Trace")
    print("="*70)
    print(f"📡 Modbus TCP Port: 5202")
    print(f"🔌 Slave ID: {SLAVE_ID}")
    print(f"⚡ AC Power: {PV_POWER_WATTS}W Überschuss")
    print(f"🏭 Manufacturer: Fronius")
    print(f"📟 Serial: 34110779")
    print(f"✅ Status: RUNNING (0x0002)")
    print(f"📊 Register: 0x9CA2, 0x9C44, 0x9CAB, 0x9C93, 0x9CA7, 0x9C9D, 0x9C74")
    print("="*70 + "\n")
    
    StartTcpServer(context, address=("0.0.0.0", 5202))
    
except KeyboardInterrupt:
    print("\n\n[INFO] Server gestoppt (CTRL+C).")
except Exception as e:
    print(f"\n[ERROR] Server-Fehler: {e}")
