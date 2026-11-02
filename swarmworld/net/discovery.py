"""Find the world on the home network with mDNS / Bonjour (zeroconf)."""

from __future__ import annotations

import asyncio
import socket

from zeroconf import IPVersion, ServiceInfo, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

SERVICE = "_swarmworld._tcp.local."


class Advert:
    def __init__(self, zc: Zeroconf, info: ServiceInfo):
        self.zc, self.info = zc, info

    def close(self) -> None:
        try:
            self.zc.unregister_service(self.info)
        finally:
            self.zc.close()


def advertise(port: int, ip: str, name: str | None = None) -> Advert:
    host = name or socket.gethostname().split(".")[0]
    info = ServiceInfo(
        SERVICE,
        f"Swarm World on {host}.{SERVICE}",
        addresses=[socket.inet_aton(ip)],
        port=port,
        properties={"path": "/ws/node"},
        server=f"{host}.local.",
    )
    zc = Zeroconf(ip_version=IPVersion.V4Only)
    zc.register_service(info)
    return Advert(zc, info)


async def discover(timeout: float = 5.0, host: str | None = None) -> str | None:
    """Return ws://host:port of the first Swarm World found on the LAN (or the one advertised by host), or None."""
    found: asyncio.Queue[str] = asyncio.Queue()
    azc = AsyncZeroconf(ip_version=IPVersion.V4Only)

    async def resolve(name: str) -> None:
        info = await azc.async_get_service_info(SERVICE, name, 3000)
        if info and info.parsed_addresses():
            await found.put(f"ws://{info.parsed_addresses()[0]}:{info.port}")

    def on_change(zeroconf, service_type, name, state_change) -> None:  # noqa: ANN001
        if host is None or name == f"Swarm World on {host}.{SERVICE}":
            asyncio.ensure_future(resolve(name))

    browser = AsyncServiceBrowser(azc.zeroconf, SERVICE, handlers=[on_change])
    try:
        return await asyncio.wait_for(found.get(), timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        await browser.async_cancel()
        await azc.async_close()
