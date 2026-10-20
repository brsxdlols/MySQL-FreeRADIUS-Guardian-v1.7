#!/usr/bin/env bash
# Controlled MK-AUTH Guardian v1.8 activation. No service restarts.
set -Eeuo pipefail
umask 077
BASE=/root/teste-guardian-v18
SNAP="$BASE/rollback-20261020-085554"
STAGE="$BASE/stage-v18"
TARGETS=(/var/check_backup_freeradius.sh /usr/local/sbin/mkauth_mysql_radius_guardian.sh /usr/local/sbin/mkauth_backup_guardian.sh)
SOURCES=("$STAGE/watchdog.sh" "$STAGE/mysql-guardian.sh" "$STAGE/backup-guardian.sh")
CRONS=(/etc/cron.d/check_backup_freeradius /etc/cron.d/mkauth_mysql_radius_guardian /etc/cron.d/mkauth_backup_guardian)
LOCKS=(/var/run/check_backup_freeradius.lock /var/run/mkauth_mysql_radius_guardian.lock /var/run/mkauth_backup_guardian.lock)
[[ $EUID == 0 ]] || { echo "Execute como root"; exit 1; }
[[ ${1:-} == --apply ]] || { echo "Uso: bash $0 --apply"; exit 1; }
(cd "$SNAP" && sha256sum -c SHA256SUMS >/dev/null) || { echo "ERRO: backup invalido"; exit 1; }
# Refuse activation if destructive recovery has been explicitly enabled.
if [[ -f /etc/default/check_backup_freeradius ]] &&
   grep -Eq '^[[:space:]]*(export[[:space:]]+)?GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY=[[:space:]]*["\x27]?sim(["\x27]|[[:space:]]|$)' /etc/default/check_backup_freeradius; then
 echo "ERRO: recuperacao destrutiva habilitada no arquivo de configuracao; desabilite antes da ativacao."
 exit 1
fi
for i in 0 1 2; do
 [[ -s ${SOURCES[$i]} ]] || exit 1
 bash -n "${SOURCES[$i]}" || exit 1
 [[ -f ${TARGETS[$i]} && -f ${CRONS[$i]} ]] || exit 1
done
mysql --defaults-file=/etc/mysql/debian.cnf -N -e 'SELECT 1' >/dev/null || { echo "MySQL indisponivel"; exit 1; }
service freeradius status >/dev/null || { echo "RADIUS indisponivel"; exit 1; }
# Acquire global and three existing per-monitor locks before touching cron/scripts.
exec 7>/var/run/mkauth-guardian-global-recovery.lock
flock -n 7 || { echo "Recuperacao em andamento; cancelado"; exit 1; }
exec 10>"${LOCKS[0]}"
exec 11>"${LOCKS[1]}"
exec 12>"${LOCKS[2]}"
flock -n 10 && flock -n 11 && flock -n 12 || { echo "Guardian em execucao; tente novamente"; exit 1; }
WORK="$BASE/deploy-$(date +%Y%m%d-%H%M%S)-$$"
mkdir -m 700 "$WORK"
APPLIED=0
rollback(){
 local rc=$?
 trap - EXIT ERR INT TERM
 if (( APPLIED )); then
   echo "Falha durante ativacao; restaurando scripts e crons originais..."
   for t in "${TARGETS[@]}" "${CRONS[@]}"; do
     [[ -f "$SNAP$t" ]] && cp -a "$SNAP$t" "$t" || true
   done
 fi
 exit "$rc"
}
trap rollback EXIT ERR INT TERM
# Prepare all replacement files in the target filesystem before changes.
for i in 0 1 2; do
 cp -a "${SOURCES[$i]}" "$WORK/script-$i"
 chmod 700 "$WORK/script-$i"
 bash -n "$WORK/script-$i"
done
# Disable only Guardian cron entries, not the system cron daemon.
APPLIED=1
for c in "${CRONS[@]}"; do mv "$c" "$WORK/$(basename "$c").disabled"; done
# Hold the existing monitor locks to ensure no prior execution is still active.
for i in 0 1 2; do
 t="${TARGETS[$i]}"
 tmp="$(dirname "$t")/.$(basename "$t").v18.$$"
 install -m 700 -o root -g root "$WORK/script-$i" "$tmp"
 mv -f "$tmp" "$t"
done
# Preserve existing cron schedules, only update labels (no service changes).
for c in "${CRONS[@]}"; do
 src="$WORK/$(basename "$c").disabled"
 sed -E 's/v1\\.[0-9]+/v1.8-rc1/g' "$src" > "$WORK/$(basename "$c").new"
 chmod 644 "$WORK/$(basename "$c").new"
 install -m 644 -o root -g root "$WORK/$(basename "$c").new" "$c"
done
for t in "${TARGETS[@]}"; do bash -n "$t"; done
mysql --defaults-file=/etc/mysql/debian.cnf -N -e 'SELECT 1' >/dev/null
service freeradius status >/dev/null
APPLIED=0
trap - EXIT ERR INT TERM
echo "INSTALACAO CONCLUIDA: v1.8-rc1 em modo seguro (recuperacao destrutiva nao autorizada por padrao)."
echo "Backup original: $SNAP"
echo "Cron jobs preservados; MariaDB e FreeRADIUS nao foram reiniciados."
