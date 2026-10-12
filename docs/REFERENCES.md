# API references used during implementation

- [MetaQuotes: copy_rates_from_pos](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py)
- [PyWavelets: Continuous Wavelet Transform](https://pywavelets.readthedocs.io/en/latest/ref/cwt.html)
- [scikit-learn: TimeSeriesSplit and chronological gaps](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)

The implementation uses explicit timestamp-based label purging rather than
blindly applying a fixed TimeSeriesSplit gap. This remains necessary when labels
span multiple source windows or rolling feature windows overlap.

The original brief is retained in `original-brief.txt`. Its paper names and arXiv
references are user-supplied research leads, not a verified bibliography or claims
that the implemented estimators replicate those papers.
