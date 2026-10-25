# Curio exploratory pilot ? USER VALIDATION PENDING

Prepared 2026-10-24. No participant data supplied or collected. This document
supersedes the generic task-selection instructions in protocol.md. Use this plan,
participant-instructions.md and blank-results.csv together; the older observation
schema is not compatible with analyze.py.

## Rationale and scope

Reviewed local sources: README.md, docs/features.md, docs/use-case-evidence.md,
docs/hackathon-readiness.md, docs/skills.md and docs/task-map.md. The research
register supports investigating tutorial/screen mismatch and attention switching;
it includes contrary evidence about fluent wrong advice and studies finding no
speed benefit. It is secondary project research, not independently reverified
publications or Curio participant evidence. No external numerical findings
are reused here.

The prototype offers push-to-talk, screenshots, spoken explanations and visual
pointing; optional coaching, memory and skill estimates are not validated human
learning measures. Model completion and map verification are not ground truth.
Latency, wrong localization/advice, voice recognition and version differences can
impair results. Live device behavior remains to be checked. Do not infer
accessibility, retention, mastery, demand or commercial benefit from code tests.

Question: for learners unfamiliar with spreadsheet formatting workflows, what
correct results, help switching, effort and failure modes occur with usual
resources versus Curio? Recruit 6?10 consenting adults, students or
self-directed learners, unfamiliar with both tasks. Screen before assignment:
exclude anyone who has performed either exact workflow in Calc in the past year
or can describe its procedure confidently. Record broader spreadsheet experience
privately. Team members are rehearsal only. This convenience sample cannot
represent all Windows learners or people with accessibility needs.

## Fixed application and assets

Use LibreOffice Calc on Windows, English UI, one laptop, one monitor, same DPI,
keyboard and mouse. Human facilitator must record the installed version, Windows,
Curio commit plus local changes, backend/model/location, network, settings,
resource URLs and SHA-256 hashes of starting .ods files in a private copy of
session-template.md. Freeze these before recruitment; do not silently substitute
Excel. Calc availability and model compatibility are preflight gates, not assumed.

Create three independent workbooks A.ods, B.ods, C.ods. Each has exactly one sheet,
Data, and A1:C7 containing the following values, all plain formatting, no rules,
no filters, no formulas. Save a clean master and duplicate per task/person.

| Item | Score | Status |
| --- | --- | --- |
| Pen | 12 | Ready |
| Pad | 8 | Hold |
| Clip | 20 | Ready |
| Tape | 5 | Hold |
| Card | 16 | Ready |
| File | 10 | Hold |

Start each task with its clean workbook open, A1 selected, browser on a blank tab.
No task hints in filenames, history or previous assistant sessions. Rehearse exact
steps and scoring on the installed build with a team member; keep rehearsal data
separate. Test rule inspection and persistence, not just apparent cell colors.
If either task cannot be completed/scored, stop and amend/version the protocol
before recruiting. Record rehearsal times to detect a gross difficulty mismatch;
if either exceeds 600 seconds or takes over twice the other, revise both and
rehearse again before freezing. Rehearsal does not prove equal difficulty.

## Tasks and objective scoring (freeze before first learner)

A: Flag high scores. Apply a conditional formatting rule to B2:B7 so values
strictly greater than 10 have a light yellow background. Save A-result.ods.
B: Flag held items. Apply a conditional formatting rule to C2:C7 so cells whose
text equals Hold have a light yellow background. Save B-result.ods.
These differ in numeric comparison versus text equality, with equal-sized ranges,
one rule and one save; they are comparable hypotheses, not proven equivalents.

For each: all original values and headers unchanged; exact target range covered;
one correct conditional rule and threshold/text; yellow background only on the
expected cells (A: B2/B4/B6; B: C3/C5/C7); no extra rule/manual yellow fills;
correct named .ods saved and persists after reopening. Any yellow shade accepted.
Use Format > Conditional management on the installed build to inspect the rule;
reopen the output after timing to check persistence. A hidden scoring rubric
must never be shown during work. If persistence fails, recode the stop as failed,
retaining elapsed time. Correct state requires all checks; partial credit is notes
only. Have a second observer audit ambiguous results; record if blinding absent.

