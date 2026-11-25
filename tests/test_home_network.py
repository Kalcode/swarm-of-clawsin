"""The steward's actions (wishes, the voice from the sky, admin, the almanac) work from the home network, never through
a tunnel or proxy: the user answers prayers from bed, and a public tunnel can't."""

from swarmworld.server.app import home_network

NONE = {}


def test_this_machine_and_the_home_network_count():
    for remote in ("127.0.0.1", "::1", "192.168.1.20", "10.0.0.7", "172.20.1.5", "fd12:3456::1", "fe80::1"):
        assert home_network(remote, NONE), remote


def test_the_internet_does_not():
    for remote in ("8.8.8.8", "1.1.1.1", "2606:4700::1111", None, "", "not an address"):
        assert not home_network(remote, NONE), remote


def test_a_request_relayed_by_a_tunnel_or_proxy_never_counts_even_from_here():
    for header in ("CF-Connecting-IP", "CF-Ray", "X-Forwarded-For", "X-Real-IP", "Forwarded"):
        assert not home_network("127.0.0.1", {header: "203.0.113.9"}), header
        assert not home_network("192.168.1.20", {header: "203.0.113.9"}), header
