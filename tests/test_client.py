"""Unit tests for the PowerMate P2 async TCP protocol client."""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any
import unittest
import zlib

import tests.conftest  # noqa: F401
from custom_components.powermate_p2.client import (
    PowerMateAuthError,
    PowerMateClient,
    PowerMateConnectionError,
    _aes_decrypt,
    _aes_encrypt,
    md5_upper,
)
from custom_components.powermate_p2.const import (
    CMD_CONTROL,
    CMD_HEARTBEAT,
    CMD_HELLO,
    CMD_LOGIN,
    CMD_QUERY_TABLE,
    CMD_STATUS_REPORT,
    DK_TYPE,
    MAGIC,
    ORDER_RF_CONTROL,
    PK_KEY,
    PK_TYPE,
    RF_VALUE_CLOSE,
    RF_VALUE_OPEN,
    RF_VALUE_STOP,
)

TEST_SESSION_ID = b"0123456789abcdef0123456789abcdef"
TEST_DK_STR = "fedcba9876543210"
TEST_DK = TEST_DK_STR.encode("utf-8")


def _encode_server_packet(
    payload: dict[str, Any],
    pkt_type: bytes = DK_TYPE,
    session_id: bytes = TEST_SESSION_ID,
    key: bytes = TEST_DK,
) -> bytes:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    enc = _aes_encrypt(raw, key)
    crc = zlib.crc32(enc) & 0xFFFFFFFF
    total_len = 42 + len(enc)
    return (
        MAGIC
        + struct.pack(">H", total_len)
        + pkt_type
        + struct.pack(">I", crc)
        + session_id
        + enc
    )


def _decode_client_packet(data: bytes, key: bytes) -> dict[str, Any]:
    assert data[:2] == MAGIC
    total_len = struct.unpack(">H", data[2:4])[0]
    assert len(data) == total_len
    enc = data[42:]
    raw = _aes_decrypt(enc, key).decode("utf-8").rstrip("\x00")
    return json.loads(raw)


