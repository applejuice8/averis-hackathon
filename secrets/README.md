# secrets/

Git-ignored. Files here must never be committed.

- `ground_truth.json` — the organizers' answer key. Only the local scorer uses
  it (`docker compose` mounts it at `/secrets/ground_truth.json`). Copy it from
  `data_v2/ground_truth.json` inside the organizer zip
  (`sdoc-hackathon-docker.zip`). In the cloud it lives in Secret Manager as
  `GROUND_TRUTH` and is only readable by the private scorer.
