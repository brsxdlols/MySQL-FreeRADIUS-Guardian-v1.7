import unittest
from ddl_guard import cancel_redundant,LOCK_QUERY,TABLES
class Sql:
    def __init__(self):
        self.query="ALTER TABLE radpostauth COLLATE='latin1_swedish_ci'";self.collation='latin1_swedish_ci';self.schema='mkradius';self.seconds=3600;self.state='Waiting for table metadata lock';self.query_id=12345;self.kills=[];self.change=False;self.evidence=[];self.fail_evidence=False
    def row(self):return '100\t'+self.schema+'\t'+str(self.seconds)+'\t'+self.state+'\t'+str(self.query_id)+'\t'+self.query+'\n'
    def sql(self,q):
        if q.startswith('KILL'):self.kills.append(q);return ''
        if q.startswith('SELECT TABLE_COLLATION'):return self.collation+'\n'
        if 'WHERE ID=100' in q:
            if self.change:self.query_id+=1
            return self.row()
        return self.row()
    def save(self,r):
        if self.fail_evidence:raise OSError('disk full')
        self.evidence.append(r)
class DdlTests(unittest.TestCase):
    def test_confirmed_redundant_waiter_uses_query_id(self):
        b=Sql();r=cancel_redundant(b.sql,b.save);self.assertEqual(r['table'],'radpostauth');self.assertEqual(b.kills,['KILL QUERY ID 12345;']);self.assertEqual(len(b.evidence),1)
    def test_different_collation_never_cancelled(self):
        b=Sql();b.collation='utf8_general_ci';self.assertIsNone(cancel_redundant(b.sql,b.save));self.assertEqual(b.kills,[])
    def test_different_sql_or_non_allowlisted_table_never_cancelled(self):
        for query in ["ALTER TABLE customers COLLATE='latin1_swedish_ci'","ALTER TABLE radacct ENGINE=InnoDB","ALTER TABLE radpostauth COLLATE='latin1_swedish_ci'; DROP TABLE x","ALTER TABLE radpostauth COLLATE='latin1_swedish_ci' -- note"]:
            b=Sql();b.query=query;self.assertIsNone(cancel_redundant(b.sql,b.save));self.assertEqual(b.kills,[])
    def test_short_or_executing_ddl_never_cancelled(self):
        for seconds,state in [(10,'Waiting for table metadata lock'),(600,'copy to tmp table')]:
            b=Sql();b.seconds=seconds;b.state=state;self.assertIsNone(cancel_redundant(b.sql,b.save))
    def test_changed_query_id_never_cancelled(self):
        b=Sql();b.change=True;self.assertIsNone(cancel_redundant(b.sql,b.save));self.assertEqual(b.kills,[])
    def test_zero_query_id_never_cancelled(self):
        b=Sql();b.query_id=0;self.assertIsNone(cancel_redundant(b.sql,b.save))
    def test_other_database_never_cancelled(self):
        b=Sql();b.schema='other';self.assertIsNone(cancel_redundant(b.sql,b.save))
    def test_evidence_failure_prevents_cancel(self):
        b=Sql();b.fail_evidence=True
        with self.assertRaises(OSError):cancel_redundant(b.sql,b.save)
        self.assertEqual(b.kills,[])
    def test_critical_query_includes_every_radius_table(self):
        for table in TABLES:self.assertIn(table,LOCK_QUERY)
if __name__=='__main__':unittest.main()
