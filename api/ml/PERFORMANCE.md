# Spam model experiments

## Dataset and protocol

- Source: the 520 labeled Averis emails in `data_v2`; no external corpus.
- Class balance: 40 spam and 480 legitimate emails.
- Deduplication: one exact duplicate removed, leaving 519 records.
- Holdout: fixed 20% stratified split (`random_state=42`), containing 104 emails and 8 spam emails.
- Selection: 5-fold repeated stratified cross-validation with 3 repeats on the remaining 415 records.
- Primary metric: spam F1. Tie-breakers: PR-AUC, false-positive rate, then mean fit time as a deployment-complexity proxy.
- Threshold: selected from 5-fold out-of-fold predictions on the training partition only.

## Results

| Candidate | CV spam F1 | CV precision | CV recall | CV PR-AUC | CV false-positive rate | Mean fit seconds |
|---|---:|---:|---:|---:|---:|---:|
| Word TF-IDF + logistic regression | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.078 |
| Word TF-IDF + calibrated linear SVM | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.115 |
| Character TF-IDF + logistic regression | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.437 |
| Word + character TF-IDF + logistic regression | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.533 |
| Binary count + random forest | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.553 |
| Reference word TF-IDF + MLP | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.685 |
| Binary count + BernoulliNB | 0.528 | 0.363 | 1.000 | 0.545 | 0.150 | 0.052 |
| Majority baseline | 0.000 | 0.000 | 0.000 | 0.075 | 0.000 | 0.074 |

## Selected approach

Word TF-IDF with balanced logistic regression is selected. Six candidates are indistinguishable on predictive metrics, so the measured lower fit cost and simpler uncalibrated pipeline break the tie. The GitHub reference's MLP does not improve any measured classification metric and is approximately nine times slower to fit in this experiment.

The out-of-fold threshold is `0.255`. On the untouched holdout, the selected approach produced 96 true negatives, 8 true positives, no false positives, and no false negatives (spam F1 and PR-AUC both 1.000).

## Limitations

These results are not evidence of general email-spam performance. The dataset is synthetic, contains only 40 spam records, and has only nine unique spam subjects and six unique spam bodies. The holdout has only eight spam messages and shares generator patterns with training data. Independently labeled production-like email, drift monitoring, and periodic re-evaluation are required before relying on this model beyond the hackathon dataset.

Executed notebooks:

- `notebooks/01_data_audit.ipynb`
- `notebooks/02_model_selection.ipynb`