C, mandatory immediate transfer: after both tasks and a five-minute neutral break,
use clean C.ods without external help. Apply one conditional rule to B2:B7 so
values less than or equal to 10 have a light yellow background. Save C-result.ods.
Same checks; expected yellow B3/B5/B7. This is a new criterion, not task A
repeated. Both conditions precede C: it cannot attribute learning to Curio.
No durable-learning claim is justified by immediate transfer.

## Conditions, allocation and timing

Usual: built-in help, web search, text guides or videos in the browser; no AI
assistants or other people. This defines the comparator, not every learner's
personal usual practice. Curio: Curio only, no browser/help/person guidance;
normal UI exploration allowed. Both: printed goal card, same hardware, no task
procedure from facilitator. Record attempted prohibited help as a deviation;
do not delete the run. Transfer: goal card and Calc only.

Assign consecutive IDs P01 onward, repeating four sequences without choosing by
ability: 1 A-usual/B-curio; 2 A-curio/B-usual; 3 B-usual/A-curio;
4 B-curio/A-usual. Always C-unassisted third. Target eight for two complete
blocks; six or ten leaves imbalance, reported explicitly. No post-hoc reassignment.
Before timed work give everyone two minutes familiarization in each condition
(order matching assignment), using a separate blank workbook and a neutral task:
locate the zoom control. Explain push-to-talk and that advice can be wrong.
Reset assistant history/profile, skill state and files between people; fresh
assistant conversation for each measured task. Disable sharing, proactive/wake
mode and persistent memory; do not use seeded demo history.

Budget 45?55 minutes: consent/screening 5, familiarization 4, two tasks up to
20, break 5, transfer up to 10, ratings/interview 5?10. Timer starts when goal
is revealed; includes reading, web/model waits, saving and recovery. Participant
says done, observer checks immediately without hints; clock continues if checks
fail and time remains. Stop at verified success, 600 seconds, giving up,
withdrawal or technical inability to continue. Never subtract delays/restart.
At exactly 600 seconds use timeout unless success was already verified.

Statuses: completed = all checks; timeout = limit without verified success;
failed = declared final wrong result or giving up before limit; error = technical
issue prevents continuation; withdrawn = participant stops participation.
Keep all consented started runs, including interventions. Delete withdrawn data
when requested; keep only permitted anonymous withdrawal count privately.
Missing period means not observed, never zero/failed by imputation.

## Measurement and interpretation

Observer logs elapsed seconds, wrong actions, resource switches and interventions
with timestamps in private notes, then totals in CSV. Wrong action = committed
edit/configuration/save contrary to rubric (wrong range/operator/value/format,
changed data or wrong file); one per committed operation, including corrected
errors. Opening an irrelevant menu, hesitation, typing before commit and undoing
an error are not separate wrong actions. Count wrong advice separately in notes.
Resource switch = transition from Calc to a help source, between help sources,
or back to Calc; opening a new source counts even in same browser. A Curio
question/answer is one help episode counted as two switches (out/back); a
follow-up is another episode. Record concurrent episodes once on return; note
this operational convention does not measure identical cognitive costs.
Intervention = each unsolicited or requested facilitator task/technical hint or
hands-on recovery episode; repeats after resumption count anew. Administrative
time announcements/rating prompts do not count. No hints normally; safety,
privacy or distress overrides silence. Mark affected rows and explain details.

Ask effort and frustration immediately after each task: 1 very low, 7 very high;
skip allowed, blank is missing. Do not treat ratings as objective productivity.
Primary summary: success counts/started counts by condition; descriptive timing
and counts/ratings with observed/missing denominators. All-run elapsed is time
spent, not time to success; timeouts are censored. Completed-only times are
selection-biased. Review task/period strata, deviations and interventions along
with paired successful participants. Never treat unsuccessful early stops as
faster success. No p-values, significance, causal productivity percentages,
population effects or automated go/no-go threshold. Use failure examples to
revise the prototype and protocol; larger randomized and delayed studies would
be required for efficacy and learning attribution.
