# Golden test set

The Phase 1 gate: the score must agree with your own judgment on 30+ real JDs.

Add one YAML file per job you have already judged:

```yaml
title: Junior SOC Analyst
company: Northwind Security
location: Vancouver, BC
verdict: apply        # apply | maybe | skip  (your call, before looking at the score)
expected_flags: []    # flag types you expect to block, e.g. [grad_window, sponsorship]
jd_text: |
  ...paste the full posting...
```

Run `python scripts/evaluate.py` (add `--llm` to include Claude extraction). It reports
how often the score band matches your verdict, rank correlation, and flag recall. Tune the
weights in `app/engine/scorer.py` until agreement is high, then lock them.

The three `sample_*.yaml` files are fictional examples; replace them with real postings.
