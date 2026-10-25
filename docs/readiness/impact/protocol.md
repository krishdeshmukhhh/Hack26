> Superseded for execution by [study-plan.md](study-plan.md). Use its task cards,
> blank-results.csv and analyze.py; this file is a historical generic draft.

# Exploratory impact pilot (not yet run)

Status: protocol prepared on 24 October 2026; no participants, observations,
quotes, completion rates or performance gains are claimed here.

## Audience and question

Initial audience hypothesis: students or self-directed learners unfamiliar with
a task in feature-rich Windows desktop software. Start with one application and
version available on the demo laptop. Do not infer age, disability, intelligence
or general computer ability from task unfamiliarity.

Question: does Curio help these learners reach a correct task result with
less coordination effort, and where does its advice mislead them? This small
pilot can reveal problems and describe this sample; it cannot establish a
population effect, accessibility benefit or commercial demand.

## Preparation before recruiting

1. Choose two comparable, different tasks A and B in the same application. For
   example, use two different worksheet-formatting operations on disposable
   workbooks. Verify both on the exact application version before the study.
2. Save clean starting files and an objectively checkable result for each task.
   Write the correctness checklist before seeing participant results. A model's
   `completed` flag, a left click and a map `verified_count` are not ground truth.
3. Fix the task time limit at 600 seconds, assistance rules and permitted usual
   resources. Include normal model/network delay in task time. Record outages;
   do not restart the clock to remove failures. Use the same device and network.
4. Use a fresh study profile and disposable files. Disable walkthrough sharing
   and persistent memory. Never seed the study's skill/task databases. Record
   baseline commit, backend/model, app version, relevant config and task IDs in
   `session.md`. Keep credentials and personal screen content out of artifacts.
5. Test the observation sheet on a team member as a rehearsal. Label it
   REHEARSAL and exclude it from participant summaries. Do not treat it as a
   representative learner or a blinded study.

## Recruitment, order and session (about 25 minutes)

Recruit 6–10 consenting adults who have not performed either selected task.
Record task familiarity before assigning a condition. Team members belong in a
separate rehearsal group. Recruit neutrally: “We are studying how people follow
instructions in desktop software; the prototype may be wrong.” Record refusals
only as a count without identifying details. Report the actual sample size.

Assign consecutive pseudonyms to this fixed rotation; do not change assignment
after seeing ability or results:

| Assignment | First period | Second period |
| --- | --- | --- |
| 1 | A, usual resources | B, Curio |
| 2 | A, Curio | B, usual resources |
| 3 | B, usual resources | A, Curio |
| 4 | B, Curio | A, usual resources |

Repeat the rotation. This balances order and task, but does not eliminate task
difficulty, learning carryover, novelty or observer effects.

Before introducing Curio, ask: “Tell me about the last time instructions did
not match your screen. What did you try, and what happened?” Ask about a concrete
event, not whether the person likes our proposed idea.

Give the same brief familiarization for both conditions. Start timing when the
task is revealed. Stop on verified correct completion, participant withdrawal or
600 seconds. Observe without coaching. If help is needed for safety or continued
participation, give it and record an intervention; keep that run in the data.
Count wrong actions using the predefined task checklist, resource/window switches
and incorrect assistant suggestions. Record crashes and network/model failures.

An observer checks the actual result independently of the assistant's claim.
Record `completed` only if all predefined checks pass. Otherwise use `timeout`,
`abandoned` or `error`, with elapsed time and a reason. A second observer should
review ambiguous cases, preferably without knowing condition. Report this
blinding as absent if it was not possible.

After each task ask effort and frustration separately on a 1–7 scale (1 low,
7 high). Ask “What helped? What misled you? What did you do next?” Avoid prompting
only positive reactions. After both tasks ask where, if anywhere, they would use
it again. Treat preferences as self-report, not measured improvement.

## Learning and transfer

If making a learning claim, add a new related task C without Curio, tutorials
or researcher hints after a fixed five-minute break. Record correctness and time
with the same rules; label the condition `unassisted`. This measures immediate
transfer only. Both previous tasks may influence it, so it cannot isolate a
Curio learning effect. A later randomized comparison and delayed follow-up
would be needed for durable-learning or retention claims. Skill mastery bars
remain model estimates, not tests of human knowledge.

## Reporting without selective exclusions

Keep every started task, including timeouts, incorrect results, abandonment,
technical errors and interventions. Record any consent withdrawal and omit its
data as requested; disclose the count if allowed without identifying anyone.
Report counts and denominators by condition, actual elapsed-time medians for all
runs alongside completion counts, and completed-only time separately. Elapsed
time for an unsuccessful run is not “time to success”; timeout observations are
censored. Never imply that quitting early is faster successful performance.

Use `scripts/readiness/impact/summarize.py` for descriptive counts only. Inspect
the task/order table and raw observations before drawing conclusions. Do not
derive causal productivity percentages from its output. Describe individual
paired differences only with task/order and failures visible. With this sample,
avoid significance tests, market-size extrapolation and generalized percentages.

## Evidence boundary

`docs/use-case-evidence.md` is the existing research register, with limitations
and contrary findings. This handoff inspected that local register; it did not
independently reverify its external publications. Research about other systems
supports a problem/design rationale, not Curio efficacy. Automated tests
support bounded software behavior; synthetic map users, scripted skill history
and analysis self-tests are simulations. A real live demo shows one observed run,
not a user-study outcome.

Until observations exist, the defensible impact statement is: “Curio targets
the coordination problems described in software-learning research. We have built
a prototype and prepared a pilot; improved learner outcomes remain unmeasured.”

## Consent script and handling plan

Read before beginning: “Participation is optional. This prototype can provide
incorrect advice. You may skip any question or stop at any time. Use only these
test files, with no personal accounts or sensitive content. We will record task
results and brief notes under a pseudonym. The screen may be sent to the
configured model service during Curio use [name the actual service/location].
We will not record audio/video/screenshots unless you separately agree. You may
participate without publicity permission. Ask us to remove your study records
using your study ID before [state deletion date/contact].”

Before using this script, the human facilitator must fill in the service,
contact, deletion date and local storage location accurately. Store any consent
linkage separately from the de-identified observations, outside the Git repo.
Choose a short retention period, such as seven days after judging, and actually
delete the linked data then. Follow venue/institution requirements if applicable.

Use separate affirmative choices in the private consent record:

- Participation and de-identified task notes: yes/no.
- Optional screen recording: yes/no (default no).
- Optional verbatim anonymous quote in presentation: yes/no (default no).
- Optional named attribution: yes/no (default no; confirm exact wording).

Do not commit participant data, names, recordings or consent signatures. Quotes
must be verbatim and traceable to consent, including negative feedback.
