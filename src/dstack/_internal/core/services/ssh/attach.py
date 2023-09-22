import time

from dstack._internal.core.services.configs import ConfigManager
from dstack._internal.core.services.ssh.ports import PortsLock
from dstack._internal.core.services.ssh.tunnel import SSHError, SSHTunnel
from dstack._internal.utils.path import PathLike
from dstack._internal.utils.ssh import (
    include_ssh_config,
    ssh_config_add_host,
    ssh_config_remove_host,
)


class SSHAttach:
    def __init__(
        self,
        hostname: str,
        ports_lock: PortsLock,
        id_rsa_path: PathLike,
        run_name: str,
        user: str = "ubuntu",
        ssh_port: int = 22,
    ):
        # TODO jumphost configuration
        self._ports_lock = ports_lock
        self.ports = ports_lock.dict()
        self.run_name = run_name
        # TODO use ssh_port, jumphost, and controlpersist in config
        self.tunnel = SSHTunnel(hostname, self.ports, id_rsa_path=id_rsa_path, user=user)
        self.ssh_host = {
            "HostName": hostname,
            "User": user,
            "IdentityFile": id_rsa_path,
            "StrictHostKeyChecking": "no",
            "UserKnownHostsFile": "/dev/null",
            "ControlPath": self.tunnel.control_sock_path,
            "ControlMaster": "auto",
            "ControlPersist": "yes",
        }
        self.ssh_config_path = str(ConfigManager().dstack_ssh_config_path)

    def attach(self):
        include_ssh_config(self.ssh_config_path)
        ssh_config_add_host(self.ssh_config_path, self.run_name, self.ssh_host)

        max_retries = 10
        self._ports_lock.release()
        for i in range(max_retries):
            try:
                self.tunnel.open()
                break
            except SSHError:
                if i < max_retries - 1:
                    time.sleep(1)
        else:
            self.detach()
            raise SSHError("Can't connect to the remote host")

    def detach(self):
        self.tunnel.close()
        ssh_config_remove_host(self.ssh_config_path, self.run_name)

    def __enter__(self):
        self.attach()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.detach()