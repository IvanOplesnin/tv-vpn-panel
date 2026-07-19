# TV VPN Panel

TV VPN Panel — управляющий сервис на FastAPI для policy routing на Raspberry Pi. Он управляет VPN-маршрутизацией устройств из TV/AP-сети, ESP32-пультами и отдельными режимами маршрутизации WireGuard-клиентов.

Поддерживаемый production-запуск — непосредственно на Linux-хосте через systemd. Сервис должен видеть сетевые интерфейсы хоста и изменять <code>ip rule</code>, таблицы маршрутизации и правила <code>iptables</code>.

## Возможности

- синхронизация устройств из <code>dnsmasq.leases</code>;
- хранение желаемого состояния устройств в JSON без отдельной БД;
- включение и отключение VPN для каждого устройства;
- выбор активного backend через routing table 200;
- привязка ESP32-пультов к устройствам;
- HTTP API, WebSocket API и встроенный веб-интерфейс;
- диагностика <code>tun0</code>, <code>sbtun0</code>, правил и маршрутов;
- просмотр WireGuard-клиентов, handshake и переданного трафика;
- именование WireGuard-клиентов и синхронизация имён из <code>wg0.conf</code>;
- режимы WireGuard-маршрутизации: <code>auto</code>, <code>direct</code>, <code>openvpn</code> и <code>vless</code>;
- безопасное обновление с тестами, smoke-check и автоматическим rollback.

## Архитектура

~~~text
Браузер / ESP32 / внешняя интеграция
                  |
             HTTP + WebSocket
                  |
          tv_vpn_panel.main
          /       |        \
         /        |         \
  store.py   system_ops.py   wireguard_*.py
     |            |               |
 JSON-файлы   ip rule/route    wg + routing script
 dnsmasq      table 200       tables 201/202
~~~

Основные компоненты:

| Компонент | Ответственность |
|---|---|
| <code>tv_vpn_panel/main.py</code> | FastAPI-приложение, HTTP API, страницы, lifecycle и WebSocket |
| <code>tv_vpn_panel/models.py</code> | Pydantic-модели запросов и ответов |
| <code>tv_vpn_panel/store.py</code> | JSON-хранилище, миграция данных и синхронизация DHCP leases |
| <code>tv_vpn_panel/system_ops.py</code> | Правила обычных устройств, probing и состояние backend |
| <code>tv_vpn_panel/wireguard_status.py</code> | Чтение <code>wg show TVVPN_WG_DEV dump</code>, handshake, трафик и route probe |
| <code>tv_vpn_panel/wireguard_registry.py</code> | Имена и желаемые режимы WireGuard-клиентов |
| <code>tv_vpn_panel/wireguard_routing.py</code> | Применение и проверка режима WireGuard-клиента |
| <code>scripts/wireguard-client-routing.sh</code> | Таблицы 201/202, индивидуальные rules, forwarding, NAT и kill switch |
| <code>tv_vpn_panel/ws.py</code> | Активные WebSocket-подключения и broadcast |

Приложение не поднимает VPN-туннели и не заменяет dnsmasq, OpenVPN, sing-box или WireGuard. Оно является control plane поверх уже настроенной сети хоста.

### Состояние и файлы

Runtime-данные находятся вне Git checkout:

| Путь по умолчанию | Содержимое |
|---|---|
| <code>/opt/tv-vpn-panel/devices.json</code> | Устройства и желаемое состояние VPN |
| <code>/opt/tv-vpn-panel/remotes.json</code> | ESP32-пульты и их привязки |
| <code>/opt/tv-vpn-panel/wireguard-clients.json</code> | Имена и режимы WireGuard-клиентов |
| <code>/var/lib/misc/dnsmasq.leases</code> | Источник DHCP leases, только чтение |
| <code>/etc/wireguard/wg0.conf</code> | Источник WireGuard peers и имён, только чтение |
| <code>/etc/default/tv-vpn-panel</code> | Локальные настройки и API token |

Запись JSON выполняется через временный файл и атомарную замену. При миграции старых <code>devices.json</code> и <code>remotes.json</code> создаётся резервная копия с суффиксом <code>.bak</code>.

WebSocket-подключения и число online-пультов хранятся только в памяти и сбрасываются после рестарта сервиса.

## Модель маршрутизации

### Устройства TV/AP-сети

Для устройства с включённым VPN создаётся правило:

~~~text
priority 32000 + последний октет IP
from DEVICE_IP/32 lookup 200
~~~

При выключении VPN приложение удаляет это правило. Оно не создаёт отдельное правило на <code>eth0</code>: дальнейший маршрут определяется остальными rules и таблицей <code>main</code>.

Routing table 200 должна обслуживаться существующей логикой хоста:

- OpenVPN через <code>tun0</code>;
- fallback через sing-box и <code>sbtun0</code>;
- отсутствие default route, если доступного backend нет.

Приложение определяет backend по default route таблицы 200. Скрипт переключения backend по умолчанию ожидается в <code>/usr/local/sbin/vpn-backend-switch.sh</code>, но API не запускает его, пока не задано <code>TVVPN_ALLOW_BACKEND_REFRESH=true</code>.

### WireGuard-клиенты

Для WireGuard используются следующие режимы:

