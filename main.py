import string
import sqlite3
import os
import subprocess
import whisper # type: ignore
import alive_progress # type: ignore
import pydub # type: ignore
#------------------------------------------------------------------------------# 


#------------------------------------------------------------------------------# 
PUNCTUATION = list(string.punctuation) + [" ", "“", "”", "¿", "¡", "。", "，", "！", "？", "：", "、", "；", "．"]

DB_FILE = "database.db"
INPUT_FOLDER = "input"
PREP_FOLDER = "prep"
WHISPER_MODEL = "medium.en"
SONG_PATH = "song"
SONG_FILE = "song.mp3"
SPLEETER_OUTPUT = "spleeter_output"
OUTPUT_VOICE_FILE = "output_voice.mp3"
OUTPUT_FILE = "output.mp3"
MIN_TIME = 200
LOUD_ADJUST = 10.0
#------------------------------------------------------------------------------# 


#------------------------------------------------------------------------------# 
# Delete spleeter output folder if it exists (do first to prompt for sudo password)

if os.path.exists(SPLEETER_OUTPUT):
	print("\nSUDO PASSWORD REQUIRED: deleting existing spleeter output folder")
	subprocess.run(["sudo", "rm", "-rf", SPLEETER_OUTPUT])
#------------------------------------------------------------------------------# 


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
	subprocess.run(["rm", "-r", PREP_FOLDER])

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
			start = w["start"]
			end = w["end"]

			t = int(float(end) * 1000) - int(float(start) * 1000)
			if t < MIN_TIME:
				continue

			word = "".join([c for c in word if c not in PUNCTUATION])

			if word == word.upper(): # means it's probably like "CHEERING" or "APPLAUSE"
				continue
			
			word = word.lower()
			word.strip()

			file_path = os.path.join(PREP_FOLDER, file)

			db.execute("INSERT INTO words (word, file, start, end) VALUES (?, ?, ?, ?)", (word, file_path, start, end))
			db.commit()

print("")
#------------------------------------------------------------------------------#


#------------------------------------------------------------------------------#
# Split song into voice and accompaniment

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

song_basename = os.path.basename(song_file).rsplit(".", 1)[0]
vocals_file = os.path.join(os.getcwd(), SPLEETER_OUTPUT, song_basename, "vocals.wav")
accompaniment_file = os.path.join(os.getcwd(), SPLEETER_OUTPUT, song_basename, "accompaniment.wav")

print(f"Vocals file: {vocals_file}")
print(f"Accompaniment file: {accompaniment_file}")

print("")
#------------------------------------------------------------------------------#

#------------------------------------------------------------------------------#
# Equalize input volume with the vocals

def match_volume(audio, target_dBFS):
    change_in_dBFS = target_dBFS - audio.dBFS
    return audio.apply_gain(change_in_dBFS + LOUD_ADJUST)

def equalize(file_path):
	voice_file = pydub.AudioSegment.from_file(vocals_file)
	avg_dBFS = voice_file.dBFS

	audio = pydub.AudioSegment.from_file(file_path)
	audio = match_volume(audio, avg_dBFS)
	audio.export(file_path, format="wav")

print("Equalizing input volume")
with alive_progress.alive_bar(len(prep_files)) as bar:
	for file in prep_files:
		file_path = os.path.join(prep_folder, file)
		print(file_path)
		equalize(file_path)
		bar()

print("")
#------------------------------------------------------------------------------#


#------------------------------------------------------------------------------#
# Transcribe vocals file

print("Transcribing vocals file")
transcript = model.transcribe(vocals_file, language="en", verbose=False, word_timestamps=True)

