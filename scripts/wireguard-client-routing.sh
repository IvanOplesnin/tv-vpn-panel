#!/usr/bin/env bash
set -Eeuo pipefail

WG_NET="${TVVPN_WG_NET:-10.10.0.0/24}"
WG_DEV="${TVVPN_WG_DEV:-wg0}"

LAN_NET="${TVVPN_LAN_NET:-192.168.1.0/24}"
LAN_DEV="${TVVPN_LAN_DEV:-eth0}"

AP_NET="${TVVPN_AP_NET:-192.168.50.0/24}"
AP_DEV="${TVVPN_AP_DEV:-enx00e04c2a7a88}"

OVPN_NET="${TVVPN_OVPN_NET:-10.8.0.0/24}"
OVPN_DEV="${TVVPN_OVPN_DEV:-tun0}"
OVPN_GW="${TVVPN_OVPN_GW:-10.8.0.1}"

VLESS_NET="${TVVPN_VLESS_NET:-172.19.0.0/30}"
VLESS_DEV="${TVVPN_VLESS_DEV:-sbtun0}"

OPENVPN_TABLE="${TVVPN_OPENVPN_TABLE:-201}"
VLESS_TABLE="${TVVPN_VLESS_TABLE:-202}"

# Приоритеты 31002–31254:
# выше общего правила WireGuard 32765,
# но ниже специального fwmark-правила 10000.
PRIORITY_BASE="${TVVPN_WG_PRIORITY_BASE:-31000}"

PROTECTED_CLIENT="${TVVPN_PROTECTED_WG_CLIENT:-10.10.0.5}"
ALLOW_PROTECTED="${TVVPN_ALLOW_PROTECTED_WG_ROUTING:-false}"

DRY_RUN="${TVVPN_WG_ROUTING_DRY_RUN:-false}"
TEST_IP="${TVVPN_ROUTE_TEST_IP:-1.1.1.1}"


log() {
    printf '[wg-client-routing] %s\n' "$*"
}


die() {
    printf '[wg-client-routing] ERROR: %s\n' "$*" >&2
    exit 1
}


is_true() {
    case "${1,,}" in
        1|true|yes|on)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}


print_cmd() {
    printf '[wg-client-routing] DRY-RUN:'
    printf ' %q' "$@"
    printf '\n'
}


run_cmd() {
    if is_true "$DRY_RUN"; then
        print_cmd "$@"
    else
        "$@"
    fi
}


flush_table() {
    local table="$1"

    if is_true "$DRY_RUN"; then
        print_cmd ip -4 route flush table "$table"
    else
        ip -4 route flush table "$table" \
            2>/dev/null || true
    fi
}


interface_has_ipv4() {
    local interface="$1"

    if is_true "$DRY_RUN"; then
        case "$interface" in
            "$OVPN_DEV")
                is_true "${TVVPN_TEST_TUN0_READY:-false}"
                ;;
            "$VLESS_DEV")
                is_true "${TVVPN_TEST_SBTUN0_READY:-false}"
                ;;
            *)
                return 0
                ;;
        esac

        return
    fi

    ip -4 addr show dev "$interface" \
        2>/dev/null |
        grep -q 'inet '
}


ensure_iptables_rule() {
    local table="$1"
    local chain="$2"

    shift 2

    local check=(
        iptables
        -t "$table"
        -C "$chain"
        "$@"
    )

    local add=(
        iptables
        -t "$table"
        -A "$chain"
        "$@"
    )

    if is_true "$DRY_RUN"; then
        print_cmd "${add[@]}"
        return
    fi

    "${check[@]}" 2>/dev/null ||
        "${add[@]}"
}


add_common_routes() {
    local table="$1"

    run_cmd ip -4 route replace \
        "$WG_NET" \
        dev "$WG_DEV" \
        table "$table"

    run_cmd ip -4 route replace \
        "$LAN_NET" \
        dev "$LAN_DEV" \
        table "$table"

    run_cmd ip -4 route replace \
        "$AP_NET" \
        dev "$AP_DEV" \
        table "$table"
}


prepare_openvpn_table() {
    flush_table "$OPENVPN_TABLE"
    add_common_routes "$OPENVPN_TABLE"

    if interface_has_ipv4 "$OVPN_DEV"; then
        run_cmd ip -4 route replace \
            "$OVPN_NET" \
            dev "$OVPN_DEV" \
            scope link \
            table "$OPENVPN_TABLE"

        run_cmd ip -4 route replace \
            default \
            via "$OVPN_GW" \
            dev "$OVPN_DEV" \
            table "$OPENVPN_TABLE"
    else
        # Kill switch: не позволяем перейти к следующему
        # policy rule и случайно использовать другой backend.
        run_cmd ip -4 route add \
            unreachable default \
            table "$OPENVPN_TABLE" \
            metric 42760
    fi
}


prepare_vless_table() {
    flush_table "$VLESS_TABLE"
    add_common_routes "$VLESS_TABLE"

    if interface_has_ipv4 "$VLESS_DEV"; then
        run_cmd ip -4 route replace \
            "$VLESS_NET" \
            dev "$VLESS_DEV" \
            scope link \
            table "$VLESS_TABLE"

        run_cmd ip -4 route replace \
            default \
            dev "$VLESS_DEV" \
            table "$VLESS_TABLE"
    else
        run_cmd ip -4 route add \
            unreachable default \
            table "$VLESS_TABLE" \
            metric 42760
    fi
}


