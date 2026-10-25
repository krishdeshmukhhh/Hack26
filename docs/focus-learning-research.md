# Focus and learning mode: research and settled features

Research checked 24 October 2026. Purpose: decide what Curio's focus/learning
mode does, based on published evidence, and mark which parts are well
supported, which are plausible, and which we should not claim. Same standard
as [use-case-evidence.md](use-case-evidence.md): effect sizes describe the
studies' populations and tasks, not Curio. We have not measured outcomes
with our own users.

Confidence labels used below:
- **Strong:** large meta-analyses or replicated randomized studies.
- **Moderate:** a meta-analysis with caveats, or a few good experiments.
- **Weak:** small studies, preprints, or self-report only. Build only if cheap
  and never claim a benefit.

## The mode in one paragraph

The learner starts a session by saying what they're working on and making an
if-then plan. Curio watches only the foreground app, window title and idle
time (no continuous screenshots), notices when the learner drifts away from the
goal, and waits for a natural break point before checking in, in a friendly,
non-controlling way. When they come back, it reminds them where they left off.
While they study, Curio tutors with hints first instead of answers, gives them
time to struggle before stepping in, prompts them to explain their reasoning,
and fades its help as they improve. At the end it quizzes them briefly and
schedules spaced review of what they learned.

## Settled features

### A. Session start: goal plus if-then plan (Strong)

- Learner states the goal ("finish the pivot table assignment") and a time
  box. Curio helps phrase one or two **implementation intentions**: "if I
  open YouTube, then I'll close it and say 'back to it'".
