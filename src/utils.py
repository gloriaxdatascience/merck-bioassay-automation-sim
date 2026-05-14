import json
import logging
from datetime import datetime, timezone
from pathlib import Path #pathlib handles file locations(paths)
from rich.logging import RichHandler

LOG_DIR = Path("data/logs") #creates a "Path object"
LOG_DIR.mkdir(parents=True, exist_ok=True) #If the data folder doesn't exist yet, create it first, then create the logs folder inside it. If the folder is already there, don't worry about it.

# Rich gives coloured, readable terminal output.
# In a real lab, this would ship to a central log aggregator.
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("lab")


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string. Used on every log entry."""
    return datetime.now(timezone.utc).isoformat() 
    #gets the exact current time in "Coordinated Universal Time" (UTC). Labs use UTC so that experiments done in different time zones can be compared accurately.
    #turns that time into a standard text format (like 2026-05-13T12:00:00) that is easy for other software to read.


def log_event(event: dict, log_file: str = "run_log.jsonl") -> None:
    """
    Append a structured JSON event to the run log.

    Why JSONL (newline-delimited JSON)?
    Each line is a valid JSON object. Easy to tail, grep, or load into pandas.
    Real lab systems like LIMS and MES use this pattern for audit trails.
    """
    path = LOG_DIR / log_file #join the folder path (data/logs) with a filename (like run_log.jsonl) to create a full address: data/logs/run_log.jsonl
    with open(path, "a") as f: #"a" stands for append. This is vital for logs because it means "add this new line to the end of the file" rather than deleting the old data and starting over.
        f.write(json.dumps(event) + "\n") #event = Python dictionary. json.dumps(event) = convert dictionary into JSON text string. + "\n" = add newline
        #f.write(...) = write that line into the file. each event becomes one JSON line in the .jsonl file. 
        #The "s" stands for "string." This takes the dictionary, flattens it into a single line of text, 
        #and adds it to the bottom of one big file (run_log.jsonl). It stays as one file that just gets longer.
    logger.info(f"[{event.get('source','?')}] {event.get('event','?')} | " #This line prints a readable summary to the terminal.
                f"plate={event.get('plate_id','?')} | status={event.get('status','?')}") #try to get the value for key "source"; if that key is missing, use "?" instead.
                #the ? is a safety net/a fallback safety value. It prevents crashes if a key is missing. 


def load_json(path: str) -> dict: 
    #path is a parameter (a placeholder)
    #The program doesn't "know" what it is until you actually use the function later in the code. For example, if you write: load_json("my_experiment.json")
    #The program takes the text "my_experiment.json" and plugs it into the placeholder path for that specific run.
    with open(path) as f:
        return json.load(f) #"reads" a JSON file and turns it into a Python dictionary (a list of keys and values) that your program can use.


def save_json(data: dict, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f: #"w" stands for Write mode.
        json.dump(data, f, indent=2) 
        #"writes" your data back into a file.
        #data: The information you want to save.
        #f: The file you are writing into.
        #indent=2: This makes the saved file look "pretty" by adding spaces. Instead of one long line of text, it creates a readable structure.
    logger.info(f"Saved JSON → {path}")