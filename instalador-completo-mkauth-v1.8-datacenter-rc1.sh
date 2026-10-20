#!/bin/bash

set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ==========================================================
# CONFIGURAÇÃO
# ==========================================================

TELEGRAM_BOT=""
TELEGRAM_CHAT_ID=""
MKAUTH_NAME="${MKAUTH_NAME:-}"
USAR_TELEGRAM="sim"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-180}"

# ==========================================================
# ARQUIVOS
# ==========================================================

SCRIPT="/var/check_backup_freeradius.sh"
CONFIG="/etc/default/check_backup_freeradius"
CRON_FILE="/etc/cron.d/check_backup_freeradius"

MONITOR_LOG="/var/log/check_backup_freeradius.log"
CRON_LOG="/var/log/check_backup_freeradius_cron.log"

STATE_DIR="/var/lib/check_backup_freeradius"
LOGROTATE="/etc/logrotate.d/check_backup_freeradius"

TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_ROOT="/root/mkauth-guardian-backups"
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERRO: execute este instalador como root."
    exit 1
fi

# Datacenter: Telegram fixo. Pergunta apenas o nome do MK-AUTH.
HOSTNAME_ATUAL="$(hostname 2>/dev/null || echo mk-auth)"
DEFAULT_NAME="$HOSTNAME_ATUAL"

if [ -r "$CONFIG" ]; then
    OLD_MKAUTH_NAME=""
    # shellcheck disable=SC1090
    . "$CONFIG"
    OLD_MKAUTH_NAME="${MKAUTH_NAME:-}"
    [ -n "$OLD_MKAUTH_NAME" ] && DEFAULT_NAME="$OLD_MKAUTH_NAME"

    # Preserva credenciais e preferencia Telegram existentes no CONFIG.

fi

printf "Nome deste MK-AUTH/VM [%s]: " "$DEFAULT_NAME"
read -r NEW_MKAUTH_NAME
MKAUTH_NAME="${NEW_MKAUTH_NAME:-$DEFAULT_NAME}"

if [ "$USAR_TELEGRAM" = "sim" ]; then
    if [ -z "$TELEGRAM_BOT" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
        echo "ERRO: Telegram está ativado, mas token ou Chat ID estão vazios."
        exit 1
    fi
fi

[ -n "$MKAUTH_NAME" ] || MKAUTH_NAME="$(hostname 2>/dev/null || echo mk-auth)"

case "$COOLDOWN_SECONDS" in
    ''|*[!0-9]*) COOLDOWN_SECONDS="180" ;;
esac

echo
echo "=========================================================="
echo " INSTALAÇÃO COMPLETA MK-AUTH V1.7.1.1 - DATACENTER"
echo " WATCHDOG + MYSQL GUARDIAN + BACKUP GUARDIAN"
echo "=========================================================="
echo
echo "MK-AUTH configurado: $MKAUTH_NAME"
echo "Telegram: $USAR_TELEGRAM"
[ "$USAR_TELEGRAM" = "sim" ] && echo "Chat ID: $TELEGRAM_CHAT_ID"
echo

# ==========================================================
# COMANDOS OBRIGATÓRIOS
# ==========================================================

for CMD in mysql curl timeout stat grep awk sed flock pgrep pkill ss tail wc free; do
    if ! command -v "$CMD" >/dev/null 2>&1; then
        echo "ERRO: comando obrigatório ausente: $CMD"
        exit 1
    fi
done

# ==========================================================
# BACKUPS
# ==========================================================

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_ROOT" "$BACKUP_DIR" 2>/dev/null || true

for ITEM in "$SCRIPT" "$CONFIG" "$CRON_FILE" "$LOGROTATE"; do
    if [ -e "$ITEM" ]; then
        DEST="$BACKUP_DIR$(dirname "$ITEM")"
        mkdir -p "$DEST"
        cp -a "$ITEM" "$DEST/$(basename "$ITEM")"
        echo "Backup criado: $DEST/$(basename "$ITEM")"
    fi
done

# ==========================================================
# DESATIVAR CRONS ANTIGOS
# ==========================================================

echo
echo "Procurando crons antigos..."

CRON_FILES="$(
    {
        [ -f /etc/crontab ] && echo /etc/crontab

        find /etc/cron.d \
            -maxdepth 1 \
            -type f \
            2>/dev/null

        find /var/spool/cron \
            /var/spool/cron/crontabs \
            -maxdepth 2 \
            -type f \
            2>/dev/null
    } | sort -u
)"

while IFS= read -r FILE; do
    [ -n "$FILE" ] || continue
    [ -f "$FILE" ] || continue

    case "$(basename "$FILE")" in
        *.bak-*|*.backup-*|*.old|*.orig|*~) continue ;;
    esac

    # Este cron será recriado abaixo.
    if [ "$FILE" = "$CRON_FILE" ]; then
        continue
    fi

    if grep -Eq \
        '^[[:space:]]*[^#].*check_backup_freeradius\.sh' \
        "$FILE" 2>/dev/null; then

        DEST="$BACKUP_DIR$(dirname "$FILE")"
        mkdir -p "$DEST"
        cp -a "$FILE" "$DEST/$(basename "$FILE")"

        sed -i \
            "/^[[:space:]]*[^#].*check_backup_freeradius\.sh/s|^|# DESATIVADO ${TIMESTAMP}: |" \
            "$FILE"

        echo "Cron antigo desativado em: $FILE"
    fi
done <<EOF
$CRON_FILES
EOF


# ==========================================================
# LIMPEZA DE BACKUPS ANTIGOS DENTRO DE /etc/cron.d
# ==========================================================

mkdir -p "$BACKUP_DIR/etc/cron.d"

find /etc/cron.d -maxdepth 1 -type f \
    \( -name '*.bak-*' -o -name '*.backup-*' -o -name '*.old' -o -name '*.orig' -o -name '*~' \) \
    -print 2>/dev/null |
while IFS= read -r OLD_BAK; do
    [ -f "$OLD_BAK" ] || continue
    BASE="$(basename "$OLD_BAK")"
    DEST="$BACKUP_DIR/etc/cron.d/$BASE"
    N=1
    while [ -e "$DEST" ]; do
        DEST="$BACKUP_DIR/etc/cron.d/${BASE}.${N}"
        N=$((N + 1))
    done
    mv "$OLD_BAK" "$DEST"
    echo "Backup antigo removido de /etc/cron.d: $OLD_BAK -> $DEST"
done

# ==========================================================
# CONFIGURAÇÃO PROTEGIDA
# ==========================================================

{
    printf 'MKAUTH_NAME=%q\n' "$MKAUTH_NAME"
    printf 'USAR_TELEGRAM=%q\n' "$USAR_TELEGRAM"
    printf 'TELEGRAM_BOT=%q\n' "$TELEGRAM_BOT"
    printf 'TELEGRAM_CHAT_ID=%q\n' "$TELEGRAM_CHAT_ID"
    printf 'COOLDOWN_SECONDS=%q\n' "$COOLDOWN_SECONDS"
} > "$CONFIG"

chown root:root "$CONFIG"
chmod 600 "$CONFIG"

# ==========================================================
# DIRETÓRIOS E LOGS
# ==========================================================

mkdir -p "$STATE_DIR"

touch "$MONITOR_LOG"
touch "$CRON_LOG"

chown root:root \
    "$STATE_DIR" \
    "$MONITOR_LOG" \
    "$CRON_LOG"

chmod 750 "$STATE_DIR"
chmod 640 "$MONITOR_LOG" "$CRON_LOG"

# ==========================================================
# SCRIPT DO MONITOR
# ==========================================================

cat > "$SCRIPT" <<'MONITOR'
#!/bin/bash

set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

CONFIG="/etc/default/check_backup_freeradius"

RADIUS_LOG="/var/log/freeradius/radius.log"
MONITOR_LOG="/var/log/check_backup_freeradius.log"

STATE_DIR="/var/lib/check_backup_freeradius"

OFFSET_FILE="$STATE_DIR/radius.offset"
INODE_FILE="$STATE_DIR/radius.inode"
COOLDOWN_FILE="$STATE_DIR/last_successful_recovery"

MESSAGE_ID_FILE="$STATE_DIR/telegram_message_id"
INCIDENT_START_FILE="$STATE_DIR/incident_start"
INCIDENT_REASON_FILE="$STATE_DIR/incident_reason"

LOCK_FILE="/var/run/check_backup_freeradius.lock"

MKAUTH_NAME="$(hostname)"
USAR_TELEGRAM="sim"
TELEGRAM_BOT=""
TELEGRAM_CHAT_ID=""
COOLDOWN_SECONDS="180"

if [ -r "$CONFIG" ]; then
    # shellcheck disable=SC1090
    . "$CONFIG"
fi

PHRASES=(
    "MySQL error: Can't connect to local MySQL server through socket"
    "Can't connect to local MySQL server through socket"
    "Couldn't connect to MySQL server"
    "Failed to reconnect"
    "no free connections are available"
    "rlm_sql_mysql: Couldn't connect"
    "rlm_sql_mysql: MySQL error"
    "Error: Something is blocking the server."
)

mkdir -p "$STATE_DIR"
touch "$MONITOR_LOG"

exec 9>"$LOCK_FILE"

if command -v flock >/dev/null 2>&1; then
    flock -n 9 || exit 0
fi

log() {
    printf '%s - %s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$*" >> "$MONITOR_LOG"
}

compact_response() {
    printf '%s' "$1" |
        tr '\r\n' '  ' |
        cut -c1-500
}

detect_mysql_service() {
    local name=""

    for name in mysql mariadb mysqld; do
        if [ -x "/etc/init.d/$name" ]; then
            printf '%s\n' "$name"
            return 0
        fi

        if command -v systemctl >/dev/null 2>&1 &&
           systemctl list-unit-files 2>/dev/null |
           grep -q "^${name}\.service"; then

            printf '%s\n' "$name"
            return 0
        fi
    done

    printf '%s\n' "mysql"
}

detect_radius_service() {
    local name=""

    for name in freeradius radiusd; do
        if [ -x "/etc/init.d/$name" ]; then
            printf '%s\n' "$name"
            return 0
        fi

        if command -v systemctl >/dev/null 2>&1 &&
           systemctl list-unit-files 2>/dev/null |
           grep -q "^${name}\.service"; then

            printf '%s\n' "$name"
            return 0
        fi
    done

    printf '%s\n' "freeradius"
}

MYSQL_SERVICE="$(detect_mysql_service)"
RADIUS_SERVICE="$(detect_radius_service)"

service_action() {
    local service_name="$1"
    local action="$2"

    if command -v systemctl >/dev/null 2>&1 &&
       [ -d /run/systemd/system ]; then

        systemctl "$action" "$service_name"
        return $?
    fi

    if command -v service >/dev/null 2>&1; then
        service "$service_name" "$action"
        return $?
    fi

    if [ -x "/etc/init.d/$service_name" ]; then
        "/etc/init.d/$service_name" "$action"
        return $?
    fi

    return 1
}