print("Cleaning up vocals transcript")
song_words = [] # [{ "word": "hello", "start": 0.0, "end": 0.5 }, ...]
for s in transcript["segments"]:
	for w in s["words"]:
		word = w["word"]
		start = w["start"]
		end = w["end"]

		t = int(float(end) * 1000) - int(float(start) * 1000)
		if t <= 0:
			continue

		word = "".join([c for c in word if c not in PUNCTUATION])

		if word == word.upper(): # means it's probably like "CHEERING" or "APPLAUSE"
			continue

		word = word.lower()
		word.strip()

		song_words.append({ "word": word, "start": start, "end": end })

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
	def __init__(self, song_word: SongWord, input_word: InputWord, speed_factor):
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

		def calc_speed_factor(result):
			input_duration = float(result["end"]) - float(result["start"])
			song_duration = end - start
			speed_factor = input_duration / song_duration
			return speed_factor

		def dist_to_one(speed_factor):
			return abs(1 - speed_factor)
		
		def is_valid_result(result):
			speed_factor = calc_speed_factor(result)
			t = int(float(result["end"]) * 1000) - int(float(result["start"]) * 1000)
			return t / speed_factor >= MIN_TIME and speed_factor != 0 and speed_factor != float("inf")
		
		# Find word in database
		results = [dict(row) for row in db.execute("SELECT * FROM words WHERE word = ?", (word,)).fetchall()]
		results = [result for result in results if is_valid_result(result)]

		# If no results, skip
		if len(results) == 0:
			# rw = ReplacedWord(sw, None, -1.0)
			print(f"No (valid) results for {word}")
			bar()
			continue

		results.sort(key=lambda result: dist_to_one(calc_speed_factor(result)))

		for result in results:
			speed_factor = calc_speed_factor(result)

			t = int(float(result["end"]) * 1000) - int(float(result["start"]) * 1000)
			if t * speed_factor < MIN_TIME:
				speed_factor = float("inf")

			if speed_factor != float("inf") and speed_factor != 0:
				iw = InputWord(result["word"], result["file"], result["start"], result["end"])
				print(f"Matched {word} with {iw.file} at {start} to {end} with speed factor {speed_factor}")
				replaced_words.append(ReplacedWord(sw, iw, speed_factor))
				bar()
				break
		
		if speed_factor == float("inf") or speed_factor == 0:
			print(f"Speed factor is {speed_factor} for {word}")
			bar()
			continue

print("")
#------------------------------------------------------------------------------# 


#------------------------------------------------------------------------------#
# Generate output voice file

def modify_speed(f_seg, speed_factor):	
	sfs = []
	while speed_factor < 0.5:
		speed_factor *= 2
		sfs.append(0.5)
	while speed_factor > 100.0:
		speed_factor /= 100
		sfs.append(100.0)
	if speed_factor != 1:
		sfs.append(speed_factor)

	if len(sfs) > 1:
		print(f"Speed factors: {sfs}")

	for sf in sfs:
		try:
			f_seg = f_seg.speedup(playback_speed=sf, crossfade=0)
		except Exception as e:
			# print(f"ZeroDivisionError for {replace.input_word.word}")
			# print(f"Speed factor: {sf}")
			print(f"Error: {e}")
			return None

	return f_seg

voice_file = pydub.AudioSegment.from_file(vocals_file)
voice_output = pydub.AudioSegment.empty()

# First clip (from the vocals file)
first_replace = replaced_words[0]
first_start = int(float(first_replace.song_word.start) * 1000)
voice_output += voice_file[:first_start]

# For every clip, take the word from the input then fill the gap with the vocals
with alive_progress.alive_bar(len(replaced_words) - 1) as bar:
	for i in range(len(replaced_words) - 1):
		replace = replaced_words[i]
		next_replace = replaced_words[i + 1]

		# Take the replace clip from the prep-ed file
		f = pydub.AudioSegment.from_file(replace.input_word.file)
		a = int(float(replace.input_word.start) * 1000)
		b = int(float(replace.input_word.end) * 1000)	
		print(f"{a}\t{b}\t{b - a}\t{replace.speed_factor:>5.2f}\t{replace.input_word.word}")
		f_seg = f[a:b]
		f_seg = modify_speed(f_seg, replace.speed_factor)
		
		if f_seg is None:
			t = (b - a) * replace.speed_factor
			silent = pydub.AudioSegment.silent(duration=t)
			voice_output += silent
		else:
			voice_output += f_seg

		# Take the next clip from the vocals file
		# f_seg = voice_file[int(float(replace.song_word.end) * 1000):int(float(next_replace.song_word.start) * 1000)]
		# voice_output += f_seg
		length = int(float(next_replace.song_word.start) * 1000) - int(float(replace.song_word.end) * 1000)
		silent = pydub.AudioSegment.silent(duration=length)
		voice_output += silent

		bar()

# Last clip from the input file
last_replace = replaced_words[-1]
f = pydub.AudioSegment.from_file(last_replace.input_word.file)
f_seg = f[int(float(last_replace.input_word.start) * 1000):int(float(last_replace.input_word.end) * 1000)]
f_seg = modify_speed(f_seg, last_replace.speed_factor)
voice_output += f_seg

# Last clip from the vocals file
f_seg = voice_file[int(float(last_replace.song_word.end) * 1000):]
voice_output += f_seg

# Save the output voice file
print(f"Saving output voice file to {OUTPUT_VOICE_FILE}")
voice_output.export(OUTPUT_VOICE_FILE, format="mp3")

print("")
#------------------------------------------------------------------------------#


#------------------------------------------------------------------------------#
# Combine voice and accompaniment

print("Combining voice and accompaniment")
command = [
	"ffmpeg", 
	"-hide_banner",
	"-loglevel", "error",
	"-y",
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