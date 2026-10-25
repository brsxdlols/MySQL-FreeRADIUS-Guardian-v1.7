import unittest
import urllib.parse
from unittest.mock import patch, MagicMock
from notification_messages import render


class NotificationTests(unittest.TestCase):
    def make(self, event, **fields):
        record = {'started':1600000000, 'reason':'database_unavailable',
                  'database':True, 'allow_sigkill':True,
                  'initial_health':{'database':False,'radius':True,'queue_errors':17},
                  'evidence_path':'/root/private-incident'}
        payload = dict(event=event,record=record,**fields)
        return render(payload, 'VM TESTE',hostname='host-test',now=1600000065)

    def test_installation_human_status_and_identity(self):
        text=self.make('installation',version='test',status='INSTALACAO CONCLUIDA',health={'database':True,'radius':True,'cron':True},allow_sigkill=True)
        self.assertIn('MK-AUTH/VM: VM TESTE',text)
        self.assertIn('Servidor Linux: host-test',text)
        self.assertIn('Cron: ativo',text)
        self.assertIn('respondendo',text)
        self.assertNotIn('True',text)

    def test_pending_backup_is_visible_in_installation_telegram(self):
        text=self.make('installation',version='test',status='INSTALACAO CONCLUIDA',backup_supervision=False)
        self.assertIn('agendamento nativo preservado',text);self.assertIn('PENDENTE',text)

    def test_supervised_backup_does_not_claim_restore_certification(self):
        text=self.make('installation',version='test',status='INSTALACAO CONCLUIDA',backup_supervision=True)
        self.assertIn('agendamento supervisionado configurado',text);self.assertIn('cada novo arquivo',text)

    def test_unconfirmed_health_does_not_claim_available(self):
        text=self.make('installation',version='test',status='VALIDADA',health={})
        self.assertIn('não confirmado',text)
        self.assertNotIn('UDP 1812/1813: disponíveis',text)

    def test_begin_has_evidence_duration_scope_and_no_success(self):
        text=self.make('recovery_begin')
        for item in ['65s','SELECT 1','17','MariaDB e FreeRADIUS','/root/private-incident']:
            self.assertIn(item,text)
        self.assertNotIn('INCIDENTE RESOLVIDO',text)

    def test_done_does_not_claim_complete_functional_recovery(self):
        text=self.make('recovery_done',health={'database':True,'radius':True})
        self.assertIn('ainda exigem validação funcional',text)
        self.assertIn('SIGKILL utilizado: não',text)
        self.assertNotIn('INCIDENTE RESOLVIDO',text)

    def test_escalation_identifies_signal_and_pid(self):
        text=self.make('escalation',signal='KILL',pid=123)
        self.assertIn('Sinal enviado: SIGKILL',text)
        self.assertIn('PID MariaDB confirmado: 123',text)

    def test_manual_reports_stopped_and_no_automatic_loop(self):
        text=self.make('recovery_manual')
        self.assertIn('RECUPERAÇÃO INTERROMPIDA',text)
        self.assertIn('Sem início duplicado',text);self.assertIn('monitor continua',text)

    def test_unknown_reason_and_error_never_leak_sql_or_secret(self):
        p={'event':'recovery_manual','record':{'reason':'SECRET_USER SQL UPDATE x', 'error':'SECRET_TOKEN', 'raw_sql':'SECRET_DATA'}}
        text=render(p,'VM',hostname='host',now=1600000000)
        self.assertNotIn('SECRET',text)

    def test_legacy_state_without_evidence_or_started_is_supported(self):
        text=render({'event':'recovery_done','record':{},'health':{}},'VM',hostname='host',now=1600000000)
        self.assertIn('não registrado',text)
        self.assertIn('/var/log/mkauth-guardian-normal-recovery.log',text)


class NotificationTransportTests(unittest.TestCase):
    def send(self, message):
        import guardian_controller as controller
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"ok":true}'
        config="USAR_TELEGRAM=sim\nTELEGRAM_BOT=123:fake-unit-test-token\nTELEGRAM_CHAT_ID=-1\nMKAUTH_NAME='VM TESTE'\n"
        with patch.object(controller,'Path') as paths,patch.object(controller,'log'),patch.object(controller.urllib.request,'urlopen',return_value=response) as sender:
            paths.return_value.read_text.return_value=config
            ok=controller.notify(message)
        self.assertTrue(ok)
        body=urllib.parse.parse_qs(sender.call_args[1]['data'].decode())
        return body['text'][0]

    def test_structured_installation_reaches_transport_as_text(self):
        text=self.send({'event':'installation','version':'test','status':'VALIDADA','health':{}})
        self.assertIn('MK-AUTH/VM: VM TESTE',text)
        self.assertIn('MONITOR MK-AUTH',text)

    def test_legacy_backup_message_still_preserves_local_label(self):
        self.assertIn('VM TESTE',self.send('Backup verificado'))


if __name__=='__main__':unittest.main()
