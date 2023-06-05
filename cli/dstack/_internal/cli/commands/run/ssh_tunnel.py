import errno
import socket
import subprocess
from contextlib import closing
from typing import Dict, List

from dstack._internal.providers.ports import PortUsedError


def get_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def port_in_use(port: int) -> bool:
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(("", port))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except socket.error as e:
        if e.errno == errno.EADDRINUSE:
            return True
        raise
    return False


def allocate_local_ports(ports: Dict[int, int]) -> Dict[int, int]:
    map_to_ports = set()
    # mapped by user
    for port, map_to_port in ports.items():
        if not map_to_port:  # None or 0
            continue
        if map_to_port in map_to_ports or port_in_use(map_to_port):
            raise PortUsedError(f"Mapped port {port}:{map_to_port} is already in use")
        map_to_ports.add(map_to_port)
    # mapped automatically
    for port, map_to_port in ports.items():
        if map_to_port:
            continue
        map_to_port = port
        while map_to_port in map_to_ports or port_in_use(map_to_port):
            map_to_port += 1
        ports[port] = map_to_port
        map_to_ports.add(map_to_port)
    return ports


def make_ssh_tunnel_args(run_name: str, ports: Dict[int, int]) -> List[str]:
    args = [
        "ssh",
        run_name,
        "-N",
        "-f",
    ]
    for port_remote, local_port in ports.items():
        args.extend(["-L", f"{local_port}:localhost:{port_remote}"])
    return args


def run_ssh_tunnel(run_name: str, ports: Dict[int, int]) -> bool:
    args = make_ssh_tunnel_args(run_name, ports)
    return (
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    )