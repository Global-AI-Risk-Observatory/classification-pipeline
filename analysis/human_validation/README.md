# Human validation

The human annotation protocol of `docs/research-plan.md`, section 3, as a script over a run in the bucket: a stratified sample of passages, one Google Sheet per rater, the ratings read back as coder files, and Cohen's kappa per field, human against human and human against the model.

    python human_validation.py sample --run gs://<bucket>/<run> --out gs://<bucket>/<run>/human_validation
    python human_validation.py sheets --project <gcp project>      # Sheets and Drive APIs enabled; gcloud auth login --enable-gdrive-access
    python human_validation.py collect --project <gcp project>
    python human_validation.py agreement

The sample: 290 passages of at most 400 words, one per filing; strata by the role that carries the labels (risk 90, adoption 70, governance 40, other roles 50) and `none` 40, of which 20 with the model's confidence low or medium; within a stratum a systematic draw over ISIC section and form; 60 passages rated by two raters, rotating through every pair of the 7 raters, 50 passages per rater.

Every rating column of a sheet is a drop-down. A list field has one column per value slot (`roles 1` to `roles 3`, `risk_types 1` to `4`, `mit_subdomains 1` to `4`, `business_functions 1` to `3`, `governance_responses 1` to `3`, `disclosure_traits 1` to `3`); the slots cover at least 94 % of the model's non-empty labels of each field on `us-2025h1_V3`.

Files: `sheets/sheets.json` holds the links of the spreadsheets of `us-2025h1_V3`; `results/<run>/sample_summary.json` the strata, sections and forms of the sample and what the word limit left out; `results/<run>/agreement.md` the kappa and agreement figures once `collect` and `agreement` have run. The sample with the model's labels, the rater sheets and the collected ratings are in the bucket under `<run>/human_validation/`; the local copies under `work/` and `sheets/rater_*.csv` carry filing text and are not committed.
