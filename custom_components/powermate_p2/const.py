"""Constants for the PowerMate P2 (Orvibo HomeMate) integration."""

from __future__ import annotations

DOMAIN = "powermate_p2"

DEFAULT_HOST = "homemate.orvibo.com"
DEFAULT_PORT = 10001
SOFTWARE_VER = "3.6.0.300"

PK_KEY = b"khggd54865SNJHGF"
MAGIC = b"hd"
PK_TYPE = b"pk"
DK_TYPE = b"dk"
UNSET_SESSION_ID = b" " * 32

CMD_HELLO = 0
CMD_LOGIN = 2
CMD_QUERY_TABLE = 4
CMD_CONTROL = 15
CMD_HEARTBEAT = 32
CMD_STATUS_REPORT = 42

DEVICE_TYPE_GATEWAY = 67
DEVICE_TYPE_RF_SHADE = 42

# Supported Orvibo / PowerMate P2 RF motorized shade & curtain deviceType codes:
# 34 = RF Curtain, 35 = RF Roller Shutter, 39 = RF Window Opener, 42 = A-OK / RF Roller Shade
SUPPORTED_RF_SHADE_TYPES = frozenset({34, 35, 39, 42})

ORDER_RF_CONTROL = "rf control"
RF_VALUE_OPEN = 380000
RF_VALUE_CLOSE = 380001
RF_VALUE_STOP = 380002

CONF_FAMILY_ID = "family_id"
CONF_PASSWORD_HASH = "password_hash"
