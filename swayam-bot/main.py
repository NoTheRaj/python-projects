# ================================================================
#  main.py — Run this file to start the bot
#  python C:\swayam_bot\main.py
# ================================================================

import logging, sys
sys.path.insert(0, r"C:\swayam_bot")
import config

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)

if __name__ == "__main__":
    from ui.startup_window import StartupWindow
    StartupWindow().run()