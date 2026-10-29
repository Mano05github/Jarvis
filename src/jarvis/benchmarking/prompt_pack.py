"""Deterministic Phase 1 Tamil-English speech evaluation prompt pack."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from jarvis.benchmarking.corpus import CorpusEntry

Prompt = tuple[str, str]

ENGLISH_PROMPTS: tuple[Prompt, ...] = (
    ("Open Notepad", "app.open"),
    ("Open the calculator", "app.open"),
    ("Launch the web browser", "app.open"),
    ("Close the current window", "app.close"),
    ("Set the volume to thirty percent", "media.volume"),
    ("Increase the volume", "media.volume"),
    ("Mute the audio", "media.mute"),
    ("Play the next song", "media.next"),
    ("Pause the music", "media.pause"),
    ("Resume playback", "media.play"),
    ("What time is it", "system.time"),
    ("What is today's date", "system.date"),
    ("Set a timer for five minutes", "timer.set"),
    ("Cancel the timer", "timer.cancel"),
    ("Remind me to drink water at six", "reminder.create"),
    ("Create a note called project ideas", "note.create"),
    ("Search for the Jarvis architecture document", "file.search"),
    ("Find my latest download", "file.search"),
    ("Show the system status", "system.status"),
    ("How much memory is available", "system.memory"),
    ("Is the laptop connected to Wi-Fi", "system.network"),
    ("Read the last notification", "notification.read"),
    ("Repeat your last response", "response.repeat"),
    ("Speak a little slower", "speech.speed"),
    ("Stop speaking", "speech.cancel"),
    ("Cancel the current request", "assistant.cancel"),
    ("Take a screenshot", "screen.capture"),
    ("Turn on do not disturb", "system.focus"),
    ("What is the weather forecast", "query.weather"),
    ("Convert twenty five Celsius to Fahrenheit", "query.convert"),
    ("Calculate one hundred and twenty divided by eight", "query.calculate"),
    ("Spell the word asynchronous", "query.spell"),
    ("Open Visual Studio Code", "app.open"),
    ("Search for Python three point twelve documentation", "web.search"),
    ("Start a new PowerShell window", "app.open"),
    ("Create a folder named voice tests", "file.create_folder"),
    ("Rename the file to benchmark results", "file.rename"),
    ("How much battery is remaining", "system.battery"),
    ("Lock the computer", "system.lock"),
    ("Jarvis are you listening", "assistant.status"),
)

TAMIL_PROMPTS: tuple[Prompt, ...] = (
    ("நோட்பேடைத் திற", "app.open"),
    ("கால்குலேட்டரைத் திற", "app.open"),
    ("இணைய உலாவியைத் திற", "app.open"),
    ("தற்போதைய சாளரத்தை மூடு", "app.close"),
    ("ஒலியளவை முப்பது சதவீதமாக வை", "media.volume"),
    ("ஒலியளவை அதிகரிக்கவும்", "media.volume"),
    ("ஒலியை நிறுத்து", "media.mute"),
    ("அடுத்த பாடலை இயக்கு", "media.next"),
    ("இசையை இடைநிறுத்து", "media.pause"),
    ("மீண்டும் இசைக்கத் தொடங்கு", "media.play"),
    ("இப்போது மணி என்ன", "system.time"),
    ("இன்றைய தேதி என்ன", "system.date"),
    ("ஐந்து நிமிடங்களுக்கு டைமர் வை", "timer.set"),
    ("டைமரை ரத்து செய்", "timer.cancel"),
    ("ஆறு மணிக்கு தண்ணீர் குடிக்க நினைவூட்டு", "reminder.create"),
    ("திட்ட யோசனைகள் என்ற குறிப்பை உருவாக்கு", "note.create"),
    ("ஜார்விஸ் கட்டமைப்பு ஆவணத்தைத் தேடு", "file.search"),
    ("சமீபத்தில் பதிவிறக்கிய கோப்பைக் கண்டுபிடி", "file.search"),
    ("கணினியின் நிலையை காட்டு", "system.status"),
    ("எவ்வளவு நினைவகம் கிடைக்கிறது", "system.memory"),
    ("மடிக்கணினி வைஃபையுடன் இணைந்துள்ளதா", "system.network"),
    ("கடைசி அறிவிப்பைப் படி", "notification.read"),
    ("கடைசி பதிலை மீண்டும் சொல்", "response.repeat"),
    ("சற்று மெதுவாக பேசு", "speech.speed"),
    ("பேசுவதை நிறுத்து", "speech.cancel"),
    ("தற்போதைய கோரிக்கையை ரத்து செய்", "assistant.cancel"),
    ("திரைப்பிடிப்பு எடு", "screen.capture"),
    ("தொந்தரவு செய்ய வேண்டாம் நிலையை இயக்கு", "system.focus"),
    ("வானிலை முன்னறிவிப்பு என்ன", "query.weather"),
    ("இருபத்தைந்து செல்சியஸை ஃபாரன்ஹீட்டாக மாற்று", "query.convert"),
    ("நூற்று இருபதை எட்டால் வகுத்தால் என்ன", "query.calculate"),
    ("அசின்க்ரோனஸ் என்ற சொல்லை எழுத்துக்கூட்டி சொல்", "query.spell"),
    ("விஷுவல் ஸ்டூடியோ கோடைத் திற", "app.open"),
    ("பைத்தான் மூன்று புள்ளி பன்னிரண்டு ஆவணங்களைத் தேடு", "web.search"),
    ("புதிய பவர்ஷெல் சாளரத்தைத் திற", "app.open"),
    ("குரல் சோதனைகள் என்ற கோப்புறையை உருவாக்கு", "file.create_folder"),
    ("கோப்பின் பெயரை பெஞ்ச்மார்க் முடிவுகள் என்று மாற்று", "file.rename"),
    ("பேட்டரியில் எவ்வளவு மின்சாரம் உள்ளது", "system.battery"),
    ("கணினியைப் பூட்டு", "system.lock"),
    ("ஜார்விஸ் நீ கேட்கிறாயா", "assistant.status"),
)

MIXED_PROMPTS: tuple[Prompt, ...] = (
    ("Jarvis Notepad ஐ open செய்", "app.open"),
    ("Calculator ஐ திறந்து வை", "app.open"),
    ("Chrome browser ஐ launch செய்", "app.open"),
    ("Current window ஐ close செய்", "app.close"),
    ("Volume ஐ thirty percent ஆக வை", "media.volume"),
    ("Volume கொஞ்சம் increase செய்", "media.volume"),
    ("Audio வை mute செய்", "media.mute"),
    ("Next song ஐ play செய்", "media.next"),
    ("Music ஐ pause செய்", "media.pause"),
    ("Playback ஐ resume செய்", "media.play"),
    ("Jarvis இப்போது time என்ன", "system.time"),
    ("Today's date என்ன", "system.date"),
    ("Five minutes க்கு timer set செய்", "timer.set"),
    ("Current timer ஐ cancel செய்", "timer.cancel"),
    ("Six PM க்கு water குடிக்க remind செய்", "reminder.create"),
    ("Project ideas என்று ஒரு note create செய்", "note.create"),
    ("Jarvis architecture document ஐ search செய்", "file.search"),
    ("Latest download ஐ கண்டுபிடி", "file.search"),
    ("System status ஐ காட்டு", "system.status"),
    ("Available memory எவ்வளவு", "system.memory"),
    ("Laptop Wi-Fi connect ஆகியிருக்கிறதா", "system.network"),
    ("Last notification ஐ படி", "notification.read"),
    ("Last response ஐ repeat செய்", "response.repeat"),
    ("கொஞ்சம் slow ஆக பேசு", "speech.speed"),
    ("Speech ஐ stop செய்", "speech.cancel"),
    ("Current request ஐ cancel செய்", "assistant.cancel"),
    ("Screen screenshot எடு", "screen.capture"),
    ("Do not disturb mode ஐ on செய்", "system.focus"),
    ("Weather forecast என்ன", "query.weather"),
    ("Twenty five Celsius ஐ Fahrenheit ஆக convert செய்", "query.convert"),
    ("One hundred and twenty divided by eight calculate செய்", "query.calculate"),
    ("Asynchronous என்ற word ஐ spell செய்", "query.spell"),
    ("Visual Studio Code ஐ open செய்", "app.open"),
    ("Python three point twelve documentation ஐ search செய்", "web.search"),
    ("New PowerShell window ஐ start செய்", "app.open"),
    ("Voice tests என்ற folder create செய்", "file.create_folder"),
    ("File name ஐ benchmark results என்று rename செய்", "file.rename"),
    ("Battery remaining எவ்வளவு", "system.battery"),
    ("Computer ஐ lock செய்", "system.lock"),
    ("Jarvis நீ listening mode ல இருக்கிறாயா", "assistant.status"),
)


def _entries(
    language: Literal["ta", "en", "mixed"], prompts: Sequence[Prompt]
) -> list[CorpusEntry]:
    entries: list[CorpusEntry] = []
    for index, (reference, intent) in enumerate(prompts, 1):
        condition_slot = (index - 1) % 5
        condition: Literal["quiet-near", "normal-room", "controlled-noise"]
        if condition_slot in {0, 1}:
            condition = "quiet-near"
        elif condition_slot in {2, 3}:
            condition = "normal-room"
        else:
            condition = "controlled-noise"
        split: Literal["development", "held-out"] = "held-out" if index % 5 == 0 else "development"
        utterance_id = f"{language}_{index:03d}"
        entries.append(
            CorpusEntry(
                utterance_id=utterance_id,
                language=language,
                reference=reference,
                intent_label=intent,
                condition=condition,
                split=split,
                audio_file=f"raw/{language}/{utterance_id}.wav",
                consented=True,
            )
        )
    return entries


def build_phase1_corpus() -> list[CorpusEntry]:
    """Build the balanced, deterministic 120-utterance Phase 1 corpus."""
    return [
        *_entries("en", ENGLISH_PROMPTS),
        *_entries("ta", TAMIL_PROMPTS),
        *_entries("mixed", MIXED_PROMPTS),
    ]