mysql_query() {
    if [ -r /etc/mysql/debian.cnf ]; then
        mysql \
            --defaults-file=/etc/mysql/debian.cnf \
            --connect-timeout=4 \
            --batch \
            --skip-column-names \
            -e "SELECT 1" 2>/dev/null
        return $?
    fi

    if [ -r /root/.my.cnf ]; then
        mysql \
            --defaults-file=/root/.my.cnf \
            --connect-timeout=4 \
            --batch \
            --skip-column-names \
            -e "SELECT 1" 2>/dev/null
        return $?
    fi

    mysql \
        -uroot \
        --no-defaults \
        --connect-timeout=4 \
        --batch \
        --skip-column-names \
        -e "SELECT 1" 2>/dev/null
}

mysql_ok() {
    local result=""

    command -v mysql >/dev/null 2>&1 || return 1

    if command -v timeout >/dev/null 2>&1; then
        result="$(
            timeout 10 bash -c '
                if [ -r /etc/mysql/debian.cnf ]; then
                    mysql \
                        --defaults-file=/etc/mysql/debian.cnf \
                        --connect-timeout=4 \
                        --batch \
                        --skip-column-names \
                        -e "SELECT 1" 2>/dev/null
                elif [ -r /root/.my.cnf ]; then
                    mysql \
                        --defaults-file=/root/.my.cnf \
                        --connect-timeout=4 \
                        --batch \
                        --skip-column-names \
                        -e "SELECT 1" 2>/dev/null
                else
                    mysql \
                        -uroot \
                        --no-defaults \
                        --connect-timeout=4 \
                        --batch \
                        --skip-column-names \
                        -e "SELECT 1" 2>/dev/null
                fi
            ' 2>/dev/null
        )"
    else
        result="$(mysql_query)"
    fi

    [ "$result" = "1" ]
}

radius_process_ok() {
    pgrep -x freeradius >/dev/null 2>&1 ||
    pgrep -x radiusd >/dev/null 2>&1
}

radius_port_ok() {
    if command -v ss >/dev/null 2>&1; then
        ss -H -lun 2>/dev/null |
            awk '{print $4}' |
            grep -Eq ':1812$'

        return $?
    fi

    if command -v netstat >/dev/null 2>&1; then
        netstat -lun 2>/dev/null |
            awk '{print $4}' |
            grep -Eq ':1812$'

        return $?
    fi

    return 0
}

radius_ok() {
    radius_process_ok && radius_port_ok
}

wait_mysql() {
    local elapsed=0

    while [ "$elapsed" -lt 60 ]; do
        if mysql_ok; then
            return 0
        fi

        sleep 3
        elapsed=$((elapsed + 3))
    done

    return 1
}

wait_radius() {
    local elapsed=0

    while [ "$elapsed" -lt 30 ]; do
        if radius_ok; then
            return 0
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    return 1
}

telegram_configured() {
    [ "$USAR_TELEGRAM" = "sim" ] &&
    [ -n "$TELEGRAM_BOT" ] &&
    [ -n "$TELEGRAM_CHAT_ID" ]
}

send_plain_telegram() {
    local message="$1"
    local response=""

    telegram_configured || return 0

    response="$(
        timeout 20 curl -sS \
            -X POST \
            "https://api.telegram.org/bot${TELEGRAM_BOT}/sendMessage" \
            --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
            --data-urlencode "text=$message" \
            2>&1
    )"

    if printf '%s' "$response" |
       grep -q '"ok":true'; then

        log "Mensagem enviada ao Telegram com sucesso."
        return 0
    fi

    log "ERRO Telegram: $(compact_response "$response")"
    return 1
}

clear_incident_state() {
    rm -f \
        "$MESSAGE_ID_FILE" \
        "$INCIDENT_START_FILE" \
        "$INCIDENT_REASON_FILE"
}

send_incident_alert() {
    local reason="$1"
    local response=""
    local message_id=""
    local start_epoch=""

    telegram_configured || return 0

    start_epoch="$(date +%s)"

    response="$(
        timeout 20 curl -sS \
            -X POST \
            "https://api.telegram.org/bot${TELEGRAM_BOT}/sendMessage" \
            --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
            --data-urlencode "text=🚨 ALERTA MK-AUTH \"$MKAUTH_NAME\"

Status: 🔴 PROBLEMA ATIVO

MK-AUTH/VM: $MKAUTH_NAME
Servidor Linux: $(hostname)

📝 Erro detectado:
$reason

🚨 Início do problema:
$(date '+%d/%m/%Y %H:%M:%S')

A recuperação automática do MySQL e FreeRADIUS foi iniciada." \
            2>&1
    )"

    message_id="$(
        printf '%s' "$response" |
            grep -o '"message_id":[0-9][0-9]*' |
            head -n 1 |
            cut -d: -f2
    )"

    if printf '%s' "$response" |
       grep -q '"ok":true' &&
       [ -n "$message_id" ]; then

        printf '%s\n' "$message_id" > "$MESSAGE_ID_FILE"
        printf '%s\n' "$start_epoch" > "$INCIDENT_START_FILE"
        printf '%s\n' "$reason" > "$INCIDENT_REASON_FILE"

        chmod 600 \
            "$MESSAGE_ID_FILE" \
            "$INCIDENT_START_FILE" \
            "$INCIDENT_REASON_FILE"

        log "Alerta enviado ao Telegram. message_id=$message_id"
        return 0
    fi

    log "ERRO ao enviar alerta: $(compact_response "$response")"
    return 1
}

format_duration() {
    local total="$1"
    local hours=0
    local minutes=0
    local seconds=0

    case "$total" in
        ''|*[!0-9]*)
            total=0
            ;;
    esac

    hours=$((total / 3600))
    minutes=$(((total % 3600) / 60))
    seconds=$((total % 60))

    if [ "$hours" -gt 0 ]; then
        printf '%dh %dm %ds' \
            "$hours" "$minutes" "$seconds"
    elif [ "$minutes" -gt 0 ]; then
        printf '%dm %ds' \
            "$minutes" "$seconds"
    else
        printf '%ds' "$seconds"
    fi
}

edit_incident_as_recovered() {
    local message_id=""
    local incident_start=""
    local reason=""
    local recovered_epoch=""
    local duration_seconds=""
    local duration_text=""
    local start_text=""
    local recovered_text=""
    local event_emoji=""
    local event_name=""
    local response=""

    telegram_configured || return 0

    [ -r "$MESSAGE_ID_FILE" ] || return 1
    [ -r "$INCIDENT_START_FILE" ] || return 1

    read -r message_id < "$MESSAGE_ID_FILE"
    read -r incident_start < "$INCIDENT_START_FILE"

    if [ -r "$INCIDENT_REASON_FILE" ]; then
        reason="$(cat "$INCIDENT_REASON_FILE")"
    else
        reason="Erro de comunicação entre MySQL e FreeRADIUS."
    fi

    case "$message_id" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac

    case "$incident_start" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac

    recovered_epoch="$(date +%s)"
    duration_seconds=$((recovered_epoch - incident_start))

    if [ "$duration_seconds" -lt 0 ]; then
        duration_seconds=0
    fi

    duration_text="$(format_duration "$duration_seconds")"

    start_text="$(
        date -d "@$incident_start" \
            '+%d/%m/%Y %H:%M:%S' 2>/dev/null
    )"

    if [ -z "$start_text" ]; then
        start_text="Horário não disponível"
    fi

    recovered_text="$(date '+%d/%m/%Y %H:%M:%S')"

    case "$reason" in
        *"Can't connect to local MySQL server"*|\
        *"Couldn't connect to MySQL server"*)

            event_emoji="🔌"
            event_name="Falha de conexão entre FreeRADIUS e MySQL"
            ;;

        *"Failed to reconnect"*)

            event_emoji="🔄"
            event_name="Falha de reconexão SQL do FreeRADIUS"
            ;;

        *"no free connections are available"*)

            event_emoji="🚫"
            event_name="Esgotamento das conexões SQL do FreeRADIUS"
            ;;

        *"Something is blocking the server"*)

            event_emoji="🧱"
            event_name="Bloqueio ou saturação do FreeRADIUS"
            ;;

        *"SELECT 1"*)

            event_emoji="🩺"
            event_name="MySQL sem resposta ao teste de saúde"
            ;;

        *)

            event_emoji="⚠️"
            event_name="Falha crítica no MySQL/FreeRADIUS"
            ;;
    esac

    response="$(
        timeout 20 curl -sS \
            -X POST \
            "https://api.telegram.org/bot${TELEGRAM_BOT}/editMessageText" \
            --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
            --data-urlencode "message_id=$message_id" \
            --data-urlencode "text=✅ MK-AUTH RECUPERADO \"$MKAUTH_NAME\"

Status: 🟢 INCIDENTE RESOLVIDO

MK-AUTH/VM: $MKAUTH_NAME
Servidor Linux: $(hostname)

$event_emoji Evento:
$event_name

📝 Erro detectado:
$reason

🚨 Início do problema:
$start_text

✅ Recuperado em:
$recovered_text

⏱️ Duração:
$duration_text

🗄️ MySQL: respondendo ao SELECT 1
📡 FreeRADIUS: funcionando
🔓 Porta UDP 1812: ativa" \
            2>&1
    )"

    if printf '%s' "$response" |
       grep -q '"ok":true'; then

        log "Mensagem original editada como recuperada."
        clear_incident_state
        return 0
    fi

    log "ERRO ao editar Telegram: $(compact_response "$response")"
    return 1
}

send_recovery_fallback() {
    local reason="$1"

    send_plain_telegram "✅ MK-AUTH RECUPERADO \"$MKAUTH_NAME\"

Status: 🟢 INCIDENTE RESOLVIDO

MK-AUTH/VM: $MKAUTH_NAME
Servidor Linux: $(hostname)

⚠️ Evento:
Falha crítica no MySQL/FreeRADIUS

📝 Erro original:
$reason

✅ Recuperado em:
$(date '+%d/%m/%Y %H:%M:%S')

🗄️ MySQL: respondendo ao SELECT 1
📡 FreeRADIUS: funcionando
🔓 Porta UDP 1812: ativa" || true
}

cooldown_active() {
    local now=""
    local last=""
    local difference=""

    [ -r "$COOLDOWN_FILE" ] || return 1

    read -r last < "$COOLDOWN_FILE"

    case "$last" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac

    case "$COOLDOWN_SECONDS" in
        ''|*[!0-9]*)
            COOLDOWN_SECONDS=180
            ;;
    esac

    now="$(date +%s)"
    difference=$((now - last))

    [ "$difference" -ge 0 ] &&
    [ "$difference" -lt "$COOLDOWN_SECONDS" ]
}

mark_recovery() {
    date +%s > "$COOLDOWN_FILE"
    chmod 600 "$COOLDOWN_FILE"
}

