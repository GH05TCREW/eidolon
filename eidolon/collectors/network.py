from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import datetime
from typing import Any

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
        nse_scripts: list[str] | None = None,
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
        self.nse_scripts = self._default_nse_scripts() if nse_scripts is None else nse_scripts
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
                port_scan_args.extend(["-O", "-sV", "--version-all", "--traceroute", "--reason"])
                script_args = self._build_script_args()
                if script_args:
                    port_scan_args.extend(script_args)
                self._send_progress(
                    "Using aggressive scan "
                    "(OS detection + version detection + scripts + traceroute)"
                )

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

            hostname, hostnames = self._parse_hostnames(host)
            mac_address, mac_vendor = self._parse_mac_address(host)

            host_data = {"ip": ip, "cidr": cidr, "status": "online"}
            if status is not None:
                status_reason = status.attrib.get("reason")
                status_ttl = status.attrib.get("reason_ttl")
                if status_reason:
                    host_data["status_reason"] = status_reason
                if status_ttl:
                    host_data["status_ttl"] = status_ttl
            if hostname:
                host_data["hostname"] = hostname
            if hostnames:
                host_data["hostnames"] = hostnames
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
            ip = self._parse_ip_address(host)
            if not ip:
                continue

            host_data = {"ip": ip}

            hostname, hostnames = self._parse_hostnames(host)
            if hostname:
                host_data["hostname"] = hostname
            if hostnames:
                host_data["hostnames"] = hostnames

            # Extract MAC address and vendor
            mac_address, mac_vendor = self._parse_mac_address(host)
            if mac_address:
                host_data["mac_address"] = mac_address
            if mac_vendor:
                host_data["vendor"] = mac_vendor

            # Parse ports with detailed service information
            ports: list[dict] = []
            ports_element = host.find("ports")
            if ports_element is not None:
                for port_elem in ports_element.findall("port"):
                    port_id = int(port_elem.attrib.get("portid", "0"))
                    protocol = port_elem.attrib.get("protocol")
                    state_elem = port_elem.find("state")
                    state = state_elem.attrib.get("state") if state_elem is not None else "unknown"
                    reason = state_elem.attrib.get("reason") if state_elem is not None else None
                    reason_ttl = (
                        state_elem.attrib.get("reason_ttl") if state_elem is not None else None
                    )

                    # Extract detailed service information
                    service_elem = port_elem.find("service")
                    service_name = None
                    service_product = None
                    service_version = None
                    service_extrainfo = None
                    service_tunnel = None
                    service_method = None
                    service_conf = None
                    service_ostype = None
                    service_hostname = None
                    service_cpes: list[str] = []
                    if service_elem is not None:
                        service_name = service_elem.attrib.get("name")
                        service_product = service_elem.attrib.get("product")
                        service_version = service_elem.attrib.get("version")
                        service_extrainfo = service_elem.attrib.get("extrainfo")
                        service_tunnel = service_elem.attrib.get("tunnel")
                        service_method = service_elem.attrib.get("method")
                        service_conf = service_elem.attrib.get("conf")
                        service_ostype = service_elem.attrib.get("ostype")
                        service_hostname = service_elem.attrib.get("hostname")
                        for cpe_elem in service_elem.findall("cpe"):
                            if cpe_elem.text:
                                service_cpes.append(cpe_elem.text)

                    port_data: dict[str, Any] = {
                        "port": port_id,
                        "protocol": protocol,
                        "state": state,
                        "service": service_name,
                    }
                    if reason:
                        port_data["reason"] = reason
                    if reason_ttl:
                        port_data["reason_ttl"] = reason_ttl
                    if service_product:
                        port_data["product"] = service_product
                    if service_version:
                        port_data["version"] = service_version
                    if service_extrainfo:
                        port_data["extrainfo"] = service_extrainfo
                    if service_tunnel:
                        port_data["tunnel"] = service_tunnel
                    if service_method:
                        port_data["method"] = service_method
                    if service_conf:
                        port_data["conf"] = service_conf
                    if service_ostype:
                        port_data["ostype"] = service_ostype
                    if service_hostname:
                        port_data["service_hostname"] = service_hostname
                    if service_cpes:
                        port_data["cpe"] = service_cpes

                    scripts = self._parse_scripts(port_elem)
                    if scripts:
                        port_data["scripts"] = scripts

                    ports.append(port_data)

            host_data["ports"] = ports

            # Parse OS detection information
            os_element = host.find("os")
            if os_element is not None:
                host_data.update(self._parse_os(os_element))

            self._parse_uptime(host, host_data)
            self._parse_distance(host, host_data)
            self._parse_timing(host, host_data)
            self._parse_traceroute(host, host_data)
            self._parse_host_scripts(host, host_data)

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

    @staticmethod
    def _default_nse_scripts() -> list[str]:
        return [
            "ssl-cert",
            "http-title",
            "http-headers",
            "http-server-header",
            "http-methods",
            "smb-os-discovery",
            "smb-security-mode",
            "smb2-time",
            "clock-skew",
        ]

    def _build_script_args(self) -> list[str]:
        if not self.nse_scripts:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for script in self.nse_scripts:
            script_id = script.strip()
            if not script_id or script_id in seen:
                continue
            normalized.append(script_id)
            seen.add(script_id)
        if not normalized:
            return []
        return ["--script", ",".join(normalized)]

    @staticmethod
    def _parse_ip_address(host: DefusedET.Element) -> str | None:
        for address_elem in host.findall("address"):
            addr_type = address_elem.attrib.get("addrtype")
            if addr_type in {"ipv4", "ipv6"}:
                ip = address_elem.attrib.get("addr")
                if ip:
                    return ip
        addr = host.find("address")
        if addr is not None:
            ip = addr.attrib.get("addr")
            if ip:
                return ip
        return None

    @staticmethod
    def _parse_hostnames(host: DefusedET.Element) -> tuple[str | None, list[str]]:
        hostnames: list[str] = []
        hostnames_elem = host.find("hostnames")
        if hostnames_elem is None:
            return None, hostnames
        for hostname_elem in hostnames_elem.findall("hostname"):
            name = hostname_elem.attrib.get("name")
            if name and name not in hostnames:
                hostnames.append(name)
        primary = hostnames[0] if hostnames else None
        return primary, hostnames

    @staticmethod
    def _parse_mac_address(host: DefusedET.Element) -> tuple[str | None, str | None]:
        for address_elem in host.findall("address"):
            addr_type = address_elem.attrib.get("addrtype")
            if addr_type == "mac":
                return address_elem.attrib.get("addr"), address_elem.attrib.get("vendor")
        return None, None

    def _parse_scripts(self, parent: DefusedET.Element) -> list[dict]:
        scripts: list[dict] = []
        for script_elem in parent.findall("script"):
            parsed = self._parse_script(script_elem)
            if parsed:
                scripts.append(parsed)
        return scripts

    def _parse_script(self, script_elem: DefusedET.Element) -> dict[str, Any] | None:
        script_id = script_elem.attrib.get("id")
        output = script_elem.attrib.get("output")
        data = self._parse_script_data(script_elem)
        if not script_id and not output and data is None:
            return None
        payload: dict[str, Any] = {}
        if script_id:
            payload["id"] = script_id
        if output:
            payload["output"] = output
        if data is not None:
            payload["data"] = data
        return payload

    def _parse_script_data(self, script_elem: DefusedET.Element) -> Any | None:
        if not list(script_elem):
            return None
        data: dict[str, Any] = {}
        items: list[Any] = []
        for child in script_elem:
            if child.tag == "elem":
                key = child.attrib.get("key")
                value = (child.text or "").strip()
                if key:
                    self._merge_script_value(data, key, value)
                elif value:
                    items.append(value)
            elif child.tag == "table":
                table_value = self._parse_script_table(child)
                key = child.attrib.get("key")
                if key:
                    self._merge_script_value(data, key, table_value)
                else:
                    items.append(table_value)
        if data and items:
            data["_items"] = items
            return data
        if data:
            return data
        if items:
            return items
        return None

    def _parse_script_table(self, table_elem: DefusedET.Element) -> Any:
        data: dict[str, Any] = {}
        items: list[Any] = []
        for child in table_elem:
            if child.tag == "elem":
                key = child.attrib.get("key")
                value = (child.text or "").strip()
                if key:
                    self._merge_script_value(data, key, value)
                elif value:
                    items.append(value)
            elif child.tag == "table":
                nested_value = self._parse_script_table(child)
                key = child.attrib.get("key")
                if key:
                    self._merge_script_value(data, key, nested_value)
                else:
                    items.append(nested_value)
        if data and items:
            data["_items"] = items
            return data
        if data:
            return data
        return items

    @staticmethod
    def _merge_script_value(target: dict[str, Any], key: str, value: Any) -> None:
        if key in target:
            existing = target[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                target[key] = [existing, value]
        else:
            target[key] = value

    def _parse_os(self, os_element: DefusedET.Element) -> dict[str, Any]:
        data: dict[str, Any] = {}
        os_matches: list[dict[str, Any]] = []
        best_accuracy = -1
        best_name: str | None = None
        for osmatch in os_element.findall("osmatch"):
            match_data: dict[str, Any] = {}
            match_name = osmatch.attrib.get("name")
            if match_name:
                match_data["name"] = match_name
            accuracy_raw = osmatch.attrib.get("accuracy")
            accuracy = None
            if accuracy_raw and accuracy_raw.isdigit():
                accuracy = int(accuracy_raw)
                match_data["accuracy"] = accuracy
            line = osmatch.attrib.get("line")
            if line:
                match_data["line"] = line

            classes: list[dict[str, Any]] = []
            for osclass in osmatch.findall("osclass"):
                class_data: dict[str, Any] = {}
                os_type = osclass.attrib.get("type")
                vendor = osclass.attrib.get("vendor")
                family = osclass.attrib.get("osfamily")
                os_gen = osclass.attrib.get("osgen")
                class_accuracy = osclass.attrib.get("accuracy")
                if os_type:
                    class_data["type"] = os_type
                if vendor:
                    class_data["vendor"] = vendor
                if family:
                    class_data["family"] = family
                if os_gen:
                    class_data["gen"] = os_gen
                if class_accuracy and class_accuracy.isdigit():
                    class_data["accuracy"] = int(class_accuracy)
                cpes = [cpe.text for cpe in osclass.findall("cpe") if cpe.text]
                if cpes:
                    class_data["cpe"] = cpes
                if class_data:
                    classes.append(class_data)
            if classes:
                match_data["classes"] = classes

            match_cpes = [cpe.text for cpe in osmatch.findall("cpe") if cpe.text]
            if match_cpes:
                match_data["cpe"] = match_cpes

            if match_data:
                os_matches.append(match_data)

            if match_name and accuracy is not None and accuracy > best_accuracy:
                best_name = match_name
                best_accuracy = accuracy

        if os_matches:
            data["os_matches"] = os_matches
        if best_name:
            data["os"] = best_name
        if best_accuracy >= 0:
            data["os_accuracy"] = f"{best_accuracy}%"

        if "os" not in data:
            osclass = os_element.find("osclass")
            if osclass is not None:
                os_family = osclass.attrib.get("osfamily")
                if os_family:
                    data["os"] = os_family
                os_vendor = osclass.attrib.get("vendor")
                if os_vendor:
                    data["os_vendor"] = os_vendor
                os_type = osclass.attrib.get("type")
                if os_type:
                    data["os_type"] = os_type
                os_gen = osclass.attrib.get("osgen")
                if os_gen:
                    data["os_gen"] = os_gen

        return data

    @staticmethod
    def _parse_uptime(host: DefusedET.Element, host_data: dict[str, Any]) -> None:
        uptime_elem = host.find("uptime")
        if uptime_elem is None:
            return
        seconds = uptime_elem.attrib.get("seconds")
        if seconds and seconds.isdigit():
            host_data["uptime_seconds"] = int(seconds)
        lastboot = uptime_elem.attrib.get("lastboot")
        if lastboot:
            host_data["uptime_last_boot"] = lastboot

    @staticmethod
    def _parse_distance(host: DefusedET.Element, host_data: dict[str, Any]) -> None:
        distance_elem = host.find("distance")
        if distance_elem is None:
            return
        value = distance_elem.attrib.get("value")
        if value and value.isdigit():
            host_data["distance"] = int(value)

    @staticmethod
    def _parse_timing(host: DefusedET.Element, host_data: dict[str, Any]) -> None:
        times_elem = host.find("times")
        if times_elem is None:
            return
        srtt = times_elem.attrib.get("srtt")
        rttvar = times_elem.attrib.get("rttvar")
        timeout = times_elem.attrib.get("to")
        if srtt and srtt.isdigit():
            host_data["rtt_srtt_us"] = int(srtt)
        if rttvar and rttvar.isdigit():
            host_data["rtt_var_us"] = int(rttvar)
        if timeout and timeout.isdigit():
            host_data["rtt_timeout_us"] = int(timeout)

    @staticmethod
    def _parse_traceroute(host: DefusedET.Element, host_data: dict[str, Any]) -> None:
        trace_elem = host.find("trace")
        if trace_elem is None:
            return
        hops: list[dict[str, Any]] = []
        for hop in trace_elem.findall("hop"):
            hop_data: dict[str, Any] = {}
            ttl = hop.attrib.get("ttl")
            rtt = hop.attrib.get("rtt")
            ipaddr = hop.attrib.get("ipaddr")
            hostname = hop.attrib.get("host")
            if ttl and ttl.isdigit():
                hop_data["ttl"] = int(ttl)
            if rtt:
                try:
                    hop_data["rtt_ms"] = float(rtt)
                except ValueError:
                    hop_data["rtt_ms"] = rtt
            if ipaddr:
                hop_data["ip"] = ipaddr
            if hostname:
                hop_data["hostname"] = hostname
            if hop_data:
                hops.append(hop_data)
        if not hops:
            return
        trace_data: dict[str, Any] = {"hops": hops}
        proto = trace_elem.attrib.get("proto")
        port = trace_elem.attrib.get("port")
        if proto:
            trace_data["proto"] = proto
        if port and port.isdigit():
            trace_data["port"] = int(port)
        host_data["traceroute"] = trace_data

    def _parse_host_scripts(self, host: DefusedET.Element, host_data: dict[str, Any]) -> None:
        hostscript_elem = host.find("hostscript")
        if hostscript_elem is None:
            return
        scripts = self._parse_scripts(hostscript_elem)
        if scripts:
            host_data["host_scripts"] = scripts