| Режим | Индивидуальное правило | Назначение |
|---|---|---|
| <code>auto</code> | отсутствует | Общее правило WireGuard-сети направляет клиента в table 200 |
| <code>direct</code> | <code>lookup main</code> | Прямой выход через LAN-интерфейс |
| <code>openvpn</code> | <code>lookup 201</code> | Только OpenVPN; при недоступном backend действует unreachable kill switch |
| <code>vless</code> | <code>lookup 202</code> | Только sing-box/VLESS; при недоступном backend действует unreachable kill switch |

Приоритет индивидуального правила равен <code>TVVPN_WG_PRIORITY_BASE + последний октет IP</code>, по умолчанию диапазон начинается с 31000.

Хост должен заранее иметь общее правило для режима <code>auto</code>, например:

~~~text
from 10.10.0.0/24 lookup 200
~~~

Routing-скрипт подготавливает таблицы 201/202 и правила forwarding/NAT при каждом изменении режима. API сначала применяет маршрут, затем сохраняет профиль. Если сохранение или проверка не удались, выполняется попытка вернуть предыдущий режим.

Сохранённый <code>routing_mode</code> является желаемым состоянием. При старте приложения автоматически повторно применяются правила обычных устройств и индивидуальные WireGuard-режимы, кроме <code>auto</code>. Если backend ещё недоступен или проверка маршрута не прошла, ошибка пишется в журнал сервиса, а фактическое состояние видно по <code>routing_mode_applied</code>.

## Production deployment через systemd

### Требования

- Raspberry Pi OS, Debian или совместимый Linux;
- Python 3.10 или новее;
- systemd;
- root-доступ для сервиса;
- доступные команды <code>ip</code>, <code>iptables</code>, <code>ping</code>, <code>wg</code> и <code>systemctl</code>;
- настроенные интерфейсы <code>eth0</code>, TV/AP, <code>wg0</code>, а также <code>tun0</code> и/или <code>sbtun0</code>;
- настроенная routing table 200 и общее правило WireGuard-сети;
- сетевой доступ к Python package index во время установки и безопасного обновления.

Bundled systemd unit стартует после <code>network-online.target</code>, <code>rc-car-routing.service</code> и <code>dnsmasq.service</code>. Если на хосте логика table 200 или DHCP работает под другими unit names, адаптируйте <code>deploy/systemd/tv-vpn-panel-fastapi.service</code> до установки.

Установите системные зависимости:

~~~bash
sudo apt-get update
sudo apt-get install -y \
  git \
  ca-certificates \
  curl \
  python3 \
  python3-venv \
  python3-pip \
  iproute2 \
  iptables \
  iputils-ping \
  wireguard-tools
~~~

Для локальной установки через <code>scripts/install-systemd.sh</code> дополнительно нужен <code>rsync</code>. Для <code>scripts/update-safe.sh</code> нужен <code>flock</code> из пакета <code>util-linux</code>.

### Preflight сети

До установки приложения проверьте базовую конфигурацию хоста:

~~~bash
python3 --version
command -v ip
command -v wg
command -v iptables
command -v ping

sudo ip -4 rule show
sudo ip -4 route show table 200
sudo wg show wg0
sudo test -r /var/lib/misc/dnsmasq.leases
~~~

Ожидается, что:

- Python имеет версию не ниже 3.10;
- table 200 существует и содержит ожидаемые маршруты;
- <code>wg show wg0</code> возвращает интерфейс и peers;
- сервис сможет читать leases и <code>/etc/wireguard/wg0.conf</code>.

Отсутствующий leases-файл не мешает процессу запуститься, но автоматическое обнаружение устройств работать не будет.

### Первая установка из Git

Рекомендуемый путь:

~~~bash
sudo git clone \
  https://github.com/IvanOplesnin/tv-vpn-panel.git \
  /opt/tv-vpn-panel-fastapi

cd /opt/tv-vpn-panel-fastapi

sudo env \
  TVVPN_REPO_URL=https://github.com/IvanOplesnin/tv-vpn-panel.git \
  TVVPN_BRANCH=main \
  ./scripts/install-from-git.sh
~~~

Installer:

1. обновляет checkout до выбранной ветки;
2. создаёт <code>/opt/tv-vpn-panel-fastapi/.venv</code>;
3. устанавливает Python-зависимости;
4. создаёт <code>/etc/default/tv-vpn-panel</code>, если файла ещё нет;
5. устанавливает unit <code>/etc/systemd/system/tv-vpn-panel.service</code>;
6. выполняет <code>systemctl enable</code> и перезапускает сервис.

Существующий <code>/etc/default/tv-vpn-panel</code> при повторной установке не перезаписывается.

Готовый unit использует фиксированные пути <code>/opt/tv-vpn-panel-fastapi</code> и <code>/etc/default/tv-vpn-panel</code>. Документация и safe updater рассчитаны именно на них. Для другой структуры сначала измените unit; одного <code>TVVPN_APP_DIR</code> недостаточно.

### Установка из локальной копии

~~~bash
sudo apt-get install -y rsync
cd /path/to/tv-vpn-panel
sudo ./scripts/install-systemd.sh
~~~

Скрипт синхронизирует текущую директорию в <code>/opt/tv-vpn-panel-fastapi</code> и удаляет там файлы, которых нет в локальной копии. Runtime JSON находится вне этой директории и не затрагивается.

