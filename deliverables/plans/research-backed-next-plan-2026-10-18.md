# Research-backed next plan for Jarvis

Date: 18 October 2026

## Research scope and limitation

This plan combines:

- the previously preserved scholarly/web research scan in `deliverables/research/original-discussion.txt`;
- the locally retained paper/model references and candidate source trees;
- Jarvis's measured results through 17 October 2026.

Live scholarly websites were not reachable from the current managed environment on 18 October, so this update does not pretend to be a fresh exhaustive database search. Titles and identifiers below come from the already preserved scan or local primary model documentation. They should be rechecked before publication, but they are sufficient for engineering decisions.

## Research conclusions that materially change the plan

### 1. Bounded agent graphs beat unrestricted autonomy

[ReAct](https://arxiv.org/abs/2210.03629) motivates alternating reasoning, action and observation. For Jarvis, that loop must be a bounded typed state machine, not a free-running prompt loop.

[OSWorld](https://arxiv.org/abs/2404.07972) and [Windows Agent Arena](https://arxiv.org/abs/2409.08264) demonstrate the reliability gap between agents and humans on real computer tasks. The preserved review records original best-agent results of 12.24% versus 72.36% human for OSWorld and 19.5% versus 74.5% for Windows Agent Arena. Exact modern numbers will change, but the design implication remains: do not grant an LLM unrestricted desktop control.

Application to Jarvis:

- keep the LLM as a proposal generator;
- execute one atomic typed capability at a time;
- cap steps, elapsed time and action count;
- verify the real postcondition after every action;
- return `success`, `failed`, `uncertain` or `needs_user`, never infer success from a click or process call.

### 2. Trusted control and untrusted data must be separate

[Not What You've Signed Up For](https://doi.org/10.1145/3605764.3623985), [AgentDojo](https://arxiv.org/abs/2406.13352), [InjecAgent](https://doi.org/10.18653/v1/2024.findings-acl.624), and [CaMeL](https://arxiv.org/abs/2503.18813) support treating webpages, documents, tool output and model text as untrusted data rather than executable instructions.

Application to Jarvis:

- observed text receives provenance labels and can fill only explicitly allowed data fields;
- only the user's trusted turn can establish the task goal;
- no webpage, PDF, email or model response can mint approval;
- policy and broker decisions occur outside the LLM;
- short-lived capability grants bind the exact operation, resource, plan digest, expiry and nonce.

### 3. Tool risk must be tested before real execution

[ToolEmu](https://arxiv.org/abs/2309.15817) supports testing risky tool behavior in simulated environments. AgentDojo adds adversarial prompt-injection scenarios.

Application to Jarvis:

- every capability first runs through a simulator and fault-injection harness;
- tests cover timeout, stale state, wrong process, ambiguous target, forged approval, replay, malicious observed text and verifier disagreement;
- real mode is enabled capability by capability only after simulation gates pass.

### 4. Structured UI evidence should precede screenshots

[Mind2Web](https://arxiv.org/abs/2306.06070) shows the value of reducing large interface representations before model use.

Application to Jarvis:

1. official application API;
2. constrained local API/command;
3. browser DOM;
4. Windows UI Automation/accessibility tree;
5. cropped screenshot/vision;
6. raw coordinates only as a last resort.

For Phase 1 application launching, no vision or coordinate control is needed.

### 5. Whisper's broad multilingual strength does not guarantee Tanglish command accuracy

[Robust Speech Recognition via Large-Scale Weak Supervision](https://arxiv.org/abs/2212.04356) reports Whisper's scale and generalization, but its own model documentation warns of uneven lower-resource language performance, accent/dialect disparities and hallucination/repetition risks. Jarvis's measured Tamil/Tanglish results confirm that limitation on this owner and hardware.

Application to Jarvis:

- do not choose STT using WER alone;
- measure semantic intent, required-slot recall, cancellation/negation recall and selective risk;
- keep transcripts as untrusted evidence;
- abstain or clarify when semantic evidence is incomplete;
- stop spending time scaling generic Whisper after Base, Small, Large-v3-turbo and Large-v3 all failed the owner Tanglish gate.

### 6. Code-mixed text resources are variation sources, not command truth

The reviewed Tamil-English code-mixed corpus paper by Chakravarthi et al. ([SLTU 2020](https://aclanthology.org/2020.sltu-1.28.pdf)) provides useful collection and annotation methodology, but its movie-comment sentiment domain does not match assistant commands. Other reviewed Tanglish datasets have spelling variability, scraped noise, weak provenance or unrelated labels.

Application to Jarvis:

- owner-recorded command/dialogue evidence remains the primary evaluation truth;
- public Tanglish text can provide spelling variants and negative examples only after filtering;
- never infer tool intent labels directly from social-media sentiment or offensive-language corpora;
- preserve both Tamil script and Romanized Tanglish rather than forcing one transliteration.

### 7. Voice turn-taking should remain modular

[Personal VAD](https://arxiv.org/abs/1908.04284) and the [WavChat spoken-dialogue survey](https://arxiv.org/abs/2411.13577) support modular voice activity, turn detection and spoken-dialogue components. A voice or speaker match must not become authorization.

Application to Jarvis:

- start with push-to-talk;
- add local VAD only to trim endpoints and detect interruption;
- use echo cancellation before always-listening behavior;
- make cancellation available from every state;
- add wake-word and personal VAD only after the command pipeline is accurate;
- never approve a destructive action solely from speaker recognition.

### 8. Expressive TTS needs controllable style and streaming, not phonetic substitution alone

[Natural language guidance of high-fidelity TTS with synthetic annotations](https://arxiv.org/abs/2402.01912), which Parler-TTS reproduces, supports natural-language control of pitch, gender and speaking style. The retained Parler implementation also supports incremental audio streaming. [Massively Multilingual Speech](https://arxiv.org/abs/2305.13516) provides broad per-language coverage, but the MMS Tamil checkpoint is a per-language VITS model rather than proof of expressive Tamil-English code switching.

Application to Jarvis:

- prefer one bilingual/code-switch-capable speaker model;
- freeze a short original style description instead of imitating a public figure;
- measure time to first playable audio as well as complete-waveform RTF;
- maintain a pronunciation/text-normalization frontend;
- do not continue treating Tamil phonetic spelling of English words as the primary solution—the owner review already rejected it.

## Target architecture

```text
Push-to-talk / typed input
    -> local input boundary
    -> STT evidence (when voice is used)
    -> deterministic text normalization
    -> conversation state machine
    -> privacy release
    -> primary LLM, authority = none
    -> InteractionEnvelope validation
    -> deterministic plan compiler
    -> policy decision
    -> trusted approval UI when required
    -> short-lived capability grant
    -> Windows capability broker
    -> postcondition verifier
    -> response composer
    -> accepted TTS engine
    -> playback / interruption
```

The existing controller should evolve into this explicit graph. Replacing it with LangGraph now would add migration risk without solving the current blockers; adopt the research pattern, not an unnecessary dependency.

## Core algorithms

### A. Conversation and execution state machine

Use explicit states:

```text
IDLE
LISTENING
TRANSCRIBING
INTERPRETING
CLARIFYING
PLANNING
AWAITING_APPROVAL
EXECUTING
VERIFYING
SPEAKING
CANCELLED
FAILED
```

Rules:

- every event has a session ID, turn ID and monotonically increasing sequence;
- each state has an allowlist of accepted events;
- cancellation is legal from every nonterminal state;
- pending clarification and approval have separate expiries;
- one turn may execute at most one consequential atomic action in Phase 1;
- maximum loop count, elapsed time and provider calls are fixed configuration, not LLM choices;
- unexpected events fail closed.

Test the state machine with generated event sequences: no sequence may execute without a compiled plan and matching policy decision; no approval may be reused; cancellation must prevent all later execution.

### B. Canonical plan digest and one-time approval

1. Compile the LLM proposal into a trusted typed plan.
2. Remove display-only text and serialize security-relevant fields in deterministic canonical JSON.
3. Calculate `plan_digest = SHA-256(canonical_plan)`.
4. Create pending approval:

```text
approval_id = 128-bit random nonce
session_id
task_id
plan_digest
risk_level
issued_at
expires_at
used = false
```

5. The trusted approval UI displays the exact operation, application/resource, reversibility and expected result.
6. On an explicit user gesture, the broker—not the LLM—issues an opaque capability grant.
7. The grant binds:

```text
task_id
plan_digest
capability_id
canonical_resource
maximum_calls = 1
expiry
approval_nonce
broker/audience identity
```

8. The broker atomically marks the nonce consumed before execution.
9. Any digest mismatch, expiry, audience mismatch or replay is denied and audited.

For the prototype, combine Windows named-pipe ACL/caller identity with an HMAC-SHA-256 grant whose key is owned by the trusted broker and protected by DPAPI. Python must not possess a key that can fabricate user approvals. A later production build can replace this with an asymmetric signature and signed broker binaries.

### C. Deterministic risk decision

Do not use an averaged ML risk score; a severe factor must not be diluted by harmless ones.

Calculate the decision as the maximum applicable risk from:

```text
operation effect
data sensitivity
destination
scope/cardinality
reversibility
required privilege
application trust
network effect
```

Suggested policy:

- R0: observe public/nonsensitive state;
- R1: reversible local operation such as opening an allowlisted app;
- R2: local mutation or graceful close where unsaved work may exist;
- R3: external communication, installation, forced termination, deletion, credentials or elevation;
- R4: prohibited behavior such as secret extraction or bypassing security.

Policy output is one of `ALLOW`, `DENY`, `ASK_USER`, `PREVIEW_ONLY`, or `SANDBOX`, plus obligations such as maximum calls and required verifier.

### D. Application registry and broker

The LLM emits only an `ApplicationId`, never an executable path or shell string.

Registry entry:

```text
application_id
display_name and aliases
publisher/signature expectation
canonical executable path or AppsFolder identifier
allowed operations
process/window match rule
risk overrides
verification strategy
```

`app.open` algorithm:

1. validate `ApplicationId` against the registry;
2. canonicalize and recheck the configured target inside the broker;
3. consume a valid capability grant if policy requires it;
4. launch without a shell and without model-supplied arguments;
5. poll for the expected process and top-level window within a bounded timeout;
6. return verified evidence or `uncertain/failed`;
7. audit metadata and evidence digests.

`app.close` algorithm:

1. resolve matching registered processes/windows;
2. clarify if more than one meaningful target exists;
3. send graceful window close first;
4. wait for a bounded verified exit;
5. if an unsaved-work dialog appears, return `needs_user`;
6. treat force termination as a different high-risk capability requiring exact approval.

### E. STT selective prediction and clarification gate

Do not send a single transcript directly to action compilation.

Pipeline:

1. push-to-talk capture;
2. endpoint trimming with local VAD;
3. bounded normalization without modifying the raw WAV;
4. candidate STT produces transcript, language evidence, token/segment confidence and optionally N-best hypotheses;
5. preserve original script and create a separate comparison-normalized form;
6. extract candidate intent, slots, negation/cancel markers and referents;
7. apply a safety gate;
8. accept, clarify or abstain.

Initial rule-based safety gate:

```text
accept only if:
  intent is supported
  all required slots are present
  no critical marker is uncertain
  top hypotheses agree on safety-critical meaning
  entity values come from heard evidence or trusted context
  calibrated confidence exceeds the per-intent threshold
otherwise clarify/abstain
```

Metrics:

- intent exact accuracy;
- required-slot recall and slot F1;
- cancellation/negation/correction recall, target 100% on development safety cases;
- semantic exact packet rate;
- selective risk versus coverage;
- empirical calibration error;
- p50/p95 latency, RTF and peak RSS;
- false execution rate, target zero.

With the current tiny dataset, do not claim statistically valid calibration. Use conservative empirical thresholds. After at least a few hundred representative labeled development utterances, evaluate temperature scaling or isotonic calibration and split-conformal prediction sets for principled abstention.

Candidate strategy:

- freeze all tested Whisper profiles as rejected baselines;
- inspect only clearly licensed multilingual/code-switch candidates with a Windows CPU or convertible ONNX/CTranslate2 path;
- gate each candidate on the same five natural Tanglish files before downloading larger assets or recording more speech;
- if no model passes, prefer typed/push-to-talk transcript confirmation over unsafe execution;
- consider targeted adaptation only after a sufficiently large consented owner dataset exists.

### F. TTS text frontend and streaming

Before synthesis:

1. Unicode normalization without destroying the displayed original;
2. protect application names, paths, acronyms and technical English tokens;
3. normalize numbers, dates and times contextually;
4. apply a versioned pronunciation lexicon;
5. attach language spans only if the selected engine supports them;
6. apply a frozen original voice/style descriptor;
7. synthesize incrementally when supported.

Cache key:

`SHA-256(model_revision || voice_profile_revision || frontend_revision || normalized_text || synthesis_parameters)`

Only cache nonsensitive, reusable phrases. Acknowledgment audio must not falsely imply that an action succeeded.

TTS development gate:

- Tamil clarity >= 4/5;
- mixed clarity >= 3.5/5;
- friendliness/Jarvis fit >= 4/5;
- identity distinctness passes;
- p95 RTF <= 1.0;
- peak RSS < 2 GB;
- report p95 time to first playable audio separately;
- zero use of unconsented public-figure/movie speaker data.

### G. Verification algorithm

Every capability declares a postcondition predicate evaluated from independent evidence.

For `app.open`:

```text
process_identity_matches_registry
AND expected_top_level_window_exists
AND observation_timestamp > action_start
```

For graceful `app.close`:

```text
target_window_absent
AND target_process_absent OR app-defined_background_process_allowed
```

If evidence conflicts or cannot be observed, return `uncertain`; do not let the LLM upgrade uncertainty to success.

## Execution roadmap

### Milestone 0 — Restore the engineering baseline

Work:

1. Replace the brittle MMS wall-clock assertion with a virtual/injected clock or a timeout-relative assertion.
2. Add risk-weighted branch tests for LLM transports/gateway, CLI failures, audit corruption, approval state and action rejection.
3. Fix the Qwen conversion-manifest/verifier mismatch and structured CLI error handling.
4. Raise combined branch coverage from 80.75% to >= 85%.
5. Run one consolidated quality command and update the checkpoint.

Algorithms/testing:

- dependency injection for clock and process observer;
- table-driven boundary tests;
- generated state-machine event sequences;
- fault injection for provider timeout, worker crash and malformed artifact.

Exit gate: Ruff, strict mypy, 188+ tests, branch coverage >= 85%, lock/dependency/workspace verification all pass together without timing flakes.

### Milestone 1 — Digest-bound approval in simulation

Work:

1. Add canonical plan serialization and digest.
2. Add expiring one-time pending approvals.
3. Bind confirmation/cancellation to the exact pending digest.
4. Reject replay, stale confirmation, changed plan and cross-session approval.
5. Persist privacy-safe approval metadata in the hash chain.

Exit gate: all positive/negative approval state-machine tests pass; no simulated action can run with an absent, stale or mismatched approval when policy requires one.

### Milestone 2 — Minimal Windows capability broker

Prerequisite: install the .NET 8 SDK.

Work:

1. Create the C# named-pipe broker and explicit protocol.
2. Apply pipe ACL and verify caller identity.
3. Add broker-owned grant verification and replay cache.
4. Implement `app.open` for the three existing application IDs.
5. Add independent process/window verification.
6. Keep real mode opt-in; simulation stays default.
7. After open is stable, add graceful `app.close`; keep forced termination separate.

Exit gate: the typed request opens/closes only registered apps, rejects forged/expired/replayed grants, verifies outcomes, and never accepts a model-supplied path or command.

### Milestone 3 — Typed end-to-end vertical slice

Scenario:

```text
"Open an app"
-> clarify which app
-> "Calculator"
-> compile
-> policy
-> execute through broker
-> verify
-> report result
-> "close it"
-> resolve referent
-> approval if required
-> graceful close
-> verify
```

Add correction and cancellation at each pending state.

Exit gate: scenario passes repeatedly from a clean machine state, including negative and fault-injection cases.

### Milestone 4 — STT challenger gate

Work:

1. Review one candidate at a time for license, immutable revision, weight hash, native dependency and CPU feasibility.
2. Run only the five-file development pilot first.
3. Measure semantic and safety metrics, not only WER.
4. Reject immediately if critical markers/slots fail or p95 resource limits are impossible.
5. Integrate as evidence only after a candidate passes.

Exit gate: 5/5 semantic commands, all required slots and safety markers preserved, usable p95 RTF/RSS, and zero false action acceptance. If no candidate passes, retain typed input rather than weakening the gate.

### Milestone 5 — Expressive TTS selection

Work:

1. Resolve whether secure read-only repository authentication is authorized for metadata-only Indic Parler inspection; otherwise choose a clearly public alternative/custom consent-cleared path.
2. Verify code, weights and dataset/reference licenses separately.
3. Build the language-aware text frontend.
4. Benchmark development prompts and streaming/TTFA where supported.
5. Conduct blinded owner listening with randomized sample order.

Exit gate: the frozen voice profile meets all development thresholds. Only then unseal held-out prompts.

### Milestone 6 — Voice integration

Work:

1. push-to-talk and endpoint VAD;
2. STT evidence and selective gate;
3. existing conversation controller;
4. approval/broker/verification;
5. TTS streaming/playback;
6. cancellation and barge-in;
7. bounded local telemetry without raw private content.

Performance budget should be measured per stage. Optimize the largest measured contributor; do not guess. Use cached nonsensitive acknowledgments only to improve perceived latency, never to claim premature success.

### Milestone 7 — Broader certification

Build a resettable Windows test environment following OSWorld/Windows Agent Arena principles:

- known initial state;
- execution-based success predicates;
- automatic cleanup/restoration;
- adversarial observed text;
- changed layouts and multiple windows;
- provider/broker/worker failure;
- approval replay and expiry;
- memory and audit tampering;
- 100-request resource drift/soak runs.

Expand the capability registry only after each new capability passes simulation, adversarial, real-execution and verifier gates.

## Work explicitly deferred

- wake word and always-listening microphone;
- autonomous multi-app workflows;
- browser/vision automation;
- permanent personal memory;
- proactive interruption;
- avatar/animation;
- arbitrary shell execution;
- exact actor/public-figure voice cloning.

These features multiply risk and do not solve the current blockers.

## Immediate sequence

The effective order is:

1. quality/coverage and flaky-test repair;
2. canonical plan digest plus one-time approval state;
3. install .NET 8 SDK;
4. narrow broker with verified `app.open`;
5. verified graceful `app.close`;
6. typed end-to-end vertical slice;
7. STT challenger gate;
8. expressive TTS selection;
9. voice integration;
10. wider capability expansion.

This sequence creates useful, testable Jarvis behavior before speech is solved, while preserving the authority boundary needed when speech and more tools are added.

## Arivan/Colibri extension

The local Arivan checkout and its pinned Colibri v1.12.0 source import were reviewed separately on 18 October 2026. The detailed findings are in `deliverables/research/arivan-colibri-reuse-review-2026-10-18.md`.

Adopt immediately:

- hard memory admission and preserved OS headroom;
- bounded FIFO inference scheduling;
- Windows Job Object child-liveness containment;
- token-exact tiny-oracle plus real-checkpoint certification patterns.

Evaluate later:

- Arivan as an isolated loopback OpenAI-compatible provider;
- Brio closed-set scoring as an uncertainty signal for a small certified local model.

Do not adopt now:

- the experimental large-model runtime as Jarvis's primary brain;
- native model tool calls as authority;
- Colibri Segment/Edge distributed inference;
- the model dashboard as the Jarvis UI;
- direct C-runtime linkage into the trusted controller.

Any future Arivan integration must disable prompt/KV persistence by default, use a DPAPI-stored loopback API key, remain outside the trusted action boundary, and pass the same 40-case quality and resource gates as the current Azure route.
