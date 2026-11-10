# Citation judge calibration

The offline citation judge is **resolver-based and deterministic**: a letter line that makes a clinical claim is *supported* iff it carries at least one FHIR reference and every referenced id resolves to a real resource in the patient's chart. Precision = supported / claim-lines.

This is a conservative lower bound on a model-based judge and needs no LLM, so it is fully reproducible in CI. To calibrate a model-based judge, hand-check 50 letters, label each claim supported/unsupported, and measure the judge's agreement (target ≥ 0.9 Cohen's κ) before swapping it in behind the same `metrics.score` interface.