### Production-конфигурация

Откройте:

~~~bash
sudo nano /etc/default/tv-vpn-panel
~~~

Минимальный пример для стандартной топологии:

~~~ini
TVVPN_HOST=0.0.0.0
TVVPN_PORT=8090

TVVPN_DEVICES_FILE=/opt/tv-vpn-panel/devices.json
TVVPN_REMOTES_FILE=/opt/tv-vpn-panel/remotes.json
TVVPN_WIREGUARD_CLIENTS_FILE=/opt/tv-vpn-panel/wireguard-clients.json
TVVPN_LEASES_FILE=/var/lib/misc/dnsmasq.leases
TVVPN_WIREGUARD_CONFIG_FILE=/etc/wireguard/wg0.conf

TVVPN_TABLE_ID=200
TVVPN_AP_INTERFACE=enx00e04c2a7a88
TVVPN_ROUTE_TEST_IP=8.8.8.8

TVVPN_WG_DEV=wg0
TVVPN_OPENVPN_TABLE=201
TVVPN_VLESS_TABLE=202
TVVPN_WG_PRIORITY_BASE=31000

TVVPN_LAN_DEV=eth0
TVVPN_OVPN_DEV=tun0
TVVPN_VLESS_DEV=sbtun0

TVVPN_POLL_INTERVAL=10
TVVPN_ENABLE_PERIODIC_SYNC=true
TVVPN_DRY_RUN=false
TVVPN_ALLOW_BACKEND_REFRESH=false

# Пустое значение подходит только для доверенной локальной сети.
TVVPN_API_TOKEN=
~~~

Для routing-скрипта при нестандартной сети также задайте:

~~~ini
TVVPN_WG_NET=10.10.0.0/24
TVVPN_WG_DEV=wg0
TVVPN_LAN_NET=192.168.1.0/24
TVVPN_AP_NET=192.168.50.0/24
TVVPN_AP_DEV=enx00e04c2a7a88
TVVPN_OVPN_NET=10.8.0.0/24
TVVPN_OVPN_GW=10.8.0.1
TVVPN_VLESS_NET=172.19.0.0/30
TVVPN_BACKEND_CHECK_IP=1.1.1.1
~~~

<code>TVVPN_AP_INTERFACE</code> используется Python-приложением для route probe обычных устройств, а <code>TVVPN_AP_DEV</code> — shell-скриптом WireGuard. Для одной AP-сети их значения должны указывать на один интерфейс.

Python API мониторинга WireGuard и routing script используют <code>TVVPN_WG_DEV</code>. Default — <code>wg0</code>.

После изменения конфигурации:

~~~bash
sudo systemctl restart tv-vpn-panel.service
sudo systemctl status tv-vpn-panel.service --no-pager -l
~~~

### Проверка подъёма сервиса

Проверьте systemd:

~~~bash
sudo systemctl is-enabled tv-vpn-panel.service
sudo systemctl is-active tv-vpn-panel.service
sudo systemctl status tv-vpn-panel.service --no-pager -l
sudo journalctl -u tv-vpn-panel.service -n 100 --no-pager
~~~

Проверьте порт и API:

~~~bash
sudo ss -ltnp | grep ':8090'

curl --fail --silent --show-error \
  http://127.0.0.1:8090/api/health \
  | python3 -m json.tool

curl --fail --silent --show-error \
  http://127.0.0.1:8090/api/diagnostics \
  | python3 -m json.tool

curl --fail --silent --show-error \
  http://127.0.0.1:8090/api/wireguard/clients \
  | python3 -m json.tool
~~~

При включённом token:

~~~bash
curl --fail --silent --show-error \
  -H 'X-API-Token: change-me' \
  http://127.0.0.1:8090/api/health \
  | python3 -m json.tool
~~~

Успешный HTTP 200 от <code>/api/health</code> означает, что приложение отвечает. Для полной готовности дополнительно проверьте:

- <code>backend.ok</code>;
- <code>devices_file_ok</code> и <code>remotes_file_ok</code>;
- <code>leases_file_exists</code> и <code>can_read_leases</code>;
- <code>ip_command_available</code>;
- ответ <code>/api/wireguard/clients</code> и его поле <code>ok</code>;
- <code>routing_mode_applied</code> нужных WireGuard-клиентов.

Веб-интерфейсы:

~~~text
http://RASPBERRY_PI_IP:8090/
http://RASPBERRY_PI_IP:8090/wireguard
http://RASPBERRY_PI_IP:8090/docs
~~~

### Проверка маршрутизации

~~~bash
sudo ip -4 rule show
sudo ip -4 route show table 200
sudo ip -4 route show table 201
sudo ip -4 route show table 202

sudo ip route get \
  8.8.8.8 \
  from 192.168.50.20 \
  iif enx00e04c2a7a88

sudo ip route get \
  8.8.8.8 \
  from 10.10.0.5 \
  iif wg0
~~~

Замените IP и интерфейсы на значения своей сети. Поле <code>vpn=true</code> в JSON означает желаемое состояние; фактическое состояние подтверждают <code>runtime.rule_present</code>, <code>runtime.route_probe_ok</code> и вывод route probe.

### Безопасное обновление

Рекомендуемый production-вариант:

~~~bash
cd /opt/tv-vpn-panel-fastapi