- Evidence: Gollwitzer and Sheeran's 2006 meta-analysis of implementation
  intentions found a medium-to-large effect on goal attainment, d = 0.65
  ([university repository record](https://kops.uni-konstanz.de/entities/publication/2e749bfb-8533-437c-8203-7e788c910c5f);
  the d is consistently reported in secondary sources, but we did not read the
  full text).
- The plan's cues double as detection rules for feature B.

### B. Off-track detection from foreground app and title (Moderate for the problem, unvalidated for our detector)

- Sample the foreground window title, app and idle time every few seconds.
  Never log keystroke content; at most count input events.
- Judge each window against the goal: rules first (the session's allowed
  apps, the if-then cues, a small known-distractions list), then the model for
  unclear titles (cached per title), then the learner's own corrections,
  which always win.
- **Drift = sustained off-goal time** (default about 90 seconds, or several
  short returns to the same distraction), not single switches. Not every
  switch is a distraction: looking something up is part of work.
- Evidence of the problem: Gloria Mark's computer-logging work reports an
  average of 47 seconds on one screen before switching (median 40), down from
  about 2.5 minutes in 2004
  ([Steelcase interview transcript](https://www.steelcase.com/research/articles/our-47-second-attention-span-with-gloria-mark-s5-ep3-transcript/)).
  Commentators caution that this measures switching, not a biological
  attention limit. Mark also reports that people interrupt themselves almost
  as often as others interrupt them
  ([Gallup interview](https://news.gallup.com/businessjournal/23146/too-many-interruptions-work.aspx)).
- Evidence for the detector: off-task detectors exist for tutoring-system
  logs ([Purdue](https://docs.lib.purdue.edu/ccpubs/396),
  [Ateneo algebra tutor](https://archium.ateneo.edu/discs-faculty-pubs/156)),
  but we found **no validated detector based on window titles**. We must
  measure our own false-alarm rate from the learner's "that wasn't a
  distraction" corrections.
- Optional, with consent each time: one screenshot when the title is
  ambiguous ("Chrome — New Tab").

### C. Check-ins at break points, not mid-thought (Strong for timing, Moderate for wording)

- **Decide whether to step in** using the just-in-time adaptive intervention
  idea: act when the learner is *vulnerable* (drifting) **and** *receptive*
  (able to respond now)
  ([Nahum-Shani et al. 2018, PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC5364076)).
- **Receptive = at a break point:** right after an app switch, when coming
  back from idle, or after a pause in typing. Interrupting at low-workload
  boundaries produced shorter resumption lag and less annoyance than at
  high-workload moments, and breakpoints can be predicted from interaction
  logs with 69–87% accuracy
  ([Iqbal & Bailey CHI 2005](https://www.interruptions.net/literature/Iqbal-CHI05-p1489-iqbal.pdf);
  [CHI 2006](https://interruptions.net/literature/Iqbal-CHI06-p741-iqbal.pdf)).
- **Escalation ladder**, one step per drift episode:
  1. Ambient: the pet glances at the learner or sits by the taskbar. No sound.
  2. Check-in: a short spoken question with choices: "still on the
     assignment? we can get back to it, or take a proper break."
  3. Plan reminder: repeats the learner's own if-then plan.
- **Wording offers choices instead of giving orders.** Controlling language
  tends to cause reactance (pushback), though individual studies are mixed
  ([2017 healthy-eating experiment](https://cris.maastrichtuniversity.nl/en/publications/should-or-could-testing-the-use-of-autonomy-supportive-language-a/);
  [null result](https://pure.uva.nl/ws/files/33032229/Published_article_Altendorf_et_al_2019_.pdf)).
  Use "want to…?" and "we could…", never "you should" or "stop".
- **Limits:** at most N check-ins per hour (default 3), snooze, quiet hours,
  and frequency tied to the existing `interaction.frequency` preference.
- **Rotate check-in variants:** in HabitLab, rotating interventions worked
  better than repeating one but increased attrition, and announcing new
  variants reduced that attrition
  ([HabitLab](https://purl.stanford.edu/qq438qv1791)).
- **Never block by default.** In a field study, blocking distracting sites
  raised self-rated productivity and focus, most for people with low
  self-control, but they also reported more stress
  ([Mark, Iqbal & Czerwinski 2017](https://www.microsoft.com/en-us/research/?p=452322));
  for people who already felt in control, blocking added workload
  ([CHI 2018 follow-up](https://www.microsoft.com/en-us/research/publication/effects-individual-differences-blocking-workplace-distractions/)).
  Strict mode is opt-in and only makes check-ins more persistent.

### D. Resume notes (Moderate)

- When the learner leaves the task, or Curio sees them drift, it captures
  "where you were and what's next" from the walkthrough step, the session
  plan or one quick spoken line. When they return: "you were on step three,
  about to add the row fields."
- Evidence: attention residue, where part of your attention stays on the
  previous unfinished task, hurts performance on the next one; Leroy and
  Glomb's "ready to resume" plan (write down where you were and what's next,
  under a minute) reduces it
  ([Leroy 2009 summary](https://www.uwb.edu/news/2024/05/17/an-ongoing-study-on-the-success-of-staying-focused)).
  The often-quoted "23 minutes to refocus" figure includes time spent on other
  work and is not cleanly sourced to one paper, so **do not quote it**.

### E. Scheduled breaks (Moderate; framed as energy, not productivity)

- The default rhythm is a fixed study/break cycle (for example 25/5,
  adjustable). The pet stretches or naps during breaks.
- Evidence: students on fixed breaks reported less fatigue and distraction
  and more concentration and motivation than students choosing their own
  breaks, with the same task completion
  ([Biwer et al. 2023](https://pubmed.ncbi.nlm.nih.gov/36859717/)). Later
  studies are mixed. Micro-breaks improve vigor (d = 0.36) and reduce fatigue
  (d = 0.35), but the effect on performance was not significant (d = 0.16)
  ([Albulescu et al. 2022](https://doaj.org/article/c6f37b6ba159469296b2cb968b65505f)).
  **Claim energy and fatigue benefits, not more output.**

### F. Self-monitoring: session timeline and reflection (Strong)

- Live timeline of on-goal, drifting and break time; an end-of-session
  summary saved locally; an optional one-line reflection ("what got in the
  way?").
- Evidence: a meta-analysis of 138 randomized studies found that prompting
  progress monitoring improves goal attainment, d = 0.40, with larger effects
  when progress is physically recorded or made public
  ([Harkin et al. 2016](https://eprints.whiterose.ac.uk/91437/)). Most
  included studies were health-related.

### G. Tutoring behaviours during study

| Behaviour | What Curio does | Evidence | Confidence |
|---|---|---|---|
| **Hints first** | Ladder: guiding question → hint → one partial step → worked example. Moves up a rung only on request or after a failed attempt. Never hands over the full answer first. Reuses `coaching_contract.AssistanceLevel` (hint/explanation/worked_example). | Unrestricted GPT-4 raised practice scores 48% but lowered exam grades 17%; a hint-only tutor avoided the harm ([Bastani et al., PNAS 2025](https://knowledge.wharton.upenn.edu/article/without-guardrails-generative-ai-can-harm-education)). A tutor that revealed one step at a time beat in-class active learning in a 194-student crossover trial ([Kestin et al. 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12179260/)). Step-based tutoring systems reach d ≈ 0.76 versus no tutoring, close to human tutors at 0.79 ([VanLehn 2011](https://marginalrevolution.com/marginalrevolution/2013/10/how-good-are-computers-as-tutors.html)). | Strong |
| **Detect hint abuse** | Rapid repeated hint requests → stop escalating and ask the learner to try or to explain what they've tried. | Students who frequently gamed a tutor learned 38% less; hint abuse is common ([Baker et al.](https://learninganalytics.upenn.edu/ryanbaker/BRCKAIED2005Final.pdf); [help abuse wiki](https://learnlab.org/research/wiki/index.php/Help_abuse)). Not asking for help when needed also hurts, so never refuse help outright. | Strong |
| **Wait before stepping in** | When the learner seems stuck, wait a short, adjustable time before offering help, unless they ask. Step in sooner after repeated failures or signs of frustration. | Confusion helped learning only when it was resolved; the authors advise against deliberately confusing struggling students ([D'Mello et al. 2014](https://acuresearchbank.acu.edu.au/item/8v7v6/confusion-can-be-beneficial-for-learning)). | Moderate |
| **Retrieval practice with feedback** | End-of-session mini-quiz (two or three questions on today's concepts) with the correct answer afterwards. | Practice testing rated high utility ([Dunlosky et al. 2013](https://www.psychologicalscience.org/news/releases/which-study-strategies-make-the-grade.html)); beats restudying, and feedback increases the effect ([Adesope et al. 2017](https://journals.sagepub.com/doi/10.3102/0034654316689306)). | Strong |
| **Spaced review** | Review questions come back at growing intervals, timed from the skill model's forgetting curve, delivered at the start of the next session. | Distributed practice rated high utility (Dunlosky); the best gap grows with how long you need to remember ([Cepeda et al. 2006](https://pubmed.ncbi.nlm.nih.gov/16719566/)). | Strong |
| **Mix similar topics** | Review sessions mix *similar, easily confused* concepts (VLOOKUP vs INDEX/MATCH) instead of blocking them. | Interleaving g = 0.42, strongest when categories are similar ([Brunmair & Richter 2019](https://www.psychologie.uni-wuerzburg.de/fileadmin/06020400/2019/Brunmair_Richter_in_press__2019_META-ANALYSIS_OF_INTERLEAVED_LEARNING.pdf)). | Moderate |
| **Self-explanation prompts** | After the learner solves a step on their own: "why did that work?" Not right after a worked example (see next row). | Self-explanation prompts g = 0.55 ([Bisra et al. 2018](https://summit.sfu.ca/item/34322)). | Strong |
| **Fade worked examples as skill grows** | Novices on a concept get a worked example; as mastery rises, partial examples, then problems with hints only. Driven by the skill model. Don't add self-explanation prompts to worked examples. | Worked examples g = 0.48 in maths; adding self-explanation prompts to them had a *negative* effect ([Barbieri et al. 2023](https://oaks.kent.edu/hcri/meta-analysis-worked-examples-effect-mathematics-performance)). Expertise reversal: examples help novices and hinder experts; adaptive fading beat fixed fading ([Salden et al. 2010 via overview](https://en.wikipedia.org/wiki/Expertise_reversal_effect)). | Strong |
| **Planning, monitoring and evaluation prompts** | At start: "what's the first thing you'll do?"; midway: "how's it going against the plan?"; at end: "what would you do differently?" | Metacognitive prompts in computer-based learning g ≈ 0.38 on self-regulation and 0.45 on performance (conference abstract) ([APS 2021](https://www.psychologicalscience.org/conventions/archive/2021icps/paper/33464/)). | Moderate |
| **Informative feedback** | Feedback names what was right or wrong and what to do next, not just "good job". | Feedback d = 0.48, larger when it carries more information ([Wisniewski et al. 2020](https://www.frontiersin.org/articles/10.3389/fpsyg.2019.03087/full)). | Strong |
| **Explain it to the fox** | Optional "teach me" mode: the learner explains a concept; Curio asks naive follow-up questions. | Experiments show benefits of preparing to teach ([Fiorella & Mayer, via review](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9979973/)); a meta-analysis of creating teaching materials found only g = 0.17. | Weak to moderate: optional, no claims |

### H. The pet as a study buddy (Weak: presentation only)

- The pet keeps the learner company during sessions (works on its own little
  task, naps on breaks, celebrates finished goals).
- Evidence: body doubling (working alongside someone) has only small studies
  and preprints, and reports range from helpful to distracting
  ([VR body doubling preprint, n = 12](https://arxiv.org/abs/2509.12153)).
  Pedagogical agents have a small overall effect (g = 0.20) and animation
  didn't matter (use-case-evidence.md §9). **Present it as company, never as
  a proven focus aid.**

## Deliberately not doing

- Blocking sites or apps by default (adds stress and workload for many).
- Continuous screenshots, webcam or emotion detection, keystroke logging.
- Quoting "23 minutes to refocus", "47-second attention span" as a brain
  limit, or any productivity percentage.
- Giving answers before hints during study sessions.
- Gamified punishment (streak loss, guilt messages).

## Privacy

Activity samples, drift episodes, session summaries and review items stay on
the device in SQLite. The model sees a window title only when the rules can't
decide, and the learner can turn that off (rules plus their own corrections
only). Everything is visible and deletable from the session history.

## How we check it works (pilot, not proof)

- Detector quality: log every check-in with the learner's response
  (accepted / dismissed / "wasn't a distraction"). Target a false-alarm rate
  low enough that learners keep the mode on; report the measured rate, not a
  guess.
- Learning: following use-case-evidence.md's pilot design, compare an
  unassisted follow-up task after a hint-first session versus an answer-first
  session. Report as exploratory.
