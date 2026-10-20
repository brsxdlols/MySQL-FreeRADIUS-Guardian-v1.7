#!/usr/bin/env python3
"""Automatic installer UI. Existing local names and credentials are preserved."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
from guardian_safety import mysql_read

VERSION='2026.10.20.3'

def label_from_config():
    try:
        for row in Path('/etc/default/check_backup_freeradius').read_text().splitlines():
            if row.startswith('MKAUTH_NAME='):
                parsed=shlex.split(row.split('=',1)[1],comments=True)
                if len(parsed)==1:return parsed[0]
    except (OSError,ValueError):pass
    return None

def check_health():
    from guardian_controller import Production
    backend=Production()
    cron=False
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if proc.joinpath('comm').read_text().strip()=='cron':cron=True;break
        except OSError:pass
    return {'database':backend.database_ready(),'radius':backend.radius_ready(),'cron':cron}

def deliver(message):
    from guardian_controller import notify
    return notify(message)

def main(argv=None):
    parser=argparse.ArgumentParser(description='Atualizacao automatica de Guardian existente; sem argumentos instala e habilita recuperacao normal.')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true',help='Somente simular; nao enviar Telegram')
    mode.add_argument('--apply',action='store_true',help='Instalar (padrao)')
    parser.add_argument('--expected-provider',help='Verificacao adicional opcional; identidade detectada automaticamente')
    parser.add_argument('--enable-normal-recovery',action='store_true',help='Compatibilidade; habilitado por padrao nesta interface')
    parser.add_argument('--allow-sigkill-exact-mariadb',action='store_true',help='Autorizar ultimo recurso; ausencia preserva configuracao existente')
    args=parser.parse_args(argv)
    print('\n==========================================================\n GUARDIAN RECOVERY '+VERSION+' — CANDIDATO\n INSTALACAO AUTOMATICA / CONFIGURACAO LOCAL PRESERVADA\n==========================================================',flush=True)
    try:
        provider=mysql_read('SELECT nome FROM mkradius.sis_provedor LIMIT 1;').strip()
        if not provider:raise RuntimeError('Nao foi possivel identificar o provedor no banco')
        if args.expected_provider is not None and args.expected_provider!=provider:
            raise RuntimeError('Provider mismatch: verificacao adicional recusada')
        label=label_from_config() or provider
        print('MK-AUTH/VM: '+label+'\nProvedor detectado no banco: '+provider,flush=True)
        print('Modo: '+('SIMULACAO, sem alteracoes' if args.dry_run else 'APLICACAO AUTOMATICA'),flush=True)
        print('Verificando compatibilidade, locks, arquivos e plano de rollback...',flush=True)
        command=[sys.executable,str(Path(__file__).with_name('install.py')),'--expected-provider',provider,'--enable-normal-recovery']
        if not args.dry_run:command.append('--apply')
        if args.allow_sigkill_exact_mariadb:command.append('--allow-sigkill-exact-mariadb')
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
        records=[]
        for row in result.stdout.splitlines():
            try:
                record=json.loads(row)
                if isinstance(record,dict):records.append(record)
            except ValueError:pass
        if result.returncode:
            print('INSTALACAO NAO CONCLUIDA. Nenhuma confirmacao de sucesso enviada ao Telegram.',flush=True)
            print(result.stdout.strip(),flush=True)
            if result.stderr:print(result.stderr.strip(),flush=True)
            return result.returncode
        plan=next((r for r in records if 'changed_paths' in r),None)
        if plan is None:raise RuntimeError('Instalador nao retornou plano verificavel')
        changed=plan['changed_paths']
        for path in changed:print(('Planejado: ' if args.dry_run else 'Atualizado: ')+path,flush=True)
        if args.dry_run:
            print('SIMULACAO CONCLUIDA. Telegram nao enviado. Execute sem --dry-run para instalar.',flush=True)
            return 0
        applied=next((r for r in records if r.get('status')=='installed'),None)
        if changed and not applied:raise RuntimeError('Confirmacao de aplicacao ausente')
        status='INSTALACAO CONCLUIDA' if changed else 'JA ATUALIZADO — CONFIGURACAO VALIDADA'
        print('\n'+status,flush=True)
        if applied:print('Backup para rollback: '+applied['backup'],flush=True)
        print('Recuperacao automatica: habilitada',flush=True)
        print('SIGKILL exato como ultimo recurso: '+('autorizado' if plan.get('allow_sigkill_exact_mariadb') else 'desabilitado'),flush=True)
        try:health=check_health()
        except Exception:health={'database':False,'radius':False}
        print('MySQL SELECT 1: '+('OK' if health['database'] else 'indisponivel ou nao verificado'),flush=True)
        print('RADIUS processo/portas: '+('OK' if health['radius'] else 'indisponivel ou nao verificado'),flush=True)
        print('Cron: '+('ativo' if health.get('cron') else 'nao confirmado; monitoramento automatico depende do cron'),flush=True)
        print('Agendamento: /etc/cron.d/mkauth-guardian-normal-recovery (a cada 30 segundos)',flush=True)
        print('Sem reinicio de MariaDB, FreeRADIUS, Docker ou cron durante a instalacao.',flush=True)
        print('Log: /var/log/mkauth-guardian-normal-recovery.log',flush=True)
        print('Acompanhar: tail -F /var/log/mkauth-guardian-normal-recovery.log',flush=True)
        print('LIMITACAO: restauracao completa do .maz e falha historica de segmentacao ainda nao certificadas.',flush=True)
        message=status+'\nGuardian Recovery '+VERSION+' (candidato)\nRecuperacao automatica habilitada. SIGKILL exato: '+str(bool(plan.get('allow_sigkill_exact_mariadb')))+'\nMySQL disponivel: '+str(health['database'])+'; RADIUS disponivel: '+str(health['radius'])+'\nSem reinicio de servicos durante a instalacao.\nRestauracao completa do backup ainda nao certificada.'
        message+='\nCron ativo: '+str(bool(health.get('cron')))
        try:sent=deliver(message)
        except Exception:sent=False
        print('Telegram: '+('OK — confirmacao entregue' if sent is True else 'desabilitado na configuracao local' if sent is None else 'FALHOU — instalacao concluida; confira configuracao e conectividade'),flush=True)
        return 0
    except Exception as error:
        print('INSTALACAO RECUSADA: '+str(error),flush=True)
        return 2

if __name__=='__main__':raise SystemExit(main())
