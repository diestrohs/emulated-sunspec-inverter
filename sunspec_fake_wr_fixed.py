#!/usr/bin/env python3
"""
SunSpec Fake WR (Wechselrichter) für EME20 / NIBE
Korrigierte Version mit explizitem Register-Mapping nach SunSpec-Spec
"""

from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock

# ====================================================
# Explizites Register-Mapping nach SunSpec
# ====================================================

# Initialize holding registers for address space 0-50000
holding_registers = [0] * 50000

# Helper: Schreibe Wert ins Holding-Register-Array
def write_reg(addr, values):
    """Schreibe ein oder mehrere Register ab Adresse addr"""
    if isinstance(values, list):
        for idx, val in enumerate(values):
            holding_registers[addr + idx] = val
    else:
        holding_registers[addr] = values

# Helper: String zu SunSpec-Registern
def str_to_regs_fixed(s, num_regs):
    """Konvertiere String zu SunSpec-Registern (Big-Endian)"""
    regs = []
    # Pad string auf volle Länge
    s = s + '\x00' * (num_regs * 2 - len(s))
    
    for i in range(num_regs):
        # Jedes Register: High Byte + Low Byte
        high_byte = ord(s[i * 2]) if i * 2 < len(s) else 0
        low_byte = ord(s[i * 2 + 1]) if i * 2 + 1 < len(s) else 0
        reg_value = (high_byte << 8) | low_byte
        regs.append(reg_value)
    
    return regs

# ====================================================
# SunSpec Register schreiben (KORREKTE Dezimal-Adressen!)
# ====================================================

# Hex → Dezimal Konvertierung:
# 0x9C44 = 40004, 0x9C74 = 40052, 0x9C93 = 40083, 0x9C9D = 40093
# 0x9CA2 = 40098, 0x9CA7 = 40103, 0x9CAB = 40107

# 40004-40008: Manufacturer ID (5 Registers)
# Hex: 0x9C44, String: "Fronius"
mfg_regs = str_to_regs_fixed("Fronius", 5)
write_reg(40004, mfg_regs)
print(f"[WRITE] Addr 40004 (0x9C44): Manufacturer = {[hex(x) for x in mfg_regs]}")

# 40052-40067: Serial Number / Model (16 Registers)
# Hex: 0x9C74
serial_regs = str_to_regs_fixed("34110779", 16)
write_reg(40052, serial_regs)
print(f"[WRITE] Addr 40052 (0x9C74): Serial = {[hex(x) for x in serial_regs[:2]]}")

# 40083-40084: Options / Reserved (2 Registers)
# Hex: 0x9C93
write_reg(40083, [0x0000, 0x0000])
print(f"[WRITE] Addr 40083 (0x9C93): Options = 0x0000 0x0000")

# 40093-40095: Firmware Version (3 Registers)
# Hex: 0x9C9D
write_reg(40093, [0xAE90, 0x0E12, 0xFFFE])
print(f"[WRITE] Addr 40093 (0x9C9D): Firmware = 0xAE90 0x0E12 0xFFFE")

# 40103-40106: Scale Factors (4 Registers)
# Hex: 0x9CA7
write_reg(40103, [0x8000, 0x8000, 0x8000, 0xFFFF])
print(f"[WRITE] Addr 40103 (0x9CA7): Scale Factors = 0x8000 0x8000 0x8000 0xFFFF")

# 40098-40099: AC Power + AC Power Scale Factor
# Hex: 0x9CA2-0x9CA3
# AC Power = 4000W (dezimal) = 0x0FA0 (hex)
# AC Power Scale Factor = 0
ac_power_watts = 4000
ac_power_sf = 0
write_reg(40098, [ac_power_watts, ac_power_sf])
print(f"[WRITE] Addr 40098 (0x9CA2): AC Power = {ac_power_watts}W (0x{ac_power_watts:04X}), SF = {ac_power_sf}")

# 40107: Inverter Status
# Hex: 0x9CAB
# 0 = Off, 1 = Sleep, 2 = Running, 3 = Error, 4 = Recovering
write_reg(40107, 0x0002)  # RUNNING
print(f"[WRITE] Addr 40107 (0x9CAB): Status = RUNNING (0x0002)")

# ====================================================
# Verifizierung: Lese die geschriebenen Werte zurück
# ====================================================

print("\n[VERIFY]")
print(f"  holding_registers[40098] = 0x{holding_registers[40098]:04X} (sollte 0x0FA0 = 4000)")
print(f"  holding_registers[40099] = 0x{holding_registers[40099]:04X} (sollte 0x0000 = 0)")
print(f"  holding_registers[40107] = 0x{holding_registers[40107]:04X} (sollte 0x0002 = RUNNING)")
print(f"  holding_registers[40004] = 0x{holding_registers[40004]:04X} (sollte 0x4672 = 'Fr')")

# ====================================================
# Modbus Slave Context erstellen
# ====================================================

store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0] * 100),
    co=ModbusSequentialDataBlock(0, [0] * 100),
    hr=ModbusSequentialDataBlock(0, holding_registers),  # KRITISCH: Alle 50000 Adressen
    ir=ModbusSequentialDataBlock(0, holding_registers)
)

context = ModbusServerContext(slaves=store, single=True)

# ====================================================
# TCP Server starten
# ====================================================

try:
    print("\n" + "="*70)
    print("🚀 SunSpec Fake WR starten (Fronius Simulation)")
    print("="*70)
    print(f"📡 Modbus TCP Server auf Port 5202")
    print(f"📊 AC Power (Reg 40098/0x9CA2): {ac_power_watts}W, SF=0")
    print(f"✅ Status (Reg 40107/0x9CAB): RUNNING")
    print("="*70 + "\n")
    
    StartTcpServer(context, address=("0.0.0.0", 5202))
    
except KeyboardInterrupt:
    print("\n\n[INFO] Server gestoppt (CTRL+C)")
except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
