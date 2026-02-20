#!/usr/bin/env python3
"""
SunSpec Fake WR v2 - Vollständige SunSpec-Struktur
Basierend auf SunSpec Alliance Specification
EME20-kompatibel
"""

from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock

# ====================================================
# Konfiguration
# ====================================================
PV_POWER_WATTS = 4000  # AC Power in Watt

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
# Vollständige SunSpec Struktur aufbauen
# ====================================================

register_data = {}

# ====================================================
# BLOCK 1: SunSpec Common Model (Model 1) ab 40000
# ====================================================
register_data[40000] = [0x5375]  # "Su"
register_data[40001] = [0x6E53]  # "nS" → "SunS" Magic Number
register_data[40002] = [1]       # Model ID = 1 (Common)
register_data[40003] = [65]      # Length = 65 Register

# Common Model Daten (40004-40068)
register_data[0x9C44] = str_to_regs("Fronius", 16)  # Manufacturer (40004-40019)
register_data[0x9C54] = str_to_regs("Symo", 16)     # Model (40020-40035)
register_data[0x9C64] = str_to_regs("", 8)          # Options (40036-40043)
register_data[0x9C6C] = str_to_regs("1.0.0", 8)    # Version (40044-40051)
register_data[0x9C74] = str_to_regs("34110779", 16) # Serial (40052-40067)
register_data[0x9C84] = [1]                         # Device Address

# ====================================================
# BLOCK 2: Three Phase Inverter (Model 103) ab 40069
# ====================================================
BASE_103 = 40069

register_data[BASE_103] = [103]   # Model ID = 103 (Three Phase)
register_data[BASE_103+1] = [50]  # Length

# AC Measurements (Base + 2 onwards)
register_data[BASE_103+2] = [200]     # AC Current Total (20.0A × SF)
register_data[BASE_103+3] = [67]      # AC Current Phase A
register_data[BASE_103+4] = [67]      # AC Current Phase B  
register_data[BASE_103+5] = [66]      # AC Current Phase C

register_data[BASE_103+6] = [0xFFFF]  # AC Voltage AB (not used)
register_data[BASE_103+7] = [0xFFFF]  # AC Voltage BC
register_data[BASE_103+8] = [0xFFFF]  # AC Voltage CA
register_data[BASE_103+9] = [2300]    # AC Voltage AN (230V × SF)
register_data[BASE_103+10] = [2300]   # AC Voltage BN
register_data[BASE_103+11] = [2300]   # AC Voltage CN

# AC POWER - DAS IST DER WICHTIGE WERT!
register_data[BASE_103+12] = [PV_POWER_WATTS]  # AC Power (W) ⭐⭐⭐
register_data[BASE_103+13] = [5000]            # AC Apparent Power (VA)
register_data[BASE_103+14] = [0]               # AC Reactive Power (var)
register_data[BASE_103+15] = [100]             # AC Power Factor (100%)

# AC Frequency
register_data[BASE_103+16] = [5000]  # AC Frequency (50.00 Hz × SF)

# AC Energy
register_data[BASE_103+17] = [29286]  # AC Lifetime Energy (WH) High Word
register_data[BASE_103+18] = [0]      # AC Lifetime Energy Low Word

# DC Current
register_data[BASE_103+19] = [180]  # DC Current (18.0A × SF)

# DC Voltage
register_data[BASE_103+20] = [4000]  # DC Voltage (400.0V × SF)

# DC Power  
register_data[BASE_103+21] = [PV_POWER_WATTS + 50]  # DC Power (W)

# Cabinet/Heat Sink Temperature
register_data[BASE_103+23] = [450]  # Temperature (45.0°C × SF)

# Status and Events
register_data[BASE_103+25] = [0x0002]  # Operating State = MPPT (Running)
register_data[BASE_103+26] = [0x0000]  # Vendor Status

# Scale Factors
register_data[BASE_103+27] = [0xFFFE]  # AC Current SF = -2
register_data[BASE_103+28] = [0xFFFE]  # AC Voltage SF = -2  
register_data[BASE_103+29] = [0x0000]  # AC Power SF = 0 ⭐
register_data[BASE_103+30] = [0xFFFE]  # AC Frequency SF = -2
register_data[BASE_103+31] = [0x0000]  # AC Energy SF = 0
register_data[BASE_103+32] = [0xFFFE]  # DC Current SF = -2
register_data[BASE_103+33] = [0xFFFE]  # DC Voltage SF = -2
register_data[BASE_103+34] = [0x0000]  # DC Power SF = 0
register_data[BASE_103+35] = [0xFFFE]  # Temperature SF = -2

# ====================================================
# LEGACY: Alte Register für Kompatibilität
# ====================================================
register_data[0x9CAB] = [0x0002]  # Status = RUNNING
register_data[0x9C93] = [0x0000, 0x0000]  # Options
register_data[0x9CA7] = [0x8000, 0x8000, 0x8000, 0xFFFF]  # Scale Factors
register_data[0x9C9D] = [0xAE90, 0x0E12, 0xFFFE]  # Firmware

# ====================================================
# Holding Register Array bauen
# ====================================================

max_addr = max(max(k, k + len(v) - 1) for k, v in register_data.items())
holding = [0] * (max_addr + 10)

for addr, values in register_data.items():
    if isinstance(values, list):
        for idx, val in enumerate(values):
            target = addr + idx + 1  # +1 Offset für pymodbus
            if target < len(holding):
                holding[target] = val

print(f"[INFO] SunSpec Fake WR v2 - Vollständige Struktur")
print(f"[INFO] Model 1 (Common) @ 40000-40068")
print(f"[INFO] Model 103 (3-Phase) @ {BASE_103} (Offset {BASE_103 - 40000})")
print(f"[INFO] AC Power @ Register {BASE_103+12} = {PV_POWER_WATTS}W")
print(f"[DEBUG] holding[{BASE_103+12+1}] = {holding[BASE_103+12+1]}")

# ====================================================
# Modbus Server
# ====================================================

store = ModbusSlaveContext(
    hr=ModbusSequentialDataBlock(0, holding),
    ir=ModbusSequentialDataBlock(0, holding)
)
context = ModbusServerContext(slaves=store, single=True)

try:
    print("\n" + "="*70)
    print("🚀 SunSpec Fake WR v2 (Vollständige SunSpec-Struktur)")
    print("="*70)
    print(f"📡 Port: 5202")
    print(f"⚡ AC Power: {PV_POWER_WATTS}W")
    print(f"📊 SunSpec Model 1 + 103 vollständig")
    print("="*70 + "\n")
    
    StartTcpServer(context, address=("0.0.0.0", 5202))
    
except KeyboardInterrupt:
    print("\n[INFO] Server gestoppt")
except Exception as e:
    print(f"\n[ERROR] {e}")