class FakeOrviboServer:
    """Local mock TCP server speaking the Orvibo HomeMate hd binary protocol."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.port: int = 0
        self.login_status: int = 0
        self.hello_status: int = 0
        self.control_statuses: list[int] = [0]
        self.received_controls: list[dict[str, Any]] = []
        self.client_writers: list[asyncio.StreamWriter] = []

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", 0
        )
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for writer in self.client_writers:
            writer.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def push_status(self, device_id: str, value1: int) -> None:
        pkt = _encode_server_packet(
            {
                "cmd": CMD_STATUS_REPORT,
                "uid": "aabbccddeeff",
                "deviceId": device_id,
                "value1": value1,
                "status": 0,
            }
        )
        for writer in list(self.client_writers):
            writer.write(pkt)
            await writer.drain()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.client_writers.append(writer)
        try:
            while True:
                prefix = await reader.readexactly(4)
                total_len = struct.unpack(">H", prefix[2:4])[0]
                rest = await reader.readexactly(total_len - 4)
                pkt_type = rest[0:2]
                key = PK_KEY if pkt_type == PK_TYPE else TEST_DK
                req = _decode_client_packet(prefix + rest, key)
                cmd = req.get("cmd")
                serial = req.get("serial")

                if cmd == CMD_HELLO:
                    resp = {
                        "cmd": CMD_HELLO,
                        "serial": serial,
                        "status": self.hello_status,
                        "key": TEST_DK_STR,
                    }
                    writer.write(
                        _encode_server_packet(
                            resp, PK_TYPE, TEST_SESSION_ID, PK_KEY
                        )
                    )
                elif cmd == CMD_LOGIN:
                    resp = {
                        "cmd": CMD_LOGIN,
                        "serial": serial,
                        "status": self.login_status,
                        "userId": "user_001",
                        "familyList": [
                            {
                                "familyId": "family_001",
                                "familyName": "Test Home",
                                "gatewayList": [
                                    {
                                        "uid": "aabbccddeeff",
                                        "model": "allone_pro_model",
                                        "isOnline": "YES",
                                    }
                                ],
                            }
                        ],
                    }
                    writer.write(_encode_server_packet(resp))
                elif cmd == CMD_QUERY_TABLE:
                    resp = {
                        "cmd": CMD_QUERY_TABLE,
                        "serial": serial,
                        "uid": "aabbccddeeff",
                        "status": 0,
                        "tableName": "device",
                        "allList": [
                            {
                                "uid": "aabbccddeeff",
                                "deviceId": "gw_dev_001",
                                "deviceName": "Allone Pro",
                                "deviceType": 67,
                                "model": "allone_pro_model",
                                "delFlag": 0,
                            },
                            {
                                "uid": "aabbccddeeff",
                                "deviceId": "shade_001",
                                "deviceName": "Living Room Shade",
                                "deviceType": 42,
                                "company": "A-OK Motor",
                                "model": "allone_pro_model",
                                "delFlag": 0,
                            },
                            {
                                "uid": "aabbccddeeff",
                                "deviceId": "shade_002",
                                "deviceName": "Office Roller Blind",
                                "deviceType": 35,
                                "company": "Dooya",
                                "model": "allone_pro_model",
                                "delFlag": 0,
                            },
                            {
                                "uid": "aabbccddeeff",
                                "deviceId": "deleted_shade",
                                "deviceName": "Old Shade",
                                "deviceType": 42,
                                "delFlag": 1,
                            },
                        ],
                    }
                    writer.write(_encode_server_packet(resp))
                elif cmd == CMD_CONTROL:
                    self.received_controls.append(req)
                    status = (
                        self.control_statuses.pop(0)
                        if self.control_statuses
                        else 0
                    )
                    resp = {
                        "cmd": CMD_CONTROL,
                        "serial": serial,
                        "uid": req.get("uid"),
                        "status": status,
                    }
                    writer.write(_encode_server_packet(resp))
                elif cmd == CMD_HEARTBEAT:
                    resp = {
                        "cmd": CMD_HEARTBEAT,
                        "serial": serial,
                        "status": 0,
                    }
                    writer.write(_encode_server_packet(resp))
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()


class TestPowerMateClient(unittest.IsolatedAsyncioTestCase):
    """Test cases for PowerMateClient."""

    def test_md5_upper_and_aes_roundtrip(self) -> None:
        """Verify uppercase MD5 digest and AES-ECB PKCS7 roundtrip."""
        digest = md5_upper("test_password_123")
        self.assertEqual(len(digest), 32)
        self.assertEqual(digest, digest.upper())

        plaintext = b'{"cmd":15,"order":"rf control","value1":380000}'
        encrypted = _aes_encrypt(plaintext, PK_KEY)
        self.assertNotEqual(encrypted, plaintext)
        self.assertEqual(_aes_decrypt(encrypted, PK_KEY), plaintext)

    async def test_client_discover_and_control(self) -> None:
        """Test full handshake, login, device discovery, Open/Close/Stop, and push updates."""
        server = FakeOrviboServer()
        await server.start()
        try:
            client = PowerMateClient(
                username="user@example.com",
                password_hash=md5_upper("secret"),
                host="127.0.0.1",
                port=server.port,
                heartbeat_interval=0.1,
            )

            shades = await client.async_discover_devices()
            self.assertEqual(client.family_id, "family_001")
            self.assertIn("aabbccddeeff", client.gateways)
            self.assertEqual(len(shades), 2)
            self.assertEqual(shades["shade_001"].name, "Living Room Shade")
            self.assertEqual(shades["shade_001"].company, "A-OK Motor")
            self.assertEqual(shades["shade_002"].name, "Office Roller Blind")
            self.assertNotIn("deleted_shade", shades)

            self.assertTrue(
                await client.async_open_shade("aabbccddeeff", "shade_001")
            )
            self.assertTrue(
                await client.async_close_shade("aabbccddeeff", "shade_001")
            )
            self.assertTrue(
                await client.async_stop_shade("aabbccddeeff", "shade_001")
            )

            self.assertEqual(len(server.received_controls), 3)
            self.assertEqual(
                server.received_controls[0]["order"], ORDER_RF_CONTROL
            )
            self.assertEqual(
                server.received_controls[0]["value1"], RF_VALUE_OPEN
            )
            self.assertEqual(
                server.received_controls[1]["value1"], RF_VALUE_CLOSE
            )
            self.assertEqual(
                server.received_controls[2]["value1"], RF_VALUE_STOP
            )

            received_pushes: list[tuple[str, int]] = []
            unsub = client.register_callback(
                lambda dev_id, val: received_pushes.append((dev_id, val))
            )
            await server.push_status("shade_001", RF_VALUE_OPEN)
            await asyncio.sleep(0.15)
            self.assertEqual(received_pushes, [("shade_001", RF_VALUE_OPEN)])
            unsub()

            await client.async_close()
        finally:
            await server.stop()

    async def test_client_retry_on_failed_control(self) -> None:
        """Verify automatic reconnect and retry when the first control attempt returns non-zero."""
        server = FakeOrviboServer()
        server.control_statuses = [1, 0]
        await server.start()
        try:
            client = PowerMateClient(
                username="user@example.com",
                password_hash=md5_upper("secret"),
                family_id="family_001",
                host="127.0.0.1",
                port=server.port,
            )
            self.assertTrue(
                await client.async_open_shade("aabbccddeeff", "shade_001")
            )
            self.assertEqual(len(server.received_controls), 2)
            await client.async_close()
        finally:
            await server.stop()

    async def test_client_auth_and_connection_errors(self) -> None:
        """Verify PowerMateAuthError on bad credentials and PowerMateConnectionError on handshake error."""
        server = FakeOrviboServer()
        server.login_status = 14
        await server.start()
        try:
            client = PowerMateClient(
                username="user@example.com",
                password_hash=md5_upper("wrong_pass"),
                host="127.0.0.1",
                port=server.port,
            )
            with self.assertRaises(PowerMateAuthError):
                await client.async_connect()
            await client.async_close()

            server.hello_status = 1
            client2 = PowerMateClient(
                username="user@example.com",
                password_hash=md5_upper("secret"),
                host="127.0.0.1",
                port=server.port,
            )
            with self.assertRaises(PowerMateConnectionError):
                await client2.async_connect()
            await client2.async_close()
        finally:
            await server.stop()


if __name__ == "__main__":
    unittest.main()
