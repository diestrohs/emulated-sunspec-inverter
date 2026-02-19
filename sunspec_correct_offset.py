#!/usr/bin/env python3
"""
SunSpec Fake WR - CORRECT MODBUS OFFSET ADDRESSING
Modbus Holding Registers: 40001-49999
PDU Address = Offset + 40001
So: PDU 0x9C44 (40004) = Offset 3 in registers array
"""

from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock

# ====================================================
# MODBUS ADDRESSING:
# PDU Address 40001-49999 (Holding Registers)
# Array Index = PDU - 40001
# ====================================================

# Create register array for Holding Registers (index 0 = PDU address 40001)
registers = [0x0000] * 10000  # 40001-50000

def write_string(pdu_addr, s, num_regs):
    """Write string, using PDU address (40001+)"""
    offset = pdu_addr - 40001
    s = s + '\x00' * (num_regs * 2)
    for i in range(num_regs):
        high = ord(s[i * 2])
        low = ord(s[i * 2 + 1])
        val = (high << 8) | low
        registers[offset + i] = val
    print(f"  PDU 0x{pdu_addr:04X} (offset {offset}): {[hex(registers[offset + j]) for j in range(min(3, num_regs))]}")

def write_value(pdu_addr, value):
    """Write single register, using PDU address"""
    offset = pdu_addr - 40001
    registers[offset] = value
    print(f"  PDU 0x{pdu_addr:04X} (offset {offset}): 0x{value:04X}")

def write_values(pdu_addr, values):
    """Write multiple registers, using PDU address"""
    offset = pdu_addr - 40001
    for i, v in enumerate(values):
        registers[offset + i] = v
    print(f"  PDU 0x{pdu_addr:04X} (offset {offset}): {[hex(v) for v in values]}")

# ====================================================
# Write SunSpec Registers
# ====================================================

print("[INIT] Writing SunSpec registers with CORRECT offset addressing:")
print()

# PDU addresses from hex:
# 0x9C44 = 40004 (Manufacturer)
# 0x9C74 = 40052 (Serial)
# 0x9C93 = 40083 (Options)
# 0x9C9D = 40093 (Firmware)
# 0x9CA2 = 40098 (AC Power)
# 0x9CA7 = 40103 (Scale Factors)
# 0x9CAB = 40107 (Status)

write_string(0x9C44, "Fronius", 5)      # Manufacturer
write_string(0x9C74, "34110779", 16)    # Serial
write_values(0x9C93, [0x0000, 0x0000])  # Options
write_values(0x9C9D, [0xAE90, 0x0E12, 0xFFFE])  # Firmware
write_values(0x9CA2, [0x0FA0, 0x0000])  # AC Power + SF
write_values(0x9CA7, [0x8000, 0x8000, 0x8000, 0xFFFF])  # Scale Factors
write_value(0x9CAB, 0x0002)             # Status = RUNNING

# ====================================================
# VERIFY
# ====================================================

print("\n[VERIFY] Reading back with correct offsets:")
print(f"  offset[3] (0x9C44/40004, Mfg) = 0x{registers[0x9C44-40001]:04X} (should be 0x4672 = 'Fr')")
print(f"  offset[97] (0x9CA2/40098, Power) = 0x{registers[0x9CA2-40001]:04X} (should be 0x0FA0 = 4000)")
print(f"  offset[106] (0x9CAB/40107, Status) = 0x{registers[0x9CAB-40001]:04X} (should be 0x0002 = RUNNING)")

verify_ok = (registers[0x9C44-40001] == 0x4672 and 
             registers[0x9CA2-40001] == 0x0FA0 and
             registers[0x9CAB-40001] == 0x0002)

if verify_ok:
    print("\n✅ REGISTER VALUES CORRECT WITH OFFSET ADDRESSING!")
else:
    print("\n❌ Register values wrong!")

# ====================================================
# Modbus Slave Context
# ====================================================

store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0x0000] * 10000),
    co=ModbusSequentialDataBlock(0, [0x0000] * 10000),
    hr=ModbusSequentialDataBlock(0, registers),  # Holding Registers (40001+)
    ir=ModbusSequentialDataBlock(0, registers)
)

context = ModbusServerContext(slaves=store, single=True)

# ====================================================
# Start Server
# ====================================================

try:
    print("\n" + "="*70)
    print("🚀 SunSpec Fake WR - CORRECTED OFFSET ADDRESSING")
    print("="*70)
    print("📡 Modbus TCP on 0.0.0.0:5202")
    print("📊 PDU Address Mapping (Holding Registers 40001+):")
    print("   • 0x9C44 (PDU 40004): Manufacturer = Fronius")
    print("   • 0x9CA2 (PDU 40098): AC Power = 4000W")
    print("   • 0x9CAB (PDU 40107): Status = RUNNING")
    print("="*70)
    print()
    
    StartTcpServer(context, address=("0.0.0.0", 5202))
    
except KeyboardInterrupt:
    print("\n[STOP] Server stopped (CTRL+C)")
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
