# Transcription

Validated live or recorded audio is separated by channel when reliable,
chunked, transcribed by Faster-Whisper, speaker-labelled, finalized and sent to
middleware as references. Segments contain ID, call, speaker, start/end,
language, text, confidence and final state.

Stereo campaigns may identify agent/customer channels. Mixed audio uses
speaker `UNKNOWN` unless diarization evidence is sufficient; the system must
not invent speaker identity. Direct transcript storage is never public.