sudo env \
  TVVPN_SAFE_WG_CLIENT=10.10.0.5 \
  ./scripts/update-safe.sh --activate
~~~

<code>TVVPN_SAFE_WG_CLIENT</code> должен указывать на доступного WireGuard-клиента в режиме <code>auto</code>. При SSH-подключении с адреса <code>10.10.0.x</code> updater пытается определить его автоматически.

Перед переключением production updater:

1. клонирует commit в отдельный release-каталог;
2. создаёт отдельный virtualenv;
3. устанавливает runtime и dev-зависимости;
4. запускает pytest;
5. поднимает изолированный dry-run сервер на порту 8091;
6. проверяет health и WireGuard API;
7. сохраняет systemd unit, environment и текущее состояние routing;
8. атомарно переключает <code>/opt/tv-vpn-panel-fastapi</code> на новый release;
9. перезапускает только <code>tv-vpn-panel.service</code>;
10. повторно проверяет API и маршрут WireGuard.

При ошибке после переключения предыдущий release восстанавливается автоматически.

Проверить candidate без изменения production:

~~~bash
sudo ./scripts/update-safe.sh --prepare-only
~~~

Режим <code>--prepare-only</code> только проверяет новый release. Последующий <code>--activate</code> создаёт и проверяет новый candidate заново.

Safe updater требует работающий <code>wg0</code> хотя бы с одним peer. Если WireGuard на конкретной установке не используется, применяйте простое in-place обновление:

~~~bash
sudo /opt/tv-vpn-panel-fastapi/scripts/update-from-git.sh
~~~

Обычный updater выполняет <code>git fetch/reset</code>, обновляет зависимости и перезапускает сервис. У него нет staged smoke-check и автоматического rollback. Не смешивайте in-place обновления с release-схемой после первого успешного запуска <code>update-safe.sh --activate</code>.

Настройки safe updater:

| Переменная | Default | Назначение |
|---|---|---|
| <code>TVVPN_APP_PATH</code> | <code>/opt/tv-vpn-panel-fastapi</code> | Production path или symlink |
| <code>TVVPN_RELEASES_DIR</code> | <code>/opt/tv-vpn-panel-releases</code> | Изолированные releases |
| <code>TVVPN_BACKUPS_DIR</code> | <code>/opt/tv-vpn-panel-backups</code> | Диагностические backup |
| <code>TVVPN_SERVICE_NAME</code> | <code>tv-vpn-panel.service</code> | systemd unit |
| <code>TVVPN_ENV_FILE</code> | <code>/etc/default/tv-vpn-panel</code> | Production environment |
| <code>TVVPN_REPO_URL</code> | GitHub repository | Источник release |
| <code>TVVPN_BRANCH</code> | <code>main</code> | Ветка |
| <code>TVVPN_TEST_HOST</code> | <code>127.0.0.1</code> | Адрес smoke-сервера |
| <code>TVVPN_TEST_PORT</code> | <code>8091</code> | Порт smoke-сервера |
| <code>TVVPN_PRODUCTION_BASE_URL</code> | <code>http://127.0.0.1:8090</code> | URL production health-check |
| <code>TVVPN_SAFE_WG_CLIENT</code> | определяется из SSH | Клиент для route verification |
| <code>TVVPN_EXPECT_WG_TABLE</code> | <code>200</code> | Ожидаемая table режима auto |
| <code>TVVPN_UPDATE_LOCK</code> | <code>/run/lock/tv-vpn-panel-update.lock</code> | Файл блокировки обновления |

### Диагностика проблем запуска

| Симптом | Что проверить |
|---|---|
| Unit не стартует | <code>journalctl -u tv-vpn-panel.service -n 100</code>, наличие <code>.venv/bin/uvicorn</code> |
| API возвращает 401 | Значение <code>TVVPN_API_TOKEN</code> и заголовок <code>X-API-Token</code> |
| <code>backend.ok=false</code> | Default route в table 200, состояние <code>tun0</code>/<code>sbtun0</code> |
| Устройства не появляются | Путь, права и содержимое <code>dnsmasq.leases</code> |
| WireGuard API возвращает <code>ok=false</code> | Команда <code>wg show wg0</code>, интерфейс и права сервиса |
| PATCH WireGuard возвращает 409 | Доступность выбранного backend, rules, tables 201/202 и route verification |
| Режим сохранён, но не применён | Поле <code>routing_mode_applied</code> и фактический <code>ip route get</code> |

Сервис запускается от root, потому что unit не задаёт <code>User</code>. Это необходимо для изменения сетевого состояния, поэтому API нельзя публиковать в интернет без token, firewall и дополнительного reverse proxy с TLS.

## HTTP API

Base URL:

~~~text
http://RASPBERRY_PI_IP:8090
~~~

Интерактивная OpenAPI-документация:

~~~text
/docs
/openapi.json
~~~

### Аутентификация

Если <code>TVVPN_API_TOKEN</code> пуст, HTTP API и WebSocket доступны без token. Для production вне изолированной доверенной сети задайте token.

HTTP поддерживает:

~~~http
X-API-Token: change-me
~~~

или:

~~~http
Authorization: Bearer change-me
~~~

Query-параметр <code>?token=change-me</code> также поддерживается, но для интеграций предпочтительнее заголовок: query string может попасть в access log и историю.

