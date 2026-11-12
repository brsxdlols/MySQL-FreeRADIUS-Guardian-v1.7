import unittest
from unittest.mock import patch
import guardian_safety
class DiagnosticTimeoutTests(unittest.TestCase):
    def test_diagnostics_have_server_side_timeout_not_just_client_timeout(self):
        with patch.object(guardian_safety.Path,'is_file',return_value=True),patch.object(guardian_safety.subprocess,'check_output',return_value=b'1\n') as run:
            self.assertEqual(guardian_safety.mysql_read('SELECT 1;'),'1\n')
        command=run.call_args[0][0]
        self.assertEqual(command[-1],'SET SESSION max_statement_time=8; SELECT 1;')
        self.assertEqual(run.call_args[1]['timeout'],12)
        self.assertNotIn('GLOBAL',command[-1])
if __name__=='__main__':unittest.main()
