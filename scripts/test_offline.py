"""Offline mount boundaries, archive rejection, report preservation and publication race."""
import concurrent.futures
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import offline
from pair_protocol import publish


class OfflineBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.input=self.root/'input';self.output=self.root/'output'
        self.input.mkdir();self.output.mkdir()

    def test_input_escape_refused_and_read_path_not_changed(self):
        value=self.input/'capture.json';value.write_text('{}')
        self.assertEqual(offline.within(value,self.input),value.resolve())
        with self.assertRaises(ValueError):offline.within(self.output,self.input)
        self.assertEqual(value.read_text(),'{}')

    def test_reports_cannot_overwrite_or_escape_output_mount(self):
        value={'status':'action_windows_verified','diagnostic_only':True,'benchmark_accepted':False}
        with patch.object(offline,'OUTPUT',self.output):
            paths=offline.write_reports(value,self.output,'diagnostic')
            before=[Path(p).read_bytes() for p in paths]
            with self.assertRaises(ValueError):offline.write_reports(value,self.output,'diagnostic')
            with self.assertRaises(ValueError):offline.write_reports(value,self.input,'elsewhere')
            for name in ('../escape','a/b','a:b',''):
                with self.assertRaises(ValueError):offline.write_reports(value,self.output,name)
        self.assertEqual(before,[Path(p).read_bytes() for p in paths])
        self.assertIn('Do not use these frame values',Path(paths[1]).read_text())

    def test_archive_inspection_is_read_only_and_rejects_unsafe_entries(self):
        path=self.input/'world.zip'
        for entries,valid in (({'Root/level.dat':b'fixture'},True),
                              ({'Root/level.dat':b'fixture','Root/../escape':b'x'},False),
                              ({'Root/level.dat':b'x','Root/LEVEL.DAT':b'y'},False)):
            with zipfile.ZipFile(path,'w') as z:
                for name,raw in entries.items():z.writestr(name,raw)
            before=path.read_bytes()
            if valid:self.assertEqual(offline.inspect_world(path)['files'],1)
            else:
                with self.assertRaises(ValueError):offline.inspect_world(path)
            self.assertEqual(path.read_bytes(),before)
        self.assertEqual(list(self.input.iterdir()),[path])

    def test_atomic_publication_has_exactly_one_winner(self):
        path=self.output/'claim.json'
        def attempt(value):
            try:publish(path,{'writer':value});return value
            except FileExistsError:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
            results=list(workers.map(attempt,(1,2)))
        winners=[r for r in results if r is not None]
        self.assertEqual(len(winners),1)
        self.assertEqual(json.loads(path.read_text())['writer'],winners[0])
        self.assertFalse(list(self.output.glob('*.tmp')))

    def test_live_host_commands_are_not_exposed(self):
        for command in ('broker','prepare','launch','measured-auto-launch'):
            with patch('sys.stderr',new=io.StringIO()),self.assertRaises(SystemExit):offline.main([command])


if __name__=='__main__':unittest.main()
