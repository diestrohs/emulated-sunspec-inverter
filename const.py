"""
Konstanten für Emulated SunSpec WR
"""

# ====================================================
# MODE SWITCH
# ====================================================
LIVE = True    # True = EVCC Live Daten (WebSocket)
              # False = statische Demo-Werte

# ====================================================
# EVCC VERBINDUNG
# ====================================================
EVCC_HOST = "192.168.178.5"           # EVCC läuft im host mode → direkte Host-IP
EVCC_WS_PORT = 7070                   # WebSocket Port
EVCC_WS_URI = f"ws://{EVCC_HOST}:{EVCC_WS_PORT}/ws"  # ⭐ Echter EVCC Endpoint ist /ws

# ====================================================
# FESTE WERTE (WR-Identität)
# ====================================================
MANUFACTURER = "OpenSource"        # Hersteller (bleibt immer gleich)
SERIAL_NUMBER = "12345678"         # Seriennummer (Fallback wenn LIVE=False)
MODEL = "EVCC"                     # Modell (optional, statisch)

# ====================================================
# STATISCHE KONFIGURATION
# ====================================================
WR_STATUS = 0x0002                 # 0x0002 = RUNNING, 0x0001 = IDLE
WR_TEMPERATURE = 45                # °C (statisch)

# ====================================================
# STATISCHE FALLBACK-WERTE (wenn LIVE=False oder EVCC offline)
# ====================================================
STATIC_VALUES = {
    "power_w": 4000,               # W - Netz-Überschuss
    "energy_kwh": 58940.909        # kWh - Gesamtenergie (wie EVCC liefert)
}

# ====================================================
# MODBUS KONFIGURATION
# ====================================================
MODBUS_PORT = 5202                 # Modbus TCP Port
MODBUS_HOST = "0.0.0.0"            # Alle Interfaces

# ====================================================
# WEBSOCKET KONFIGURATION
# ====================================================
WS_OPEN_TIMEOUT = 10               # Timeout beim Verbinden (Sekunden)
WS_PING_INTERVAL = 30              # Heartbeat-Frequenz (Sekunden)
WS_PING_TIMEOUT = 10               # Ping-Response Timeout (Sekunden)
WS_MAX_SIZE = 1_000_000            # Maximale Nachrichtengröße (Bytes)
WS_QUEUE_MAX_SIZE = 100            # Maximale Queue-Größe (Messages)

# ====================================================
# BACKOFF KONFIGURATION
# ====================================================
WS_BACKOFF_BASE = 1                # Basis-Backoff (Sekunden)
WS_BACKOFF_MAX = 60                # Maximales Backoff (Sekunden)

# ====================================================
# VERSION
# ====================================================
VERSION = "v0.1.0"
VERSION_INFO = "Code Cleanup, Thread-Safe Register Updates, Konsistenz-Verbesserungen"

# ====================================================
# SUNSPEC REGISTER MAPPING
# ====================================================
SUNSPEC_IDENTIFIER_ADDR = 0x9C40   # "SunS"
MANUFACTURER_ADDR = 0x9C44         # "OpenSource"
SERIAL_NUMBER_ADDR = 0x9C74        # Seriennummer
INVERTER_STATUS_ADDR = 0x9CAB      # Status (RUNNING/IDLE)
AC_POWER_ADDR = 0x9C93             # AC Total Power
TOTAL_ENERGY_ADDR = 0x9C9D         # Total Energy (32-bit)
VPV1_ADDR = 0x9CA2                 # VPV1 (DC Voltage)
TEMPERATURE_ADDR = 0x9CA7          # Temperatur
