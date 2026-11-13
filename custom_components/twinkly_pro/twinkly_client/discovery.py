"""Local network discovery for Twinkly devices via UDP broadcast (port 5555) and HTTP probing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import socket
from typing import Any

import aiohttp

from .client import TwinklyClient, TwinklyError
from .models import GestaltInfo, SyncInfo

_LOGGER = logging.getLogger(__name__)

DISCOVERY_UDP_PORT = 5555
DISCOVERY_PAYLOAD = b"\x01discover"


@dataclass(slots=True)
class DiscoveredTwinklyDevice:
    """Represents a Twinkly device discovered via LAN UDP broadcast or Cloud."""

    host: str
    name: str
    mac: str
    uuid: str
    product_code: str = ""
    number_of_led: int = 0
    led_profile: str = "RGB"
    fw_version: str = ""
    sync_mode: str = "none"
    group_uid: str = ""
    master_uid: str = ""
    scene_name: str = ""
    composition_name: str = ""
    source: str = "lan"  # "lan", "cloud", "cloud+lan"

    @property
    def unique_id(self) -> str:
        """Return canonical unique_id (MAC address or UUID)."""
        return (self.mac or self.uuid or self.host).lower()

    @property
    def display_label(self) -> str:
        """Return human-readable label for ConfigFlow multi-select."""
        parts = [f"{self.name}"]
        if self.number_of_led:
            parts.append(f"{self.number_of_led} {self.led_profile}")
        if self.product_code:
            parts.append(self.product_code)
        if self.scene_name:
            parts.append(f"Сцена: {self.scene_name}")
        if self.sync_mode in ("master", "slave") and self.group_uid:
            comp = self.composition_name or f"Группа {self.group_uid[:6]}"
            parts.append(f"[{comp}: {self.sync_mode.upper()}]")
        if self.host:
            parts.append(f"IP: {self.host}")
        return " • ".join(parts)


class _TwinklyDiscoveryProtocol(asyncio.DatagramProtocol):
    """Asyncio UDP protocol that collects responses from Twinkly controllers on port 5555."""

    def __init__(self) -> None:
        self.found_hosts: dict[str, str] = {}  # host -> advertised_name

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        """Parse UDP discovery response packet from a Twinkly device.

        Response format:
        - Bytes 0..3: IP octets in reverse order
        - Bytes 4..5: b'OK'
        - Bytes 6..N: Null-terminated device name string
        """
        host_ip = str(addr[0])
        if len(data) >= 6 and data[4:6] == b"OK":
            raw_name = data[6:].split(b"\x00", 1)[0]
            try:
                dev_name = raw_name.decode("utf-8", errors="replace").strip()
            except Exception:
                dev_name = "Twinkly"
            self.found_hosts[host_ip] = dev_name or "Twinkly"
        elif host_ip not in self.found_hosts:
            self.found_hosts[host_ip] = "Twinkly"


async def async_discover_lan_hosts(timeout: float = 1.6) -> dict[str, str]:
    """Broadcast `\\x01discover` on UDP port 5555 and return `{ip: device_name}`."""
    loop = asyncio.get_running_loop()
    protocol = _TwinklyDiscoveryProtocol()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(False)

    try:
        sock.bind(("0.0.0.0", 0))
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            sock=sock,
        )
    except OSError as err:
        _LOGGER.debug("Could not bind UDP discovery socket: %s", err)
        try:
            sock.close()
        except OSError:
            pass
        return {}

    try:
        # Send 3 broadcast bursts to maximize UDP reception across Wi-Fi
        intervals = [0.4, 0.5, max(0.2, timeout - 0.9)]
        for wait_sec in intervals:
            try:
                transport.sendto(DISCOVERY_PAYLOAD, ("255.255.255.255", DISCOVERY_UDP_PORT))
            except OSError as err:
                _LOGGER.debug("UDP broadcast sendto failed: %s", err)
            await asyncio.sleep(wait_sec)
    finally:
        transport.close()

    return dict(protocol.found_hosts)


async def async_probe_discovered_host(
    host: str,
    session: aiohttp.ClientSession | None = None,
    fallback_name: str = "Twinkly",
) -> DiscoveredTwinklyDevice | None:
    """Query /xled/v1/gestalt and /xled/v1/sync on a discovered IP address."""
    client = TwinklyClient(host=host, session=session, timeout=4.0)
    try:
        gestalt: GestaltInfo = await client.get_gestalt(force_refresh=True)
        fw_ver = await client.get_firmware_version(force_refresh=True)
        sync: SyncInfo = SyncInfo()
        try:
            await client.authenticate()
            sync = await client.get_sync()
        except TwinklyError:
            pass

        return DiscoveredTwinklyDevice(
            host=host,
            name=gestalt.device_name or fallback_name,
            mac=gestalt.mac,
            uuid=gestalt.uuid,
            product_code=gestalt.product_code,
            number_of_led=gestalt.number_of_led,
            led_profile=gestalt.led_profile,
            fw_version=fw_ver,
            sync_mode=sync.mode,
            group_uid=sync.group_uid,
            master_uid=sync.master_uid,
            source="lan",
        )
    except Exception as err:
        _LOGGER.debug("Failed probing Twinkly host %s: %s", host, err)
        return None
    finally:
        await client.close()


async def async_discover_twinkly_devices(
    session: aiohttp.ClientSession | None = None,
    extra_hosts: list[str] | None = None,
    timeout: float = 1.6,
) -> list[DiscoveredTwinklyDevice]:
    """Discover all active Twinkly controllers on the local network and probe their metadata."""
    lan_hosts = await async_discover_lan_hosts(timeout=timeout)
    for h in extra_hosts or []:
        if h and h not in lan_hosts:
            lan_hosts[h] = "Twinkly"

    if not lan_hosts:
        return []

    tasks = [
        async_probe_discovered_host(ip, session=session, fallback_name=adv_name)
        for ip, adv_name in lan_hosts.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    devices: list[DiscoveredTwinklyDevice] = []
    seen_ids: set[str] = set()
    for res in results:
        if isinstance(res, DiscoveredTwinklyDevice):
            uid = res.unique_id
            if uid not in seen_ids:
                seen_ids.add(uid)
                devices.append(res)

    return devices
