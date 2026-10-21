import tempfile
import unittest
from pathlib import Path
from compatible_backup import split_dump

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
