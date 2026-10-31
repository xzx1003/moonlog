import unittest
from core import corpus,dataset_hash,score,summarize,reference,default,grid


class Evaluation(unittest.TestCase):
    def test_confusion_and_event_delays(self):
        s=score([False,True,True,False,True,None],
                [True,False,True,False,False,True],warmup=0)
        m=summarize([s])
        self.assertEqual([m[k] for k in ['tp','fp','fn','tn']], [1,1,2,1])
        self.assertEqual(m['precision'],0.5)
        self.assertEqual(m['recall'],1/3)
        self.assertEqual(m['f1'],0.4)
        self.assertEqual(m['false_positive_rate'],0.5)
        self.assertEqual(m['event_recall'],0.5)
        self.assertEqual(m['missed_events'],1)
        self.assertEqual(m['detected_delay_minutes'],[5])

    def test_zero_denominators(self):
        m=summarize([score([False,False],[False,False],0)])
        self.assertIsNone(m['precision'])
        self.assertIsNone(m['recall'])
        self.assertIsNone(m['f1'])
        self.assertEqual(m['false_positive_rate'],0)
        self.assertIsNone(m['event_recall'])
        self.assertIsNone(m['median_detected_delay_minutes'])

    def test_unknown_and_warmup_censoring(self):
        s=score([True,True,True,None,False],[True,True,True,True,False],2)
        self.assertEqual(s['tp'],1)
        m=summarize([s])
        self.assertEqual(m['event_count'],0)
        self.assertEqual(m['left_censored_events'],1)

    def test_split_reproducible_and_disjoint(self):
        tune,test=corpus('tune'),corpus('test')
        self.assertEqual(dataset_hash(tune),dataset_hash(corpus('tune')))
        self.assertNotEqual(dataset_hash(tune),dataset_hash(test))
        self.assertFalse({c['seed'] for c in tune}&{c['seed'] for c in test})
        self.assertEqual(len(tune),18)
        for c in tune+test:
            self.assertTrue(all(0<=e<=t for e,t in zip(c['errors'],c['totals'])))

    def test_sustained_baseline_pollution(self):
        p=default('ewma');p.update(window=2,parameter_tenths=10)
        hits,trace=reference([1,1,20,20,20],'ewma',p)
        self.assertEqual(hits,[False,False,True,False,False])
        self.assertEqual([t['baseline'] for t in trace],[1,20,20])

    def test_all_missed_events_are_not_zero_delay(self):
        m=summarize([score([False,True,True],[False,False,False],0)])
        self.assertEqual(m['event_recall'],0)
        self.assertEqual(m['missed_events'],1)
        self.assertIsNone(m['median_detected_delay_minutes'])

    def test_oracle_uses_past_only(self):
        for name in ['moving-average','ewma','mad']:
            p=default(name);p['window']=2
            hits,trace=reference([1,1,10,0],name,p)
            self.assertEqual(hits[:3],[False,False,True])
            self.assertEqual(trace[0]['baseline'],1)
            self.assertEqual(trace[0]['threshold'],1 if name=='mad' else 3)

    def test_equal_budget_and_common_warmup(self):
        for name in ['moving-average','ewma','mad']:
            trials=list(grid(name))
            self.assertEqual(len(trials),24)
            self.assertLessEqual(max(p['window'] for p in trials),12)


if __name__=='__main__':unittest.main()
