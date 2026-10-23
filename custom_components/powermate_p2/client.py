"""Async TCP client for PowerMate P2 (Orvibo HomeMate protocol)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import logging
import struct
from typing import Any
import zlib

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    CMD_CONTROL,
    CMD_HEARTBEAT,
    CMD_HELLO,
    CMD_LOGIN,
    CMD_QUERY_TABLE,
    CMD_STATUS_REPORT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEVICE_TYPE_GATEWAY,
    DK_TYPE,
    MAGIC,
    ORDER_RF_CONTROL,
    PK_KEY,
    PK_TYPE,
    RF_VALUE_CLOSE,
    RF_VALUE_OPEN,
    RF_VALUE_STOP,
    SOFTWARE_VER,
    SUPPORTED_RF_SHADE_TYPES,
    UNSET_SESSION_ID,
)

_LOGGER = logging.getLogger(__name__)


def md5_upper(password: str) -> str:
    """Return uppercase MD5 hex digest required by Orvibo HomeMate."""
    return hashlib.md5(password.encode("utf-8")).hexdigest().upper()


def _aes_encrypt(data: bytes, key: bytes) -> bytes:
    """Encrypt bytes using AES-128-ECB with PKCS7 padding."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _aes_decrypt(data: bytes, key: bytes) -> bytes:
    """Decrypt bytes using AES-128-ECB with PKCS7 unpadding."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    raw = decryptor.update(data) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(raw) + unpadder.finalize()


@dataclass
class PowerMateGateway:
    """Representation of an Allone Pro / PowerMate P2 hub."""

    uid: str
    device_id: str
    name: str
    model: str
    online: bool = True


@dataclass
class PowerMateShade:
    """Representation of a motorized shade paired to the hub."""

    device_id: str
    uid: str
    name: str
    raw_name: str
    company: str
    model: str
    device_type: int


class PowerMateAuthError(Exception):
    """Raised when authentication fails."""


class PowerMateConnectionError(Exception):
    """Raised when communication with the server fails."""


class PowerMateClient:
    """Manages the encrypted TCP session to homemate.orvibo.com:10001."""

    def __init__(
        self,
        username: str,
        password_hash: str,
        family_id: str | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        heartbeat_interval: float = 90.0,
    ) -> None:
        """Initialize the PowerMate P2 client."""
        self.username = username
        self.password_hash = password_hash.upper()
        self.family_id = family_id
        self.user_id: str | None = None
        self._host = host
        self._port = port
        self._heartbeat_interval = heartbeat_interval

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._session_id: bytes = UNSET_SESSION_ID
        self._dk: bytes | None = None
        self._serial: int = 1
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._closing = False

        self.gateways: dict[str, PowerMateGateway] = {}
        self.shades: dict[str, PowerMateShade] = {}
        self._callbacks: list[Callable[[str, int], None]] = []

    @property
    def connected(self) -> bool:
        """Return True if an authenticated session is active."""
        return (
            self._writer is not None
            and not self._writer.is_closing()
            and self._dk is not None
        )

    def register_callback(
        self, callback: Callable[[str, int], None]
    ) -> Callable[[], None]:
        """Register a callback(device_id, value1) for push state updates."""
        self._callbacks.append(callback)

        def _remove() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return _remove

    def _next_serial(self) -> int:
        self._serial = (self._serial % 999999) + 1
        return self._serial

    def _build_packet(
        self,
        payload: dict[str, Any],
        pkt_type: bytes,
        session_id: bytes,
        key: bytes,
    ) -> bytes:
        raw_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        encrypted = _aes_encrypt(raw_json, key)
        crc = zlib.crc32(encrypted) & 0xFFFFFFFF
        total_len = 42 + len(encrypted)
        header = (
            MAGIC
            + struct.pack(">H", total_len)
            + pkt_type
            + struct.pack(">I", crc)
            + session_id
        )
        return header + encrypted

    async def _send_request(
        self,
        payload: dict[str, Any],
        pkt_type: bytes,
        session_id: bytes,
        key: bytes,
        timeout: float = 8.0,
    ) -> dict[str, Any]:
        if self._writer is None or self._writer.is_closing():
            raise PowerMateConnectionError("Not connected")

        serial = payload.get("serial")
        if serial is None:
            serial = self._next_serial()
            payload["serial"] = serial

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[serial] = fut

        packet = self._build_packet(payload, pkt_type, session_id, key)
        try:
            async with self._write_lock:
                self._writer.write(packet)
                await asyncio.wait_for(self._writer.drain(), timeout=timeout)
            return await asyncio.wait_for(fut, timeout=timeout)
        except Exception as err:
            self._pending.pop(serial, None)
            cmd_num = payload.get("cmd")
            raise PowerMateConnectionError(
                f"Request cmd={cmd_num} failed: {err}"
            ) from err

    async def _reader_loop(self) -> None:
        """Continuously read packets from the TCP stream."""
        reader = self._reader
        if reader is None:
            return
        try:
            while not self._closing:
                header_prefix = await reader.readexactly(4)
                if header_prefix[:2] != MAGIC:
                    raise PowerMateConnectionError(
                        f"Invalid magic: {header_prefix[:2]!r}"
                    )
                total_len = struct.unpack(">H", header_prefix[2:4])[0]
                if total_len < 42 or total_len > 65535:
                    raise PowerMateConnectionError(
                        f"Invalid packet length: {total_len}"
                    )
                rest = await reader.readexactly(total_len - 4)
                pkt_type = rest[0:2]
                session_id = rest[6:38]
                encrypted = rest[38:]

                key = PK_KEY if pkt_type == PK_TYPE else (self._dk or PK_KEY)
                raw = (
                    _aes_decrypt(encrypted, key)
                    .decode("utf-8", errors="replace")
                    .rstrip("\x00")
                )
                msg = json.loads(raw)

                if pkt_type == PK_TYPE and msg.get("cmd") == CMD_HELLO:
                    self._session_id = session_id

                serial = msg.get("serial")
                if isinstance(serial, int) and serial in self._pending:
                    fut = self._pending.pop(serial)
                    if not fut.done():
                        fut.set_result(msg)
                    continue

                # Unsolicited push message (e.g. cmd=42 status update)
                cmd = msg.get("cmd")
                if cmd in (CMD_STATUS_REPORT, CMD_CONTROL):
                    device_id = msg.get("deviceId")
                    value1 = msg.get("value1")
                    if isinstance(device_id, str) and isinstance(value1, int):
                        for cb in list(self._callbacks):
                            try:
                                cb(device_id, value1)
                            except Exception:
                                _LOGGER.exception("Error in PowerMate callback")
        except asyncio.CancelledError:
            pass
        except Exception as err:
            if not self._closing:
                _LOGGER.debug("PowerMate reader loop ended: %s", err)
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(
                        PowerMateConnectionError("Connection closed")
                    )
            self._pending.clear()

    async def _heartbeat_loop(self) -> None:
        """Keep the cloud TCP session warm with periodic cmd=32 heartbeats."""
        try:
            while not self._closing:
                await asyncio.sleep(self._heartbeat_interval)
                if not self.connected or self._dk is None:
                    continue
                try:
                    await self._send_request(
                        {
                            "cmd": CMD_HEARTBEAT,
                            "ver": SOFTWARE_VER,
                            "clientType": 1,
                        },
                        DK_TYPE,
                        self._session_id,
                        self._dk,
                        timeout=6.0,
                    )
                except Exception as err:
                    _LOGGER.debug(
                        "PowerMate heartbeat failed, will reconnect on next action: %s",
                        err,
                    )
                    await self._close_socket()
        except asyncio.CancelledError:
            pass

    async def _close_socket(self) -> None:
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        self._reader_task = None
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        self._dk = None

    async def async_close(self) -> None:
        """Shut down the client and background tasks."""
        self._closing = True
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None
        await self._close_socket()

    async def async_connect(self) -> None:
        """Establish TCP connection, handshake (cmd=0), and authenticate (cmd=2)."""
        async with self._connect_lock:
            if self.connected:
                return

            await self._close_socket()
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=10.0,
                )
            except Exception as err:
                raise PowerMateConnectionError(
                    f"Cannot connect to {self._host}:{self._port}: {err}"
                ) from err

            self._reader_task = asyncio.create_task(self._reader_loop())

            # Step 1: Handshake (cmd=0)
            hello_payload = {
                "cmd": CMD_HELLO,
                "ver": SOFTWARE_VER,
                "source": "HomeMate",
                "softwareVersion": "30600300",
                "sysVersion": "Android14",
                "hardwareVersion": "HomeAssistant",
                "language": "en",
                "identifier": "ha-powermate-p2",
                "phoneName": "HomeAssistant",
                "clientType": 1,
            }
            hello_resp = await self._send_request(
                hello_payload, PK_TYPE, UNSET_SESSION_ID, PK_KEY
            )
            if hello_resp.get("status") != 0 or "key" not in hello_resp:
                await self._close_socket()
                raise PowerMateConnectionError(
                    f"Handshake failed: {hello_resp}"
                )

            self._dk = hello_resp["key"].encode("utf-8")

            # Step 2: Login (cmd=2)
            if not self.family_id:
                init_login = {
                    "cmd": CMD_LOGIN,
                    "ver": SOFTWARE_VER,
                    "userName": self.username,
                    "password": self.password_hash,
                    "type": 3,
                    "clientType": 1,
                }
                init_resp = await self._send_request(
                    init_login, DK_TYPE, self._session_id, self._dk
                )
                if init_resp.get("status") != 0:
                    await self._close_socket()
                    login_status = init_resp.get("status")
                    raise PowerMateAuthError(
                        f"Login failed (status={login_status})"
                    )
                self.user_id = init_resp.get("userId")
                families = init_resp.get("familyList") or []
                if families:
                    self.family_id = families[0].get("familyId")

            login_payload: dict[str, Any] = {
                "cmd": CMD_LOGIN,
                "ver": SOFTWARE_VER,
                "userName": self.username,
                "password": self.password_hash,
                "type": 3,
                "clientType": 1,
            }
            if self.family_id:
                login_payload["familyId"] = self.family_id

            login_resp = await self._send_request(
                login_payload, DK_TYPE, self._session_id, self._dk
            )
            if login_resp.get("status") != 0:
                await self._close_socket()
                login_status = login_resp.get("status")
                raise PowerMateAuthError(
                    f"Login failed (status={login_status})"
                )

            self.user_id = login_resp.get("userId") or self.user_id
            gw_list = list(login_resp.get("gatewayList") or [])
            for fam in login_resp.get("familyList") or []:
                if not self.family_id and fam.get("familyId"):
                    self.family_id = fam.get("familyId")
                gw_list.extend(fam.get("gatewayList") or [])
            for gw in gw_list:
                uid = gw.get("uid")
                if uid:
                    self.gateways[uid] = PowerMateGateway(
                        uid=uid,
                        device_id=uid,
                        name="PowerMate P2 Hub",
                        model=gw.get("model", "Allone Pro"),
                        online=(gw.get("isOnline") == "YES"),
                    )

            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop()
                )

    async def async_discover_devices(self) -> dict[str, PowerMateShade]:
        """Query the device table on homemate.orvibo.com and populate hubs and shades."""
        await self.async_connect()
        assert self._dk is not None

        uids = list(self.gateways.keys()) or [""]
        for uid in uids:
            resp = await self._send_request(
                {
                    "cmd": CMD_QUERY_TABLE,
                    "ver": SOFTWARE_VER,
                    "uid": uid,
                    "userName": self.username,
                    "familyId": self.family_id or "",
                    "tableName": "device",
                    "dataType": "all",
                    "lastUpdateTime": 0,
                    "pageIndex": 0,
                },
                DK_TYPE,
                self._session_id,
                self._dk,
            )
            for row in resp.get("allList") or resp.get("device") or []:
                if row.get("delFlag") not in (0, None):
                    continue
                dev_type = row.get("deviceType")
                dev_id = row.get("deviceId")
                dev_uid = row.get("uid") or uid
                raw_name = (row.get("deviceName") or "Shade").strip()
                if dev_type == DEVICE_TYPE_GATEWAY and dev_uid:
                    existing = self.gateways.get(dev_uid)
                    self.gateways[dev_uid] = PowerMateGateway(
                        uid=dev_uid,
                        device_id=dev_id or dev_uid,
                        name=raw_name or "Allone Pro",
                        model=row.get("model")
                        or (existing.model if existing else "Allone Pro"),
                        online=existing.online if existing else True,
                    )
                elif dev_type in SUPPORTED_RF_SHADE_TYPES and dev_id:
                    self.shades[dev_id] = PowerMateShade(
                        device_id=dev_id,
                        uid=dev_uid,
                        name=raw_name,
                        raw_name=raw_name,
                        company=(row.get("company") or "A-OK Motor").strip(),
                        model=row.get("model") or "RF Shade Motor",
                        device_type=int(dev_type),
                    )

        return self.shades

    async def async_send_rf_command(
        self, uid: str, device_id: str, value1: int
    ) -> bool:
        """Send an RF shade control command (380000=Open, 380001=Close, 380002=Stop)."""
        for attempt in range(2):
            try:
                await self.async_connect()
                assert self._dk is not None
                payload = {
                    "uid": uid,
                    "userName": self.username,
                    "deviceId": device_id,
                    "order": ORDER_RF_CONTROL,
                    "value1": value1,
                    "value2": 0,
                    "value3": 0,
                    "value4": 0,
                    "delayTime": 0,
                    "qualityOfService": 1,
                    "defaultResponse": 1,
                    "cmd": CMD_CONTROL,
                    "clientType": 1,
                    "ver": SOFTWARE_VER,
                }
                resp = await self._send_request(
                    payload, DK_TYPE, self._session_id, self._dk, timeout=8.0
                )
                status = resp.get("status")
                if status == 0:
                    return True
                _LOGGER.warning(
                    "PowerMate command returned status=%s for device=%s",
                    status,
                    device_id,
                )
                if attempt == 0:
                    await self._close_socket()
            except Exception as err:
                _LOGGER.debug(
                    "PowerMate command attempt %d failed for %s: %s",
                    attempt + 1,
                    device_id,
                    err,
                )
                await self._close_socket()
                if attempt == 1:
                    raise
        return False

    async def async_open_shade(self, uid: str, device_id: str) -> bool:
        """Send RF Open (380000)."""
        return await self.async_send_rf_command(uid, device_id, RF_VALUE_OPEN)

    async def async_close_shade(self, uid: str, device_id: str) -> bool:
        """Send RF Close (380001)."""
        return await self.async_send_rf_command(uid, device_id, RF_VALUE_CLOSE)

    async def async_stop_shade(self, uid: str, device_id: str) -> bool:
        """Send RF Stop (380002)."""
        return await self.async_send_rf_command(uid, device_id, RF_VALUE_STOP)
