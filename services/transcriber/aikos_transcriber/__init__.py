"""aikos transcriber: speech from the door station and the room keys → text in Home Assistant, locally.

Receiver (rtp + segmentation) → worker per utterance (Whisper, language, echo filter, who is speaking) → Home Assistant.
Modules: config, receiver, worker, audio, whisper, translate, echo, live, ha, identity/ (who is speaking).
Run one side with `python -m aikos_transcriber` (configuration from the environment, see config.py).
"""
__version__ = "1.2.1"
