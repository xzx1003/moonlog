"""Parser tests use fabricated fixtures, never production accuracy evidence."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from real import load_dataset


def fixture():
    start=dt.datetime(2026,1,1)
    fmt=lambda t:t.strftime('%Y-%m-%dT%H:%M:%SZ')
    return dict(schema_version=1,bucket_minutes=5,kind='real-incident',
                dataset_id='parser-test-only', provenance='fabricated unit fixture',
                annotation_method='test only',annotator='unit test',
                annotation_frozen_at='2026-01-02T00:00:00Z',traces=[dict(id='one',
                buckets=[dict(start=fmt(start+dt.timedelta(minutes=5*i)),total=10,errors=0) for i in range(16)],
                annotations=[dict(start=fmt(start+dt.timedelta(minutes=60)),
                                  end_exclusive=fmt(start+dt.timedelta(minutes=70)),
                                  label='incident',evidence='fabricated assertion')])])


class RealInput(unittest.TestCase):
    def load(self,d):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.json';path.write_text(json.dumps(d))
            return load_dataset(path)

    def test_unannotated_is_unknown_and_intervals_exclusive(self):
        _,cases,digest=self.load(fixture())
        self.assertEqual(cases[0]['labels'],[None]*12+[True,True,None,None])
        self.assertEqual(len(digest),64)

    def test_invalid_inputs(self):
        mutations=[
            lambda d:d.update(kind='synthetic'),
            lambda d:d['traces'][0]['buckets'][1].update(start='2026-01-01T00:10:00Z'),
            lambda d:d['traces'][0]['buckets'][0].update(errors=11),
            lambda d:d['traces'][0]['buckets'][0].update(total=True),
            lambda d:d['traces'][0]['annotations'][0].update(evidence=''),
            lambda d:d['traces'][0]['annotations'][0].update(start='2026-01-01T00:01:00Z'),
            lambda d:d['traces'][0]['annotations'][0].update(end_exclusive='2026-01-02T00:00:00Z'),
        ]
        for mutate in mutations:
            d=fixture();mutate(d)
            with self.subTest(d=d),self.assertRaises(ValueError):self.load(d)

    def test_overlap_unknown_is_not_silent(self):
        d=fixture();a=copy.deepcopy(d['traces'][0]['annotations'][0]);a['label']='unknown'
        d['traces'][0]['annotations'].append(a)
        with self.assertRaises(ValueError):self.load(d)

    def test_no_scored_labels_is_rejected(self):
        d=fixture();d['traces'][0]['annotations'][0]['label']='unknown'
        with self.assertRaises(ValueError):self.load(d)

    def test_repeated_trace_ids_rejected(self):
        d=fixture();d['traces'].append(copy.deepcopy(d['traces'][0]))
        with self.assertRaises(ValueError):self.load(d)


if __name__=='__main__':unittest.main()