Страницы <code>/</code> и <code>/wireguard</code> отдаются без API dependency. При включённом token встроенный интерфейс сохраняет его в <code>localStorage</code> браузера и добавляет к API/WebSocket-запросам.

### Каталог endpoints

| Метод | Путь | Назначение |
|---|---|---|
| GET | <code>/api/health</code> | Быстрая проверка приложения и runtime-файлов |
| GET | <code>/api/diagnostics</code> | Rules, routes, интерфейсы и конфигурационные пути |
| POST | <code>/api/backend/refresh</code> | Запустить внешний backend switch script, если разрешено |
| GET | <code>/api/device-types</code> | Допустимые типы устройств |
| GET | <code>/api/devices</code> | Синхронизировать leases и вернуть устройства |
| POST | <code>/api/devices/sync</code> | Синхронизировать leases и повторно применить все device rules |
| POST | <code>/api/devices</code> | Создать или обновить ручное устройство |
| GET | <code>/api/devices/{mac}</code> | Устройство, backend и фактический route probe |
| PATCH | <code>/api/devices/{mac}</code> | Изменить имя, тип или pinned |
| POST | <code>/api/devices/{mac}/vpn</code> | Явно установить VPN-состояние |
| POST | <code>/api/devices/{mac}/toggle</code> | Переключить VPN-состояние |
| DELETE | <code>/api/devices/{mac}</code> | Удалить устройство и его rule |
| GET | <code>/api/remotes</code> | Список ESP32-пультов |
| POST | <code>/api/remotes</code> | Создать или upsert-пульт |
| GET | <code>/api/remotes/{remote_id}</code> | Получить один пульт |
| PATCH | <code>/api/remotes/{remote_id}</code> | Изменить имя, enabled или binding |
| POST | <code>/api/remotes/{remote_id}/bind</code> | Привязать пульт к MAC устройства |
| POST | <code>/api/remotes/{remote_id}/unbind</code> | Удалить привязку |
| DELETE | <code>/api/remotes/{remote_id}</code> | Удалить пульт |
| GET | <code>/api/wireguard/clients</code> | Статус WireGuard peers и маршрутов |
| POST | <code>/api/wireguard/clients/sync-names</code> | Импортировать имена из комментариев <code>wg0.conf</code> |
| PATCH | <code>/api/wireguard/clients/{client_ip}</code> | Изменить имя и/или режим маршрутизации |

Все API endpoints требуют token, если он настроен. HTML-страницы и WebSocket перечислены отдельно.

### Коды ошибок

| Код | Значение |
|---:|---|
| 400 | Ошибка бизнес-валидации или пустое обновление |
| 401 | Неверный API token |
| 404 | Устройство, пульт, WireGuard-клиент или config не найден |
| 409 | Режим WireGuard не удалось применить или проверить |
| 422 | Тело запроса не прошло Pydantic-валидацию |
| 503 | WireGuard status/config временно недоступен |

<code>POST /api/backend/refresh</code> возвращает HTTP 200 и объект с <code>ok=false</code>, если запуск backend script запрещён настройкой.

### Health

~~~bash
curl http://192.168.50.1:8090/api/health
~~~

Пример ответа:

~~~json
{
  "ok": true,
  "backend": {
    "active": "sing-box",
    "ok": true,
    "table_id": "200",
    "table_has_default": true,
    "default_route": "default dev sbtun0"
  },
  "devices_count": 4,
  "managed_devices_count": 3,
  "remotes_count": 1,
  "online_remotes_count": 1,
  "dry_run": false,
  "devices_file_ok": true,
  "remotes_file_ok": true,
  "leases_file_exists": true,
  "can_read_leases": true,
  "ip_command_available": true,
  "service_user": "root",
  "backend_switch_allowed": false
}
~~~

Поле верхнего уровня <code>ok=true</code> не гарантирует доступность VPN backend. Проверяйте вложенное <code>backend.ok</code>.

### Diagnostics

~~~bash
curl http://192.168.50.1:8090/api/diagnostics
~~~

Ответ содержит:

- пути runtime-файлов;
- table ID, AP interface и route-test IP;
- полный вывод <code>ip rule</code>;
- маршруты table 200;
- состояние <code>tun0</code> и <code>sbtun0</code>;
- количество устройств и пультов.

Diagnostics может раскрывать детали сети. Защищайте endpoint token и firewall.

### Устройства

Идентификатор устройства — нормализованный lowercase MAC.

Пример объекта:

~~~json
{
  "name": "Bedroom TV",
  "ip": "192.168.50.20",
  "mac": "b8:87:6e:4a:cd:2c",
  "vpn": false,
  "type": "tv",
  "pinned": true,
  "name_override": true,
  "lease_name": "android-tv",
  "lease_expiry": "1783970000"
}
~~~

Список:

~~~bash
curl http://192.168.50.1:8090/api/devices
~~~

Запрос синхронизирует текущие DHCP leases. Устройства с <code>pinned=true</code> идут первыми, MAC зарегистрированных ESP32-пультов исключаются.

Создание ручного устройства:

~~~bash
curl -X POST http://192.168.50.1:8090/api/devices \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Living room console",
    "ip": "192.168.50.40",
    "mac": "aa:bb:cc:dd:ee:40",
    "type": "console"
  }'
