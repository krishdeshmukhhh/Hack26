# Defects and coordinator actions

No new production defect is confirmed by the 99 deterministic checks. These checks ran against the shared working tree, which already contained coordinator production edits; they do not certify the baseline commit alone.

## Observed Windows blocker: SAPI access denied

Reproduce from repository root with the project interpreter:

```powershell
$env:CURIO_TEST_SAPI='1'
curio-py/.venv/Scripts/python.exe -m pytest curio-py/tests/test_hands_free_native.py -q -p no:cacheprovider --basetemp scripts/readiness/demo/tmp-native-20261024-a
```

The recorded run failed all 8 cases in 2.75s. Reproduction must use a fresh temp directory on later runs. CreateRecoContext, GetAudioInputs and synthesized speech operations fail with COM error -2147024891 (access denied). The worker emits a hands-free-unavailable message. Native log: native-smoke.txt. Capability smoke discovers audio devices but zero Qt TTS voices. This is an environment/access blocker, not evidence of an algorithmic SAPI defect. Coordinator should rehearse outside this restricted process, check Windows speech/microphone permissions and installed English recognition/voices, then repeat acoustic wake, push-to-talk and playback checks. Do not relax machine permissions automatically.

## Evidence limits requiring coordinator attention

- Ordinary workflow completion and skill updates depend on model STEP output, not verified Excel state. Reproduce with the owned pivot journey: fixture says done and real persistence records completion without Excel running. Suggested future fix: add independently sourced application-state evidence before exposing any stronger success claim. Current labels correctly limit the claim.
- Tutor completion records are in memory and coaching is excluded from ordinary learning. Restart the tutor service and its prior attempts are absent. This is a documented limitation, not a regression. Persist attributed math evidence through an approved adapter only if the coordinator explicitly expands scope; do not claim tutoring drives current cross-session recommendations.
- docs/live-tutoring.md contains an outdated paragraph saying nothing is wired to startup, while its opening and current app architecture describe integrated tray/runtime wiring. Suggested fix: coordinator remove/update that obsolete isolated-package paragraph.

No production changes were made. The initial request-construction check failure was a test-harness assumption about string versus block content, corrected in the owned test; it is not a production defect.
