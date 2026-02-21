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
│   └─ WebSocket ws://IP:7070/ws                               │
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
Version: v0.0.6 - EVCC WebSocket Integration
"""

import asyncio
import json
import logging
import random
import threading
import websockets
from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock
from const import *  # Importiere alle Konstanten

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

# ====================================================
# Dynamische Werte (zur Laufzeit aktualisiert)
# ====================================================
# Diese Variablen werden von EVCC WebSocket gefüllt
current_power_w = STATIC_VALUES["power_w"]       # aktuelle Leistung
current_energy_kwh = STATIC_VALUES["energy_kwh"] # Gesamtenergie
register_lock = threading.Lock()

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

def _update_power_register(power_w):
    """Update SunSpec AC Power Register (0x9C93)"""
    global sunspec_registers, holding

    # 16-bit signed integer (für negative Werte)
    if power_w < 0:
        power_w = (1 << 16) + int(power_w)
    else:
        power_w = int(power_w) & 0xFFFF

    sunspec_registers[AC_POWER_ADDR] = power_w
    sunspec_registers[AC_POWER_ADDR + 1] = 0x0000  # Scale Factor

    # Auch in Holding-Array aktualisieren (mit +1 Offset)
    holding[AC_POWER_ADDR + 1] = power_w
    holding[AC_POWER_ADDR + 2] = 0x0000

    # Datastore direkt aktualisieren (falls holding kopiert wurde)
    store_ref = globals().get("store")
    if store_ref is not None:
        store_ref.setValues(3, AC_POWER_ADDR, [power_w, 0x0000])

def update_power_register(power_w):
    """Thread-sicheres Update des SunSpec AC Power Registers (0x9C93)"""
    with register_lock:
        _update_power_register(power_w)

def _update_energy_register(energy_kwh):
    """Update SunSpec Total Energy Register (0x9C9D) - 32-bit"""
    global sunspec_registers, holding

    # kWh → Wh (1:1 Mapping ohne Berechnungen)
    energy_wh = int(energy_kwh * 1000)

    # 32-bit in zwei 16-bit Register aufteilen (Big Endian)
    high = (energy_wh >> 16) & 0xFFFF
    low = energy_wh & 0xFFFF

    sunspec_registers[TOTAL_ENERGY_ADDR] = high
    sunspec_registers[TOTAL_ENERGY_ADDR + 1] = low
    sunspec_registers[TOTAL_ENERGY_ADDR + 2] = 0x0000  # Scale Factor

    # Auch in Holding-Array aktualisieren (mit +1 Offset)
    holding[TOTAL_ENERGY_ADDR + 1] = high
    holding[TOTAL_ENERGY_ADDR + 2] = low
    holding[TOTAL_ENERGY_ADDR + 3] = 0x0000

    # Datastore direkt aktualisieren (falls holding kopiert wurde)
    store_ref = globals().get("store")
    if store_ref is not None:
        store_ref.setValues(3, TOTAL_ENERGY_ADDR, [high, low, 0x0000])

def update_energy_register(energy_kwh):
    """Thread-sicheres Update des SunSpec Total Energy Registers (0x9C9D)"""
    with register_lock:
        _update_energy_register(energy_kwh)

def update_registers_from_values():
    """Update alle dynamischen Register basierend auf current_* Variablen"""
    global current_power_w, current_energy_kwh

    with register_lock:
        _update_power_register(current_power_w)
        _update_energy_register(current_energy_kwh)

# ====================================================
# SunSpec Register Dictionary definieren
# ====================================================

register_data = {}

# ====================================================
# EVCC WebSocket Integration (Production-Grade)
# ====================================================

class EvccWebsocketClient:
    """Robuster WebSocket-Client mit Reconnect, Message Queue und Deduplication"""
    
    def __init__(self, host, port, coordinator_callback):
        self.url = f"ws://{host}:{port}/ws"  # ⭐ EVCC WebSocket Endpoint
        self.coordinator_callback = coordinator_callback
        self._task = None
        self._consumer_task = None
        self._ws = None
        self._running = False
        self._message_queue = asyncio.Queue(maxsize=WS_QUEUE_MAX_SIZE)
        self._last_signature = None
        
        # Backoff-Konfiguration (exponentiell bis 60s)
        self._backoff_base = WS_BACKOFF_BASE
        self._backoff_max = WS_BACKOFF_MAX
    
    async def connect(self):
        """Starte WebSocket-Verbindung"""
        if self._task and not self._task.done():
            _LOGGER.debug("WebSocket-Client bereits aktiv")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run())
        self._consumer_task = asyncio.create_task(self._consume_messages())
        _LOGGER.info("WebSocket-Client gestartet")

    async def wait(self):
        """Warte bis der WebSocket-Task beendet ist"""
        if self._task:
            await self._task
    
    async def disconnect(self):
        """Trenne WebSocket-Verbindung sauber"""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception as err:
                _LOGGER.debug("Fehler beim Schließen der WS: %s", err)
        
        for task in (self._task, self._consumer_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as err:
                    _LOGGER.debug("Fehler beim Stoppigen des Tasks: %s", err)
        
        self._task = None
        self._consumer_task = None
        self._ws = None
        self._clear_queue()
        _LOGGER.info("WebSocket-Client getrennt")
    
    async def _run(self):
        """Hauptschleife: Verbinde, empfange Nachrichten, Reconnect bei Fehler"""
        backoff = self._backoff_base
        
        while self._running:
            try:
                _LOGGER.info("Verbinde zu EVCC WebSocket: %s", self.url)
                async with websockets.connect(
                    self.url,
                    open_timeout=WS_OPEN_TIMEOUT,    # ⭐ Timeout beim Verbinden
                    ping_interval=WS_PING_INTERVAL,  # ⭐ Heartbeat
                    ping_timeout=WS_PING_TIMEOUT,    # ⭐ Ping-Timeout
                    max_size=WS_MAX_SIZE,             # ⭐ Max Message Size
                ) as ws:
                    self._ws = ws
                    _LOGGER.info("✅ EVCC WebSocket verbunden!")
                    backoff = self._backoff_base  # Reset nach erfolgreichem Connect
                    
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            
                            # Filtere relevante Nachrichten
                            if self._is_relevant_update(data):
                                _LOGGER.debug("Relevante WS-Nachricht empfangen")
                                
                                # Deduplication: Skip wenn gleiche Daten wie zuletzt
                                signature = self._signature(data)
                                if signature == self._last_signature:
                                    _LOGGER.debug("Duplicate WS-Nachricht ignoriert")
                                    continue
                                self._last_signature = signature
                                
                                # Schreibe in asynce Queue (non-blocking)
                                if not self._message_queue.full():
                                    await self._message_queue.put(data)
                                else:
                                    _LOGGER.warning("WS-Message Queue voll; Nachricht wird verworfen")
                        
                        except json.JSONDecodeError:
                            _LOGGER.debug("Nicht-JSON WS-Nachricht ignoriert")
                        except Exception as e:
                            _LOGGER.error("Fehler bei WS-Nachrichtenverarbeitung: %s", e)
            
            except websockets.exceptions.WebSocketException as e:
                self._ws = None
                self._last_signature = None
                _LOGGER.warning("❌ WS-Fehler: %s", e)
                sleep_for = self._next_backoff(backoff)
                _LOGGER.debug("Backoff nach WS-Fehler: %.2fs", sleep_for)
                await asyncio.sleep(sleep_for)
                backoff = min(backoff * 2, self._backoff_max)
            
            except asyncio.CancelledError:
                _LOGGER.debug("WebSocket-Run-Task abgebrochen")
                break
            
            except Exception as e:
                self._ws = None
                self._last_signature = None
                _LOGGER.warning("⚠️ Unerwarteter WS-Fehler: %s", e)
                sleep_for = self._next_backoff(backoff)
                _LOGGER.debug("Backoff nach Fehler: %.2fs", sleep_for)
                await asyncio.sleep(sleep_for)
                backoff = min(backoff * 2, self._backoff_max)
    
    async def _consume_messages(self):
        """Separate Task: Verarbeite Nachrichten aus der Queue"""
        while self._running or not self._message_queue.empty():
            try:
                data = await self._message_queue.get()
                await self.coordinator_callback(data)
            except asyncio.CancelledError:
                _LOGGER.debug("Consumer-Task abgebrochen")
                break
            except Exception as err:
                _LOGGER.error("Fehler im Consumer-Task: %s", err)
            finally:
                self._message_queue.task_done()
    
    def _clear_queue(self):
        """Leere die Message Queue"""
        while not self._message_queue.empty():
            try:
                self._message_queue.get_nowait()
                self._message_queue.task_done()
            except asyncio.QueueEmpty:
                break
    
    def _next_backoff(self, current: int) -> float:
        """Exponential Backoff mit Jitter"""
        jitter = random.uniform(0, current)
        return min(current + jitter, self._backoff_max)
    
    def _is_relevant_update(self, data: dict) -> bool:
        """Filtere nur relevante EVCC-Updates (Power, Energy)"""
        if not isinstance(data, dict):
            return False
        
        # Akzeptiere "site" oder direkt pvEnergy/gridPower/residualPower Updates
        if "site" in data:
            return True
        if "gridPower" in data or "residualPower" in data or "pvEnergy" in data:
            return True
        
        return False
    
    def _signature(self, data: dict) -> str:
        """Erstelle Hash der Nachrichten-Inhalte für Deduplication"""
        try:
            return json.dumps(data, sort_keys=True)
        except Exception:
            return str(data)

async def evcc_websocket_worker():
    """Asynchroner WebSocket-Worker mit Message Queue"""
    global current_power_w, current_energy_kwh, ws_client
    
    ws_client = EvccWebsocketClient(EVCC_HOST, EVCC_WS_PORT, handle_evcc_update)
    await ws_client.connect()
    await ws_client.wait()

async def handle_evcc_update(data):
    """Callback: Verarbeite EVCC-Updates"""
    global current_power_w, current_energy_kwh
    
    try:
        if "site" in data:
            site = data["site"]
        else:
            site = data
        _LOGGER.debug("EVCC update empfangen: keys=%s", list(site.keys()))

            
        # Leistung (residualPower fallback, wenn gridPower fehlt)
        if "gridPower" in site:
            power_value = site["gridPower"]
            power_source = "gridPower"
        elif "residualPower" in site:
            power_value = site["residualPower"]
            power_source = "residualPower"
        else:
            power_value = None
            power_source = None

        if power_value is not None:
            old_power = current_power_w
            current_power_w = max(0, int(power_value))
            if current_power_w != old_power:
                _LOGGER.info("Power aktualisiert: %d W → %d W", old_power, current_power_w)
            _LOGGER.debug("EVCC %s: %s W → Register 0x9C93=%d", power_source, power_value, current_power_w)
        
        # Energie (kWh)
        if "pvEnergy" in site:
            current_energy_kwh = float(site["pvEnergy"])
            _LOGGER.debug("Energy aktualisiert: %.2f kWh", current_energy_kwh)
            _LOGGER.debug("EVCC pvEnergy: %.3f kWh", current_energy_kwh)
        
        update_registers_from_values()
        _LOGGER.debug(
            "Register aktualisiert: 0x9C93=%d W, 0x9C9D=%.3f kWh",
            current_power_w,
            current_energy_kwh,
        )
    
    except Exception as e:
        _LOGGER.error("Fehler bei EVCC-Update-Verarbeitung: %s", e)

def run_evcc_websocket():
    """Starte WebSocket-Worker in eigenem Event Loop (für threading)"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(evcc_websocket_worker())
    except KeyboardInterrupt:
        _LOGGER.info("WebSocket-Worker durch Benutzer gestoppt")
    except Exception as e:
        _LOGGER.error("WebSocket-Worker Fehler: %s", e)
    finally:
        loop.close()

