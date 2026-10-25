import unittest
from radius_signals import count_unfinished

class RadiusSignalTests(unittest.TestCase):
    def test_real_format_bare_accounting_sql(self):
        self.assertEqual(count_unfinished(b'Ignoring duplicate packet from client synthetic due to unfinished request in component accounting module sql\n'),1)
    def test_bracketed_core_queue_is_preserved(self):
        self.assertEqual(count_unfinished(b'unfinished request in component <core> module <queue>\n'),1)
    def test_bare_sqlippool(self):
        self.assertEqual(count_unfinished(b'unfinished request in component accounting module sqlippool\n'),1)
    def test_preacct(self):
        self.assertEqual(count_unfinished(b'unfinished request in component accounting module <preacct>\n'),1)
    def test_case_insensitive_crlf(self):
        self.assertEqual(count_unfinished(b'UNFINISHED REQUEST IN COMPONENT ACCOUNTING MODULE SQL\r\n'),1)
    def test_counts_repeated_messages(self):
        self.assertEqual(count_unfinished(b'unfinished request in component accounting module sql\n'*37),37)
    def test_unrelated_duplicate_is_not_a_stuck_request(self):
        self.assertEqual(count_unfinished(b'Ignoring duplicate packet\nOpening additional connection sql\n'),0)
    def test_unrelated_module_or_split_messages_do_not_match(self):
        self.assertEqual(count_unfinished(b'unfinished request in component accounting module sqljunk\nunfinished request in component x\nmodule sql\n'),0)

if __name__=='__main__':unittest.main()
