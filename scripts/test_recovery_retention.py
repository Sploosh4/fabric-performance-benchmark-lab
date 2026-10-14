"""Deletion-boundary checks on tiny synthetic worlds only."""
import json
from pathlib import Path
import tempfile
import unittest
from recovery_retention import register,prune


class RecoveryRetention(unittest.TestCase):
    def world(self,root,name):
        path=root/name;path.mkdir();(path/'level.dat').write_bytes(b'fixture');return path

    def test_one_receipted_copy_kept_unknown_history_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            old=self.world(root,'20261010-100000-aaaaaaaa')
            new=self.world(root,'20261010-110000-bbbbbbbb')
            unknown=self.world(root,'20261010-090000')
            for path in (old,new):register(root,path,'a'*64,'owned-test-world')
            self.assertEqual(prune(root,new.name,'a'*64,'owned-test-world'),[old.name])
            self.assertFalse(old.exists());self.assertTrue(new.exists());self.assertTrue(unknown.exists())

    def test_modified_copy_prevents_cleanup_without_deleting_other_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=self.world(root,'20261010-100000-aaaaaaaa');new=self.world(root,'20261010-110000-bbbbbbbb')
            for path in (old,new):register(root,path,'a'*64,'owned-test-world')
            (old/'level.dat').write_bytes(b'changed')
            with self.assertRaises(ValueError):prune(root,new.name,'a'*64,'owned-test-world')
            self.assertTrue(old.exists());self.assertTrue(new.exists())

    def test_outside_root_wrong_source_and_missing_keep_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'copies';root.mkdir()
            outside=self.world(base,'20261010-100000-aaaaaaaa')
            with self.assertRaises(ValueError):register(root,outside,'a'*64,'owned-test-world')
            keep=self.world(root,'20261010-110000-bbbbbbbb')
            with self.assertRaises(ValueError):prune(root,keep.name,'a'*64,'owned-test-world')
            register(root,keep,'a'*64,'owned-test-world')
            with self.assertRaises(ValueError):prune(root,keep.name,'b'*64,'owned-test-world')
            self.assertTrue(outside.exists());self.assertTrue(keep.exists())


if __name__=='__main__':unittest.main()
