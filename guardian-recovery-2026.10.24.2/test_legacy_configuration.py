import contextlib,hashlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import install_frontend as frontend
from installer_settings import choose_settings,parse_settings
FIXTURE=Path(__file__).with_name('legacy_monitor_fixture.sh').read_bytes()
class LegacyConfigurationTests(unittest.TestCase):
 def setup(self,original=None,bad=False):
  folder=tempfile.TemporaryDirectory();root=Path(folder.name);legacy=root/'monitor';legacy.write_bytes(b'unknown' if bad else FIXTURE);legacy.chmod(0o700);cnf=root/'config'
  if original is not None:cnf.write_text(original)
  actual=Path
  def mapped(value):
   return cnf if str(value)=='/etc/default/check_backup_freeradius' else legacy if str(value)=='/var/check_backup_freeradius.sh' else actual(value)
  return folder,cnf,legacy,mapped
 def choose(self,text,provider,interactive):
  return choose_settings(text,provider,interactive=False,loader=Mock(side_effect=AssertionError('Must preserve existing Telegram')))
 def test_absent_config_recovers_embedded_telegram_without_execution(self):
  folder,cnf,legacy,mapped=self.setup()
  try:
   with patch.object(frontend,'Path',side_effect=mapped),patch.object(frontend,'choose_settings',side_effect=self.choose),patch.object(frontend.subprocess,'run') as execute,contextlib.redirect_stdout(io.StringIO()) as output:
    args=type('Args',(),{'dry_run':True,'non_interactive':True})()
    with frontend.prepared_config('FIXTURE PROVIDER',args) as (file,label):
     candidate=json.loads(Path(file).read_text());v=parse_settings(candidate['content']);self.assertEqual(v['TELEGRAM_CHAT_ID'],'-1001234567890');self.assertEqual(label,'FIXTURE PROVIDER');self.assertIsNone(candidate['base_sha256']);self.assertEqual(candidate['legacy_source_sha256'],hashlib.sha256(FIXTURE).hexdigest())
    execute.assert_not_called();self.assertFalse(cnf.exists());self.assertNotIn('123456789:',output.getvalue())
  finally:folder.cleanup()
 def test_existing_local_settings_override_embedded_values(self):
  original="MKAUTH_NAME='LOCAL LABEL'\nUSAR_TELEGRAM=nao\n"
  folder,cnf,legacy,mapped=self.setup(original,bad=True)
  try:
   with patch.object(frontend,'Path',side_effect=mapped),patch.object(frontend,'choose_settings',side_effect=self.choose),patch.object(frontend,'read_legacy') as reader:
    args=type('Args',(),{'dry_run':True,'non_interactive':True})()
    with frontend.prepared_config('DB LABEL',args) as (file,label):self.assertEqual(label,'LOCAL LABEL');self.assertIsNone(json.loads(Path(file).read_text())['legacy_source_sha256'])
    reader.assert_not_called();self.assertEqual(cnf.read_text(),original)
  finally:folder.cleanup()
 def test_unknown_legacy_does_not_fetch_defaults_or_create_config(self):
  folder,cnf,legacy,mapped=self.setup(bad=True)
  try:
   with patch.object(frontend,'Path',side_effect=mapped),patch.object(frontend,'choose_settings') as chooser:
    args=type('Args',(),{'dry_run':True,'non_interactive':True})()
    with self.assertRaises(RuntimeError):
     with frontend.prepared_config('DB LABEL',args):pass
    chooser.assert_not_called();self.assertFalse(cnf.exists())
  finally:folder.cleanup()
if __name__=='__main__':unittest.main()
