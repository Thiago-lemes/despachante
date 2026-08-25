#!/bin/bash
set -euo pipefail

BACKUP_DIR=/var/backups/despachante
DB_NAME=despachante
DIAS_RETENCAO=14

DATA=$(date +%F)
DESTINO="$BACKUP_DIR/despachante_$DATA.sql.gz"

pg_dump "$DB_NAME" | gzip > "$DESTINO.tmp"
mv "$DESTINO.tmp" "$DESTINO"

find "$BACKUP_DIR" -name 'despachante_*.sql.gz' -mtime "+$DIAS_RETENCAO" -delete
