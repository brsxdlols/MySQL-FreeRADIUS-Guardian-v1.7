"""Detailed Telegram messages using verified facts, never raw SQL or client logs."""
import datetime
import socket
import time


REASONS = {
    'database_unavailable': 'MySQL/MariaDB não respondeu à verificação SELECT 1.',
    'radius_unavailable': 'Processo ou portas UDP do FreeRADIUS indisponíveis.',
    'persistent_queue_or_lock': 'Requisições RADIUS pendentes persistentes ou bloqueio SQL crítico.',
    'backup_failure': 'Falha de backup encaminhada ao coordenador.',
    'authorized_manual_test': 'Recuperação solicitada manualmente.',
}


def stamp(value):
    if value is None:
        return 'não registrado'
    return datetime.datetime.fromtimestamp(value).astimezone().strftime('%d/%m/%Y %H:%M:%S %z')


def clean(value, limit=160):
    return ' '.join(str(value).split())[:limit]


def health_lines(health):
    return [
        '🗄 MySQL SELECT 1: ' + ('respondendo' if health.get('database') else 'não confirmado'),
        '📡 FreeRADIUS processo e UDP 1812/1813: ' + ('disponíveis' if health.get('radius') else 'não confirmados'),
    ]


def duration(record, now):
    started = record.get('started')
    return str(max(0, int(now-started)))+'s' if isinstance(started, (int, float)) else 'não registrada'


def render(payload, name, hostname=None, now=None):
    now = time.time() if now is None else now
    hostname = socket.gethostname() if hostname is None else hostname
    event = payload['event']
    record = payload.get('record') or {}
    health = payload.get('health') or {}
    identity = ['MK-AUTH/VM: '+clean(name), 'Servidor Linux: '+clean(hostname)]
    if event == 'installation':
        title = '✅ MONITOR MK-AUTH — '+clean(payload['status'])
        lines = [title, '', *identity, '', 'Guardian Recovery '+clean(payload['version']),
                 'Verificação agendada: a cada 30 segundos.',
                 'Cron: '+('ativo' if health.get('cron') else 'não confirmado; verificar agendamento'),
                 'Recuperação coordenada: habilitada.',
                 'SIGKILL no PID exato do MariaDB: '+('autorizado como último recurso' if payload.get('allow_sigkill') else 'desabilitado'),
                 '', *health_lines(health), '', 'Nenhum serviço foi reiniciado pela instalação.',
                 'Restauração completa do backup ainda não certificada.', 'Data: '+stamp(now)]
        if payload.get('backup_supervision') is False:
            lines += ['', '⚠️ Backup: agendamento nativo preservado.', 'Supervisor de backup PENDENTE de homologação do modelo; a proteção MySQL/FreeRADIUS foi instalada.']
        elif payload.get('backup_supervision') is True:
            lines += ['', 'Backup: agendamento supervisionado configurado; restauração de cada novo arquivo ainda depende de teste.']
        return '\n'.join(lines)
    titles = {
        'recovery_begin': '🚨 ALERTA MK-AUTH — RECUPERAÇÃO INICIADA',
        'recovery_done': '✅ MK-AUTH — SERVIÇOS DISPONÍVEIS APÓS RECUPERAÇÃO',
        'recovery_manual': '❌ ALERTA CRÍTICO MK-AUTH — RECUPERAÇÃO INTERROMPIDA',
        'escalation': '⚠️ MK-AUTH — ESCALONAMENTO CONTROLADO DO MARIADB',
    }
    lines = [titles[event], '', *identity, '', '🔌 Evento:',
             REASONS.get(record.get('reason'), 'Solicitação específica registrada no diagnóstico local.'),
             '', '🚨 Início da recuperação: '+stamp(record.get('started')),
             '⏱ Tempo desde o início: '+duration(record, now)]
    initial = record.get('initial_health') or {}
    if initial:
        lines += ['', '📝 Evidência no início:', *health_lines(initial),
                  'Avisos novos de requisição pendente na amostra: '+str(initial.get('queue_errors', 0)),
                  'Bloqueio SQL crítico detectado: '+('sim' if initial.get('critical_lock') else 'não')]
    if event == 'recovery_done':
        lines += ['', '✅ Disponibilidade confirmada em: '+stamp(now), *health_lines(health),
                  'SIGKILL utilizado: '+('sim' if record.get('used_sigkill') else 'não'),
                  'Escopo: '+('MariaDB e FreeRADIUS' if record.get('database') else 'FreeRADIUS'),
                  '', 'Accounting/autenticação completos ainda exigem validação funcional.']
    elif event == 'recovery_begin':
        lines += ['', 'Escopo: '+('MariaDB e FreeRADIUS' if record.get('database') else 'FreeRADIUS'),
                  'Parada normal antes de escalonar; um único coordenador controla a recuperação.',
                  'SIGKILL exato autorizado: '+('sim' if record.get('allow_sigkill') else 'não')]
    elif event == 'escalation':
        kind = payload.get('signal')
        lines += ['', 'Sinal enviado: '+('SIGKILL' if kind == 'KILL' else 'SIGTERM'),
                  'PID MariaDB confirmado: '+str(payload['pid']),
                  'Identidade validada e evidências privadas registradas antes do sinal.']
    else:
        lines += ['', 'Não foi possível concluir a recuperação dentro das condições seguras.',
                  'Fase: '+clean(record.get('phase', 'manual')),
                  'Nenhuma nova tentativa automática até intervenção e revisão das evidências.']
    lines += ['', '📁 Diagnóstico local:',
              clean(record.get('evidence_path') or '/var/log/mkauth-guardian-normal-recovery.log', 300)]
    return '\n'.join(lines)
