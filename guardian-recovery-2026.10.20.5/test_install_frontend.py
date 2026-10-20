import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch
import install_frontend as frontend

class AutomaticInstallTests(unittest.TestCase):
    def invoke(self,args=(),code=0,changed=True,delivery=True):
        records=[{'mode':'apply','changed_paths':['/synthetic/config'] if changed else [],'allow_sigkill_exact_mariadb':False}]
        if changed:records.append({'status':'installed','backup':'/synthetic/rollback'})
        completed=subprocess.CompletedProcess([],code,'\n'.join(json.dumps(r) for r in records),'')
        output=io.StringIO()
        with patch.object(frontend,'mysql_read',return_value='DB PROVIDER\n'),patch.object(frontend,'prepared_config',return_value=contextlib.nullcontext((None,'LOCAL VM'))),patch.object(frontend.subprocess,'run',return_value=completed) as runner,patch.object(frontend,'check_health',return_value={'database':True,'radius':True}),patch.object(frontend,'deliver',return_value=delivery) as notifier,contextlib.redirect_stdout(output):
            result=frontend.main(list(args))
        return result,output.getvalue(),runner,notifier
    def test_no_argument_installs_using_database_identity_preserving_local_label(self):
        code,text,run,notify=self.invoke()
        self.assertEqual(code,0);self.assertIn('MK-AUTH/VM: LOCAL VM',text)
        command=run.call_args[0][0];self.assertEqual(command[command.index('--expected-provider')+1],'DB PROVIDER')
        self.assertIn('--apply',command);self.assertIn('--enable-normal-recovery',command);self.assertNotIn('--allow-sigkill-exact-mariadb',command)
        notify.assert_called_once()
    def test_wrong_explicit_provider_never_applies_or_notifies(self):
        code,text,run,notify=self.invoke(['--expected-provider','WRONG'])
        self.assertEqual(code,2);run.assert_not_called();notify.assert_not_called()
    def test_failed_install_never_sends_success(self):
        code,text,run,notify=self.invoke(code=3)
        self.assertEqual(code,3);notify.assert_not_called();self.assertNotIn('Telegram: OK',text)
    def test_dry_run_never_applies_or_sends_telegram(self):
        code,text,run,notify=self.invoke(['--dry-run'])
        self.assertEqual(code,0);self.assertNotIn('--apply',run.call_args[0][0]);notify.assert_not_called()
    def test_telegram_failure_does_not_claim_delivery(self):
        code,text,run,notify=self.invoke(delivery=False)
        self.assertEqual(code,0);self.assertIn('Telegram: FALHOU',text);self.assertNotIn('Telegram: OK',text)
    def test_telegram_disabled_is_distinct_from_delivery(self):
        code,text,run,notify=self.invoke(delivery=None)
        self.assertEqual(code,0);self.assertIn('Telegram: desabilitado',text)
    def test_idempotent_run_reports_validated_instead_of_reinstalled(self):
        code,text,run,notify=self.invoke(changed=False)
        self.assertEqual(code,0);self.assertIn('JA ATUALIZADO',text);self.assertNotIn('Backup para rollback:',text)

if __name__=='__main__':unittest.main()
