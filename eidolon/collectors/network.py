from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import datetime

from defusedxml import ElementTree as DefusedET

from eidolon.collectors.base import BaseCollector
from eidolon.core.models.event import CollectorEvent


class ScanCancelledError(Exception):
    """Raised when a scan is cancelled."""

    pass


class NetworkCollector(BaseCollector):
    """
    Network scanning collector backed by nmap.

    Performs a ping sweep (-sn) to identify live hosts, then an optional targeted port scan of
    discovered hosts. No synthetic data is emitted; results mirror nmap output.
    """

    def __init__(
        self,
        cidrs: list[str],
        ping_concurrency: int = 64,
        port_scan_workers: int = 32,
        ports: list[int] | None = None,
        port_preset: str | None = None,
        dns_resolution: bool = True,
        aggressive: bool = False,
        nmap_path: str = "nmap",
        cancellation_checker: Callable[[], bool] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(name="network")
        self.cidrs = cidrs
        self.ping_concurrency = ping_concurrency
        self.port_scan_workers = port_scan_workers
        self.ports = ports or []
        self.port_preset = port_preset
        self.dns_resolution = dns_resolution
        self.aggressive = aggressive
        self.nmap_path = nmap_path
        self.cancellation_checker = cancellation_checker
        self.progress_callback = progress_callback
        self._active_process: subprocess.Popen | None = None

    def _send_progress(self, message: str) -> None:
        """Send formatted progress message to callback."""
        if self.progress_callback:
            self.progress_callback(message)

    def collect(self) -> Iterable[CollectorEvent]:
        discovered_hosts: list[str] = []
        host_to_cidr: dict[str, str] = {}

        self._send_progress(f"Starting scan of {len(self.cidrs)} network(s)...")

        for cidr in self.cidrs:
            # Check cancellation before each target
            self._check_cancellation()

            self._send_progress(f"Discovering hosts in {cidr}...")
            sweep_args = ["-sn", "-oX", "-", cidr]
            sweep_args = self._with_dns_flag(sweep_args)
            sweep_args = self._with_parallelism(sweep_args, self.ping_concurrency)
            sweep_xml = self._run_nmap(sweep_args, show_output=False)
            hosts = self._parse_ping_sweep(sweep_xml, cidr)

            if hosts:
                self._send_progress(f"Found {len(hosts)} live host(s) in {cidr}")
                for host in hosts:
                    ip = host.get("ip")
                    hostname = host.get("hostname")
                    if ip:
                        discovered_hosts.append(ip)
                        host_to_cidr[ip] = cidr
                        host_desc = f"{ip} ({hostname})" if hostname else ip
                        self._send_progress(f"  → {host_desc}")
            else:
                self._send_progress(f"No live hosts found in {cidr}")

            for host in hosts:
                yield self._build_event(host)

        # Check cancellation before port scan
        self._check_cancellation()

        port_spec = self._build_port_spec()
        if port_spec and discovered_hosts:
            self._send_progress(f"\nScanning ports on {len(discovered_hosts)} host(s)...")
            port_scan_args = ["-Pn", *port_spec, "-oX", "-", *discovered_hosts]
            port_scan_args = self._with_dns_flag(port_scan_args)
            port_scan_args = self._with_parallelism(port_scan_args, self.port_scan_workers)
            if self.aggressive:
                port_scan_args.extend(["-O", "-sV"])
                self._send_progress("Using aggressive scan (OS detection + version detection)")

            port_scan_xml = self._run_nmap(port_scan_args, show_output=False)

            for host_payload in self._parse_port_scan(port_scan_xml):
                cidr = host_to_cidr.get(host_payload.get("ip", ""))
                if cidr:
                    host_payload["cidr"] = cidr

                # Report open ports
                ip = host_payload.get("ip")
                ports = host_payload.get("ports", [])
                open_ports = [p for p in ports if p.get("state") == "open"]
                if open_ports:
                    self._send_progress(f"  {ip}: {len(open_ports)} open port(s)")
                    for port in open_ports:
                        service = port.get("service", "unknown")
                        self._send_progress(f"    → {port['port']}/{service}")
                else:
                    self._send_progress(f"  {ip}: No open ports found")

                yield self._build_event(host_payload)

        self._send_progress("\nScan complete!")

    def _check_cancellation(self) -> None:
        """Check if scan was cancelled and raise exception if so."""
        if self.cancellation_checker and self.cancellation_checker():
            # Kill active process if running
            if self._active_process:
                with suppress(Exception):
                    self._active_process.terminate()
                    self._active_process.wait(timeout=2)
                with suppress(Exception):
                    self._active_process.kill()
                self._active_process = None
            raise ScanCancelledError("Scan was cancelled")

    def _run_nmap(self, args: list[str], show_output: bool = True) -> str:
        cmd = [self.nmap_path, *args]
        try:
            self._active_process = subprocess.Popen(  # noqa: S603
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )

            # Capture output line by line
            stdout_lines = []
            # Read stdout in real-time
            if self._active_process.stdout:
                for line in iter(self._active_process.stdout.readline, ""):
                    if not line:
                        break
                    stdout_lines.append(line)
                    # Only send raw output to UI if show_output is True (for debugging)
                    # Normally we send custom formatted messages via _send_progress
                    # Check cancellation while reading
                    if self.cancellation_checker and self.cancellation_checker():
                        self._check_cancellation()

            # Wait for process to complete and get stderr
            _, stderr = self._active_process.communicate()
            returncode = self._active_process.returncode
            self._active_process = None

            stdout = "".join(stdout_lines)

            if returncode != 0:
                raise RuntimeError(f"nmap failed ({returncode}): {stderr.strip()}")
            return stdout
        except ScanCancelledError:
            # Re-raise cancellation without wrapping
            raise
        except (OSError, subprocess.SubprocessError, RuntimeError):
            self._active_process = None
            raise

    def _build_port_spec(self) -> list[str]:
        if self.port_preset == "full":
            return ["-p-"]
        if self.ports:
            return ["-p", ",".join(str(p) for p in self.ports)]
        return []

    def _with_dns_flag(self, args: list[str]) -> list[str]:
        return args + (["-R"] if self.dns_resolution else ["-n"])

    def _with_parallelism(self, args: list[str], value: int) -> list[str]:
        if value <= 0:
            return args
        return [*args, "--min-parallelism", str(value), "--max-parallelism", str(value)]

    def _parse_ping_sweep(self, xml_text: str, cidr: str) -> list[dict]:
        hosts: list[dict] = []
        root = DefusedET.fromstring(xml_text)
        for host in root.findall("host"):
            status = host.find("status")
            if status is None or status.attrib.get("state") != "up":
                continue
            addr = host.find("address")
            if addr is None:
                continue
            ip = addr.attrib.get("addr")
            if not ip:
                continue

            # Extract hostname if available
            hostname = None
            hostnames_elem = host.find("hostnames")
            if hostnames_elem is not None:
                hostname_elem = hostnames_elem.find("hostname")
                if hostname_elem is not None:
                    hostname = hostname_elem.attrib.get("name")

            # Extract MAC address and vendor
            mac_address = None
            mac_vendor = None
            for address_elem in host.findall("address"):
                addr_type = address_elem.attrib.get("addrtype")
                if addr_type == "mac":
                    mac_address = address_elem.attrib.get("addr")
                    mac_vendor = address_elem.attrib.get("vendor")
                    break

            host_data = {"ip": ip, "cidr": cidr, "status": "online"}
            if hostname:
                host_data["hostname"] = hostname
            if mac_address:
                host_data["mac_address"] = mac_address
            if mac_vendor:
                host_data["vendor"] = mac_vendor
            hosts.append(host_data)
        return hosts

    def _parse_port_scan(self, xml_text: str) -> list[dict]:
        results: list[dict] = []
        root = DefusedET.fromstring(xml_text)
        for host in root.findall("host"):
            addr = host.find("address")
            if addr is None:
                continue
            ip = addr.attrib.get("addr")
            if not ip:
                continue

            host_data = {"ip": ip}

            # Extract MAC address and vendor
            mac_address = None
            mac_vendor = None
            for address_elem in host.findall("address"):
                addr_type = address_elem.attrib.get("addrtype")
                if addr_type == "mac":
                    mac_address = address_elem.attrib.get("addr")
                    mac_vendor = address_elem.attrib.get("vendor")
                    break

            if mac_address:
                host_data["mac_address"] = mac_address
            if mac_vendor:
                host_data["vendor"] = mac_vendor

            # Parse ports with detailed service information
            ports = []
            ports_element = host.find("ports")
            if ports_element is not None:
                for port_elem in ports_element.findall("port"):
                    port_id = int(port_elem.attrib.get("portid", "0"))
                    state_elem = port_elem.find("state")
                    state = state_elem.attrib.get("state") if state_elem is not None else "unknown"

                    # Extract detailed service information
                    service_elem = port_elem.find("service")
                    service_name = None
                    service_product = None
                    service_version = None
                    if service_elem is not None:
                        service_name = service_elem.attrib.get("name")
                        service_product = service_elem.attrib.get("product")
                        service_version = service_elem.attrib.get("version")

                    port_data = {"port": port_id, "state": state, "service": service_name}
                    if service_product:
                        port_data["product"] = service_product
                    if service_version:
                        port_data["version"] = service_version

                    ports.append(port_data)

            host_data["ports"] = ports

            # Parse OS detection information
            os_element = host.find("os")
            if os_element is not None:
                osmatch = os_element.find("osmatch")
                if osmatch is not None:
                    os_name = osmatch.attrib.get("name")
                    os_accuracy = osmatch.attrib.get("accuracy")
                    if os_name:
                        host_data["os"] = os_name
                    if os_accuracy:
                        host_data["os_accuracy"] = f"{os_accuracy}%"

                # Get OS class for more general info
                osclass = os_element.find("osclass")
                if osclass is not None:
                    os_family = osclass.attrib.get("osfamily")
                    if os_family and "os" not in host_data:
                        host_data["os"] = os_family

            results.append(host_data)
        return results

    def _build_event(self, payload: dict) -> CollectorEvent:
        now = datetime.utcnow()
        return CollectorEvent(
            source_type="network",
            source_id=payload.get("ip", "network-scan"),
            entity_type="Asset",
            payload=payload,
            collected_at=now,
            confidence=0.8,
        )
