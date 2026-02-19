#!/usr/bin/env python3
"""
SunSpec Fake WR mit Custom Modbus Handler
Behandelt explizit die SunSpec Hex-Adressen (0x9C44, 0x9CA2, etc.)
"""

from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.datastore.store import BaseModbusDataBlock

# ====================================================
# Custom Modbus Data Block für explizites Addressing
# ====================================================

class CustomSunSpecDataBlock(BaseModbusDataBlock):
    """Custom Register Store für SunSpec Adressen"""
    
    def __init__(self):
        self.registers = {}
        self._setup_registers()
    
    def _setup_registers(self):
        """Initialisiere alle SunSpec Register"""
        
        # Helper
        def str_to_regs(s, num_regs):
            """String zu Registers"""
            regs = []
            s = s + '\x00' * (num_regs * 2 - len(s))
            for i in range(num_regs):
                high = ord(s[i*2])
                low = ord(s[i*2+1])
                regs.append((high << 8) | low)
            return regs
        
        # 0x9C44 (hex) = 40004 (dezimal): Manufacturer "Fronius"
        mfg = str_to_regs("Fronius", 5)
        for i, val in enumerate(mfg):
            self.registers[40004 + i] = val
        print(f"[INIT] 0x9C44 (40004): Manufacturer = {[hex(x) for x in mfg]}")
        
        # 0x9CA2 (hex) = 40098 (dezimal): AC Power
        self.registers[40098] = 4000      # AC Power = 4000W (0x0FA0)
        self.registers[40099] = 0         # AC Power Scale Factor = 0
        print(f"[INIT] 0x9CA2 (40098): AC Power = 4000W (0x{4000:04X})")
        print(f"[INIT] 0x9CA3 (40099): AC Power SF = 0")
        
        # 0x9CAB (hex) = 40107 (dezimal): Status = RUNNING
        self.registers[40107] = 0x0002    # RUNNING
        print(f"[INIT] 0x9CAB (40107): Status = RUNNING (0x0002)")
        
        # 0x9C74 (hex) = 40052 (dezimal): Serial "34110779"
        serial = str_to_regs("34110779", 16)
        for i, val in enumerate(serial):
            self.registers[40052 + i] = val
        print(f"[INIT] 0x9C74 (40052): Serial = {[hex(x) for x in serial[:2]]}")
        
        # 0x9C93 (hex) = 40083 (dezimal): Options
        self.registers[40083] = 0x0000
        self.registers[40084] = 0x0000
        print(f"[INIT] 0x9C93 (40083): Options = 0x0000 0x0000")
        
        # 0x9C9D (hex) = 40093 (dezimal): Firmware
        self.registers[40093] = 0xAE90
        self.registers[40094] = 0x0E12
        self.registers[40095] = 0xFFFE
        print(f"[INIT] 0x9C9D (40093): Firmware = 0xAE90 0x0E12 0xFFFE")
        
        # 0x9CA7 (hex) = 40103 (dezimal): Scale Factors
        self.registers[40103] = 0x8000
        self.registers[40104] = 0x8000
        self.registers[40105] = 0x8000
        self.registers[40106] = 0xFFFF
        print(f"[INIT] 0x9CA7 (40103): Scale Factors = 0x8000 0x8000 0x8000 0xFFFF")
    
    def validate(self, address):
        """Validate address exists"""
        return address in self.registers or address < 50000
    
    def getValues(self, address, count=1):
        """Read multiple registers"""
        result = []
        for i in range(count):
            result.append(self.registers.get(address + i, 0))
        return result
    
    def setValues(self, address, values):
        """Write multiple registers"""
        for i, val in enumerate(values):
            self.registers[address + i] = val

# ====================================================
# Verifikation
# ====================================================

print("[VERIFY] Checking register values:")
db = CustomSunSpecDataBlock()

# Read back values
ac_power_val = db.registers.get(40098, 0)
ac_power_sf = db.registers.get(40099, 0)
status_val = db.registers.get(40107, 0)
mfg_val = db.registers.get(40004, 0)

print(f"  registers[40098] (AC Power) = 0x{ac_power_val:04X} (should be 0x0FA0)")
print(f"  registers[40099] (AC Power SF) = 0x{ac_power_sf:04X} (should be 0x0000)")
print(f"  registers[40107] (Status) = 0x{status_val:04X} (should be 0x0002)")
print(f"  registers[40004] (Manufacturer) = 0x{mfg_val:04X} (should be 0x4672 = 'Fr')")

if ac_power_val == 0x0FA0 and status_val == 0x0002:
    print("\n✅ Register values CORRECT!")
else:
    print("\n❌ Register values WRONG!")

# ====================================================
# Modbus Server mit Custom Data Block
# ====================================================

store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0] * 50000),
    co=ModbusSequentialDataBlock(0, [0] * 50000),
    hr=db,  # ← Custom Data Block!
    ir=db
)

context = ModbusServerContext(slaves=store, single=True)

# ====================================================
# Start Server
# ====================================================

try:
    print("\n" + "="*70)
    print("🚀 SunSpec Fake WR (Custom Modbus Handler)")
    print("="*70)
    print("📡 TCP Server on Port 5202")
    print("🎯 Register Mapping:")
    print("   0x9CA2 (40098): AC Power = 4000W")
    print("   0x9CAB (40107): Status = RUNNING")
    print("   0x9C44 (40004): Manufacturer = Fronius")
    print("="*70 + "\n")
    
    StartTcpServer(context, address=("0.0.0.0", 5202))
    
except KeyboardInterrupt:
    print("\n[INFO] Server stopped (CTRL+C)")
except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
