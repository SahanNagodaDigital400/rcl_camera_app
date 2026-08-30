# Experiments

One-off harnesses kept so the findings in `../README.md` can be re-run rather
than re-argued — particularly against real photos, where the conclusions may
differ from the synthetic proxies they were measured on.

- `compare_indexes.py` — A/B two indexes on the same leave-one-out query set.
  Used for the grey-world test (finding §3). Each index is scored with the
  preprocessing it was built with, or the comparison measures an asymmetry
  rather than the idea.

The colour-descriptor sweep (finding §4) is in this POC's git history.
