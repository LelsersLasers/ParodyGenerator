import string
import sqlite3
import os
import subprocess
import whisper
import random
import alive_progress

PUNCTUATION = list(string.punctuation) + [" ", "“", "”", "¿", "¡", "。", "，", "！", "？", "：", "、", "；", "．"]


DB_FILE = "database.db"
INPUT_FOLDER = "input"
PREP_FOLDER = "prep"
WHISPER_MODEL = "tiny.en"
SONG_PATH = "song"
SONG_FILE = "song.mp3"
SPLEETER_OUTPUT = "spleeter_output"
OUTPUT_VOICE_FILE = "output_voice.mp3"
OUTPUT_FILE = "output.mp3"
TEMP_FOLDER = "temp"
CONCAT_LIST_FILE = "concat_list.txt"

#------------------------------------------------------------------------------# 
# Setup SQLite3 database

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS words (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	word TEXT NOT NULL,
	file TEXT NOT NULL,
	start TEXT NOT NULL,
	end TEXT NOT NULL
);
"""

DROP_TABLE = "DROP TABLE IF EXISTS words;"

print("Preparing a clean database")
db = sqlite3.connect("database.db")
db.row_factory = sqlite3.Row

# Drop table if it exists
db.execute(DROP_TABLE)
db.commit()

# Create table
db.execute(CREATE_TABLE)
db.commit()

print("")
#------------------------------------------------------------------------------#


#------------------------------------------------------------------------------#
# Prepare input files

# Delete prep folder if it exists
if os.path.exists(PREP_FOLDER):
	print("Deleting existing prep folder")
	subprocess.run(["rm", "-vr", PREP_FOLDER])

# Create prep folder
print("Creating prep folder")
os.mkdir(PREP_FOLDER)

# Copy input files to prep folder (and convert to .wav if necessary)
input_folder = os.path.join(os.getcwd(), INPUT_FOLDER)
prep_folder = os.path.join(os.getcwd(), PREP_FOLDER)

files = os.listdir(input_folder)

print(f"Converting {len(files)} files")
with alive_progress.alive_bar(len(files)) as bar:
	for file in os.listdir(input_folder):
		download_filepath = os.path.join(input_folder, file)
		new_name = file.rsplit(".", 1)[0] + ".wav"
		new_filepath = os.path.join(prep_folder, new_name)

		if file.endswith(".mp4"):
			print(f"Converting {file} to {new_name}")
			command = f"ffmpeg -hide_banner -loglevel error -v 0 -y -i {download_filepath} -q:a 0 -map a {new_filepath}".split()
			subprocess.run(command)
		elif file.endswith(".mp3"):
			print(f"Converting {file} to {new_name}")
			command = f"ffmpeg -hide_banner -loglevel error -v 0 -y -i {download_filepath} {new_filepath}".split()
			subprocess.run(command)
		else:
			print(f"Copying {file} to {new_name}")
			command = f"cp {download_filepath} {new_filepath}".split()
			subprocess.run(command)
	bar()

print("")
#------------------------------------------------------------------------------#


#------------------------------------------------------------------------------# 
# Transcribe input files to database

# Setup Whisper
print(f"Loading Whisper model {WHISPER_MODEL}")
model = whisper.load_model(WHISPER_MODEL)

# Get list of files in prep folder
prep_files = os.listdir(prep_folder)

# Transcribe each file
for file in prep_files:
	print(f"Transcribing {file}")

	filepath = os.path.join(prep_folder, file)
	transcript = model.transcribe(filepath, language="en", verbose=False, word_timestamps=True)

	print(f"Inserting words into database for {file}")

	for s in transcript["segments"]:
		for w in s["words"]:
			word = w["word"]
			word = "".join([c for c in word if c not in PUNCTUATION])

			if word == word.upper(): # means it's probably like "CHEERING" or "APPLAUSE"
				continue
			
			word = word.lower()
			word.strip()

			file_path = os.path.join(PREP_FOLDER, file)

			db.execute("INSERT INTO words (word, file, start, end) VALUES (?, ?, ?, ?)", (word, file_path, w["start"], w["end"]))
			db.commit()

print("")
#------------------------------------------------------------------------------#


#------------------------------------------------------------------------------#
# Split song into voice and accompaniment

# Delete spleeter output folder if it exists
if os.path.exists(SPLEETER_OUTPUT):
	print("Deleting existing spleeter output folder")
	subprocess.run(["sudo", "rm", "-rvf", SPLEETER_OUTPUT])

song_file = os.path.join(os.getcwd(), SONG_FILE)

print(f"Splitting song {song_file}")
spleeter_output_path = os.path.join(os.getcwd(), SPLEETER_OUTPUT)
song_path = os.path.join(os.getcwd(), SONG_PATH)
command = [
    "docker", "run", 
    "-v", f"{spleeter_output_path}:/output", 
    "-v", f"{song_path}:/input", 
    "deezer/spleeter:3.6-5stems", 
    "separate", 
    "-o", "/output", 
    f"/input/{SONG_FILE}"
]
subprocess.run(command)
# command = F"docker run -v $(pwd)/{SPLEETER_OUTPUT}:/output -v $(pwd)/{SONG_PATH}:/input deezer/spleeter:3.6-5stems separate -o /output /input/{SONG_FILE}".split()
# subprocess.run(command)

song_basename = os.path.basename(song_file).rsplit(".", 1)[0]
vocals_file = os.path.join(os.getcwd(), SPLEETER_OUTPUT, song_basename, "vocals.wav")
accompaniment_file = os.path.join(os.getcwd(), SPLEETER_OUTPUT, song_basename, "accompaniment.wav")

print(f"Vocals file: {vocals_file}")
print(f"Accompaniment file: {accompaniment_file}")

print("Transcribing vocals file")
transcript = model.transcribe(vocals_file, language="en", verbose=False, word_timestamps=True)

print("Cleaning up vocals transcript")
song_words = [] # [{ "word": "hello", "start": 0.0, "end": 0.5 }, ...]
for s in transcript["segments"]:
	for w in s["words"]:
		# word = w["word"].lower()
		# word = "".join([c for c in word if c not in PUNCTUATION])
		# word = word.strip()

		word = w["word"]
		word = "".join([c for c in word if c not in PUNCTUATION])

		if word == word.upper(): # means it's probably like "CHEERING" or "APPLAUSE"
			continue

		word = word.lower()
		word.strip()

		song_words.append({ "word": word, "start": w["start"], "end": w["end"] })

print("")
#------------------------------------------------------------------------------#


#------------------------------------------------------------------------------# 
# Match words in vocals to words in database

class SongWord:
	def __init__(self, word, start, end):
		self.word = word
		self.start = start
		self.end = end
class InputWord:
	def __init__(self, word, file, start, end):
		self.word = word
		self.file = file
		self.start = start
		self.end = end
class ReplacedWord:
	def __init__(self, song_word, input_word, speed_factor):
		self.song_word = song_word
		self.input_word = input_word
		self.speed_factor = speed_factor

replaced_words: list[ReplacedWord] = []

print("Matching words in vocals to words in database")
with alive_progress.alive_bar(len(song_words)) as bar:
	for song_word in song_words:
		word = song_word["word"]
		start = song_word["start"]
		end = song_word["end"]

		sw = SongWord(word, start, end)

		# Find word in database
		results = [dict(row) for row in db.execute("SELECT * FROM words WHERE word = ?", (word,)).fetchall()]

		# If no results, skip
		if len(results) == 0:
			# rw = ReplacedWord(sw, None, -1.0)
			print(f"No match for {word}")
			continue

		# Choose random result
		result = random.choice(results)

		# Calculate speed factor
		input_duration = float(result["end"]) - float(result["start"])
		song_duration = end - start
		speed_factor = input_duration / song_duration

		iw = InputWord(result["word"], result["file"], result["start"], result["end"])

		print(f"Matched {word} with {iw.file} at {start} to {end} with speed factor {speed_factor}")

		replaced_words.append(ReplacedWord(sw, iw, speed_factor))
	bar()

print("")
#------------------------------------------------------------------------------# 


#------------------------------------------------------------------------------#
# Generate output voice file

# Delete temp folder if it exists
if os.path.exists(TEMP_FOLDER):
	print("\nSUDO PASSWORD NEEDED: Deleting existing temp folder.")
	subprocess.run(["rm", "-rv", TEMP_FOLDER])

# Create temp folder for processed audio files
print("Creating temp folder")
os.mkdir(TEMP_FOLDER)

list_file = open(os.path.join(TEMP_FOLDER, CONCAT_LIST_FILE), "w")

clip_i = 0

# First clip (take from the vocals file)
first_replace = replaced_words[0]
first_start = first_replace.song_word.start
first_sf = first_replace.speed_factor

first_clip_fn = f"{clip_i}.wav"
first_clip_fp = os.path.join(TEMP_FOLDER, first_clip_fn)

# ffmpeg -hide_banner -loglevel error -y -i {vocals_file} -ss {first_start} -filter:a "atempo={speed_factor}" -c:a pcm_s16le {first_clip_fp}
command = f"ffmpeg -hide_banner -loglevel error -y -i {vocals_file} -t {first_start} -c copy {first_clip_fp}".split()
subprocess.run(command)

list_file.write(f"file '{first_clip_fp}'\n")
clip_i += 1

# For every clip, take the word from the input then fill the gap with the vocals
with alive_progress.alive_bar(len(replaced_words) - 1) as bar:
	for i in range(len(replaced_words) - 1):
		replace = replaced_words[i]
		next_replace = replaced_words[i + 1]

		replace_start = replace.song_word.start
		replace_end = replace.song_word.end

		next_start = next_replace.song_word.start

		# Take the replace clip from the prep-ed file
		replace_clip_fn = f"{clip_i}.wav"
		replace_clip_fp = os.path.join(TEMP_FOLDER, replace_clip_fn)
		clip_i += 1

		command = f"ffmpeg -hide_banner -loglevel error -y -i {replace.input_word.file} -ss {replace_start} -to {replace_end} -filter:a \"atempo={replace.speed_factor}\" -c copy {replace_clip_fp}".split()
		subprocess.run(command)

		list_file.write(f"file '{replace_clip_fp}'\n")

		# Take the next clip from the vocals file
		next_clip_fn = f"{clip_i}.wav"
		next_clip_fp = os.path.join(TEMP_FOLDER, next_clip_fn)
		clip_i += 1

		command = f"ffmpeg -hide_banner -loglevel error -y -i {vocals_file} -ss {replace_end} -to {next_start} -c copy {next_clip_fp}".split()
		subprocess.run(command)

		list_file.write(f"file '{next_clip_fp}'\n")

		bar()

# Last clip
last_replace = replaced_words[-1]
last_start = last_replace.song_word.start
last_end = last_replace.song_word.end

last_clip_fn = f"{clip_i}.wav"
last_clip_fp = os.path.join(TEMP_FOLDER, last_clip_fn)
clip_i += 1

command = f"ffmpeg -hide_banner -loglevel error -y -i {last_replace.input_word.file} -ss {last_start} -to {last_end} -filter:a \"atempo={last_replace.speed_factor}\" -c copy {last_clip_fp}".split()
subprocess.run(command)

list_file.write(f"file '{last_clip_fp}'\n")

# Last clip from the vocals file
last_vocals_clip_fn = f"{clip_i}.wav"
last_vocals_clip_fp = os.path.join(TEMP_FOLDER, last_vocals_clip_fn)

command = f"ffmpeg -hide_banner -loglevel error -y -i {vocals_file} -ss {last_end} -c copy {last_vocals_clip_fp}".split()
subprocess.run(command)

list_file.write(f"file '{last_vocals_clip_fp}'\n")

list_file.close()

# Concatenate all clips
print("Concatenating all clips")
output_fp = os.path.join(os.getcwd(), OUTPUT_VOICE_FILE)
command = f"ffmpeg -hide_banner -loglevel error -f concat -safe 0 -i {os.path.join(TEMP_FOLDER, CONCAT_LIST_FILE)} -c copy {output_fp}".split()
subprocess.run(command)

# Clean up temp folder
print("Cleaning up temp folder")
subprocess.run(["rm", "-rf", TEMP_FOLDER])

print("")
#------------------------------------------------------------------------------#


#------------------------------------------------------------------------------#
# Combine voice and accompaniment

command = [
    "ffmpeg", 
    "-i", accompaniment_file,
    "-i", OUTPUT_VOICE_FILE,
    "-filter_complex",
    "[0][1]amix=inputs=2:duration=longest",
    OUTPUT_FILE
]
subprocess.run(command)

print("")
#------------------------------------------------------------------------------#


#------------------------------------------------------------------------------#
# Close the database
print("Closing database")
db.close()
#------------------------------------------------------------------------------#


print("Done!")