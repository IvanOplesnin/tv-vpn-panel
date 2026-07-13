FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TVVPN_DEVICES_FILE=/data/devices.json \
    TVVPN_LEASES_FILE=/var/lib/misc/dnsmasq.leases \
    TVVPN_DRY_RUN=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY tv_vpn_panel /app/tv_vpn_panel

EXPOSE 8090
CMD ["uvicorn", "tv_vpn_panel.main:app", "--host", "0.0.0.0", "--port", "8090"]
