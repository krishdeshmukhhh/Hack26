# Curio: use-case evidence and claim audit

Research checked 24 October 2026. Purpose: substantiate the problem, choose an
initial audience, and distinguish research-backed design choices from untested
product ideas. This is external evidence, not a Curio user study or customer
endorsement. Automated application tests establish software behavior, not human
learning outcomes, demand, accessibility, retention or willingness to pay.

## Evidence register

### 1. Tutorial coordination and state mismatches: direct problem evidence

Luo and Guo's October 2026 paper surveyed 87 learners and observed eight Maya
users. Respondents reported repeated rewatching (67%, 58 people), different
results despite following steps (59%, 51), and disruptive attention switching
(39%, 34). Survey data were collected at one university in January–April 2025
using convenience/snowball recruitment. Findings describe this sample, not all
students or all computer users. Publisher search-indexed article sections were
available; direct full-page opening returned HTTP 403.

[Understanding Practices, Device Ecologies, and Challenges in Video-Based Software Learning](https://www.tandfonline.com/doi/full/10.1080/10447318.2026.2734326)

### 2. Integrated tutorial support: preference is not faster performance

Pause-and-Play (UIST 2011) evaluated synchronized software/tutorial interaction
with 15 participants. Thirteen preferred it over the traditional player, but
completion time and error rate did not differ significantly. Useful support for
reducing coordination friction; insufficient basis for a productivity percentage.
The evaluation concerned SketchUp tutorials and a non-LLM system.

[Pause-and-Play, author-hosted paper](https://grail.cs.washington.edu/wp-content/uploads/2015/08/pongnumkul2011pal.pdf)

### 3. Visual references: strong rationale for region-based questions

AQuA (CHI 2024) examined 633 questions among 5,944 messages/comments on 20
official Fusion 360 tutorial livestreams. It also collected visually anchored
questions from 24 participants across Fusion 360, Photoshop and Excel. A
16-person answer evaluation favored its context/documentation-augmented approach
over baselines. This supports asking about a visible UI region. It does not
isolate screenshots from documentation or prove desktop task completion gains.

[AQuA paper and methods](https://arxiv.org/html/2403.05213v1)

### 4. Guidance versus automation: direct comparison in complex software

GuidedCopilot (CHI 2025) compared guided/semi-automated and fully automated
assistance with 20 participants on Sheets/Figma tasks, plus a 10-person follow-up
exploration. Eighteen of 20 reported greater control with guidance in Sheets;
16 of 20 did so in Figma. Learnability findings concern perceived potential,
not a longitudinal retention test. Semi-automation was part of the intervention,
so results cannot be assigned to visual pointing alone.

[Do It For Me vs. Do It With Me](https://arxiv.org/html/2504.15549v1)

### 5. AI advice can worsen confusion: essential contrary evidence

SoftAIBot's IUI 2024 study involved 16 participants. When instructions were
wrong, 10 struggled to map them onto the actual interface; 14 assumed the
specialized assistant was correct because its answers were well formatted.
This supports verification/recovery features and testing incorrect advice. It
contradicts any assumption that fluent AI guidance is inherently trustworthy.

[Why and When LLM-Based Assistants Can Go Wrong](https://arxiv.org/html/2402.08030v1)

### 6. Contextual assistance for screen-reader users: adjacent population

AskEase's January 2026 author manuscript reports a within-subject study with 12
screen-reader users. Mean completion was 1.5 of two tasks versus 0.5 with usual
tools, within a 20-minute period. Participant comments describe less copying,
window switching and lost context. This supports accessible contextual guidance
as an adjacent use case. Curio has not been validated for this population,
and visual pointing cannot be assumed to meet its accessibility needs.

[AskEase full paper, including participant accounts](https://arxiv.org/html/2601.18092v1)

### 7. Older adults: relevant research, separate design requirements

Synapse (2022) tested interactive, trial-and-error guidance with 18 adults aged
60+ on smartphones. Authors report better support and greater confidence and
motivation than video tutorials. Its recorded demonstrations and mobile setting
differ materially from a desktop LLM tutor.

[Synapse, authors' publication page](https://www.mingmingfan.com/lab/publication/imwut22-oa-interactive-guidance/)

### 8. Population-level need for technology help

Pew's 2021 U.S. survey reported that 26% of adults generally needed someone to
set up or show them how to use new devices. The figure was 66% for ages 75+.
This is older, broad device-use evidence, not a current estimate of demand for
AI software tutoring or a market-size calculation.

[Pew: Navigating technological challenges](https://www.pewresearch.org/internet/2021/09/01/navigating-technological-challenges/)

### 9. Pedagogical agents: modest support, no proof for a pet

A 2021 meta-analysis covered 32 effect sizes from 21 studies, totaling 2,104
participants. Overall learning benefit was small: Hedges' g = 0.20. Animation
did not significantly moderate results. These were instructional agents, not
evidence that an animated desktop animal improves retention or reduces anxiety.

[Castro-Alonso et al., university-hosted published paper](https://pure.eur.nl/ws/files/57710012/Castro_Alonso2021_Article_EffectivenessOfMultimediaPedag.pdf)

### 10–12. Public firsthand accounts: real examples, not prevalence estimates

- A Blender community discussion describes repeated pausing to inspect enabled
  add-ons, configuration and input actions, and a short tutorial taking much
  longer to follow. This is pseudonymous, self-reported experience, not a
  measured time study. [Blender learner discussion](https://www.reddit.com/r/blender/comments/gaxmyw/)
- A person transitioning from Premiere to DaVinci describes confusion with the
  unfamiliar interface. This suggests difficulty can arise from changing tools,
  not just being generally inexperienced. [DaVinci learner account](https://www.reddit.com/r/davinciresolve/comments/1th97lj/any_tips_for_guys_who_are_new_to_the_software/)
- A Blackmagic forum thread describes trouble following the Beginner's Guide
  and identifies page selection, menus and version/layout differences as factors.
  Only search-indexed text was accessible; direct opening returned 403.
  [Blackmagic user report](https://forum.blackmagicdesign.com/viewtopic.php?p=1062375&t=204499)

None is a Curio testimonial. Identities and experiences are not independently
verified. Complaints found through targeted searches cannot establish frequency.

### 13. Competition: screen-aware pointing is already an existing capability

Microsoft's June 2025 Windows announcement describes Copilot Vision seeing a
shared screen, discussing it and highlighting where to click. This establishes
feature overlap, not independent evidence of user benefit or market demand.
Do not claim Curio is first to combine screen understanding and guidance.

[Microsoft's Vision/Highlights announcement](https://blogs.windows.com/windowsexperience/2025/06/12/copilot-vision-on-windows-with-highlights-now-available-in-us/)

### 14. Step segmentation alone can fail to improve learning

An Excel tutorial experiment described by its researcher compared text/screenshots,
normal video and auto-paused video, with 71 successful performance measurements.
Auto-pausing did not improve performance or reduce reported effort. This limits
claims that simply breaking instructions into steps necessarily improves outcomes.

[Researcher's account and underlying study reference](https://www.bera.ac.uk/blog/does-breaking-up-a-video-into-parts-improve-learning)

### 15. Scam prevention: serious problem, unvalidated proposed solution

FTC data show over $12.5 billion in reported U.S. fraud losses during 2024.
These are reported losses across fraud categories, not losses attributable to
screen-visible phishing. The statistic does not establish whether Curio can
detect scams accurately, prevent losses or safely reassure a user.

[FTC's 2024 fraud data release](https://www.ftc.gov/news-events/news/press-releases/2025/03/new-ftc-data-show-big-jump-reported-losses-fraud-125-billion-2024)

## Audit of previously suggested additions

| Suggestion | Evidence status | Product decision |
| --- | --- | --- |
| Ask about a selected region; find an interface control | Directly relevant visual-anchor research, plus competitor feature precedent | Best-supported addition; test localization accuracy. |
| One-step tutoring and recovery from a wrong panel | Relevant guidance/state-mismatch evidence; incremental benefit unmeasured | Prioritize task verification and recovery, not just more prompts. |
| Before/after screenshot troubleshooting | State mismatch is documented; paired-image diagnosis is unvalidated here | Prototype on a small set of known errors. |
| Teach-back; gradually fade guidance | Guided learning supports the direction; our research does not establish these exact interventions | Require an unassisted follow-up task to test learning. |
| Per-app teaching preferences and explainable suggestions | Research documents differing user expectations; habit inference itself is unvalidated | Let users choose/correct preferences; test habit inference separately. |
| Remember successful workflows, task checkpoints, recurring fixes | Plausible response to repeated coordination problems; no direct efficacy evidence established | Validate recurrence before building workflow recording. |
| Animated pet | Small general agent effect; animal design and animation benefit unknown | Treat as optional presentation; compare with a simple pointer. |
| UI translation, presentation coaching, portable profiles | No targeted evidence established in this review | Do not pitch these as validated priorities. |
| Suspicious-link explanations | Fraud need is documented; detection effectiveness is not | Separate project scope unless accuracy can be evaluated. |

## Defensible audience and statement

Recommended initial audience, as an inference: students or self-directed learners
attempting unfamiliar tasks in feature-rich desktop software, initially in one
application. Target unfamiliarity with a task/application, not assumptions about
age or general intelligence. The university survey and design-software studies
make this a defensible starting hypothesis, not proof it is the best market.
Older adults and screen-reader users need their own co-design and evaluation.

Proposed problem statement: People learning complex software can lose progress
when tutorial instructions do not match their application's current state. Curio
aims to offer on-demand explanations and visual guidance within that workflow.
Its effects on success, independence and frustration must still be measured.

## Next validation: evidence from our own users

Recruit 6–10 learners unfamiliar with a chosen application's task. Collect recent
examples of getting stuck before describing Curio. Ask what they tried, where
their screen differed, and what happened. Do not ask only whether they like the idea.

Use two comparable, different tasks and alternate assistance order between users:
usual resources for one task, Curio for the other. Record correct completion,
time including failures/timeouts, wrong actions, external-help switches, and a
short effort/frustration rating. Keep task difficulty and assistance rules fixed;
count researcher interventions. Include a new unassisted task if claiming learning.
This small pilot is exploratory, not a population-level causal estimate.

Ask afterwards what helped, what misled them, and when they would use it again.
Get explicit consent before using attributed quotes, screenshots or recordings.
Keep quotes verbatim and distinguish participants' impressions from measured
performance. Compare against existing screen-aware assistance before claiming
superiority. Do not invent customers, market size, willingness to pay, retention
gains, accessibility benefits, or productivity percentages.

Suggested demo claim until that pilot: We built and technically tested a prototype
addressing coordination and context problems documented in software-learning
research. We have not yet demonstrated improved human outcomes with Curio.
