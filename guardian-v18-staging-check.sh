#!/usr/bin/env bash
# Guardian v1.8 staged deploy helper. Defaults to read-only --check.
set -Eeuo pipefail
umask 077
MODE="${1:---check}"
ROOT="/root/teste-guardian-v18"
SRC="$ROOT/instalador-v18.sh"
SNAP="$ROOT/rollback-20261020-085554"
STAGE="$ROOT/stage-v18"
FILES=(/var/check_backup_freeradius.sh /usr/local/sbin/mkauth_mysql_radius_guardian.sh /usr/local/sbin/mkauth_backup_guardian.sh)
CRONS=(/etc/cron.d/check_backup_freeradius /etc/cron.d/mkauth_mysql_radius_guardian /etc/cron.d/mkauth_backup_guardian)
die(){ echo "ERRO: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "execute como root"
[[ "$MODE" == --check || "$MODE" == --apply || "$MODE" == --rollback ]] || die "uso: $0 --check|--apply|--rollback"
[[ -f "$SRC" ]] || die "instalador fonte ausente"
[[ -f "$SNAP/SHA256SUMS" ]] || die "snapshot ausente"
(cd "$SNAP" && sha256sum -c SHA256SUMS >/dev/null) || die "snapshot corrompido"
command -v flock >/dev/null || die "flock ausente"
mkdir -p "$STAGE"
chmod 700 "$STAGE"
if [[ "$MODE" != --rollback ]]; then
  bash -n "$SRC" || die "sintaxe do instalador"
  extract(){
    local start="$1" end="$2" dest="$3"
    awk -v start="$start" -v end="$end" '$0==start {p=1;next} p && $0==end {exit} p {print}' "$SRC" > "$dest"
    [[ -s "$dest" ]] || die "extracao vazia: $dest"
    bash -n "$dest" || die "sintaxe invalida: $dest"
    chmod 700 "$dest"
  }
  extract "cat > \"\$SCRIPT\" <<'MONITOR'" "MONITOR" "$STAGE/watchdog.sh"
  extract "cat > \"\$MYSQL_GUARDIAN\" <<'GUARDIAN17'" "GUARDIAN17" "$STAGE/mysql-guardian.sh"
  extract "cat > \"\$BACKUP_GUARDIAN\" <<'GUARDIAN16'" "GUARDIAN16" "$STAGE/backup-guardian.sh"
  [[ $(grep -c 'mkauth-guardian-global-recovery.lock' "$SRC") -eq 5 ]] || die "contagem de locks inesperada"
  [[ $(grep -c 'GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY' "$SRC") -eq 5 ]] || die "contagem de protecoes inesperada"
fi
echo "Modo: $MODE"
echo "Snapshot: $SNAP"
echo "Arquivos extraidos: $STAGE"
echo "Servicos: $(mysql --defaults-file=/etc/mysql/debian.cnf -N -e 'SELECT 1' 2>/dev/null || echo MYSQL_INDISPONIVEL)"
if [[ "$MODE" == --check ]]; then
  echo "CHECK OK. Nenhum arquivo ativo alterado."
  exit 0
fi
# Apply and rollback deliberately require maintenance window and manual approval.
# This helper intentionally does NOT automate service-impacting cron changes.
die "Aplicacao/rollback bloqueados nesta revisao: falta validar concorrencia de cron e processos ativos em homologacao. Use --check."