# ====================================================
# Globale WebSocket-Instanz
# ====================================================
ws_client = None

# ====================================================
# SunSpec Register Dictionary definieren
# ====================================================

register_data = {}
sunspec_registers = {}  # Globales Register-Dict (für Updates)

# ========== FESTE WR-IDENTITÄT ==========
# Diese Register bleiben immer konstant

# ---- 0x9C40: SunSpec Identifier ("SunS") - CRITICAL!
register_data[SUNSPEC_IDENTIFIER_ADDR] = [0x5375, 0x6E53]  # "Su" + "nS"

# ---- 0x9C44 (40004): Manufacturer
register_data[MANUFACTURER_ADDR] = str_to_regs(MANUFACTURER, 5)

# ---- 0x9C74 (40148): Serial Number (16 Register = 32 Bytes)
register_data[SERIAL_NUMBER_ADDR] = str_to_regs(SERIAL_NUMBER, 16)

# ---- 0x9CAB (40235): Inverter Status
register_data[INVERTER_STATUS_ADDR] = [WR_STATUS]  # 0x0002 = RUNNING

# ========== DYNAMISCHE WERTE (Später von EVCC) ==========
# Diese Register werden dynamisch aktualisiert

# ---- 0x9C93 (40179): AC Total Power (dynamisch aus EVCC)
power_w = int(current_power_w) & 0xFFFF
register_data[AC_POWER_ADDR] = [power_w, 0x0000]

