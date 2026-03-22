# ================================================================
#  core/orchestrator.py
#  The main pipeline. Calls all other modules in order.
#  V2 change: add gemini + chatgpt tab lines in _open_tabs()
# ================================================================

import time, logging, sys,os
from selenium.webdriver.common.by import By
sys.path.insert(0, r"C:\swayam_bot")
import config
from core.browser_controller import BrowserController
from core.course_navigator   import CourseNavigator
from core.ai_answerer        import AIAnswerer
from core.answer_picker      import AnswerPicker

logger = logging.getLogger(__name__)


class Orchestrator:

    def __init__(self, status_cb=None, manual_answer_cb=None):
        """
        status_cb(msg)         → sends text to the popup's log box
        manual_answer_cb(q)    → called when AI is stuck; should return
                                  a letter from the user or None to skip
        """
        self._status = status_cb       or print
        self._ask_me = manual_answer_cb or (lambda q: None)
        self.b = None

    def status(self, msg):
        logger.info(msg)
        self._status(msg)
    def _open_tabs(self):
        """Open tabs for Swayam and Claude, handle CAPTCHA if present."""
        self.b.open_tab(config.COURSE_SITE_URL, "swayam")
        self.b.open_tab(config.CLAUDE_URL, "claude")
        self._wait_for_captcha()
        self.b.switch_to("swayam")

    def _wait_for_captcha(self):
        """
        Check if Cloudflare CAPTCHA is present on Claude tab.
        If yes, notify the user and wait until it's solved before continuing.
        """
        self.b.switch_to("claude")
        
        # Check if CAPTCHA is present
        captcha = self.b.safe_find(
            By.XPATH,
            "//*[contains(text(),'Verify you are human') or "
            "contains(text(),'security verification') or "
            "contains(text(),'Performing security')]",
            timeout=5
        )
        
        if captcha:
            self.status("⚠️  CAPTCHA detected on Claude tab!")
            self.status("🔐  Please solve the CAPTCHA in the Claude tab, then click Continue in this window.")
            
            # Notify UI to show a Continue button — wait until user signals done
            if hasattr(self, '_wait_for_user'):
                self._wait_for_user()  # UI hook (see below)
            else:
                # Fallback: poll until CAPTCHA disappears automatically
                self.status("⏳  Waiting for CAPTCHA to be solved...")
                while True:
                    time.sleep(3)
                    still_there = self.b.safe_find(
                        By.XPATH,
                        "//*[contains(text(),'Verify you are human') or "
                        "contains(text(),'security verification') or "
                        "contains(text(),'Performing security')]",
                        timeout=3
                    )
                    if not still_there:
                        self.status("✅  CAPTCHA solved! Continuing...")
                        break
        else:
            self.status("✅  No CAPTCHA detected. Claude tab ready.")

    # ── Main entry point ──────────────────────────────────────────

    def run(self):
        try:
            self.status("🌐  Launching Chrome with your profile...")
            self.b = BrowserController().launch()
            self._open_tabs()

            # ── First-run login pause ─────────────────────────────────
            session_flag = r"C:\swayam_bot\chrome_session\logged_in.flag"
            if not os.path.exists(session_flag):
                self.status("🔐  FIRST RUN: Please log into Swayam and Claude manually.")
                self.status("⏳  You have 60 seconds. Switch between tabs and log in to both.")
                time.sleep(120)
                open(session_flag, "w").close()  # create flag so pause never runs again
                self.status("✅  Login window closed. Continuing...")

            nav    = CourseNavigator(self.b)
            ai     = AIAnswerer(self.b)
            picker = AnswerPicker()

            self.status("🔑  Logging in to Swayam...")
            if not nav.login():
                self.status("❌  Login failed."); return False

            self.status("📚  Finding your Swayam course...")
            if not nav.open_course():
                self.status("❌  Course not found. Check COURSE_NAME_KEYWORD in config.py")
                return False

            self.status("🔍  Checking for a new week...")
            if not nav.check_new_week():
                self.status("ℹ️  No new week yet. Check back later!")
                return True

            self.status("📝  Opening the assessment...")
            if not nav.open_assessment():
                self.status("❌  Assessment not found."); return False

            self.status("❓  Reading questions from the page...")
            questions = nav.get_questions()
            if not questions:
                self.status("❌  No questions found — selectors need updating.")
                return False

            self.status(f"🤖  Answering {len(questions)} question(s) using Claude...")
            for q in questions:
                self._handle_question(q, ai, picker, nav)
                time.sleep(config.BETWEEN_QUESTIONS)

            self.status("📤  Submitting assessment...")
            if not nav.submit():
                self.status("⚠️  Could not auto-submit. Please click Submit manually.")
            else:
                self.status("🎉  Done! Assessment submitted.")

            return True

        except Exception as e:
            logger.exception(e)
            if self.b: self.b.screenshot("crash")
            self.status(f"❌  Unexpected error: {e}")
            return False

        finally:
            if self.b:
                time.sleep(4)
                self.b.quit()

    # ── Per-question logic ────────────────────────────────────────

    def _handle_question(self, q, ai, picker, nav):
        self.status(f"  ❓  Q{q['index']}: {q['text'][:50]}...")

        # ── Image question — send screenshot to Claude ────────────
        if q.get("is_image_question"):
            image_path = q.get("image_path")
            if image_path:
                self.status(f"  🖼️  Q{q['index']}: Image question — sending to Claude...")
                letter = ai.ask_gemini_with_image(image_path, q["options"])

                if not letter:
                    self.status(f"  🔄  Q{q['index']}: Retrying image question...")
                    letter = ai.ask_gemini_with_image(image_path, q["options"])

                if letter:
                    nav.select_answer(q, letter)
                    self.status(f"  ✅  Q{q['index']} → {letter}  (Claude read image)")
                    return

            # Both attempts failed — skip this question
            self.status(f"  ⏭️  Q{q['index']}: Claude could not read image — skipping.")
            return

        # ── Normal text question — ask Claude ─────────────────────
        answers = ai.ask_all(q["text"], q["options"])
        chosen, why = picker.pick(answers, q["index"])
        picker.log_result(q, answers, chosen, why)

        # Retry once if unclear
        if chosen is None:
            self.status(f"  🔄  Q{q['index']}: unclear — retrying Claude...")
            retry_letter = ai.ask_claude(q["text"], q["options"], attempt=2)
            if retry_letter:
                chosen = retry_letter
                why    = "retry succeeded"
            else:
                self.status(f"  🙋  Q{q['index']}: still unclear — asking you...")
                chosen = self._ask_me(q)
                why    = "answered manually" if chosen else "skipped"

        if chosen:
            nav.select_answer(q, chosen)
            self.status(f"  ✅  Q{q['index']} → {chosen}  ({why})")
        else:
            self.status(f"  ⏭️  Q{q['index']} → Skipped")