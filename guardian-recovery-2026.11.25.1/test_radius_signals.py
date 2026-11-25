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

class QueueCapacitySignalTests(unittest.TestCase):
    line=b'Error: Something is blocking the server.  There are 65536 packets in the queue, waiting to be processed.  Ignoring the new request.\n'
    def test_exact_production_warning_without_unfinished(self):
        from radius_signals import count_queue_full
        self.assertEqual(count_queue_full(self.line),1);self.assertEqual(count_unfinished(self.line),0)
    def test_other_positive_queue_capacities(self):
        from radius_signals import count_queue_full
        self.assertEqual(count_queue_full(self.line.replace(b'65536',b'4096')),1)
    def test_zero_or_missing_capacity_is_not_accepted(self):
        from radius_signals import count_queue_full
        for number in [b'0',b'-1',b'']:
            self.assertEqual(count_queue_full(self.line.replace(b'65536',number)),0)
    def test_case_and_spaces_and_crlf(self):
        from radius_signals import count_queue_full
        self.assertEqual(count_queue_full(self.line.upper().replace(b'  ',b'\t').replace(b'\n',b'\r\n')),1)
    def test_many_complete_warnings_count_once_each(self):
        from radius_signals import count_queue_full
        self.assertEqual(count_queue_full(self.line*7),7)
    def test_incomplete_warning_or_multiline_fragment_is_not_accepted(self):
        from radius_signals import count_queue_full
        for data in [b'Something is blocking the server.',self.line.replace(b'  There',b'\nThere'),self.line.replace(b'Ignoring the new request.',b'')]:
            self.assertEqual(count_queue_full(data),0)

class QueueCapacityLogBoundaryTests(unittest.TestCase):
    def test_actual_dated_radius_log(self):
        from radius_signals import count_queue_full
        self.assertEqual(count_queue_full(b'Fri Nov 20 09:24:59 2026 : '+QueueCapacitySignalTests.line),1)
    def test_warning_text_inside_auth_log_is_not_server_saturation(self):
        from radius_signals import count_queue_full
        self.assertEqual(count_queue_full(b'Fri Nov 20 09:24:59 2026 : Auth: Login incorrect ['+QueueCapacitySignalTests.line.rstrip()+b']\n'),0)
