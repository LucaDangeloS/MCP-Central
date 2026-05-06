"""tinyproxy configuration generator.

Reads BLOCKED_IP_RANGES and BLOCKED_DOMAINS from settings and writes
a tinyproxy.conf that denies those destinations. The entrypoint.sh
script calls this before starting tinyproxy.
"""

from __future__ import annotations

from pathlib import Path

from hub.config import get_settings


_CONF_TEMPLATE = """\
# MCP Central — generated tinyproxy configuration
# DO NOT EDIT — regenerated at container startup

Port {port}
Listen 127.0.0.1
Timeout 30
MaxClients 100
MinSpareServers 2
MaxSpareServers 5
StartServers 2
LogLevel Error
DisableViaHeader Yes

# Allow only the hub process (127.0.0.1) to use this proxy
Allow 127.0.0.1

{deny_rules}
"""

_FILTER_TEMPLATE = """\
# Blocked domains filter file
{domains}
"""


def generate_tinyproxy_conf(conf_path: Path, filter_path: Path) -> None:
    """Write tinyproxy.conf and a domain filter file from current settings."""
    settings = get_settings()

    deny_rules: list[str] = []

    # Block RFC-1918 and other private/special ranges
    for cidr in settings.blocked_ip_ranges_list:
        # tinyproxy uses DenyAllow rules based on client IP, not destination.
        # For destination filtering we use the upstream proxy filter + iptables-less approach:
        # We configure tinyproxy with an upstream filter list (domains) and
        # emit ACL-style comments for ops reference.
        # The actual IP-based blocking happens at the network level via docker-compose
        # internal network settings. tinyproxy filters by domain name here.
        deny_rules.append(f"# Blocked IP range: {cidr}")

    # Domain-based filter file
    domain_lines = "\n".join(
        f"^{domain.replace('.', r'\.')}$" for domain in settings.blocked_domains_list
    )

    if settings.blocked_domains_list:
        deny_rules.append(f"Filter \"{filter_path}\"")
        deny_rules.append("FilterDefaultDeny No")
        deny_rules.append("FilterExtended Yes")

    conf_content = _CONF_TEMPLATE.format(
        port=settings.proxy_port,
        deny_rules="\n".join(deny_rules),
    )

    filter_content = _FILTER_TEMPLATE.format(domains=domain_lines)

    conf_path.parent.mkdir(parents=True, exist_ok=True)
    conf_path.write_text(conf_content)
    filter_path.write_text(filter_content)


def get_default_conf_path() -> Path:
    return Path("/etc/tinyproxy/tinyproxy.conf")


def get_default_filter_path() -> Path:
    return Path("/etc/tinyproxy/blocked_domains.txt")
