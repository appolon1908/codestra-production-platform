# Barge-in

When voice activity occurs during TTS, the controller stops speaking, discards
all buffered audio, accepts customer audio, and permits a new transcription and
decision. Tests verify that buffered bytes are removed immediately.

`BARGE_IN_STOP_P95_MS<500` remains an unverified live-runtime target. Local
state-machine execution is not evidence of media/network/TTS stop latency.

