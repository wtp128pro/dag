# manifest_examples — schemas/manifest.schema.json (Workstream B)

`manifest.schema.json` is NOT auto-run by `validate_run.py` against a run dir (a manifest is produced
by a partitioned run's sharder, not part of the pipeline artifact set). These two files exercise it
directly:

- `valid.json` — a well-formed shard manifest (grain + shards[shard_id→locator] + results_index +
  sampling_log). **Validates.**
- `invalid_missing_grain.json` — omits the required `grain`. **Rejected.**

Check:
```
python3 - <<'PY'
import json,sys; sys.path.insert(0,'scripts')
import validate_run as V
sch=json.load(open('schemas/manifest.schema.json')); validate,_=V.make_validator()
for f,exp in [("scripts/tests/manifest_examples/valid.json",True),
              ("scripts/tests/manifest_examples/invalid_missing_grain.json",False)]:
    ok = not validate(json.load(open(f)), sch); print(f, "valid=",ok,"expected",exp)
PY
```
Expected: `valid.json valid=True`, `invalid_missing_grain.json valid=False`.