recover_mysql_radius() {
    local reason="$1"
    exec 8>/var/run/mkauth-guardian-global-recovery.lock
    if ! flock -n 8; then
        log "Outra recuperacao em andamento; watchdog nao reiniciara servicos."
        return 0
    fi

    if [ "${GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY:-nao}" != "sim" ]; then
        log "MODO SEGURO: falha detectada, restart automatico MySQL/Radius bloqueado."
        return 1
    fi
    log "======================================================"
    log "ERRO CRÍTICO DETECTADO"
    log "MK-AUTH: $MKAUTH_NAME"
    log "Motivo completo: $reason"
    log "Serviço MySQL detectado: $MYSQL_SERVICE"
    log "Serviço FreeRADIUS detectado: $RADIUS_SERVICE"
    log "Iniciando recuperação automática."

    clear_incident_state
    send_incident_alert "$reason" || true

    log "Parando o FreeRADIUS antes da recuperação."

    service_action "$RADIUS_SERVICE" stop \
        >> "$MONITOR_LOG" 2>&1 || true

    log "Reiniciando o serviço $MYSQL_SERVICE."

    if ! service_action "$MYSQL_SERVICE" restart \
        >> "$MONITOR_LOG" 2>&1; then

        log "ERRO: não foi possível reiniciar o MySQL."

        service_action "$RADIUS_SERVICE" start \
            >> "$MONITOR_LOG" 2>&1 || true

        send_plain_telegram "❌ MYSQL NÃO RECUPERADO \"$MKAUTH_NAME\"

Não foi possível reiniciar o serviço $MYSQL_SERVICE.

Servidor: $(hostname)
Data: $(date '+%d/%m/%Y %H:%M:%S')" || true

        return 1
    fi

    if ! wait_mysql; then
        log "ERRO: MySQL não respondeu após 60 segundos."

        service_action "$RADIUS_SERVICE" start \
            >> "$MONITOR_LOG" 2>&1 || true

        send_plain_telegram "❌ MYSQL NÃO RECUPERADO \"$MKAUTH_NAME\"

O MySQL não respondeu ao SELECT 1 após 60 segundos.

Servidor: $(hostname)
Data: $(date '+%d/%m/%Y %H:%M:%S')" || true

        return 1
    fi

    log "MySQL está respondendo corretamente ao SELECT 1."
    log "Iniciando o serviço $RADIUS_SERVICE."

    if ! service_action "$RADIUS_SERVICE" start \
        >> "$MONITOR_LOG" 2>&1; then

        log "ERRO: não foi possível iniciar o FreeRADIUS."

        send_plain_telegram "❌ FREERADIUS NÃO INICIOU \"$MKAUTH_NAME\"

O MySQL voltou, mas o FreeRADIUS não iniciou.

Servidor: $(hostname)
Data: $(date '+%d/%m/%Y %H:%M:%S')" || true

        return 1
    fi

    if ! wait_radius; then
        log "ERRO: FreeRADIUS não confirmou processo/porta 1812."

        send_plain_telegram "⚠️ RECUPERAÇÃO PARCIAL \"$MKAUTH_NAME\"

MySQL: respondendo
FreeRADIUS: não confirmou processo ou porta UDP 1812

Servidor: $(hostname)
Data: $(date '+%d/%m/%Y %H:%M:%S')" || true

        return 1
    fi

    mark_recovery

    log "RECUPERAÇÃO CONCLUÍDA."
    log "MySQL: respondendo."
    log "FreeRADIUS: processo ativo e porta UDP 1812 aberta."
    log "Cooldown ativado por $COOLDOWN_SECONDS segundos."
    log "======================================================"

    if telegram_configured; then
        if ! edit_incident_as_recovered; then
            log "Não foi possível editar o alerta original."
            log "Enviando mensagem nova de recuperação."

            send_recovery_fallback "$reason"
            clear_incident_state
        fi
    fi

    return 0
}

CURRENT_INODE=""
CURRENT_SIZE="0"
LAST_INODE=""
LAST_OFFSET="0"
NEW_LINES=""
FOUND_PHRASE=""

if [ -f "$RADIUS_LOG" ]; then
    CURRENT_INODE="$(
        stat -c '%i' "$RADIUS_LOG" 2>/dev/null
    )"

    CURRENT_SIZE="$(
        stat -c '%s' "$RADIUS_LOG" 2>/dev/null
    )"

    case "$CURRENT_SIZE" in
        ''|*[!0-9]*)
            CURRENT_SIZE=0
            ;;
    esac

    if [ -r "$INODE_FILE" ]; then
        read -r LAST_INODE < "$INODE_FILE"
    fi

    if [ -r "$OFFSET_FILE" ]; then
        read -r LAST_OFFSET < "$OFFSET_FILE"
    fi

    case "$LAST_OFFSET" in
        ''|*[!0-9]*)
            LAST_OFFSET=0
            ;;
    esac

    if [ ! -f "$OFFSET_FILE" ]; then
        printf '%s\n' "$CURRENT_INODE" > "$INODE_FILE"
        printf '%s\n' "$CURRENT_SIZE" > "$OFFSET_FILE"

        log "Monitor iniciado."
        log "MK-AUTH: $MKAUTH_NAME"
        log "Posição inicial do radius.log: $CURRENT_SIZE bytes."
    else
        if [ "$CURRENT_INODE" != "$LAST_INODE" ] ||
           [ "$CURRENT_SIZE" -lt "$LAST_OFFSET" ]; then

            LAST_OFFSET=0
        fi

        if [ "$CURRENT_SIZE" -gt "$LAST_OFFSET" ]; then
            START_BYTE=$((LAST_OFFSET + 1))

            NEW_LINES="$(
                tail -c +"$START_BYTE" \
                    "$RADIUS_LOG" 2>/dev/null
            )"
        fi

        printf '%s\n' "$CURRENT_INODE" > "$INODE_FILE"
        printf '%s\n' "$CURRENT_SIZE" > "$OFFSET_FILE"

        for PHRASE in "${PHRASES[@]}"; do
            MATCH="$(
                printf '%s\n' "$NEW_LINES" |
                    grep -F -- "$PHRASE" |
                    head -n 1
            )"

            if [ -n "$MATCH" ]; then
                FOUND_PHRASE="$MATCH"
                break
            fi
        done
    fi
else
    log "AVISO: radius.log não encontrado."
fi

# MySQL realmente indisponível ignora o cooldown.
if ! mysql_ok; then
    if [ -n "$FOUND_PHRASE" ]; then
        recover_mysql_radius "$FOUND_PHRASE"
    else
        recover_mysql_radius \
            "MySQL não respondeu ao comando SELECT 1."
    fi

    exit $?
fi

# Erro novo no log com banco respondendo.
if [ -n "$FOUND_PHRASE" ]; then
    if cooldown_active; then
        log "Erro SQL encontrado durante o cooldown."
        log "Reinício ignorado porque o MySQL está respondendo."
        log "Erro: $FOUND_PHRASE"
        exit 0
    fi

    recover_mysql_radius "$FOUND_PHRASE"
    exit $?
fi

exit 0
MONITOR

chown root:root "$SCRIPT"
chmod 700 "$SCRIPT"

# ==========================================================
# VALIDAR MONITOR
# ==========================================================

if ! bash -n "$SCRIPT"; then
    echo
    echo "ERRO: falha de sintaxe no monitor."
    exit 1
fi

# ==========================================================
# CRON A CADA 30 SEGUNDOS
# ==========================================================

cat > "$CRON_FILE" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

* * * * * root echo "\$(date '+\%F \%T') execução imediata" >> $CRON_LOG; timeout 120 $SCRIPT >> $CRON_LOG 2>&1
* * * * * root sleep 30; echo "\$(date '+\%F \%T') execução após 30 segundos" >> $CRON_LOG; timeout 120 $SCRIPT >> $CRON_LOG 2>&1
EOF

chown root:root "$CRON_FILE"
chmod 644 "$CRON_FILE"

# ==========================================================
# LOGROTATE
# ==========================================================

cat > "$LOGROTATE" <<EOF
$MONITOR_LOG $CRON_LOG {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    create 0640 root root
}
EOF

chown root:root "$LOGROTATE"
chmod 644 "$LOGROTATE"

# ==========================================================
# LIMPAR ESTADOS ANTERIORES
# ==========================================================

rm -f \
    "$STATE_DIR/radius.offset" \
    "$STATE_DIR/radius.inode" \
    "$STATE_DIR/last_successful_recovery" \
    "$STATE_DIR/telegram_message_id" \
    "$STATE_DIR/incident_start" \
    "$STATE_DIR/incident_reason" \
    /var/run/check_backup_freeradius.lock

# ==========================================================
# REINICIAR CRON
# ==========================================================

if command -v systemctl >/dev/null 2>&1 &&
   [ -d /run/systemd/system ]; then

    systemctl restart cron 2>/dev/null ||
    systemctl restart crond 2>/dev/null ||
    true
else
    service cron restart 2>/dev/null ||
    service crond restart 2>/dev/null ||
    true
fi

# Inicializa a posição de leitura.
"$SCRIPT"

# ==========================================================
# TESTAR TELEGRAM
# ==========================================================

echo
if [ "$USAR_TELEGRAM" = "sim" ]; then
    echo "Testando Telegram..."

TELEGRAM_RESPONSE="$(
    timeout 20 curl -sS \
        -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT}/sendMessage" \
        --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
        --data-urlencode "text=✅ MONITOR MK-AUTH INSTALADO

MK-AUTH/VM: $MKAUTH_NAME
Servidor Linux: $(hostname)

Monitor MySQL + FreeRADIUS instalado com sucesso.
Verificação automática: a cada 30 segundos.

Data: $(date '+%d/%m/%Y %H:%M:%S')" \
        2>&1
)"

if printf '%s' "$TELEGRAM_RESPONSE" |
   grep -q '"ok":true'; then

    echo "Telegram: OK"
else
    echo "Telegram: ERRO"
    echo "$TELEGRAM_RESPONSE"
fi
fi


# ==========================================================
# RESULTADO
# ==========================================================

echo
echo "=========================================================="
echo " INSTALAÇÃO CONCLUÍDA"
echo "=========================================================="
echo
echo "MK-AUTH:"
echo "  $MKAUTH_NAME"
echo
echo "Monitor:"
echo "  $SCRIPT"
echo
echo "Configuração protegida:"
echo "  $CONFIG"
echo
echo "Cron:"
echo "  $CRON_FILE"
echo
echo "Log de eventos:"
echo "  $MONITOR_LOG"
echo
echo "Log das execuções:"
echo "  $CRON_LOG"
echo
echo "Entradas ativas encontradas:"

{
    [ -f /etc/crontab ] && grep -nE '^[[:space:]]*[^#].*check_backup_freeradius\.sh' /etc/crontab 2>/dev/null || true

    find /etc/cron.d -maxdepth 1 -type f 2>/dev/null |
    while IFS= read -r F; do
        case "$(basename "$F")" in
            *.bak-*|*.backup-*|*.old|*.orig|*~) continue ;;
        esac
        grep -nH -E '^[[:space:]]*[^#].*check_backup_freeradius\.sh' "$F" 2>/dev/null || true
    done

    find /var/spool/cron /var/spool/cron/crontabs -maxdepth 2 -type f 2>/dev/null |
    while IFS= read -r F; do
        grep -nH -E '^[[:space:]]*[^#].*check_backup_freeradius\.sh' "$F" 2>/dev/null || true
    done
}

