# Alternatives and demonstrable differentiation

Checked 24 October 2026. This is a documentation comparison, not a hands-on
benchmark. Vendor sources establish advertised behavior, not independent efficacy.
Availability, plan and region need checking on the demonstration machine.
“Not established” means the reviewed sources do not answer the question; it does
not mean a competitor lacks the capability. No product is ranked overall.

## User, task and context

| Alternative / category | Specific user and task | Context acquisition and repeated-upload burden |
| --- | --- | --- |
| Microsoft Copilot Vision / screen-aware assistant | Desktop user asks where to go next in an unfamiliar application. | User shares visual context during a voice session; repeated manual screenshot uploads are unnecessary during sharing. Current Microsoft 365 documentation describes session-bound visual input and work-data grounding. Do not conflate this SKU with every consumer Copilot rollout. [Vision mechanics](https://support.microsoft.com/en-us/microsoft-365-copilot/how-vision-microsoft-365-works). |
| Gemini Live / screen-aware assistant | Android user discusses their screen; Chrome user asks about a page. | Android sharing sends the full device screen; hold/lock stops sharing and requires re-sharing. Chrome Live follows the shared tab and can include other tabs. Neither fairly represents a fresh screenshot-upload burden for every question. [Android instructions](https://support.google.com/gemini/answer/15274899?co=GENIE.Platform%3DAndroid&hl=en-CA), [Chrome instructions](https://support.google.com/gemini/answer/16363185?hl=en). |
| Scribe / reusable tutorial documentation | Process owner records a workflow for a colleague to follow later. | Browser/desktop capture generates steps and screenshots; mobile uses uploaded images. Readers reuse the guide. Capture authoring and maintenance effort are distinct from learner effort. [Features](https://scribe.com/features). |
| Whatfix Flows / interactive tutorial and digital adoption | Employee completes a supported business process inside an organization’s application. | Authored steps overlay the web application; targeting can use login, URL and visible elements. Requires deployment and authored content rather than learner screenshot uploads. [Flows](https://support.whatfix.com/docs/what-are-flows), [segmentation](https://support.whatfix.com/docs/segmentation-best-practices). |
| Copilot in Excel / software copilot | Spreadsheet user builds formulas, charts or PivotTables, or requests workbook edits. | Works in the workbook, with chat, plan and edit modes. Upload-only chat is an inadequate proxy for this integrated context. [Excel FAQ](https://support.microsoft.com/en-us/excel/copilot/frequently-asked-questions-about-copilot-in-excel). |
| Khanmigo / AI tutor | Learner requests academic hints/explanations, including help with a photographed problem. | Learners supply necessary context; image uploads are supported. History retains a generated image description rather than the original. Live desktop acquisition is not established here. [Guidelines](https://support.khanacademy.org/hc/en-us/articles/13860282793869-What-are-the-Community-Guidelines-for-Khanmigo), [history](https://support.khanacademy.org/hc/en-us/articles/14394854880909-How-do-I-view-my-child-s-Khanmigo-chat-history). |
| Curio / Windows companion prototype | Learner asks for the next action in an unfamiliar desktop task. | Ordinary turns automatically capture all monitors, including click-triggered continuation turns. No file picker each step, but images are still acquired/sent per turn; this is not continuous video. Tutorial/equation capture requires feature buttons. [Turn pipeline](../../../curio-py/curio/companion_manager.py), [capture](../../../curio-py/curio/screen_capture.py), [coaching](../../../curio-py/curio/coaching_runtime.py). |

## Guidance, recovery, reuse, adaptation and control

| Alternative | Visual guidance and mistake recovery | Workflow reuse / sharing | Assistance adaptation | Verification and user control |
| --- | --- | --- | --- | --- |
| Copilot Vision | Microsoft documents highlighting and next-step discussion. | Visual sessions do not reuse earlier screens; other history features should not be equated with reusable task paths. | Conversational follow-ups; inspectable concept-mastery model not established here. | User starts sharing. Vision does not click, type or scroll. Outcome verification not established. [Getting started](https://support.microsoft.com/en-gb/microsoft-365-copilot/get-started-vision-microsoft-365-copilot). |
| Gemini Live | Chrome Live can scroll/highlight relevant page content; this feature is rolling out. | Android chats can be resumed; shared tutorial-path export not established here. | Interruption and conversational follow-ups; longitudinal skill calibration not established. | Stop screen/tab sharing and manage permissions. Highlighting/navigation is not a correctness check. Sources in first table. |
| Scribe | Annotated steps; authors revise screenshots/instructions. Live diagnosis of a reader’s wrong app state not established here. | Link/embed sharing; exports and desktop capture depend on plan. | Author-customized guide; concept-based help fading not established here. | Author review, edits and redaction. Capturing a process does not prove a reader completed it. [Workflow](https://scribe.com/tools/documentation-app), [plans](https://scribe.com/pricing). |
| Whatfix Flows | In-app overlays; docs expose branching, back/resume, completion-rule and element-reselection controls. | Authored flows are repeatedly delivered to users. | Segmentation targets content and roles; distinct from Curio’s heuristic concept estimate. | Configured step progression has more structure than a model claim alone, but does not establish every business outcome. Sources in first table. |
| Copilot in Excel | Generates/edits workbook content; user can plan before editing. This executes tasks as well as explaining. | Workbook output is retained; reusable teaching-path sharing not established here. | Mode/prompt choices; validated cross-app learning transfer not established here. | Microsoft instructs users to review/verify output. Excel web shortcuts include cancellation/acceptance. [FAQ](https://support.microsoft.com/en-us/excel/copilot/frequently-asked-questions-about-copilot-in-excel), [controls](https://support.microsoft.com/en-us/accessibility/excel/keyboard-shortcuts-in-excel). |
| Khanmigo | Hints, questions, explanations; feedback for inaccurate replies. Desktop target-pointing not established here. | Teacher/parent visibility and conversation history rather than a desktop path map. | Reading-style/language preferences and responsive dialogue. | Guidelines require checking other sources. Feedback is not independent mathematical verification. [Preferences](https://support.khanacademy.org/hc/en-us/articles/19846024600845-How-can-I-change-the-default-language-that-Khanmigo-responds-in), [feedback](https://support.khanacademy.org/hc/en-us/articles/13983335341069-How-do-I-leave-feedback-about-Khanmigo). |
| Curio | POINT overlay, fresh-screen continuation and conversational retry. Recovery depends on model interpretation. | Local task paths; configured opt-in summary sharing and pull/merge. No crowd adoption established. | Assistance-weighted BKT estimates/concept aliases affect request context; Skills UI exposes evidence/reset/export. | User performs actions; Escape cancels. Ordinary completion is model-reported. Separate polynomial tutor has bounded exact checks and recognition confirmation. [Audit](claim-audit.md). |

## Two advantages the prototype can exhibit

1. **Reusable guidance connected to inspectable assistance estimates.** A recorded
   walkthrough can become context for a later task; concept evidence can change
   requested assistance and be inspected/reset. A concrete alternative to a fixed
   guide. Real-storage/loopback tests establish data flow with scripted replies,
   not reliable live adaptation or superior learning.
2. **Fresh-screen, click-paced help inside a Windows companion.** Ask, see a
   target, act, then get another screen-grounded instruction without manually
   attaching each screenshot. An advantage over a manual-upload workflow, not
   over all screen-aware assistants.

These are implemented contributions, not uniqueness claims. Neither has a
measured user-benefit advantage over alternatives. Arbitrary app-update recovery,
calibrated mastery, proven cross-app transfer and learning improvement remain
aspirations. The exact tutor is a bounded verification exhibit, not a general
desktop-verification mechanism.

Prior art is explicit: Microsoft’s [12 June 2025 Windows announcement](https://blogs.windows.com/windowsexperience/2025/06/12/copilot-vision-on-windows-with-highlights-now-available-in-us/)
already described showing users where to click with Highlights. Current support
pages can redirect between product families; this dated consumer announcement
establishes overlap without assuming current availability for every account.

## Research limits

Sources are official vendor/help pages and the primary studies in
[problem-and-audience.md](problem-and-audience.md). iorad was considered, but its
homepage exposed almost no descriptive content through the research tool;
Whatfix provides the documented interactive-tutorial comparison instead. No
accounts were created or competitor trials run. Do not imply every alternative
requires repeated uploads or offers only static text. Fair trial suggestions are
in [handoff.md](handoff.md).
