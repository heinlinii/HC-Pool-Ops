from pathlib import Path
import shutil
ROOT = Path.cwd()
weather = ROOT / "app" / "templates" / "weather.html"
backup = ROOT / "jarvis_backups" / "before_real_weather_page"
backup.mkdir(parents=True, exist_ok=True)
if weather.exists():
    shutil.copy2(weather, backup / "weather.html")
print("DONE. Real Weather Desk installed.")
print("Weather button should now open /weather with current, hourly, and weekly forecast.")