echo
echo "Permissão da configuração:"
ls -l "$CONFIG"

echo
echo "Acompanhar execuções:"
echo "  tail -F $CRON_LOG"
echo
echo "Acompanhar falhas e recuperações:"
echo "  tail -F $MONITOR_LOG"
echo

# ==========================================================
# ETAPA 2 — APLICAR GUARDIANS V1.4 + V1.6
# ==========================================================

echo
echo "=========================================================="
echo " INSTALANDO GUARDIANS COMPLEMENTARES"
echo "=========================================================="
echo

PATCH_TEMP="/root/.mkauth-patch-v1.6-$$.sh"
cat > "$PATCH_TEMP" <<'PATCH_EMBUTIDO'
#!/bin/bash
set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

PATCH_VERSION="1.8-rc1"
CONFIG="/etc/default/check_backup_freeradius"
WATCHDOG="/var/check_backup_freeradius.sh"

MYSQL_GUARDIAN="/usr/local/sbin/mkauth_mysql_radius_guardian.sh"
MYSQL_CRON="/etc/cron.d/mkauth_mysql_radius_guardian"
MYSQL_LOG="/var/log/mkauth_mysql_radius_guardian.log"
MYSQL_RUN_LOG="/var/log/mkauth_mysql_radius_guardian_cron.log"
MYSQL_STATE="/var/lib/mkauth_mysql_radius_guardian"

BACKUP_GUARDIAN="/usr/local/sbin/mkauth_backup_guardian.sh"
BACKUP_CRON="/etc/cron.d/mkauth_backup_guardian"
BACKUP_LOG="/var/log/mkauth_backup_guardian.log"
BACKUP_RUN_LOG="/var/log/mkauth_backup_guardian_cron.log"
BACKUP_STATE="/var/lib/mkauth_backup_guardian"

SQL_FILE="/opt/mk-auth/mysql/up_database.sql"
STAMP="$(date '+%Y%m%d-%H%M%S')"
PATCH_BACKUP_DIR="/root/mkauth-guardian-backups/$STAMP"
mkdir -p "$PATCH_BACKUP_DIR"
chmod 700 /root/mkauth-guardian-backups "$PATCH_BACKUP_DIR" 2>/dev/null || true
CRON_WAS_STOPPED=0

echo
echo "======================================================"
echo " COMPONENTES COMPLEMENTARES MK-AUTH V1.7.1"
echo " WATCHDOG + MYSQL/RADIUS GUARDIAN V1.7 + BACKUP GUARDIAN V1.6"
echo "======================================================"
echo

if [ "$(id -u)" -ne 0 ]; then
    echo "ERRO: execute como root."
    exit 1
fi

for CMD in mysql timeout pgrep pkill flock ss grep awk sed stat; do
    if ! command -v "$CMD" >/dev/null 2>&1; then
        echo "ERRO: comando obrigatório ausente: $CMD"
        exit 1
    fi
done

if [ ! -f "$WATCHDOG" ]; then
    echo "ERRO: monitor principal não encontrado:"
    echo "  $WATCHDOG"
    echo
    echo "Este patch é somente para máquinas que já receberam o instalador principal."
    exit 1
fi

if [ ! -r "$CONFIG" ]; then
    echo "ERRO: configuração protegida não encontrada:"
    echo "  $CONFIG"
    exit 1
fi

MKAUTH_NAME="$(hostname 2>/dev/null || echo mk-auth)"
USAR_TELEGRAM="nao"
TELEGRAM_BOT=""
TELEGRAM_CHAT_ID=""
. "$CONFIG"

echo "MK-AUTH preservado: ${MKAUTH_NAME:-$(hostname)}"
echo "Telegram: ${USAR_TELEGRAM:-nao}"
echo

mysql_installer() {
    if [ -r /etc/mysql/debian.cnf ]; then
        timeout 15 mysql --defaults-file=/etc/mysql/debian.cnf \
            --connect-timeout=5 --batch --skip-column-names "$@" 2>/dev/null
        return $?
    fi
    if [ -r /root/.my.cnf ]; then
        timeout 15 mysql --defaults-file=/root/.my.cnf \
            --connect-timeout=5 --batch --skip-column-names "$@" 2>/dev/null
        return $?
    fi
    timeout 15 mysql -uroot --no-defaults \
        --connect-timeout=5 --batch --skip-column-names "$@" 2>/dev/null
}

if [ "$(mysql_installer -e "SELECT 1;" 2>/dev/null)" != "1" ]; then
    echo "ERRO: MySQL não respondeu ao SELECT 1."
    echo "Não vou instalar o patch enquanto o banco estiver indisponível."
    exit 1
fi

restart_cron() {
    service cron start 2>/dev/null ||
    service cron restart 2>/dev/null ||
    systemctl restart cron 2>/dev/null ||
    true
}

cleanup_install() {
    if [ "$CRON_WAS_STOPPED" -eq 1 ]; then
        restart_cron
    fi
}
trap cleanup_install EXIT INT TERM

echo "Parando cron temporariamente..."
service cron stop 2>/dev/null || systemctl stop cron 2>/dev/null || true
CRON_WAS_STOPPED=1

pkill -TERM -f '/usr/local/sbin/mkauth_mysql_radius_guardian\.sh' 2>/dev/null || true
pkill -TERM -f '/usr/local/sbin/mkauth_backup_guardian\.sh' 2>/dev/null || true
sleep 2

for ITEM in "$MYSQL_GUARDIAN" "$MYSQL_CRON" "$BACKUP_GUARDIAN" "$BACKUP_CRON"; do
    if [ -e "$ITEM" ]; then
        DEST="$PATCH_BACKUP_DIR$(dirname "$ITEM")"
        mkdir -p "$DEST"
        cp -a "$ITEM" "$DEST/$(basename "$ITEM")"
        echo "Backup criado: $DEST/$(basename "$ITEM")"
    fi
done

mkdir -p "$MYSQL_STATE" "$BACKUP_STATE"
touch "$MYSQL_LOG" "$MYSQL_RUN_LOG" "$BACKUP_LOG" "$BACKUP_RUN_LOG"

chown root:root \
    "$MYSQL_STATE" "$BACKUP_STATE" \
    "$MYSQL_LOG" "$MYSQL_RUN_LOG" \
    "$BACKUP_LOG" "$BACKUP_RUN_LOG"

chmod 750 "$MYSQL_STATE" "$BACKUP_STATE"
chmod 640 "$MYSQL_LOG" "$MYSQL_RUN_LOG" "$BACKUP_LOG" "$BACKUP_RUN_LOG"

cat > "$MYSQL_GUARDIAN" <<'GUARDIAN17'
#!/bin/bash
set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

GUARDIAN_VERSION="1.8-rc1"

CONFIG="/etc/default/check_backup_freeradius"
LOG="/var/log/mkauth_mysql_radius_guardian.log"
STATE_DIR="/var/lib/mkauth_mysql_radius_guardian"
LOCK_FILE="/var/run/mkauth_mysql_radius_guardian.lock"

FAIL_START_FILE="$STATE_DIR/mysql_fail_start"
LAST_RECOVERY_FILE="$STATE_DIR/last_recovery"
MESSAGE_ID_FILE="$STATE_DIR/message_id"
INCIDENT_START_FILE="$STATE_DIR/incident_start"

QUEUE_OFFSET_FILE="$STATE_DIR/queue_log_offset"
QUEUE_INODE_FILE="$STATE_DIR/queue_log_inode"
QUEUE_BAD_SAMPLES_FILE="$STATE_DIR/queue_bad_samples"
QUEUE_FIRST_BAD_FILE="$STATE_DIR/queue_first_bad"

WAIT_AUTO_RECOVERY="90"
MYSQL_START_TIMEOUT="150"
COOLDOWN_SECONDS="300"

# Fila funcionalmente travada:
# 10+ erros novos em uma amostra e 2 amostras consecutivas.
QUEUE_MIN_ERRORS="10"
QUEUE_CONFIRM_SAMPLES="2"
QUEUE_POST_RECOVERY_WAIT="15"

INCIDENT_ROOT="/root/mkauth-guardian-incidentes"

MKAUTH_NAME="$(hostname 2>/dev/null || echo mk-auth)"
USAR_TELEGRAM="nao"
TELEGRAM_BOT=""
TELEGRAM_CHAT_ID=""

[ -r "$CONFIG" ] && . "$CONFIG"

mkdir -p "$STATE_DIR" "$INCIDENT_ROOT"
touch "$LOG"

exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

log() {
    printf '%s - %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"
}

compact() {
    printf '%s' "$1" | tr '\r\n' '  ' | cut -c1-500
}

mysql_exec() {
    if [ -r /etc/mysql/debian.cnf ]; then
        timeout 12 mysql \
            --defaults-file=/etc/mysql/debian.cnf \
            --connect-timeout=4 \
            --batch \
            --skip-column-names \
            "$@" 2>/dev/null
        return $?
    fi

    if [ -r /root/.my.cnf ]; then
        timeout 12 mysql \
            --defaults-file=/root/.my.cnf \
            --connect-timeout=4 \
            --batch \
            --skip-column-names \
            "$@" 2>/dev/null
        return $?
    fi

    timeout 12 mysql \
        -uroot \
        --no-defaults \
        --connect-timeout=4 \
        --batch \
        --skip-column-names \
        "$@" 2>/dev/null
}

mysql_ok() {
    [ "$(mysql_exec -e "SELECT 1;" 2>/dev/null)" = "1" ]
}

mysql_service() {
    local s=""
    for s in mariadb mysql mysqld; do
        if [ -x "/etc/init.d/$s" ]; then
            printf '%s\n' "$s"
            return 0
        fi
    done
    printf '%s\n' "mysql"
}

radius_service() {
    if [ -x /etc/init.d/freeradius ]; then
        printf '%s\n' "freeradius"
    elif [ -x /etc/init.d/radiusd ]; then
        printf '%s\n' "radiusd"
    else
        printf '%s\n' "freeradius"
    fi
}

radius_log_file() {
    if [ -f /var/log/freeradius/radius.log ]; then
        printf '%s\n' "/var/log/freeradius/radius.log"
    elif [ -f /var/log/radius/radius.log ]; then
        printf '%s\n' "/var/log/radius/radius.log"
    else
        return 1
    fi
}

radius_process_ok() {
    pgrep -x freeradius >/dev/null 2>&1 ||
    pgrep -x radiusd >/dev/null 2>&1
}

radius_port_ok() {
    ss -H -lun 2>/dev/null |
        awk '{print $4}' |
        grep -Eq '(^|:)1812$'
}

radius_ok() {
    radius_process_ok && radius_port_ok
}

wait_mysql() {
    local limit="$1"
    local elapsed=0

    while [ "$elapsed" -lt "$limit" ]; do
        mysql_ok && return 0
        sleep 2
        elapsed=$((elapsed + 2))
    done

    return 1
}

