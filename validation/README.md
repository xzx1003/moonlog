# Public data validation

This folder records validation against small public samples from [Loghub](https://github.com/logpai/loghub), rather than claiming that synthetic data is real evidence.

The source samples are not copied into this repository. Download links, source licenses/usage notes, conversion commands, hashes, and observed results belong in `validation/loghub-results.md`. The samples are research datasets with different schemas and may not contain timestamps usable by MoonLog; conversion failures are recorded as limitations rather than silently treated as success.

Run `python3 validation/prepare_loghub.py` to download the 2k structured samples and produce normalized, local-only text fixtures. Review the source terms before redistribution.
