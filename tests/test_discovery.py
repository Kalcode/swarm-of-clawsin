import asyncio

import pytest

from swarmworld.net.discovery import advertise, discover
from swarmworld.server.__main__ import lan_ip


async def test_discovery_roundtrip():
    ip = lan_ip()
    if ip.startswith("127."):
        pytest.skip("no LAN interface")
    try:
        ad = await asyncio.to_thread(advertise, 17777, ip, "swarmtest")
    except OSError as exc:
        pytest.skip(f"multicast unavailable: {exc}")
    try:
        url = await discover(6.0)
    finally:
        await asyncio.to_thread(ad.close)
    if url is None:
        pytest.skip("mDNS lookup returned nothing (multicast blocked on this network)")
    assert url.endswith(":17777")