wait_radius() {
    local elapsed=0

    while [ "$elapsed" -lt 60 ]; do
        radius_ok && return 0
        sleep 2
        elapsed=$((elapsed + 2))
    done

    return 1
}

telegram_ok() {
    [ "${USAR_TELEGRAM:-nao}" = "sim" ] &&
    [ -n "${TELEGRAM_BOT:-}" ] &&
    [ -n "${TELEGRAM_CHAT_ID:-}" ] &&
    command -v curl >/dev/null 2>&1
}

telegram_simple() {
    local text="$1"

    telegram_ok || return 0

    timeout 20 curl -sS \
        -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT}/sendMessage" \
        --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
        --data-urlencode "text=$text" \
        >/dev/null 2>&1 || true
}

format_duration() {
    local total="$1"
    local h=0
    local m=0
    local s=0

    case "$total" in
        ''|*[!0-9]*) total=0 ;;
    esac

    h=$((total / 3600))
    m=$(((total % 3600) / 60))
    s=$((total % 60))

    if [ "$h" -gt 0 ]; then
        printf '%dh %dm %ds' "$h" "$m" "$s"
    elif [ "$m" -gt 0 ]; then
        printf '%dm %ds' "$m" "$s"
    else
        printf '%ds' "$s"
    fi
}

send_alert() {
    local detail="$1"
    local response=""
    local message_id=""
    local start_epoch=""

    telegram_ok || return 0

    start_epoch="$(date +%s)"

    response="$(
        timeout 20 curl -sS \
            -X POST \
            "https://api.telegram.org/bot${TELEGRAM_BOT}/sendMessage" \
            --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
            --data-urlencode "text=🚨 ALERTA MK-AUTH \"$MKAUTH_NAME\"

Status: 🔴 PROBLEMA ATIVO

🗄️ Evento:
Falha de conexão com MySQL/MariaDB

📝 Detalhes:
$detail

🚨 Início:
$(date '+%d/%m/%Y %H:%M:%S')

O Guardian v1.7 está acompanhando a recuperação." \
            2>&1
    )"

    message_id="$(
        printf '%s' "$response" |
            grep -o '"message_id":[0-9][0-9]*' |
            head -n1 |
            cut -d: -f2
    )"

    if printf '%s' "$response" | grep -q '"ok":true' &&
       [ -n "$message_id" ]; then

        printf '%s\n' "$message_id" > "$MESSAGE_ID_FILE"
        printf '%s\n' "$start_epoch" > "$INCIDENT_START_FILE"

        chmod 600 "$MESSAGE_ID_FILE" "$INCIDENT_START_FILE"

        log "Alerta Telegram enviado. message_id=$message_id"
        return 0
    fi

    log "ERRO Telegram: $(compact "$response")"
    return 1
}

finish_alert() {
    local result_text="$1"
    local message_id=""
    local start_epoch=""
    local duration=""
    local response=""

    telegram_ok || {
        rm -f "$MESSAGE_ID_FILE" "$INCIDENT_START_FILE"
        return 0
    }

    [ -r "$MESSAGE_ID_FILE" ] || return 0
    [ -r "$INCIDENT_START_FILE" ] || return 0

    read -r message_id < "$MESSAGE_ID_FILE"
    read -r start_epoch < "$INCIDENT_START_FILE"

    case "$message_id" in
        ''|*[!0-9]*) return 1 ;;
    esac

    case "$start_epoch" in
        ''|*[!0-9]*) return 1 ;;
    esac

    duration="$(format_duration $(($(date +%s) - start_epoch)))"

    response="$(
        timeout 20 curl -sS \
            -X POST \
            "https://api.telegram.org/bot${TELEGRAM_BOT}/editMessageText" \
            --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
            --data-urlencode "message_id=$message_id" \
            --data-urlencode "text=✅ MK-AUTH RECUPERADO \"$MKAUTH_NAME\"

Status: 🟢 INCIDENTE RESOLVIDO

🗄️ Evento:
Falha de conexão com MySQL/MariaDB

✅ Recuperado em:
$(date '+%d/%m/%Y %H:%M:%S')

⏱️ Duração:
$duration

$result_text" \
            2>&1
    )"

    if printf '%s' "$response" | grep -q '"ok":true'; then
        log "Mensagem Telegram editada como recuperada."
    else
        log "ERRO ao editar Telegram: $(compact "$response")"
    fi

    rm -f "$MESSAGE_ID_FILE" "$INCIDENT_START_FILE"
}

cooldown_active() {
    local last=""
    local diff=0

    [ -r "$LAST_RECOVERY_FILE" ] || return 1

    read -r last < "$LAST_RECOVERY_FILE"

    case "$last" in
        ''|*[!0-9]*) return 1 ;;
    esac

    diff=$(($(date +%s) - last))

    [ "$diff" -ge 0 ] &&
    [ "$diff" -lt "$COOLDOWN_SECONDS" ]
}

restart_radius() {
    if [ "${GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY:-nao}" != "sim" ]; then
        log "MODO SEGURO: restart FreeRADIUS nao autorizado."
        return 1
    fi
    exec 8>/var/run/mkauth-guardian-global-recovery.lock
    if ! flock -n 8; then
        log "Recuperacao global em andamento; restart FreeRADIUS adiado."
        return 0
    fi
    local s=""

    s="$(radius_service)"

    log "Reiniciando serviço $s."

    service "$s" restart >> "$LOG" 2>&1 || true

    wait_radius
}

controlled_mysql_recovery() {
    exec 8>/var/run/mkauth-guardian-global-recovery.lock
    if ! flock -n 8; then
        log "Recuperacao global em andamento; nao reiniciara MySQL."
        return 1
    fi
    if [ "${GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY:-nao}" != "sim" ]; then
        log "MODO SEGURO: recuperacao com parada forcada do MySQL desabilitada."
        return 1
    fi
    local ms=""
    local rs=""
    local mysql_processes=""

    ms="$(mysql_service)"
    rs="$(radius_service)"

    log "Iniciando recuperação controlada."
    log "Serviço MySQL: $ms"
    log "Serviço FreeRADIUS: $rs"

    service "$rs" stop >> "$LOG" 2>&1 || true
    service "$ms" stop >> "$LOG" 2>&1 || true

    sleep 8

    pkill -TERM mysqld 2>/dev/null || true
    pkill -TERM mariadbd 2>/dev/null || true

    sleep 10

    if pgrep -x mysqld >/dev/null 2>&1 ||
       pgrep -x mariadbd >/dev/null 2>&1; then

        mysql_processes="$(
            pgrep -af 'mysqld|mariadbd' |
                tr '\n' ' '
        )"

        log "Processo MySQL permaneceu preso: $mysql_processes"
        log "MODO SEGURO: processo MySQL persistente; KILL -9 proibido. Intervencao manual necessaria."
        return 1

        sleep 4
    fi

    if ! pgrep -x mysqld >/dev/null 2>&1 &&
       ! pgrep -x mariadbd >/dev/null 2>&1; then

        rm -f \
            /var/run/mysqld/mysqld.sock \
            /var/run/mysqld/mysqld.pid \
            /run/mysqld/mysqld.sock \
            /run/mysqld/mysqld.pid

        mkdir -p /var/run/mysqld
        chown mysql:mysql /var/run/mysqld
        chmod 755 /var/run/mysqld
    fi

    service "$ms" start >> "$LOG" 2>&1 || true

    if ! wait_mysql "$MYSQL_START_TIMEOUT"; then
        log "CRÍTICO: MySQL não respondeu após recuperação controlada."
        return 1
    fi

    log "MySQL recuperado."

    service "$rs" start >> "$LOG" 2>&1 || true

    if ! wait_radius; then
        log "FreeRADIUS não respondeu após start. Tentando restart."
        service "$rs" restart >> "$LOG" 2>&1 || true
    fi

    wait_radius
}

radacct_special_lock_active() {
    local n=""

    n="$(
        mysql_exec -e "
        SELECT COUNT(*)
        FROM information_schema.PROCESSLIST
        WHERE DB='mkradius'
          AND (
                INFO REGEXP '^ALTER[[:space:]]+TABLE[[:space:]]+`?(radacct|radippool)`?[[:space:]]+COLLATE[[:space:]]*='
             OR (
                  INFO REGEXP 'radacct|radippool'
                  AND STATE LIKE '%metadata lock%'
                )
              );
        " 2>/dev/null
    )"

    case "$n" in
        ''|*[!0-9]*) n=0 ;;
    esac

    [ "$n" -gt 0 ]
}

queue_reset_state() {
    rm -f \
        "$QUEUE_BAD_SAMPLES_FILE" \
        "$QUEUE_FIRST_BAD_FILE"
}

queue_set_to_log_end() {
    local file=""
    local inode=""
    local size=""

    file="$(radius_log_file 2>/dev/null)" || return 0

    inode="$(stat -c '%i' "$file" 2>/dev/null || echo 0)"
    size="$(stat -c '%s' "$file" 2>/dev/null || echo 0)"

    printf '%s\n' "$inode" > "$QUEUE_INODE_FILE"
    printf '%s\n' "$size" > "$QUEUE_OFFSET_FILE"

    chmod 600 \
        "$QUEUE_INODE_FILE" \
        "$QUEUE_OFFSET_FILE"

    queue_reset_state
}

queue_new_error_count() {
    local file=""
    local inode=""
    local size=""
    local old_inode=""
    local old_offset=""
    local start=""
    local count=""

    file="$(radius_log_file 2>/dev/null)" || {
        printf '%s\n' "0"
        return 0
    }

    inode="$(stat -c '%i' "$file" 2>/dev/null || echo 0)"
    size="$(stat -c '%s' "$file" 2>/dev/null || echo 0)"

    if [ ! -r "$QUEUE_INODE_FILE" ] ||
       [ ! -r "$QUEUE_OFFSET_FILE" ]; then

        printf '%s\n' "$inode" > "$QUEUE_INODE_FILE"
        printf '%s\n' "$size" > "$QUEUE_OFFSET_FILE"

        chmod 600 \
            "$QUEUE_INODE_FILE" \
            "$QUEUE_OFFSET_FILE"

        printf '%s\n' "0"
        return 0
    fi

    read -r old_inode < "$QUEUE_INODE_FILE"
    read -r old_offset < "$QUEUE_OFFSET_FILE"

    case "$old_offset" in
        ''|*[!0-9]*) old_offset=0 ;;
    esac

    if [ "$old_inode" != "$inode" ] ||
       [ "$size" -lt "$old_offset" ]; then

        printf '%s\n' "$inode" > "$QUEUE_INODE_FILE"
        printf '%s\n' "$size" > "$QUEUE_OFFSET_FILE"

        queue_reset_state

        printf '%s\n' "0"
        return 0
    fi

    if [ "$size" -eq "$old_offset" ]; then
        printf '%s\n' "0"
        return 0
    fi

    start=$((old_offset + 1))

    count="$(
        tail -c +"$start" "$file" 2>/dev/null |
            grep -F -c \
            'due to unfinished request in component <core> module <queue>' \
            2>/dev/null ||
        true
    )"

    printf '%s\n' "$inode" > "$QUEUE_INODE_FILE"
    printf '%s\n' "$size" > "$QUEUE_OFFSET_FILE"

    case "$count" in
        ''|*[!0-9]*) count=0 ;;
    esac

    printf '%s\n' "$count"
}

