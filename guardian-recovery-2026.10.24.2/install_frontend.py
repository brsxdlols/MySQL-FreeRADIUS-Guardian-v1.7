#!/usr/bin/env python3
"""Automatic installer UI. Existing local names and credentials are preserved."""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import os
from guardian_safety import mysql_read
from legacy_migration import read_legacy
from installer_settings import choose_settings,render_settings

VERSION='2026.10.24.2'

@contextlib.contextmanager
def prepared_config(provider,args):
    path=Path('/etc/default/check_backup_freeradius')
    if path.is_symlink():raise RuntimeError('Configuracao local nao pode ser symlink')
    original=path.read_bytes() if path.exists() else None
    interactive=not(args.dry_run or args.non_interactive)
    if interactive and not sys.stdin.isatty():raise RuntimeError('Terminal interativo necessario; use --non-interactive para manter os valores automaticamente')
    setup_text=original.decode('utf-8') if original is not None else ''
    legacy_hash=None
    legacy=Path('/var/check_backup_freeradius.sh')
    if original is None and (legacy.exists() or legacy.is_symlink()):
        credentials,legacy_hash=read_legacy(legacy)
        import shlex
        setup_text=''.join(key+'='+shlex.quote(value)+'\n' for key,value in credentials.items())
        print('Telegram recuperado de monitor legado revisado; credenciais preservadas sem executar o script.',flush=True)
    values=choose_settings(setup_text,provider,interactive=interactive)
    content=render_settings(original.decode('utf-8') if original is not None else '',values)
    with tempfile.TemporaryDirectory(prefix='mkauth-guardian-settings.',dir='/root') as folder:
        candidate=Path(folder)/'config.json'
        data={'base_sha256':hashlib.sha256(original).hexdigest() if original is not None else None,'content':content,'legacy_source_sha256':legacy_hash}
        fd=os.open(str(candidate),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(data,stream)
        yield str(candidate),values['MKAUTH_NAME']

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
    parser.add_argument('--allow-sigkill-exact-radius',action='store_true',help='Autorizar SIGKILL somente no PID exato do RADIUS apos TERM e prazo')
    parser.add_argument('--cancel-redundant-radius-ddl',action='store_true',help='Cancelar somente ALTER de collation redundante em espera nas tabelas RADIUS')
    parser.add_argument('--restart-database-on-persistent-queue',action='store_true',help='Recuperar MariaDB e RADIUS apos quatro amostras consecutivas de fila travada')
    parser.add_argument('--non-interactive',action='store_true',help='Manter nome e Telegram sem perguntas; configuracao ausente usa padroes verificados do datacenter')
    args=parser.parse_args(argv)
    print('\n==========================================================\n GUARDIAN RECOVERY '+VERSION+' — CANDIDATO\n INSTALACAO AUTOMATICA / CONFIGURACAO LOCAL PRESERVADA\n==========================================================',flush=True)
    try:
        provider=mysql_read('SELECT nome FROM mkradius.sis_provedor LIMIT 1;').strip()
        if not provider:raise RuntimeError('Nao foi possivel identificar o provedor no banco')
        if args.expected_provider is not None and args.expected_provider!=provider:
            raise RuntimeError('Provider mismatch: verificacao adicional recusada')
        print('Provedor detectado no banco: '+provider,flush=True)
        print('Modo: '+('SIMULACAO, sem alteracoes' if args.dry_run else 'APLICACAO AUTOMATICA'),flush=True)
        print('Verificando compatibilidade, locks, arquivos e plano de rollback...',flush=True)
        command=[sys.executable,str(Path(__file__).with_name('install.py')),'--expected-provider',provider,'--enable-normal-recovery']
        if not args.dry_run:command.append('--apply')
        if args.allow_sigkill_exact_mariadb:command.append('--allow-sigkill-exact-mariadb')
        for flag in ['allow_sigkill_exact_radius','cancel_redundant_radius_ddl','restart_database_on_persistent_queue']:
            if getattr(args,flag):command.append('--'+flag.replace('_','-'))
        with prepared_config(provider,args) as prepared:
            candidate,label=prepared
            print('MK-AUTH/VM: '+label,flush=True)
            if candidate:command+=['--local-config-file',candidate]
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
        if plan.get('backup_supervision') is False:
            print('BACKUP: cron nativo preservado. Supervisor de backup PENDENTE: modelo requer homologacao; nenhuma tabela ou caminho foi ignorado para liberar a instalacao.',flush=True)
        elif plan.get('backup_supervision') is True:print('BACKUP: agendamento supervisionado configurado; cada arquivo ainda depende de validacao e teste de restauracao.',flush=True)
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
        print('SIGKILL no PID exato do FreeRADIUS: '+('autorizado' if plan.get('allow_sigkill_exact_radius') else 'desabilitado'),flush=True)
        print('Recuperar banco e RADIUS em fila persistente: '+('sim' if plan.get('restart_database_on_persistent_queue') else 'politica anterior'),flush=True)
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
        message={'event':'installation','version':VERSION,'status':status,'health':health,'allow_sigkill':bool(plan.get('allow_sigkill_exact_mariadb')),'allow_radius_sigkill':bool(plan.get('allow_sigkill_exact_radius')),'backup_supervision':plan.get('backup_supervision')}
        try:sent=deliver(message)
        except Exception:sent=False
        print('Telegram: '+('OK — confirmacao entregue' if sent is True else 'desabilitado na configuracao local' if sent is None else 'FALHOU — instalacao concluida; confira configuracao e conectividade'),flush=True)
        return 0
    except Exception as error:
        print('INSTALACAO RECUSADA: '+str(error),flush=True)
        return 2

if __name__=='__main__':raise SystemExit(main())
