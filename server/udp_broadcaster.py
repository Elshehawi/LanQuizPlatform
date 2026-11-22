"""Background UDP LAN discovery beacon thread."""

from __future__ import annotations

import socket
import threading
import time

from shared.config import (
    UDP_BROADCAST_PORT,
    UDP_BROADCAST_INTERVAL,
    UDP_MAGIC,
    SERVER_PORT,
    DEFAULT_COURSE_TITLE,
)


def get_local_ip() -> str:
    """Get the local LAN IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class UDPBroadcaster:
    """Broadcasts UDP discovery packets on the LAN."""

    def __init__(self, port: int = SERVER_PORT, course_title: str = DEFAULT_COURSE_TITLE):
        self._port = port
        self._course_title = course_title
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        """Start broadcasting in a daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop broadcasting."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _broadcast_loop(self):
        """Continuously broadcast UDP packets."""
        local_ip = get_local_ip()
        message = f"{UDP_MAGIC}|{local_ip}|{self._port}|{self._course_title}"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1)

        try:
            while self._running:
                try:
                    sock.sendto(
                        message.encode("utf-8"),
                        ("<broadcast>", UDP_BROADCAST_PORT),
                    )
                except OSError:
                    pass  # Network interface unavailable
                time.sleep(UDP_BROADCAST_INTERVAL)
        finally:
            sock.close()


def listen_for_server(timeout: float = 4.0) -> dict | None:
    """Listen for a UDP broadcast and return server info or None."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", UDP_BROADCAST_PORT))
    except OSError:
        sock.close()
        return None
    sock.settimeout(timeout)

    try:
        data, addr = sock.recvfrom(1024)
        message = data.decode("utf-8")
        parts = message.split("|")
        if len(parts) == 4 and parts[0] == UDP_MAGIC:
            return {
                "ip": parts[1],
                "port": int(parts[2]),
                "course_title": parts[3],
            }
    except socket.timeout:
        pass
    except OSError:
        pass
    finally:
        sock.close()
    return None
