# Release Notes

## Phase 1C

- Added investigation analysis endpoint workflow for ordered-image sessions.
- Added canonical retained investigation model as the single retained result source.
- Added desktop projection endpoint: GET /investigations/latest.
- Added glasses projection endpoint: GET /investigations/latest/glasses.
- Added deterministic Copilot prompt generation from retained investigation data.
- Added atomic persistence for retained investigation writes.
- Added unknown freshness handling in the desktop investigation panel.
- Added focused regression coverage for retention and atomic persistence behavior.
- Investigation suite status: 53 tests passing in code/prototype_v1/test_investigations_api.py.
