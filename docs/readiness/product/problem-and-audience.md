# Problem and audience evidence

Checked 24 October 2026. Findings belong to their original populations/systems,
not Curio. The starting register was
[use-case-evidence.md](../../use-case-evidence.md); sources marked rechecked were
independently opened in this pass. Access limits remain attached to other leads.

## Studies and limits

| Evidence / date | Sample and method | Finding relevant to the problem | Limitation and implication |
| --- | --- | --- | --- |
| [Pause-and-Play, UIST 2011](https://grail.cs.washington.edu/wp-content/uploads/2015/08/pongnumkul2011pal.pdf), rechecked, pp. 7–8 | 15 participants, ages 18–49, university-list recruitment; within-subject SketchUp tasks, counterbalanced interface order, about one hour. Collection dates not recovered. | 13 preferred synchronized playback, but completion time and error rate did not differ significantly. | Small, older, non-LLM study with two displays. Preference supports investigating coordination friction, not a speed claim. |
| [AQuA, CHI 2024](https://arxiv.org/html/2403.05213v1), manuscript 8 March 2024, rechecked | 633 questions from 5,944 comments/messages in 20 Fusion 360 tutorials; visual-anchor collection with 24 participants and answer evaluation with 16. Collection dates not recovered. | Visual references and software documentation supported answers about tutorial content. | Answer quality is not desktop completion or retention. Visual input/retrieval/prompts were combined; screenshot benefit alone not isolated. Introduction inconsistently says 663 questions; abstract reports 633, used here and in the existing register. |
| [SoftAIBot, IUI 2024](https://arxiv.org/html/2402.08030v1), manuscript February 2024, rechecked, §§3–4 | 16 people, mainly university-list/snowball recruitment; remote within-subject Excel/PowerPoint tasks, think-aloud, questionnaires/interviews, counterbalanced conditions. Collection dates not recovered. | Better expert-rated answers did not translate into significant task-completion/accuracy differences; users could still trust faulty help. | Small, highly educated sample and older GPT-4 interventions. Contrary evidence against assuming tailored fluent advice produces correct work. |
| [GuidedCopilot, CHI 2025](https://arxiv.org/html/2504.15549v1), manuscript 22 April 2025, rechecked, §§5–8 | 20-person within-subject Sheets/Figma comparison, counterbalanced tasks/conditions, observed task evaluation/interviews; follow-up design exploration with 10. Collection dates not recovered. | Greater perceived control with guided assistance: 18/20 in Sheets, 16/20 in Figma. Some participants preferred full automation. | Includes semi-automation and visuals, not Curio’s pointer alone. Perceived learnability is not delayed retention or universal preference for guidance. |
| [AskEase, January 2026 manuscript](https://arxiv.org/html/2601.18092v1), rechecked, §§5–6 | 12 screen-reader users; within-subject unfamiliar computer tasks versus usual tools, 20-minute task periods, workload/interviews. Collection dates not recovered. | Mean completed tasks: 1.5 of two with AskEase versus 0.5 with baseline. | Small specialized population and different accessibility-oriented system. Does not establish Curio accessibility or justify visual-only guidance for blind users. |
| [Pew report](https://www.pewresearch.org/internet/2021/09/01/the-internet-and-the-pandemic/) and [technology-help chapter](https://www.pewresearch.org/internet/2021/09/01/navigating-technological-challenges/), published 1 September 2021, rechecked | 4,623 U.S. adults, 12–18 April 2021; address-recruited American Trends Panel, online survey weighted for U.S. representation. | 26% generally needed help setting up/learning new devices; 66% among ages 75+. | Broad device help during the pandemic, not current desktop-tutoring demand, willingness to pay or market size. Age alone is not a persona. |
| [Luo and Guo, October 2026](https://www.tandfonline.com/doi/full/10.1080/10447318.2026.2734326), **register-only; publisher returned 403 again** | Existing register reports n=87 survey at one university, January–April 2025 convenience/snowball recruitment, plus eight observed Maya users. | Register reports rewatching 58/87, result mismatch 51/87, attention switching 34/87. | Full methods not independently reverified here. Do not headline these figures until the paper is accessible/checked. No population estimate follows. |

The register also discusses older-adult mobile guidance, animated agents, video
segmentation and fraud losses. Those sources were not independently rechecked
here. None establishes that Curio’s pet improves learning, that segmentation
always helps, or that Curio prevents scams. Keep these propositions unsupported.

## Firsthand accounts, with provenance

Individual experiences below are not Curio testimonials. We conducted no
interviews. Paraphrases avoid presenting borrowed quotations as our user discovery.

| Account | Date, sample and collection method | What it illustrates / limits |
| --- | --- | --- |
| Pause-and-Play P3 and P12, results section of the 2011 paper above | Two selected accounts within the 15-person moderated study; exact session dates unavailable. | P3 valued not manually stopping when behind; P12 preferred familiar seeking controls. Motivate testing coordination and control; selected accounts cannot establish frequency. |
| GuidedCopilot P03 and P17, §6.1.2 above | Two selected interviews in the 20-person 2025 study; exact dates unavailable. | P03 described template-customization effort; P17 wanted completion rather than learning shape creation. Challenges a single assistance style for every task/user. |
| [Blender shadow-catcher request](https://www.reddit.com/r/blenderhelp/comments/1qj2a9a/blender_5_eevee_help_with_setting_up_shadow/), rechecked | One pseudonymous public author, purposively found through tutorial/version-mismatch search. Accessed 24 October 2026; rendered relative age and search publication labels conflict, so exact post date is unverified. | Author could not reconcile old blend-mode instructions with changed EEVEE documentation. Concrete mismatch example, not independently verified task evidence, demand estimate or proof Curio solves it. |
| Original register’s [Blender thread](https://www.reddit.com/r/blender/comments/gaxmyw/) and [Blackmagic report](https://forum.blackmagicdesign.com/viewtopic.php?p=1062375&t=204499) | Register-level leads only. Original Blender URL failed retrieval here; Blackmagic access was already limited. Dates/sample not reliably recovered. | Not fresh corroboration. Comments, votes and search results are not independent learners or prevalence estimates. |

## Audience audit: findings versus inference

**Research finding:** tutorial/application coordination, missing context and
mapping instructions to controls occur in studied software-learning situations.
Wrong AI advice and unwanted automation can create work. This establishes a
plausible problem, not product-market fit.

**Initial audience inference:** adults learning an unfamiliar task in feature-rich
Windows software, starting with students/self-directed learners in one prepared
application. Recruit by task unfamiliarity and concrete recent difficulty, not
presumed intelligence, age or general computer incompetence.

**Open assumptions:** learners need help often enough to return; will share
screenshots and tolerate audio/overlays; prefer a companion to existing help;
and find history-based adaptation useful. Fewer manual uploads may reduce
file-picker effort while increasing concern about all-monitor capture. No
Curio willingness-to-pay, repeat-use or accessibility evidence was found.
A seeded dashboard supplies none of these facts.

**Recommendation:** follow the existing [impact protocol](../impact/protocol.md)
for an exploratory 6–10-person counterbalanced pilot; this is a proposed sample,
not recruited participants. Interview about a recent failure before showing the
product. Observer-check final state, retain timeouts/misleading advice, and count
researcher interventions. Test an unassisted related task before claiming
learning. Include an available screen-aware baseline as well as usual resources.
A small pilot identifies failure modes, not population effects. No experiment
or participant session was run by this workstream.
