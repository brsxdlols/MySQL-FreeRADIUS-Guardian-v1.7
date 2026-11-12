#!/bin/bash

LOG_FILE="/var/log/freeradius/radius.log"
LOG_OUTPUT="/var/log/check_backup_freeradius.log"
PHRASES=("MySQL error: Can't connect to local MySQL server through socket" "Couldn't connect to MySQL server" "conflicting" "unfinished" "handshake" "Error: Something is blocking the server.")

TELEGRAM_BOT="123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
TELEGRAM_CHAT_ID="-1001234567890"
TELEGRAM_API_URL="https://api.telegram.org/bot${TELEGRAM_BOT}/sendMessage"

# Registrar início da verificação
echo "$(date '+%Y-%m-%d %H:%M:%S') - Iniciando verificação no FreeRADIUS..." >> "$LOG_OUTPUT"

LOG_LINES=$(tail -n 5 "$LOG_FILE")
FOUND_ERROR=0

for PHRASE in "${PHRASES[@]}"; do 
    if echo "$LOG_LINES" | grep -q "$PHRASE"; then
        FOUND_ERROR=1
        MSG="⚠️ ALERTA: Problema detectado no FreeRADIUS! $PHRASE"
        ENCODED_MSG=$(echo "$MSG" | jq -sRr @uri)

        # Registrar tentativa de envio
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Enviando alerta para o Telegram..." >> "$LOG_OUTPUT"
        
        # Enviar alerta para o Telegram e capturar resposta
        TELEGRAM_RESPONSE=$(curl -s -X POST "$TELEGRAM_API_URL" -d "chat_id=$TELEGRAM_CHAT_ID" -d "text=$MSG" -d "parse_mode=Markdown")

        # Verificar se a mensagem foi enviada corretamente
        if echo "$TELEGRAM_RESPONSE" | grep -q '"ok":true'; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') - ✅ ALERTA ENVIADO COM SUCESSO!" >> "$LOG_OUTPUT"
        else
            echo "$(date '+%Y-%m-%d %H:%M:%S') - ❌ ERRO AO ENVIAR ALERTA PARA O TELEGRAM! Resposta da API: $TELEGRAM_RESPONSE" >> "$LOG_OUTPUT"
        fi

        # Reiniciar serviços
        service mysql restart && echo "$(date '+%Y-%m-%d %H:%M:%S') - MySQL reiniciado" >> "$LOG_OUTPUT"
        service freeradius restart && echo "$(date '+%Y-%m-%d %H:%M:%S') - FreeRADIUS reiniciado" >> "$LOG_OUTPUT"

        break
    fi
done

# Se nenhum erro foi encontrado, registrar e enviar mensagem ao Telegram
if [ "$FOUND_ERROR" -eq 0 ]; then
#    MSG="✅ FreeRADIUS está funcionando corretamente. Nenhum problema detectado."
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Nenhum problema detectado. FreeRADIUS está funcionando corretamente." >> "$LOG_OUTPUT"
    
    TELEGRAM_RESPONSE=$(curl -s -X POST "$TELEGRAM_API_URL" -d "chat_id=$TELEGRAM_CHAT_ID" -d "text=$MSG" -d "parse_mode=Markdown")

    if echo "$TELEGRAM_RESPONSE" | grep -q '"ok":true'; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - ✅ STATUS ENVIADO COM SUCESSO PARA O TELEGRAM!" >> "$LOG_OUTPUT"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - ❌ ERRO AO ENVIAR STATUS PARA O TELEGRAM! Resposta da API: $TELEGRAM_RESPONSE" >> "$LOG_OUTPUT"
    fi
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - Verificação concluída." >> "$LOG_OUTPUT"