prepare_forwarding_rules() {
    local egress

    for egress in \
        "$LAN_DEV" \
        "$OVPN_DEV" \
        "$VLESS_DEV"
    do
        ensure_iptables_rule \
            filter \
            FORWARD \
            -s "$WG_NET" \
            -i "$WG_DEV" \
            -o "$egress" \
            -j ACCEPT

        ensure_iptables_rule \
            filter \
            FORWARD \
            -d "$WG_NET" \
            -i "$egress" \
            -o "$WG_DEV" \
            -m conntrack \
            --ctstate RELATED,ESTABLISHED \
            -j ACCEPT

        ensure_iptables_rule \
            nat \
            POSTROUTING \
            -s "$WG_NET" \
            -o "$egress" \
            -j MASQUERADE
    done
}


prepare_tables() {
    log \
        "Preparing dedicated routing tables " \
        "${OPENVPN_TABLE} and ${VLESS_TABLE}"

    prepare_openvpn_table
    prepare_vless_table
    prepare_forwarding_rules
}


client_last_octet() {
    python3 - "$1" "$WG_NET" <<'PY'
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1])
network = ipaddress.ip_network(
    sys.argv[2],
    strict=False,
)

if address.version != 4 or address not in network:
    raise SystemExit(
        "client IP is outside the WireGuard network"
    )

if address in {
    network.network_address,
    network.broadcast_address,
}:
    raise SystemExit("client IP is not usable")

if address == network.network_address + 1:
    raise SystemExit(
        "server WireGuard address cannot be managed"
    )

print(int(str(address).split(".")[-1]))
PY
}


remove_managed_rule() {
    local priority="$1"

    if is_true "$DRY_RUN"; then
        print_cmd ip -4 rule del \
            priority "$priority"
        return
    fi

    # Диапазон 31000–31254 зарезервирован
    # этим скриптом для WireGuard-клиентов.
    while ip -4 rule del \
        priority "$priority" \
        >/dev/null 2>&1
    do
        :
    done
}


show_client_status() {
    local client_ip="$1"
    local last_octet
    local priority

    last_octet="$(
        client_last_octet "$client_ip"
    )" || die "Invalid client IP: $client_ip"

    priority=$((PRIORITY_BASE + last_octet))

    log "Managed priority: $priority"

    if is_true "$DRY_RUN"; then
        print_cmd ip -4 rule show

        print_cmd ip -4 route get \
            "$TEST_IP" \
            from "$client_ip" \
            iif "$WG_DEV"

        return
    fi

    ip -4 rule show |
        grep -E "^${priority}:" ||
        log \
            "No individual rule; auto mode uses " \
            "the general WireGuard rule"

    ip -4 route get \
        "$TEST_IP" \
        from "$client_ip" \
        iif "$WG_DEV" \
        2>&1 || true
}


set_mode() {
    local client_ip="$1"
    local mode="$2"
    local last_octet
    local priority

    case "$mode" in
        auto|direct|openvpn|vless)
            ;;
        *)
            die "Unknown mode: $mode"
            ;;
    esac

    last_octet="$(
        client_last_octet "$client_ip"
    )" || die "Invalid client IP: $client_ip"

    priority=$((PRIORITY_BASE + last_octet))

    if
        [[ "$client_ip" == "$PROTECTED_CLIENT" ]] &&
        [[ "$mode" != "auto" ]] &&
        ! is_true "$ALLOW_PROTECTED"
    then
        die "Protected WireGuard client ${client_ip} can only use auto mode"
    fi

    prepare_tables
    remove_managed_rule "$priority"

    case "$mode" in
        auto)
            log \
                "${client_ip}: auto mode, using " \
                "the general table 200 rule"
            ;;
        direct)
            run_cmd ip -4 rule add \
                from "${client_ip}/32" \
                lookup main \
                priority "$priority"
            ;;
        openvpn)
            run_cmd ip -4 rule add \
                from "${client_ip}/32" \
                lookup "$OPENVPN_TABLE" \
                priority "$priority"
            ;;
        vless)
            run_cmd ip -4 rule add \
                from "${client_ip}/32" \
                lookup "$VLESS_TABLE" \
                priority "$priority"
            ;;
    esac

    run_cmd ip -4 route flush cache

    show_client_status "$client_ip"
}


usage() {
    cat <<'USAGE'
Usage:
  wireguard-client-routing.sh prepare
  wireguard-client-routing.sh set CLIENT_IP auto|direct|openvpn|vless
  wireguard-client-routing.sh clear CLIENT_IP
  wireguard-client-routing.sh status CLIENT_IP

Environment:
  TVVPN_PROTECTED_WG_CLIENT
      Protected SSH client. Default: 10.10.0.5

  TVVPN_ALLOW_PROTECTED_WG_ROUTING=true
      Explicitly allow switching the protected client.

  TVVPN_WG_ROUTING_DRY_RUN=true
      Print commands without modifying the system.
USAGE
}


command_name="${1:-}"

case "$command_name" in
    prepare)
        [[ "$#" -eq 1 ]] || {
            usage >&2
            exit 2
        }

        prepare_tables
        ;;

    set)
        [[ "$#" -eq 3 ]] || {
            usage >&2
            exit 2
        }

        set_mode "$2" "$3"
        ;;

    clear)
        [[ "$#" -eq 2 ]] || {
            usage >&2
            exit 2
        }

        set_mode "$2" auto
        ;;

    status)
        [[ "$#" -eq 2 ]] || {
            usage >&2
            exit 2
        }

        show_client_status "$2"
        ;;

    *)
        usage >&2
        exit 2
        ;;
esac
