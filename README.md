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

