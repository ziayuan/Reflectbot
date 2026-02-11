import json
import os
from datetime import datetime

DIARY_FILE = 'diary.json'

class DiaryManager:
    def __init__(self, file_path=DIARY_FILE):
        self.file_path = file_path
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=4, ensure_ascii=False)

    def _load_data(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_data(self, data):
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def add_entry(self, content):
        data = self._load_data()
        # Use existing BEIJING_TZ definition if imported or define local
        # Ideally pass timestamp from bot, but for simplicity modify here
        from datetime import datetime, timezone, timedelta
        beijing_now = datetime.now(timezone(timedelta(hours=8)))
        
        entry = {
            "timestamp": beijing_now.isoformat(),
            "content": content
        }
        data.append(entry)
        self._save_data(data)
        return entry

    def get_entries_for_day(self, date_str):
        """
        date_str should be in format 'YYYY-MM-DD'
        """
        data = self._load_data()
        day_entries = []
        for entry in data:
            # Assumes timestamp is ISO format "YYYY-MM-DDTHH:MM:SS..."
            # Simple string matching for date part works if standard ISO
            if entry['timestamp'].startswith(date_str):
                day_entries.append(entry)
        return day_entries
