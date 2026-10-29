# Tanglish resources and Tamil-dub interaction review

Updated: 10 October 2026

## Conclusion

The project is now aimed at the correct language problem: natural spoken Tanglish with short, contextual follow-ups. No reviewed public text corpus is suitable as direct command truth, and movie material is not suitable as training data. The correct Phase 1 design combines owner-recorded speech, filtered Tanglish text variation, and original multi-turn dialogue tests.

## Tanglish resource findings

### Tanglish-Corpus-185k

Source: <https://huggingface.co/datasets/vishnu-n/Tanglish-Corpus-185k>  
Reviewed revision: `927f5b497b9f9e35ffc2a10b621a97f6e02ac9c2`

- 185,973 text rows: 174,331 YouTube, 11,549 DravidianCodeMix and 93 Reddit rows.
- Useful for colloquial constructions, negative/background examples and spelling variants such as the `pannu` family.
- Weak for direct Jarvis command supervision: only sparse examples mention Notepad, Calculator, volume or screenshots.
- User-generated comments contain handles, profanity and uncontrolled subject matter. The repository claims CC BY 4.0, but upstream YouTube/Reddit provenance requires a separate legal/relicensing decision before redistribution or training.

Decision: use only a locally filtered, provenance-preserving research derivative for variation mining. Do not treat it as intent labels or acoustic data.

### nlp-for-tanglish

Source: <https://github.com/goru001/nlp-for-tanglish>  
Reviewed revision: `46db92b...`

- Historical FastAI/ULMFiT notebooks under MIT; data and trained models are external.
- The transliteration notebook checks the Devanagari Unicode range rather than Tamil and contains threshold logic that is unsuitable for production use.
- The stack is old and is not a Windows/Python 3.12 inference choice.

Decision: research reference only. Reimplement needed normalization tests rather than adopting the code or model.

### Kaggle transliterated-word dataset

Source: <https://www.kaggle.com/datasets/younusmohamed/tanglish-and-tamil-transliterated-words-dataset>  
Reviewed version: 4

- The downloaded CSV has 242,337 rows and two fields, `word` and `count`; it does not contain Tamil-to-Roman pairs or cleaned canonical forms.
- High-frequency scraping artifacts include `com`, `youtube`, `href` and `amp`.
- It remains useful as a filtered frequency prior for variants such as `pannu`, `panna`, `panni`, `pannunga`, `vendam`, `venam`, `illa` and `illai`.

Decision: filter aggressively and use only as a frequency prior. It is not a transliterator or semantic corpus.

### Morgan-Tanglish-v7

Sources: <https://www.researchgate.net/publication/407468354_Morgan-Tanglish-v7_Sentence_Embeddings_for_Romanised_Tamil-English_Code-Mixed_Text> and <https://huggingface.co/vishnu-n/Morgan-Tanglish-v7>  
Reviewed model revision: `87357d...`

- Apache-2.0, multilingual MiniLM-derived, 384-dimensional sentence embeddings; repository size is about 488 MB.
- Reported TanglishSTS Spearman correlation is 0.8689, but nuanced and technical subsets are materially lower.
- The benchmark is small, many training/evaluation pairs were machine-generated, and the paper reports limited human annotation.

Decision: benchmark later as a semantic intent matcher on private held-out Jarvis commands. It is not an LLM, an STT model or a policy authority.

### Academic corpora

- Chakravarthi et al. 2020, <https://aclanthology.org/2020.sltu-1.28.pdf>: 15,744 code-mixed posts and useful annotation methodology, but movie-comment sentiment data rather than commands. The paper is CC BY-NC; the linked dataset needs its own license verification.
- CEUR offensive-language work, <https://ceur-ws.org/Vol-3159/T3-8.pdf>: confirms spelling variability and overfitting risk in a small Tanglish classification set; labels are unrelated to assistant intent.
- Tamil Lyrics Corpus, <https://aclanthology.org/2021.dravidianlangtech-1.1.pdf>: large but poetic/formal and copyright-sensitive, not conversational commands.
- Tanglish sociolinguistic background, <https://www.degruyter.com/document/doi/10.1515/glot-2008-0016/html>: useful context, but the full source was not openly available for verification.

Decision: use as methodology/background, not training truth.

### Tanglish voice-agent blog and released models

Source: <https://blog.sugiv.fyi/tanglish-voice-agent-speech-to-speech-stack>

- Valuable engineering pattern: streaming VAD, modular STT/transliteration/LLM/TTS, interruption and latency measurement.
- The described cloud GPU stack uses large models and is unsuitable for the Ryzen 5 7520U Phase 1 target.
- A separate transliteration model adds about 1.44 seconds in the reported pipeline, so Jarvis should first test whether preserving dual-script STT and normalizing only for comparison is sufficient.
- The released Qwen model is roughly 16.4 GB BF16. The Fish Speech voice assets declare a non-commercial share-alike license and require stronger provenance/consent review than the blog summary suggests.

Decision: adopt the modular streaming ideas, not the cloud models or private dataset.

## Tamil-dubbed Tony/JARVIS interaction analysis

The review used publicly viewable short clips from Iron Man, Iron Man 2, Iron Man 3, The Avengers and Avengers: Age of Ultron. Automatic Tamil transcripts were unreliable, so conclusions are restricted to interaction structure observable from scene context. Exact lexical claims require a licensed Tamil audio source and manual native-speaker verification.

Stable behavior patterns:

1. Tony gives incremental commands rather than one complete formal request.
2. Follow-ups depend on the shared screen/workspace: this, that, the smaller ones, the previous result.
3. JARVIS asks a narrow question when a missing scope changes the result.
4. JARVIS reports outcome plus a useful reason, constraint or resource status.
5. Tony is fast, elliptical and colloquial; JARVIS is calm, precise and concise.
6. Technical names and nouns remain English or transliterated inside Tamil grammar.
7. The wake name starts a session but is not repeated on every follow-up.
8. Proactive speech is reserved for relevant danger, failure or resource constraints.
9. Urgency shortens both command and response.

Age of Ultron is the end of JARVIS as Tony's assistant; later Tony interactions use F.R.I.D.A.Y. Those later scenes can inform a general assistant interaction style but must not be labeled JARVIS evidence.

Copyright boundary: movie clips and dialogue will not be shipped, redistributed or used as a speech-training corpus. Derived annotations describe dialogue acts and context requirements; all benchmark dialogue is newly written.

## Resulting Phase 1 evaluation model

| Layer | Evidence | Primary metrics |
|---|---|---|
| Speech | Owner-recorded English, Tamil and natural Tanglish | intent/entity/negation preservation, latency, RTF; WER/CER diagnostic |
| Understanding | Filtered spelling variants and private text paraphrases | intent accuracy, slot F1, cancel/negation recall, confidence calibration |
| Dialogue | Original pattern-derived multi-turn scenarios | referent resolution, correction, clarification, pending-operation safety, response act |

The first vertical slice is a contextual file workflow: show latest downloads, open the first result, correct to the second, request a copy, and cancel or confirm through policy. It tests more of the intended Jarvis behavior than forty unrelated one-shot commands.
