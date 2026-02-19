#!/usr/bin/env python3
"""
SunSpec Fake WR - ULTRA-DIRECT APPROACH
Direkte ModbusSequentialDataBlock mit voll-befülltem Array
"""

from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock

# ====================================================
# INIT: Großes Register-Array
# ====================================================

# Größes Array für ALLE möglichen Adressen
registers = [0x0000] * 65536

print("[INIT] Creating register array (65536 addresses)...")

# ====================================================
# Helper: String zu Hex-Registern
# ====================================================

def write_string(addr, s, num_regs):
    """Write string to registers (Big-Endian)"""
    s = s + '\x00' * (num_regs * 2)
    for i in range(num_regs):
        high = ord(s[i * 2])
        low = ord(s[i * 2 + 1])
        registers[addr + i] = (high << 8) | low
    print(f"  [WRITE] Addr {addr} (0x{addr:04X}): {[hex(registers[addr + j]) for j in range(min(num_regs, 3))]}")

def write_value(addr, value):
    """Write single register"""
    registers[addr] = value
    print(f"  [WRITE] Addr {addr} (0x{addr:04X}): 0x{value:04X}")

def write_values(addr, values):
    """Write multiple registers"""
    for i, v in enumerate(values):
        registers[addr + i] = v
    print(f"  [WRITE] Addr {addr} (0x{addr:04X}): {[hex(v) for v in values]}")

# ====================================================
# SunSpec Register Layout
# ====================================================

# Decimal addresses (from SunSpec hex conversion)
# 0x9C44 = 40004 → Manufacturer
# 0x9C74 = 40052 → Serial
# 0x9C93 = 40083 → Options  
# 0x9C9D = 40093 → Firmware
# 0x9CA2 = 40098 → AC Power
# 0x9CA7 = 40103 → Scale Factors
# 0x9CAB = 40107 → Status

print("\n[WRITE] SunSpec Registers:")

# 40004-40008: Manufacturer "Fronius"
write_string(40004, "Fronius", 5)

# 40052-40067: Serial "34110779"
write_string(40052, "34110779", 16)

# 40083-40084: Options
write_values(40083, [0x0000, 0x0000])

# 40093-40095: Firmware
write_values(40093, [0xAE90, 0x0E12, 0xFFFE])

# **40098-40099: AC Power + Scale Factor**
write_values(40098, [0x0FA0, 0x0000])  # 4000W, SF=0

# 40103-40106: Scale Factors
write_values(40103, [0x8000, 0x8000, 0x8000, 0xFFFF])

# **40107: Status = RUNNING**
write_value(40107, 0x0002)

# ====================================================
# Verifizierung
# ====================================================

print("\n[VERIFY]:")
print(f"  registers[40098] = 0x{registers[40098]:04X} (should be 0x0FA0)")
print(f"  registers[40099] = 0x{registers[40099]:04X} (should be 0x0000)")
print(f"  registers[40107] = 0x{registers[40107]:04X} (should be 0x0002)")
print(f"  registers[40004] = 0x{registers[40004]:04X} (should be 0x4672 = 'Fr')")

verify_ok = (
    registers[40098] == 0x0FA0 and 
    registers[40107] == 0x0002 and
    registers[40004] == 0x4672
)

if verify_ok:
    print("\n✅ ALL REGISTER VALUES CORRECT!\n")
else:
    print("\n❌ REGISTER VALUES WRONG!\n")

# ====================================================
# Modbus Slave Context
# ====================================================

store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0x0000] * 65536),
    co=ModbusSequentialDataBlock(0, [0x0000] * 65536),
    hr=ModbusSequentialDataBlock(0, registers),  # ← Our register array
    ir=ModbusSequentialDataBlock(0, registers)
)

context = ModbusServerContext(slaves=store, single=True)

# ====================================================
# Start Server
# ====================================================

try:
    print("="*70)
    print("🚀 SunSpec Fake WR - ULTRA DIRECT")
    print("="*70)
    print("📡 Modbus TCP on 0.0.0.0:5202")
    print("🎯 SunSpec Registers configured:")
    print("   • Manufacturer (0x9C44/40004): Fronius")
    print("   • AC Power (0x9CA2/40098): 4000W")
    print("   • Status (0x9CAB/40107): RUNNING")
    print("="*70)
    print()
    
    StartTcpServer(context, address=("0.0.0.0", 5202))
    
except KeyboardInterrupt:
    print("\n[STOP] Server stopped")
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