queue_confirmed() {
    local new_errors="$1"
    local samples=0
    local now=""

    case "$new_errors" in
        ''|*[!0-9]*) new_errors=0 ;;
    esac

    if [ "$new_errors" -lt "$QUEUE_MIN_ERRORS" ]; then
        queue_reset_state
        return 1
    fi

    if [ -r "$QUEUE_BAD_SAMPLES_FILE" ]; then
        read -r samples < "$QUEUE_BAD_SAMPLES_FILE"
    fi

    case "$samples" in
        ''|*[!0-9]*) samples=0 ;;
    esac

    samples=$((samples + 1))

    printf '%s\n' "$samples" > "$QUEUE_BAD_SAMPLES_FILE"
    chmod 600 "$QUEUE_BAD_SAMPLES_FILE"

    if [ ! -r "$QUEUE_FIRST_BAD_FILE" ]; then
        now="$(date +%s)"
        printf '%s\n' "$now" > "$QUEUE_FIRST_BAD_FILE"
        chmod 600 "$QUEUE_FIRST_BAD_FILE"
    fi

    log "Fila Radius: $new_errors erros novos; amostra ruim $samples/$QUEUE_CONFIRM_SAMPLES."

    [ "$samples" -ge "$QUEUE_CONFIRM_SAMPLES" ]
}

