import contextlib
import hashlib
import io
import unittest
from unittest.mock import Mock,patch
import installer_settings as settings

class SetupSettingsTests(unittest.TestCase):
    def setUp(self):
        self.token='123456789:'+('A'*35)
        self.other='987654321:'+('B'*35)
        self.values=dict(MKAUTH_NAME='LOCAL VM',USAR_TELEGRAM='sim',TELEGRAM_BOT=self.token,TELEGRAM_CHAT_ID='-1001234567890')
        self.text=settings.render_settings('GUARDIAN_CUSTOM=preserved\n',self.values)
    def select(self,original=None,answers=(),secrets=(),loader=None,interactive=True):
        read=Mock(side_effect=answers);secret=Mock(side_effect=secrets)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):values=settings.choose_settings(self.text if original is None else original,'DATABASE PROVIDER',interactive=interactive,read=read,secret=secret,loader=loader)
        return values,output.getvalue(),read,secret
    def test_enter_preserves_name_and_credentials_without_download(self):
        loader=Mock(side_effect=AssertionError('No download allowed'))
        values,text,read,secret=self.select(answers=['',''],loader=loader)
        self.assertEqual(values,self.values);loader.assert_not_called();secret.assert_not_called();self.assertNotIn(self.token,text)
    def test_name_change_keeps_credentials(self):
        values,_,_,_=self.select(answers=['NEW VM',''])
        self.assertEqual(values['MKAUTH_NAME'],'NEW VM');self.assertEqual(values['TELEGRAM_BOT'],self.token)
    def test_operator_replaces_credentials_with_hidden_input(self):
        values,text,read,secret=self.select(answers=['','n','-1009876543210'],secrets=[self.other])
        self.assertEqual(values['TELEGRAM_BOT'],self.other);self.assertEqual(values['TELEGRAM_CHAT_ID'],'-1009876543210');secret.assert_called_once();self.assertNotIn(self.other,text)
    def test_change_prompt_enter_keeps_each_existing_value(self):
        values,_,_,_=self.select(answers=['','n',''],secrets=[''])
        self.assertEqual(values,self.values)
    def test_first_install_loads_defaults_and_asks_name(self):
        defaults={k:self.values[k] for k in ('TELEGRAM_BOT','TELEGRAM_CHAT_ID')};loader=Mock(return_value=defaults)
        values,_,read,_=self.select(original='',answers=['FIRST VM',''],loader=loader)
        self.assertEqual(values['MKAUTH_NAME'],'FIRST VM');self.assertEqual(values['TELEGRAM_BOT'],self.token);loader.assert_called_once()
    def test_noninteractive_preserves_without_prompt(self):
        values,_,read,secret=self.select(interactive=False)
        self.assertEqual(values,self.values);read.assert_not_called();secret.assert_not_called()
    def test_disabled_telegram_is_preserved_without_default_fetch(self):
        original='MKAUTH_NAME=LOCAL\nUSAR_TELEGRAM=nao\n';loader=Mock(side_effect=AssertionError('No download'))
        values,_,_,_=self.select(original=original,answers=['',''],loader=loader)
        self.assertEqual(values['USAR_TELEGRAM'],'nao');loader.assert_not_called()
    def test_unavailable_default_source_allows_private_manual_input(self):
        loader=Mock(side_effect=RuntimeError('Unavailable'))
        values,text,_,secret=self.select(original='',answers=['FIRST VM','-1001234567890',''],secrets=[self.token],loader=loader)
        self.assertEqual(values['TELEGRAM_BOT'],self.token);secret.assert_called_once();self.assertNotIn(self.token,text)
    def test_source_hash_mismatch_is_rejected_before_parsing(self):
        with self.assertRaises(RuntimeError):settings.defaults_from_source(b'untrusted source')
    def test_verified_source_is_read_as_data_never_executed(self):
        source=('TELEGRAM_BOT="'+self.token+'"\nTELEGRAM_CHAT_ID="-1001234567890"\ntouch /SHOULD_NEVER_EXIST\n').encode()
        with patch.object(settings,'LEGACY_SHA256',hashlib.sha256(source).hexdigest()):values=settings.defaults_from_source(source)
        self.assertEqual(values['TELEGRAM_BOT'],self.token)
    def test_invalid_new_token_is_not_in_error_message(self):
        bad='private-invalid-token'
        with self.assertRaises(RuntimeError) as error:self.select(answers=['','n',''],secrets=[bad])
        self.assertNotIn(bad,str(error.exception))
    def test_roundtrip_shell_quoted_name_and_preserve_other_options(self):
        values=dict(self.values,MKAUTH_NAME="VM 'with spaces' $(not-a-command)")
        text=settings.render_settings(self.text,values)
        self.assertEqual(settings.parse_settings(text),values);self.assertIn('GUARDIAN_CUSTOM=preserved',text)
        self.assertEqual(settings.render_settings(text,values),text)
    def test_control_characters_in_name_are_rejected(self):
        values=dict(self.values,MKAUTH_NAME='bad\nname')
        with self.assertRaises(RuntimeError):settings.render_settings(self.text,values)

if __name__=='__main__':unittest.main()