~~~

Если <code>mac</code> не передан, создаётся внутренний идентификатор вида <code>manual-IP</code>.

Изменение метаданных:

~~~bash
curl -X PATCH \
  http://192.168.50.1:8090/api/devices/b8:87:6e:4a:cd:2c \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Bedroom TV",
    "type": "tv",
    "pinned": true
  }'
~~~

После ручного изменения имени устанавливается <code>name_override=true</code>. DHCP hostname продолжает обновляться в <code>lease_name</code>, но не заменяет отображаемое имя.

Установить VPN:

~~~bash
curl -X POST \
  http://192.168.50.1:8090/api/devices/b8:87:6e:4a:cd:2c/vpn \
  -H 'Content-Type: application/json' \
  -d '{"vpn": true}'
~~~

Переключить:

~~~bash
curl -X POST \
  http://192.168.50.1:8090/api/devices/b8:87:6e:4a:cd:2c/toggle
~~~

Получить желаемое и фактическое состояние:

~~~bash
curl \
  http://192.168.50.1:8090/api/devices/b8:87:6e:4a:cd:2c
~~~

~~~json
{
  "ok": true,
  "device": {
    "name": "Bedroom TV",
    "ip": "192.168.50.20",
    "mac": "b8:87:6e:4a:cd:2c",
    "vpn": true,
    "type": "tv",
    "pinned": true,
    "name_override": true,
    "lease_name": "android-tv",
    "lease_expiry": "1783970000"
  },
  "backend": {
    "active": "sing-box",
    "ok": true,
    "table_id": "200",
    "table_has_default": true,
    "default_route": "default dev sbtun0"
  },
  "runtime": {
    "rule_present": true,
    "route_probe_ok": true,
    "route_probe": "8.8.8.8 from 192.168.50.20 dev sbtun0 table 200"
  }
}
~~~

Повторно применить правила всех устройств:

~~~bash
curl -X POST http://192.168.50.1:8090/api/devices/sync
~~~

Удалить:

~~~bash
curl -X DELETE \
  http://192.168.50.1:8090/api/devices/b8:87:6e:4a:cd:2c
~~~

Устройство из актуального DHCP lease появится снова при следующей синхронизации.

Допустимые типы не следует хардкодить в клиентах:

~~~bash
curl http://192.168.50.1:8090/api/device-types
~~~

### Backend

~~~bash
curl -X POST http://192.168.50.1:8090/api/backend/refresh
~~~

Выполнение возможно только при <code>TVVPN_ALLOW_BACKEND_REFRESH=true</code>. В dry-run скрипт не запускается.

### ESP32-пульты

Пример объекта:

~~~json
{
  "remote_id": "remote-bedroom-01",
  "name": "Bedroom remote",
  "remote_mac": "aa:bb:cc:dd:ee:ff",
  "target_mac": "b8:87:6e:4a:cd:2c",
  "enabled": true,
  "firmware": "0.1.0",
  "last_seen": "2026-07-17T12:00:00Z",
  "last_ip": "192.168.1.50"
}
~~~

Список:

~~~bash
curl http://192.168.50.1:8090/api/remotes
~~~

Создать или обновить:

~~~bash
curl -X POST http://192.168.50.1:8090/api/remotes \
  -H 'Content-Type: application/json' \
  -d '{
    "remote_id": "remote-bedroom-01",
    "name": "Bedroom remote",
    "remote_mac": "aa:bb:cc:dd:ee:ff",
    "target_mac": "b8:87:6e:4a:cd:2c",
    "enabled": true,
    "firmware": "0.1.0"
  }'
~~~

Изменить существующий пульт:

~~~bash
curl -X PATCH \
  http://192.168.50.1:8090/api/remotes/remote-bedroom-01 \
  -H 'Content-Type: application/json' \
  -d '{"name": "Bedroom button", "enabled": true}'
~~~

Привязать:

~~~bash
curl -X POST \
  http://192.168.50.1:8090/api/remotes/remote-bedroom-01/bind \
  -H 'Content-Type: application/json' \
  -d '{"target_mac": "b8:87:6e:4a:cd:2c"}'
~~~

Отвязать:

~~~bash
curl -X POST \
  http://192.168.50.1:8090/api/remotes/remote-bedroom-01/unbind
~~~

Для снятия binding используйте отдельный endpoint <code>/unbind</code>. Значение <code>null</code> в PATCH не очищает binding.

Удалить:

~~~bash
curl -X DELETE \
  http://192.168.50.1:8090/api/remotes/remote-bedroom-01
~~~

Если пульт сообщает <code>remote_mac</code>, устройство с таким MAC удаляется из списка управляемых устройств.

### WireGuard

Статус клиентов:

~~~bash
curl http://192.168.50.1:8090/api/wireguard/clients
~~~

Сокращённый пример ответа:

~~~json
{
  "ok": true,
  "interface": "wg0",
  "generated_at": "2026-07-17T12:00:00+00:00",
  "online_threshold_seconds": 180,
  "peers": [
    {
      "public_key": "PUBLIC_KEY",
      "public_key_short": "PUBLIC_KEY",
      "name": "Bedroom tablet",
      "name_is_default": false,
      "routing_mode": "direct",
      "routing_mode_applied": true,
      "endpoint": "203.0.113.10:51820",
      "allowed_ips": ["10.10.0.6/32"],
      "ip": "10.10.0.6",
      "status": "online",
      "latest_handshake_unix": 1784289600,
      "latest_handshake_at": "2026-07-17T12:00:00+00:00",
      "latest_handshake_age_seconds": 10,
      "transfer_rx_bytes": 1024,
      "transfer_tx_bytes": 2048,
      "persistent_keepalive_seconds": 25,
      "route_probe_ok": true,
      "route_probe": "8.8.8.8 from 10.10.0.6 dev eth0 table main"
    }
  ],
  "error": null
}
~~~

Статусы peer:

- <code>online</code> — handshake был не более 180 секунд назад;
- <code>idle</code> — handshake есть, но старше порога;
- <code>never</code> — handshake ещё не было.

Изменить имя:

~~~bash
curl -X PATCH \
  http://192.168.50.1:8090/api/wireguard/clients/10.10.0.6 \
  -H 'Content-Type: application/json' \
  -d '{"name": "Bedroom tablet"}'
~~~

Изменить режим:

~~~bash
curl -X PATCH \
  http://192.168.50.1:8090/api/wireguard/clients/10.10.0.6 \
  -H 'Content-Type: application/json' \
  -d '{"routing_mode": "openvpn"}'
~~~

Имя и режим можно передать одним запросом. Пустое тело запрещено.

Синхронизировать имена из <code>/etc/wireguard/wg0.conf</code>:

~~~bash
curl -X POST \
  http://192.168.50.1:8090/api/wireguard/clients/sync-names
~~~

Пример config:

~~~ini
# Bedroom tablet
[Peer]
PublicKey = PUBLIC_KEY
AllowedIPs = 10.10.0.6/32
~~~

Также распознаются комментарии с префиксами <code>name:</code>, <code>name=</code>, <code>client:</code>, <code>client=</code>, <code>peer:</code> и <code>peer=</code>. Ручное имя не перезаписывается обычной синхронизацией.

## WebSocket API

Endpoint:

~~~text
ws://192.168.50.1:8090/ws
~~~

Если API token включён, он должен быть передан при соединении:

~~~text
ws://192.168.50.1:8090/ws?token=change-me
~~~

Пульт обычно подключается так:

~~~text
ws://192.168.50.1:8090/ws?remote_id=remote-bedroom-01&token=change-me
~~~

Поддерживаемые входящие сообщения:

| Type | Назначение |
|---|---|
| <code>hello</code> | Зарегистрировать remote metadata и необязательный binding |
| <code>ping</code> | Обновить last seen и получить <code>pong</code> |
| <code>get_state</code> | Получить состояние привязанного устройства |
| <code>set_vpn</code> | Явно установить VPN |
| <code>toggle_vpn</code> | Переключить VPN |
| <code>sync</code> | Синхронизировать устройства и повторно применить rules |

Hello:

~~~json
{
  "type": "hello",
  "remote_id": "remote-bedroom-01",
  "remote_name": "Bedroom remote",
  "remote_mac": "aa:bb:cc:dd:ee:ff",
  "target_mac": "b8:87:6e:4a:cd:2c",
  "firmware": "0.1.0"
}
~~~

Установить VPN:

~~~json
{
  "type": "set_vpn",
  "vpn": true
}
~~~

Переключить:

~~~json
{
  "type": "toggle_vpn"
}
~~~

Запросить состояние:

~~~json
{
  "type": "get_state"
}
~~~

Основные исходящие types:

- <code>hello_ok</code>;
- <code>pong</code>;
- <code>pairing_required</code>;
- <code>devices</code>;
- <code>state</code>;
- <code>error</code>.

Если <code>remote_id</code> не привязан или пульт disabled, сервер отвечает <code>pairing_required</code>. HTTP остаётся предпочтительным API для service-to-service автоматизации.

## Переменные окружения

### Приложение