collect_queue_evidence() {
    local stamp=""
    local dir=""
    local rlog=""

    stamp="$(date '+%Y%m%d-%H%M%S')"
    dir="$INCIDENT_ROOT/${stamp}-radius-queue"

    mkdir -p "$dir"
    chmod 700 "$dir"

    {
        echo "Data: $(date)"
        echo "Host: $(hostname)"
        echo "Guardian: $GUARDIAN_VERSION"
        echo
        service mysql status 2>&1 || true
        echo
        service freeradius status 2>&1 || service radiusd status 2>&1 || true
        echo
        uptime
        free -h
    } > "$dir/resumo.txt" 2>&1

    mysql_exec -e "
    SELECT
        ID,
        USER,
        HOST,
        DB,
        COMMAND,
        TIME,
        STATE,
        LEFT(INFO,1000) AS INFO
    FROM information_schema.PROCESSLIST
    ORDER BY TIME DESC;
    " > "$dir/processlist.txt" 2>&1 || true

    mysql_exec -e "
    SHOW GLOBAL STATUS
    WHERE Variable_name IN (
        'Threads_connected',
        'Threads_running',
        'Max_used_connections',
        'Slow_queries',
        'Aborted_connects',
        'Aborted_clients',
        'Questions',
        'Queries'
    );
    " > "$dir/mysql-status.txt" 2>&1 || true

    mysql_exec -e "
    SHOW ENGINE INNODB STATUS\G
    " > "$dir/innodb-status.txt" 2>&1 || true

    mysql_exec -e "
    SHOW ENGINE TOKUDB STATUS\G
    " > "$dir/tokudb-status.txt" 2>&1 || true

    ps -eo pid,ppid,etimes,%cpu,%mem,stat,wchan:35,args \
        > "$dir/processos.txt" 2>&1 || true

    ss -lunp > "$dir/udp.txt" 2>&1 || true

    rlog="$(radius_log_file 2>/dev/null || true)"

    if [ -n "$rlog" ]; then
        tail -3000 "$rlog" > "$dir/radius.log" 2>&1 || true
    fi

    chmod 600 "$dir"/* 2>/dev/null || true

    log "Diagnóstico pré-recuperação salvo em: $dir"

    printf '%s\n' "$dir"
}

functional_queue_recovery() {
    exec 8>/var/run/mkauth-guardian-global-recovery.lock
    if ! flock -n 8; then
        log "Outra recuperacao em andamento; MySQL Guardian nao reiniciara servicos."
        return 0
    fi
    local ms=""
    local rs=""
    local evidence_dir=""

    ms="$(mysql_service)"
    rs="$(radius_service)"

    if [ "${GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY:-nao}" != "sim" ]; then
        log "MODO SEGURO: fila funcional suspeita; reinicios automaticos bloqueados."
        return 1
    fi
    evidence_dir="$(collect_queue_evidence)"

    log "======================================================"
    log "RADIUS FUNCIONALMENTE TRAVADO"
    log "MySQL responde SELECT 1, Radius está UP, mas fila <core><queue> persiste."
    log "Diagnóstico: $evidence_dir"

    telegram_simple "🚨 ALERTA MK-AUTH \"$MKAUTH_NAME\"

Status: 🔴 RADIUS FUNCIONALMENTE TRAVADO

MySQL: processo ativo / SELECT 1 responde
FreeRADIUS: processo ativo
UDP 1812: ativa

Porém foram detectadas amostras consecutivas de:
unfinished request in component <core> module <queue>

A recuperação MySQL + FreeRADIUS foi iniciada.

Diagnóstico salvo:
$evidence_dir"

    log "Parando $rs."
    service "$rs" stop >> "$LOG" 2>&1 || true

    sleep 3

    log "Reiniciando serviço $ms."
    service "$ms" restart >> "$LOG" 2>&1 || true

    if ! wait_mysql "$MYSQL_START_TIMEOUT"; then
        log "Restart simples do MySQL não recuperou. Aplicando recuperação controlada."

        if ! controlled_mysql_recovery; then
            log "CRÍTICO: recuperação controlada também falhou."
            return 1
        fi
    else
        log "MySQL voltou após restart."

        service "$rs" start >> "$LOG" 2>&1 || true

        if ! wait_radius; then
            log "FreeRADIUS não confirmou após start. Tentando restart."
            service "$rs" restart >> "$LOG" 2>&1 || true
        fi
    fi

    if ! mysql_ok || ! radius_ok; then
        log "CRÍTICO: serviços não passaram na validação após recuperação da fila."
        return 1
    fi

    sleep "$QUEUE_POST_RECOVERY_WAIT"

    queue_set_to_log_end

    date +%s > "$LAST_RECOVERY_FILE"
    chmod 600 "$LAST_RECOVERY_FILE"

    log "RECUPERAÇÃO FUNCIONAL CONCLUÍDA."
    log "MySQL: ativo."
    log "FreeRADIUS: ativo."
    log "UDP 1812: ativa."
    log "Monitor da fila reinicializado."
    log "======================================================"

    telegram_simple "✅ MK-AUTH RECUPERADO \"$MKAUTH_NAME\"

Status: 🟢 RADIUS NORMALIZADO

🗄️ MySQL: reiniciado e respondendo
📡 FreeRADIUS: ativo
🔓 UDP 1812: ativa

O monitor da fila <core><queue> foi reinicializado.

Diagnóstico anterior:
$evidence_dir"

    return 0
}

NOW="$(date +%s)"

if mysql_ok; then

    #
    # NOVO V1.7:
    # detecta MySQL "vivo", Radius "vivo", porém fila funcional travada.
    #
    if radius_ok; then
        QUEUE_NEW_ERRORS="$(queue_new_error_count)"

        case "$QUEUE_NEW_ERRORS" in
            ''|*[!0-9]*) QUEUE_NEW_ERRORS=0 ;;
        esac

        if [ "$QUEUE_NEW_ERRORS" -ge "$QUEUE_MIN_ERRORS" ]; then

            #
            # Se for o cenário conhecido de ALTER radacct/radippool/metadata lock,
            # não reinicia o MySQL aqui. Deixa o Backup Guardian v1.6 atuar.
            #
            if radacct_special_lock_active; then
                log "Fila Radius detectada, porém existe ALTER/metadata lock em radacct/radippool."
                log "Ação deixada para o Backup Guardian v1.6."
                queue_reset_state
                exit 0
            fi

            if queue_confirmed "$QUEUE_NEW_ERRORS"; then

                if cooldown_active; then
                    log "Fila funcional confirmada, mas cooldown de recuperação está ativo."
                    exit 0
                fi

                if functional_queue_recovery; then
                    exit 0
                fi

                log "CRÍTICO: recuperação funcional da fila falhou."

                telegram_simple "❌ ALERTA CRÍTICO MK-AUTH \"$MKAUTH_NAME\"

O Guardian v1.7 detectou fila RADIUS funcionalmente travada e tentou reiniciar MySQL + FreeRADIUS, porém a validação final falhou."

                exit 1
            fi
        else
            queue_reset_state
        fi
    fi

    #
    # Lógica v1.4 preservada.
    #
    if [ -r "$FAIL_START_FILE" ]; then

        read -r FAIL_START < "$FAIL_START_FILE"

        case "$FAIL_START" in
            ''|*[!0-9]*) FAIL_START="$NOW" ;;
        esac

        DURATION=$((NOW - FAIL_START))

        log "MySQL voltou após ${DURATION}s."

        restart_radius || {
            log "CRÍTICO: FreeRADIUS não recuperou após retorno do MySQL."
            exit 1
        }

        rm -f "$FAIL_START_FILE"

        date +%s > "$LAST_RECOVERY_FILE"
        chmod 600 "$LAST_RECOVERY_FILE"

        queue_set_to_log_end

        log "RECUPERAÇÃO CONFIRMADA."
        log "MySQL: ativo"
        log "FreeRADIUS: ativo"
        log "UDP 1812: ativa"
        log "======================================================"

        finish_alert "🗄️ MySQL: ativo
📡 FreeRADIUS: reiniciado e funcionando
🔓 Porta UDP 1812: ativa" || true

    elif ! radius_ok; then

        log "MySQL ativo, mas FreeRADIUS está inativo."

        if cooldown_active; then
            log "Cooldown ativo; aguardando próxima verificação."
            exit 0
        fi

        send_alert "MySQL responde normalmente, porém o FreeRADIUS ou a porta UDP 1812 estão inativos." || true

        if restart_radius; then

            date +%s > "$LAST_RECOVERY_FILE"
            chmod 600 "$LAST_RECOVERY_FILE"

            queue_set_to_log_end

            log "FreeRADIUS recuperado."

            finish_alert "🗄️ MySQL: ativo
📡 FreeRADIUS: reiniciado
🔓 Porta UDP 1812: ativa" || true

        else
            log "CRÍTICO: não foi possível recuperar o FreeRADIUS."
            exit 1
        fi
    fi

    exit 0
fi

#
# MySQL realmente indisponível - lógica v1.4.
#

queue_reset_state

if [ ! -r "$FAIL_START_FILE" ]; then

    printf '%s\n' "$NOW" > "$FAIL_START_FILE"
    chmod 600 "$FAIL_START_FILE"

    log "======================================================"
    log "MYSQL INDISPONÍVEL"
    log "Iniciando janela de recuperação automática de ${WAIT_AUTO_RECOVERY}s."

    send_alert "MySQL não respondeu ao comando SELECT 1.
Será aguardada a recuperação automática antes de qualquer ação forçada." || true

    exit 0
fi

read -r FAIL_START < "$FAIL_START_FILE"

case "$FAIL_START" in
    ''|*[!0-9]*)
        FAIL_START="$NOW"
        printf '%s\n' "$NOW" > "$FAIL_START_FILE"
        ;;
esac

FAIL_DURATION=$((NOW - FAIL_START))

if [ "$FAIL_DURATION" -lt "$WAIT_AUTO_RECOVERY" ]; then
    log "MySQL ainda indisponível há ${FAIL_DURATION}s; aguardando recuperação automática."
    exit 0
fi

if cooldown_active; then
    log "MySQL indisponível, mas cooldown está ativo."
    exit 0
fi

log "MySQL indisponível há ${FAIL_DURATION}s."
log "Janela de recuperação automática encerrada."

if controlled_mysql_recovery; then

    rm -f "$FAIL_START_FILE"

    date +%s > "$LAST_RECOVERY_FILE"
    chmod 600 "$LAST_RECOVERY_FILE"

    queue_set_to_log_end

    log "RECUPERAÇÃO CONTROLADA CONCLUÍDA."
    log "MySQL: ativo"
    log "FreeRADIUS: ativo"
    log "UDP 1812: ativa"
    log "======================================================"

    finish_alert "🛠️ Recuperação controlada executada
🗄️ MySQL: ativo
📡 FreeRADIUS: ativo
🔓 Porta UDP 1812: ativa" || true

    exit 0
fi

log "CRÍTICO: recuperação controlada falhou."
exit 1
GUARDIAN17

cat > "$BACKUP_GUARDIAN" <<'GUARDIAN16'
#!/bin/bash
set -u
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
GUARDIAN_VERSION="1.8-rc1"
CONFIG="/etc/default/check_backup_freeradius"
LOG="/var/log/mkauth_backup_guardian.log"
STATE_DIR="/var/lib/mkauth_backup_guardian"
LOCK_FILE="/var/run/mkauth_backup_guardian.lock"
LAST_RECOVERY_FILE="$STATE_DIR/last_recovery"
SQL_FILE="/opt/mk-auth/mysql/up_database.sql"
LOCK_SECONDS="300"
MIN_METADATA_LOCKS="3"
COOLDOWN_SECONDS="300"
MKAUTH_NAME="$(hostname 2>/dev/null || echo mk-auth)"
USAR_TELEGRAM="nao"
TELEGRAM_BOT=""
TELEGRAM_CHAT_ID=""
[ -r "$CONFIG" ] && . "$CONFIG"
mkdir -p "$STATE_DIR"
touch "$LOG"
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0
log(){ printf '%s - %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }
mysql_exec(){
    if [ -r /etc/mysql/debian.cnf ]; then
        timeout 15 mysql --defaults-file=/etc/mysql/debian.cnf --connect-timeout=5 --batch --skip-column-names "$@" 2>/dev/null
    elif [ -r /root/.my.cnf ]; then
        timeout 15 mysql --defaults-file=/root/.my.cnf --connect-timeout=5 --batch --skip-column-names "$@" 2>/dev/null
    else
        return 1
    fi
}
mysql_ok(){ [ "$(mysql_exec -e "SELECT 1;" 2>/dev/null)" = "1" ]; }
radius_service(){
    if [ -x /etc/init.d/freeradius ]; then printf '%s\n' freeradius;
    elif [ -x /etc/init.d/radiusd ]; then printf '%s\n' radiusd;
    else printf '%s\n' freeradius; fi
}
radius_ok(){
    (pgrep -x freeradius >/dev/null 2>&1 || pgrep -x radiusd >/dev/null 2>&1) &&
    ss -H -lun 2>/dev/null | awk '{print $4}' | grep -Eq '(^|:)1812$'
}
wait_radius(){
    local elapsed=0
    while [ "$elapsed" -lt 60 ]; do radius_ok && return 0; sleep 2; elapsed=$((elapsed+2)); done
    return 1
}
telegram_ok(){
    [ "${USAR_TELEGRAM:-nao}" = "sim" ] &&
    [ -n "${TELEGRAM_BOT:-}" ] &&
    [ -n "${TELEGRAM_CHAT_ID:-}" ] &&
    command -v curl >/dev/null 2>&1
}
telegram_send(){
    local msg="$1"
    telegram_ok || return 0
    timeout 20 curl -sS -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT}/sendMessage" \
    --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
    --data-urlencode "text=$msg" >/dev/null 2>&1 || true
}
cooldown_active(){
    local last="" diff=0
    [ -r "$LAST_RECOVERY_FILE" ] || return 1
    read -r last < "$LAST_RECOVERY_FILE"
    case "$last" in ''|*[!0-9]*) return 1 ;; esac
    diff=$(($(date +%s)-last))
    [ "$diff" -ge 0 ] && [ "$diff" -lt "$COOLDOWN_SECONDS" ]
}
protect_sql(){
    local table collation stamp backup
    [ -f "$SQL_FILE" ] || return 0
    for table in radacct radippool; do
        collation="$(mysql_exec -e "SELECT TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA='mkradius' AND TABLE_NAME='$table';")"
        [ "$collation" = "latin1_swedish_ci" ] || continue
        if grep -Eiq "^[[:space:]]*ALTER[[:space:]]+TABLE[[:space:]]+\`?$table\`?[[:space:]]+COLLATE[[:space:]]*=[[:space:]]*'latin1_swedish_ci'[[:space:]]*;" "$SQL_FILE"; then
            stamp="$(date '+%Y%m%d-%H%M%S')"
            backup="/root/up_database.sql.bak-auto-v18-${table}-${stamp}-$$"
            if cp -a "$SQL_FILE" "$backup"; then
                sed -i -E "/^[[:space:]]*ALTER[[:space:]]+TABLE[[:space:]]+\`?$table\`?[[:space:]]+COLLATE[[:space:]]*=[[:space:]]*'latin1_swedish_ci'[[:space:]]*;/ {
                    s|^|-- DESATIVADO GUARDIAN V1.8-rc1 ${stamp}: collation ja correta; evita metadata lock - |
                }" "$SQL_FILE"
                log "ALTER redundante $table desativado; backup $backup"
            else
                log "ERRO: backup SQL falhou; $table nao modificado"
            fi
        fi
    done
}
alter_ids(){
    mysql_exec -e "SELECT ID FROM information_schema.PROCESSLIST
    WHERE DB='mkradius' AND COMMAND='Query'
      AND INFO REGEXP '^ALTER[[:space:]]+TABLE[[:space:]]+`?(radacct|radippool)`?[[:space:]]+COLLATE[[:space:]]*='
    ORDER BY TIME DESC;"
}
alter_detail(){
    mysql_exec -e "SELECT CONCAT('ID=',ID,' | TIME=',TIME,'s | STATE=',COALESCE(STATE,''),' | INFO=',LEFT(COALESCE(INFO,''),300))
    FROM information_schema.PROCESSLIST
    WHERE DB='mkradius' AND COMMAND='Query'
      AND INFO REGEXP '^ALTER[[:space:]]+TABLE[[:space:]]+`?(radacct|radippool)`?[[:space:]]+COLLATE[[:space:]]*='
    ORDER BY TIME DESC LIMIT 1;"
}
metadata_count(){
    mysql_exec -e "SELECT COUNT(*) FROM information_schema.PROCESSLIST
    WHERE DB='mkradius' AND INFO REGEXP 'radacct|radippool'
      AND (STATE LIKE '%metadata lock%' OR STATE LIKE '%table level lock%' OR STATE LIKE '%Waiting for table%');"
}
metadata_max_time(){
    mysql_exec -e "SELECT COALESCE(MAX(TIME),0) FROM information_schema.PROCESSLIST
    WHERE DB='mkradius'
      AND (INFO REGEXP '^ALTER[[:space:]]+TABLE[[:space:]]+`?(radacct|radippool)`?[[:space:]]+COLLATE[[:space:]]*='
        OR (INFO REGEXP 'radacct|radippool' AND
           (STATE LIKE '%metadata lock%' OR STATE LIKE '%table level lock%' OR STATE LIKE '%Waiting for table%')));"
}

protect_sql
if ! mysql_ok; then
    log "MySQL indisponível. Tratamento deixado para o MySQL Guardian v1.4."
    exit 0
fi

IDS="$(alter_ids 2>/dev/null)"
LOCK_COUNT="$(metadata_count 2>/dev/null)"
MAX_TIME="$(metadata_max_time 2>/dev/null)"
case "$LOCK_COUNT" in ''|*[!0-9]*) LOCK_COUNT=0 ;; esac
case "$MAX_TIME" in ''|*[!0-9]*) MAX_TIME=0 ;; esac

if [ -z "$IDS" ] || [ "$LOCK_COUNT" -lt "$MIN_METADATA_LOCKS" ] || [ "$MAX_TIME" -lt "$LOCK_SECONDS" ]; then
    exit 0
fi
if cooldown_active; then
    log "Bloqueio detectado durante cooldown; nova ação ignorada."
    exit 0
fi

exec 8>/var/run/mkauth-guardian-global-recovery.lock
if ! flock -n 8; then
    log "Outra recuperacao em andamento; Backup Guardian aguardara."
    exit 0
fi
IDS="$(alter_ids 2>/dev/null)"
[ -n "$IDS" ] || exit 0
DETAIL="$(alter_detail 2>/dev/null)"
log "======================================================"
log "BACKUP/UPGRADE TRAVADO"
log "Detalhe: ${DETAIL:-ALTER TABLE radacct/radippool travado}"
log "Metadata locks: $LOCK_COUNT"
log "Maior espera: ${MAX_TIME}s"

telegram_send "🚨 ALERTA MK-AUTH \"$MKAUTH_NAME\"

Status: 🔴 PROBLEMA ATIVO

🗄️ Evento:
Backup/upgrade travado em radacct/radippool

📝 Detalhes:
${DETAIL:-ALTER TABLE radacct/radippool travado}

🔐 Metadata locks:
$LOCK_COUNT

⏱️ Maior espera:
${MAX_TIME}s

Backup Guardian v1.8-rc1 iniciou a recuperação."

if [ "${GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY:-nao}" != "sim" ]; then
    log "MODO SEGURO: metadata lock detectado; recuperacao destrutiva nao autorizada."
    telegram_send "⚠️ MK-AUTH: metadata lock detectado; modo seguro ativo, intervencao manual necessaria."
    exit 0
fi

RS="$(radius_service)"
service "$RS" stop >> "$LOG" 2>&1 || true
sleep 2

for ID in $IDS; do
    case "$ID" in ''|*[!0-9]*) continue ;; esac
    log "Executando KILL da sessão SQL $ID."
    mysql_exec -e "KILL $ID;" >> "$LOG" 2>&1 || true
done

sleep 2

# IMPORTANTE: este Guardian nunca mata mysqld/mariadbd.
pkill -TERM -f '/opt/mk-auth/update/upgradebd\.php' 2>/dev/null || true
pkill -TERM -f '/opt/mk-auth/scripts/backup\.php' 2>/dev/null || true
pkill -TERM -f 'mysql .*mkradius.*up_database\.sql' 2>/dev/null || true

sleep 5

if pgrep -f '/opt/mk-auth/update/upgradebd\.php' >/dev/null 2>&1 ||
   pgrep -f '/opt/mk-auth/scripts/backup\.php' >/dev/null 2>&1; then
    log "Backup/upgrade ainda ativo; aplicando KILL apenas nesses processos."
    pkill -KILL -f '/opt/mk-auth/update/upgradebd\.php' 2>/dev/null || true
    pkill -KILL -f '/opt/mk-auth/scripts/backup\.php' 2>/dev/null || true
fi

NEW_IDS="$(alter_ids 2>/dev/null)"
for ID in $NEW_IDS; do
    case "$ID" in ''|*[!0-9]*) continue ;; esac
    log "ALTER reapareceu. Executando KILL da sessão SQL $ID."
    mysql_exec -e "KILL $ID;" >> "$LOG" 2>&1 || true
done

sleep 3
service "$RS" start >> "$LOG" 2>&1 || true
if ! wait_radius; then
    log "FreeRADIUS não confirmou após start; executando restart."
    service "$RS" restart >> "$LOG" 2>&1 || true
fi
sleep 5

FINAL_ALTERS="$(alter_ids 2>/dev/null)"
FINAL_LOCKS="$(metadata_count 2>/dev/null)"
case "$FINAL_LOCKS" in ''|*[!0-9]*) FINAL_LOCKS=999 ;; esac

if mysql_ok && radius_ok && [ -z "$FINAL_ALTERS" ]; then
    date +%s > "$LAST_RECOVERY_FILE"; chmod 600 "$LAST_RECOVERY_FILE"
    log "RECUPERAÇÃO CONCLUÍDA."
    log "Metadata locks restantes: $FINAL_LOCKS"
    log "MySQL: permaneceu ativo."
    log "FreeRADIUS: ativo."
    log "UDP 1812: ativa."
    log "======================================================"

    telegram_send "✅ MK-AUTH RECUPERADO \"$MKAUTH_NAME\"

Status: 🟢 INCIDENTE RESOLVIDO

🛑 Backup/upgrade travado: encerrado
🗄️ MySQL: permaneceu ativo
📡 FreeRADIUS: reiniciado e funcionando
🔓 Porta UDP 1812: ativa
🔐 Metadata locks restantes: $FINAL_LOCKS"
    exit 0
fi

log "CRÍTICO: recuperação não confirmada."
log "ALTER restante: ${FINAL_ALTERS:-nenhum}"
log "Metadata locks restantes: $FINAL_LOCKS"

telegram_send "❌ ALERTA CRÍTICO MK-AUTH \"$MKAUTH_NAME\"

Backup Guardian v1.8-rc1 tentou recuperar o travamento de radacct/radippool, mas a validação final falhou.

ALTER restante:
${FINAL_ALTERS:-nenhum}

Metadata locks restantes:
$FINAL_LOCKS"

exit 1
GUARDIAN16

chown root:root "$MYSQL_GUARDIAN" "$BACKUP_GUARDIAN"
chmod 700 "$MYSQL_GUARDIAN" "$BACKUP_GUARDIAN"

bash -n "$MYSQL_GUARDIAN" || { echo "ERRO: sintaxe Guardian v1.7."; exit 1; }
bash -n "$BACKUP_GUARDIAN" || { echo "ERRO: sintaxe Guardian v1.6."; exit 1; }

cat > "$MYSQL_CRON" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
* * * * * root echo "\$(date '+\%F \%T') MySQL Guardian imediato v1.7" >> $MYSQL_RUN_LOG; timeout 300 $MYSQL_GUARDIAN >> $MYSQL_RUN_LOG 2>&1
* * * * * root sleep 30; echo "\$(date '+\%F \%T') MySQL Guardian após 30 segundos v1.7" >> $MYSQL_RUN_LOG; timeout 300 $MYSQL_GUARDIAN >> $MYSQL_RUN_LOG 2>&1
EOF

cat > "$BACKUP_CRON" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
* * * * * root echo "\$(date '+\%F \%T') Backup Guardian imediato v1.6" >> $BACKUP_RUN_LOG; timeout 180 $BACKUP_GUARDIAN >> $BACKUP_RUN_LOG 2>&1
* * * * * root sleep 30; echo "\$(date '+\%F \%T') Backup Guardian após 30 segundos v1.6" >> $BACKUP_RUN_LOG; timeout 180 $BACKUP_GUARDIAN >> $BACKUP_RUN_LOG 2>&1
EOF

chown root:root "$MYSQL_CRON" "$BACKUP_CRON"
chmod 644 "$MYSQL_CRON" "$BACKUP_CRON"

rm -f \
    "$MYSQL_STATE/mysql_fail_start" \
    "$MYSQL_STATE/message_id" \
    "$MYSQL_STATE/incident_start"

if [ -f "$SQL_FILE" ]; then
    for TABLE in radacct radippool; do
        COLLATION="$(mysql_installer -e "SELECT TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA='mkradius' AND TABLE_NAME='$TABLE';")"
        echo "Collation atual de $TABLE: ${COLLATION:-nao localizada}"
        [ "$COLLATION" = "latin1_swedish_ci" ] || continue
        if grep -Eiq "^[[:space:]]*ALTER[[:space:]]+TABLE[[:space:]]+\`?$TABLE\`?[[:space:]]+COLLATE[[:space:]]*=[[:space:]]*'latin1_swedish_ci'[[:space:]]*;" "$SQL_FILE"; then
            cp -a "$SQL_FILE" "/root/up_database.sql.bak-v18-${TABLE}-${STAMP}-$$" || { echo "ERRO: backup SQL falhou"; exit 1; }
            sed -i -E "/^[[:space:]]*ALTER[[:space:]]+TABLE[[:space:]]+\`?$TABLE\`?[[:space:]]+COLLATE[[:space:]]*=[[:space:]]*'latin1_swedish_ci'[[:space:]]*;/ {
                s|^|-- DESATIVADO PATCH V1.8-rc1 ${STAMP}: collation ja correta; evita metadata lock - |
            }" "$SQL_FILE"
            echo "ALTER redundante de $TABLE desativado com backup."
        fi
    done
else
    echo "ATENCAO: $SQL_FILE nao encontrado."
fi

echo
echo "Validacao estatica dos monitores (sem execucao):"
bash -n "$WATCHDOG" || { echo "ERRO: sintaxe watchdog"; exit 1; }
bash -n "$MYSQL_GUARDIAN" || { echo "ERRO: sintaxe MySQL Guardian"; exit 1; }
bash -n "$BACKUP_GUARDIAN" || { echo "ERRO: sintaxe Backup Guardian"; exit 1; }
echo "OK: nenhum Guardian executado durante instalacao."

restart_cron
CRON_WAS_STOPPED=0
trap - EXIT INT TERM

sleep 2

echo
echo "======================================================"
echo " INSTALADOR COMPLETO V1.8-rc1 INSTALADO"
echo "======================================================"
echo "Monitor principal preservado: $WATCHDOG"
echo "MySQL Guardian: $MYSQL_GUARDIAN"
grep -m1 '^GUARDIAN_VERSION=' "$MYSQL_GUARDIAN" || true
echo "Backup Guardian: $BACKUP_GUARDIAN"
grep -m1 '^GUARDIAN_VERSION=' "$BACKUP_GUARDIAN" || true
echo
echo "Evidências automáticas da fila Radius:"
echo "  /root/mkauth-guardian-incidentes/"
echo
echo "Crons:"
echo "  $MYSQL_CRON"
echo "  $BACKUP_CRON"
echo
echo "Verificação da radacct:"
mysql_installer -e "SELECT TABLE_NAME,ENGINE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA='mkradius' AND TABLE_NAME='radacct';" || true
echo
echo "Linha no up_database.sql:"
grep -nC 2 -Ei 'ALTER[[:space:]]+TABLE[[:space:]]+`?radacct`?[[:space:]]+COLLATE' "$SQL_FILE" 2>/dev/null || true
echo
echo "Acompanhar:"
echo "  tail -F $MYSQL_RUN_LOG"
echo "  tail -F $BACKUP_RUN_LOG"
PATCH_EMBUTIDO

chmod 700 "$PATCH_TEMP"

if ! bash -n "$PATCH_TEMP"; then
    echo "ERRO: falha de sintaxe no patch complementar."
    rm -f "$PATCH_TEMP"
    exit 1
fi

bash "$PATCH_TEMP"
PATCH_RC=$?
rm -f "$PATCH_TEMP"

if [ "$PATCH_RC" -ne 0 ]; then
    echo "ERRO: patch complementar retornou $PATCH_RC."
    exit "$PATCH_RC"
fi

echo
echo "=========================================================="
echo " INSTALAÇÃO COMPLETA V1.7.1 FINALIZADA"
echo "=========================================================="
echo
echo "Monitor principal:"
echo "  /var/check_backup_freeradius.sh"
echo "MySQL Guardian:"
echo "  /usr/local/sbin/mkauth_mysql_radius_guardian.sh"
echo "Backup Guardian:"
echo "  /usr/local/sbin/mkauth_backup_guardian.sh"
echo
echo "Versões:"
grep -m1 '^GUARDIAN_VERSION=' /usr/local/sbin/mkauth_mysql_radius_guardian.sh 2>/dev/null || true
grep -m1 '^GUARDIAN_VERSION=' /usr/local/sbin/mkauth_backup_guardian.sh 2>/dev/null || true
echo
echo "Crons ativos:"
cat /etc/cron.d/check_backup_freeradius 2>/dev/null || true
cat /etc/cron.d/mkauth_mysql_radius_guardian 2>/dev/null || true
cat /etc/cron.d/mkauth_backup_guardian 2>/dev/null || true
echo
echo
echo "=========================================================="
echo " VALIDAÇÃO DE CRONS ATIVOS"
echo "=========================================================="

ACTIVE_CRON_LINES="$(
    grep -hE '^[*]' \
        /etc/cron.d/check_backup_freeradius \
        /etc/cron.d/mkauth_mysql_radius_guardian \
        /etc/cron.d/mkauth_backup_guardian \
        2>/dev/null | wc -l
)"

echo "Linhas ativas esperadas: 6"
echo "Linhas ativas encontradas: $ACTIVE_CRON_LINES"

if [ "$ACTIVE_CRON_LINES" -ne 6 ]; then
    echo "ATENÇÃO: quantidade inesperada de linhas ativas nos três crons."
fi

echo
echo "Saúde final:"
echo -n "MySQL SELECT 1: "
if [ -r /etc/mysql/debian.cnf ]; then
    mysql --defaults-file=/etc/mysql/debian.cnf -NBe "SELECT 1" 2>/dev/null || true
else
    mysql -uroot --no-defaults -NBe "SELECT 1" 2>/dev/null || true
fi
service freeradius status 2>/dev/null || service radiusd status 2>/dev/null || true
ss -lun 2>/dev/null | grep -E '(^|:)1812([[:space:]]|$)' || true
echo
