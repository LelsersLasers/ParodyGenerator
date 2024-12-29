# Parody Generator

Given input videos, extract words and matches them to a song.
Example goal: https://www.youtube.com/watch?v=f1isY4zw9lE

## Tech Stack

- Python
- Whisper (audio to text)
- SQLite (storing transcriptions/words/timestamps)
- Spleeter (audio separation) (run through Docker)
- FFMPEG (converting mp4/mp3 to wav and merging acompaniment with voice)
- Pydub (general audio processing, cutting, merging)

## Current State

- It does sort of work.
- The main issue is that the transcriptions/timestamps are not super accurate.
- Also, splicing and replacing audio word by word has some issues, meaning some words (like really short ones) are not well down.
- It also sounds really choppy.
- I did not spend much time finding input audio, so there are a lot of words without matches
- It is also a bit finicky to set up as some files/paths are not very flexible.