| Переменная | Default | Назначение |
|---|---|---|
| <code>TVVPN_HOST</code> | <code>0.0.0.0</code> | Адрес uvicorn |
| <code>TVVPN_PORT</code> | <code>8090</code> | Порт uvicorn |
| <code>TVVPN_DEVICES_FILE</code> | <code>/opt/tv-vpn-panel/devices.json</code> | Устройства |
| <code>TVVPN_REMOTES_FILE</code> | <code>/opt/tv-vpn-panel/remotes.json</code> | Пульты |
| <code>TVVPN_WIREGUARD_CLIENTS_FILE</code> | <code>/opt/tv-vpn-panel/wireguard-clients.json</code> | Профили WireGuard |
| <code>TVVPN_LEASES_FILE</code> | <code>/var/lib/misc/dnsmasq.leases</code> | DHCP leases |
| <code>TVVPN_WIREGUARD_CONFIG_FILE</code> | <code>/etc/wireguard/wg0.conf</code> | WireGuard config для sync имён |
| <code>TVVPN_TABLE_ID</code> | <code>200</code> | Общая VPN table |
| <code>TVVPN_AP_INTERFACE</code> | <code>enx00e04c2a7a88</code> | Входной интерфейс route probe устройств |
| <code>TVVPN_ROUTE_TEST_IP</code> | <code>8.8.8.8</code> | Цель route probe |
| <code>TVVPN_WG_DEV</code> | <code>wg0</code> | WireGuard-интерфейс для API и routing script |
| <code>TVVPN_BACKEND_SWITCH_SCRIPT</code> | <code>/usr/local/sbin/vpn-backend-switch.sh</code> | Внешний backend switch script |
| <code>TVVPN_WIREGUARD_ROUTING_SCRIPT</code> | Скрипт из текущего checkout | Применение режима WireGuard |
| <code>TVVPN_WG_PRIORITY_BASE</code> | <code>31000</code> | База индивидуальных WG priorities |
| <code>TVVPN_OPENVPN_TABLE</code> | <code>201</code> | Выделенная OpenVPN table |
| <code>TVVPN_VLESS_TABLE</code> | <code>202</code> | Выделенная VLESS table |
| <code>TVVPN_LAN_DEV</code> | <code>eth0</code> | Direct-интерфейс |
| <code>TVVPN_OVPN_DEV</code> | <code>tun0</code> | OpenVPN-интерфейс |
| <code>TVVPN_VLESS_DEV</code> | <code>sbtun0</code> | sing-box/VLESS-интерфейс |
| <code>TVVPN_API_TOKEN</code> | пусто | Token HTTP API и WebSocket |
| <code>TVVPN_POLL_INTERVAL</code> | <code>10</code> | Период sync/broadcast в секундах |
| <code>TVVPN_ENABLE_PERIODIC_SYNC</code> | <code>true</code> | Фоновая синхронизация |
| <code>TVVPN_DRY_RUN</code> | <code>false</code> | Не выполнять mutating network commands |
| <code>TVVPN_ALLOW_BACKEND_REFRESH</code> | <code>false</code> | Разрешить backend refresh API |

### WireGuard routing script

| Переменная | Default |
|---|---|
| <code>TVVPN_WG_NET</code> | <code>10.10.0.0/24</code> |
| <code>TVVPN_WG_DEV</code> | <code>wg0</code> |
| <code>TVVPN_LAN_NET</code> | <code>192.168.1.0/24</code> |
| <code>TVVPN_LAN_DEV</code> | <code>eth0</code> |
| <code>TVVPN_AP_NET</code> | <code>192.168.50.0/24</code> |
| <code>TVVPN_AP_DEV</code> | <code>enx00e04c2a7a88</code> |
| <code>TVVPN_OVPN_NET</code> | <code>10.8.0.0/24</code> |
| <code>TVVPN_OVPN_DEV</code> | <code>tun0</code> |
| <code>TVVPN_OVPN_GW</code> | <code>10.8.0.1</code> |
| <code>TVVPN_VLESS_NET</code> | <code>172.19.0.0/30</code> |
| <code>TVVPN_VLESS_DEV</code> | <code>sbtun0</code> |
| <code>TVVPN_OPENVPN_TABLE</code> | <code>201</code> |
| <code>TVVPN_VLESS_TABLE</code> | <code>202</code> |
| <code>TVVPN_WG_PRIORITY_BASE</code> | <code>31000</code> |
| <code>TVVPN_BACKEND_CHECK_IP</code> | <code>1.1.1.1</code> |
| <code>TVVPN_PROTECTED_WG_CLIENT</code> | пусто |
| <code>TVVPN_ALLOW_PROTECTED_WG_ROUTING</code> | <code>false</code> |
| <code>TVVPN_WG_ROUTING_DRY_RUN</code> | <code>false</code> |

<code>TVVPN_PROTECTED_WG_CLIENT</code> может запретить перевод административного клиента из <code>auto</code> в другой режим. Для явного обхода задаётся <code>TVVPN_ALLOW_PROTECTED_WG_ROUTING=true</code>.

При <code>TVVPN_DRY_RUN=true</code> приложение не вызывает routing script. <code>TVVPN_WG_ROUTING_DRY_RUN</code> предназначен для самостоятельного тестирования shell-скрипта.

## Локальная разработка

Linux/macOS:

~~~bash
python3 -m venv .venv
. .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install \
  -r requirements.txt \
  -r requirements-dev.txt

mkdir -p .runtime
printf '[]\n' > .runtime/devices.json
printf '[]\n' > .runtime/remotes.json
printf '[]\n' > .runtime/wireguard-clients.json
: > .runtime/dnsmasq.leases

TVVPN_DRY_RUN=true \
TVVPN_ENABLE_PERIODIC_SYNC=false \
TVVPN_API_TOKEN= \
TVVPN_DEVICES_FILE=.runtime/devices.json \
TVVPN_REMOTES_FILE=.runtime/remotes.json \
TVVPN_WIREGUARD_CLIENTS_FILE=.runtime/wireguard-clients.json \
TVVPN_LEASES_FILE=.runtime/dnsmasq.leases \
.venv/bin/uvicorn \
  tv_vpn_panel.main:app \
  --reload \
  --host 127.0.0.1 \
  --port 8090
~~~

Dry-run сохраняет JSON-состояние, но пропускает:

- добавление и удаление device rules;
- применение WireGuard routing mode;
- запуск backend switch script.

Read-only команды <code>ip</code> и <code>wg</code> всё ещё могут выполняться для диагностики.

Тесты:

~~~bash
python -m pytest -q
~~~

Часть тестов routing-скрипта требует Bash и рассчитана на Linux-окружение.
