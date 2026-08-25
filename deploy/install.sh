#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Execute este instalador como root." >&2
    exit 1
fi

PROJECT_DIR=/home/rodrigo/Desenvolvimentos/Clientes/Teixeira/Despachante
WEBAPP_DIR="$PROJECT_DIR/webapp"
ENV_DIR=/etc/kingdom-tech
ENV_FILE="$ENV_DIR/despachante.env"

install -d -m 0750 "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
    install -m 0600 "$PROJECT_DIR/deploy/despachante.env.example" "$ENV_FILE"
    secret_key="$(runuser -u rodrigo -- /usr/bin/python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
    sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$secret_key|" "$ENV_FILE"
fi
chown root:rodrigo "$ENV_FILE"
chmod 0640 "$ENV_FILE"

install -m 0644 "$PROJECT_DIR/deploy/despachante-web.service" /etc/systemd/system/despachante-web.service
install -m 0644 "$PROJECT_DIR/deploy/despachante-worker.service" /etc/systemd/system/despachante-worker.service

runuser -u rodrigo -- env HOME=/home/rodrigo /usr/bin/python3 "$WEBAPP_DIR/manage.py" migrate --noinput
runuser -u rodrigo -- env HOME=/home/rodrigo /usr/bin/python3 "$WEBAPP_DIR/manage.py" collectstatic --noinput
runuser -u rodrigo -- env HOME=/home/rodrigo /usr/bin/python3 "$WEBAPP_DIR/manage.py" check

systemctl daemon-reload
systemctl enable despachante-web.service despachante-worker.service
systemctl restart despachante-web.service despachante-worker.service

echo "Instalacao concluida."
