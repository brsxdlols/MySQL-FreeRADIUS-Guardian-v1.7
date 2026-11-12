import unittest
from unittest.mock import patch,Mock
import install_frontend as f
class TelegramFollowupTests(unittest.TestCase):
 def run_case(self,results,choices,repair=True,interactive=True):
  callback=Mock(return_value=repair)
  with patch.object(f,'deliver',side_effect=results) as send:
   result=f.telegram_followup({},interactive,callback,read=Mock(side_effect=choices))
  return result,send,callback
 def test_retry_after_failure(self):
  result,send,fix=self.run_case([False,True],['2']);self.assertTrue(result);self.assertEqual(send.call_count,2);fix.assert_not_called()
 def test_repair_then_deliver(self):
  result,send,fix=self.run_case([False,True],['1']);self.assertTrue(result);fix.assert_called_once()
 def test_ignore_does_not_send_again(self):
  result,send,fix=self.run_case([False],['']);self.assertFalse(result);self.assertEqual(send.call_count,1);fix.assert_not_called()
 def test_noninteractive_never_prompts(self):
  result,send,fix=self.run_case([False],[],interactive=False);self.assertFalse(result);self.assertEqual(send.call_count,1)
 def test_disabled_never_prompts(self):
  result,send,fix=self.run_case([None],[]);self.assertIsNone(result)
 def test_failed_repair_can_be_ignored(self):
  result,send,fix=self.run_case([False],['1','3'],repair=False);self.assertFalse(result);self.assertEqual(send.call_count,1)
 def test_retry_limit(self):
  result,send,fix=self.run_case([False]*6,['2']*5);self.assertFalse(result);self.assertEqual(send.call_count,6)
