import unittest
from core import default, reference
from pollution import frozen_reference


class Pollution(unittest.TestCase):
    def test_freeze_prevents_absorption_but_can_lock_on_healthy_shift(self):
        p=default('ewma');p.update(window=2,parameter_tenths=10)
        errors=[1,1,20,20,20,1]
        regular,_=reference(errors,'ewma',p)
        frozen,trace=frozen_reference(errors,p)
        self.assertEqual(regular,[False,False,True,False,False,False])
        self.assertEqual(frozen,[False,False,True,True,True,False])
        self.assertEqual([r['baseline'] for r in trace],[1,1,1,1])
        # Same observations can represent an expected traffic shift; the policy
        # cannot infer operational truth from counts alone.

    def test_nonalerts_still_update_and_strict_threshold(self):
        p=default('ewma');p.update(window=2,parameter_tenths=5)
        hits,trace=frozen_reference([2,2,6,13],p)
        self.assertEqual(hits,[False,False,False,True])
        self.assertEqual(trace[1]['baseline'],4)

    def test_mad_flat_contamination_majority_masks_probe(self):
        p=default('mad');p['window']=6
        hits,trace=reference([1,1,20,20,20,20,20],'mad',p)
        self.assertFalse(hits[6])
        self.assertEqual(trace[0]['baseline'],20)
        hits,_=reference([1,1,1,1,20,20,20],'mad',p)
        self.assertTrue(hits[6])

    def test_mad_half_contamination_inflates_scale(self):
        p=default('mad');p['window']=6
        hits,trace=reference([1,1,1,20,20,20,20],'mad',p)
        self.assertEqual(trace[0]['baseline'],10.5)
        self.assertGreater(trace[0]['threshold'],20)
        self.assertFalse(hits[6])


if __name__=='__main__':unittest.main()
