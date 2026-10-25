import tempfile
import unittest
import io
import tarfile
from unittest.mock import patch
from pathlib import Path
from compatible_backup import split_dump
import compatible_backup as backup

class TemplateTests(unittest.TestCase):
    def archive(self,path,complete=True):
        tables=['radacct','radippool','sis_cliente','sis_provedor']
        with tarfile.open(str(path),'w:bz2') as archive:
            for table in tables:
                data=('CREATE TABLE `'+table+'` (id int);\n'+('-- Dump completed\n' if complete else '')).encode()
                member=tarfile.TarInfo('opt/mk-auth/dados/LAB/'+table+'.sql');member.size=len(data);archive.addfile(member,io.BytesIO(data))
            data=''.join('source /opt/mk-auth/dados/LAB/'+table+'.sql;\n' for table in tables).encode()
            member=tarfile.TarInfo('opt/mk-auth/bckp/tarbackup.sql');member.size=len(data);archive.addfile(member,io.BytesIO(data))
        return tables

    def test_small_complete_backup_is_a_valid_template(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'SMALL.maz';tables=self.archive(path)
            self.assertLess(path.stat().st_size,100000)
            with patch.object(backup,'BACKUPS',root),patch.object(backup,'mysql_read',return_value='\n'.join(tables)):
                result=backup.discover_template()
            self.assertEqual(result['tables'],tables)

    def test_small_incomplete_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.archive(root/'INCOMPLETE.maz',False)
            with patch.object(backup,'BACKUPS',root),self.assertRaisesRegex(RuntimeError,'No structurally validated'):
                backup.discover_template()

class SplitTests(unittest.TestCase):
    def dump(self):
        return b'-- MariaDB dump\n/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;\n-- Table structure for table `radacct`\nCREATE TABLE `radacct` (id int);\nINSERT INTO `radacct` VALUES (1);\n-- Table structure for table `radippool`\nCREATE TABLE `radippool` (id int);\n/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;\n-- Dump completed on synthetic test\n'
    def test_each_native_source_has_own_header_schema_and_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);dump=root/'all.sql';dump.write_bytes(self.dump());output=root/'sql';output.mkdir()
            split_dump(dump,output,['radacct','radippool'])
            for table in ['radacct','radippool']:
                data=(output/(table+'.sql')).read_bytes();self.assertIn(b'@OLD_CHARACTER_SET_CLIENT=',data);self.assertIn(('CREATE TABLE `'+table+'`').encode(),data);self.assertIn(b'Dump completed',data)
            self.assertNotIn(b'CREATE TABLE `radippool`',(output/'radacct.sql').read_bytes())
    def test_missing_table_is_not_publishable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);dump=root/'all.sql';dump.write_bytes(self.dump());output=root/'sql';output.mkdir()
            with self.assertRaises(RuntimeError):split_dump(dump,output,['radacct','radippool','sis_cliente'])
    def test_absent_completion_is_not_publishable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);dump=root/'all.sql';dump.write_bytes(self.dump().replace(b'-- Dump completed on synthetic test\n',b''));output=root/'sql';output.mkdir()
            with self.assertRaises(RuntimeError):split_dump(dump,output,['radacct','radippool'])

if __name__=='__main__':unittest.main()