# ---- 0x9C9D (40189): Total Energy 32-bit (dynamisch aus EVCC)
energy_wh = int(current_energy_kwh * 1000)
energy_hi = (energy_wh >> 16) & 0xFFFF
energy_lo = energy_wh & 0xFFFF
register_data[TOTAL_ENERGY_ADDR] = [energy_hi, energy_lo, 0x0000]

# ---- 0x9CA2 (40167): VPV1 (DC Voltage)
register_data[VPV1_ADDR] = [600, 0x0000]

# ---- 0x9CA7 (40199): Temperatur + Scale Factors
register_data[TEMPERATURE_ADDR] = [WR_TEMPERATURE * 10, 0x8000, 0x8000, 0xFFFF]

# ====================================================
# Holding Register Array bauen
# ====================================================

# Das größte Register bestimmen
if register_data:  # Nur wenn register_data nicht leer ist
    max_reg_addr = max(register_data.keys())
    max_length = max(len(v) for v in register_data.values())
    max_addr = max_reg_addr + max_length + 10
else:
    # Fallback wenn register_data leer ist
    _LOGGER.error("❌ KRITISCHER FEHLER: register_data ist leer! Konstanten nicht importiert?")
    max_addr = 0x10000  # Default große Größe

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
print(f"[INIT] SunSpec Identifier (0x9C40) = 0x{holding[SUNSPEC_IDENTIFIER_ADDR+1]:04X} 0x{holding[SUNSPEC_IDENTIFIER_ADDR+2]:04X} (sollte 0x5375 0x6E53)")
print(f"[INIT] Manufacturer (0x9C44) = 0x{holding[MANUFACTURER_ADDR+1]:04X}")
print(f"[INIT] Status (0x9CAB) = 0x{holding[INVERTER_STATUS_ADDR+1]:04X}")

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
    print(f"🚀 SunSpec Fake WR (Fronius Simulation) — {VERSION}")
    print("="*70)
    print(f"📡 Modbus TCP Port: {MODBUS_PORT}")
    print(f"")
    print(f"🏭 WR-Identität:")
    print(f"   Manufacturer: {MANUFACTURER}")
    print(f"   Model: {MODEL}")
    print(f"   Serial: {SERIAL_NUMBER}")
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
        print(f"   Status: {'🟢 Verbindet...' if LIVE else '🔴 DEAKTIVIERT'}")
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
        print("[MAIN] ✅ EVCC WebSocket-Worker gestartet (mit Reconnect & Message Queue)\n")
    
    # Starte Modbus Server (blockierend)
    StartTcpServer(context, address=(MODBUS_HOST, MODBUS_PORT))
    
except KeyboardInterrupt:
    print("\n\n[INFO] Server gestoppt (CTRL+C).")
except Exception as e:
    print(f"\n[ERROR] Server-Fehler: {e}")
