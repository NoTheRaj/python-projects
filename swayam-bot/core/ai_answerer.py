# ================================================================
#  core/ai_answerer.py
#  Image questions use Gemini Vision API (free, no credit card)
#  Uses the NEW google-genai SDK: pip install google-genai
#
#  IMPORTANT: gemini-2.0-flash was RETIRED March 3 2026.
#  Current free models: gemini-2.5-flash, gemini-2.5-flash-lite
#
#  Setup:
#    1. pip install google-genai
#    2. Get free API key: https://aistudio.google.com/apikey
#    3. Add to config.py:  GEMINI_API_KEY = "AIza..."
# ================================================================

import time, re, logging, os
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import sys
sys.path.insert(0, r"C:\swayam_bot")
import config

logger = logging.getLogger(__name__)

# ── Model fallback chain (primary → backup) ───────────────────────
# gemini-2.5-flash      : 10 RPM, 250 RPD  — best vision quality
# gemini-2.5-flash-lite : 15 RPM, 1000 RPD — faster, still accurate
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]

# Seconds between API calls to stay under 10 RPM (= 1 req / 6s, we use 7s)
GEMINI_REQUEST_GAP = 7


def build_prompt(q_text, options):
    opts = "\n".join([f"{k}) {v}" for k, v in options.items()])
    return (
        f"This is a multiple choice question from a Swayam online course. "
        f"Reply with ONLY the letter of the correct answer — A, B, C, or D. "
        f"No explanation. Just the single letter.\n\n"
        f"Question: {q_text}\n\n"
        f"Options:\n{opts}\n\n"
        f"Answer:"
    )


def extract_letter(text):
    if not text:
        return None
    text = text.strip().upper()
    m = re.search(r'\b([A-D])\b', text)
    if m:
        return m.group(1)
    for ch in text:
        if ch in "ABCD":
            return ch
    return None


def slow_type(element, text, delay=0.08):
    for char in text:
        element.send_keys(char)
        time.sleep(delay)


def _parse_retry_delay(error_str):
    """
    Extract the retryDelay seconds from a 429 error message.
    Google tells us exactly how long to wait — we use it.
    Example: 'retryDelay': '19s'  →  returns 21 (19 + 2s buffer)
    """
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", error_str)
    if m:
        return int(m.group(1)) + 2
    return 30  # safe default


class AIAnswerer:

    def __init__(self, browser):
        self.b = browser
        self._gemini_client = None
        self._last_gemini_call = 0.0   # timestamp of last API call

    def _get_gemini_client(self):
        if self._gemini_client is not None:
            return self._gemini_client

        api_key = getattr(config, "GEMINI_API_KEY", None)
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set in config.py.\n"
                "1. Get a FREE key: https://aistudio.google.com/apikey\n"
                "2. Add to config.py:  GEMINI_API_KEY = 'AIza...'\n"
                "3. Install SDK:  pip install google-genai"
            )

        try:
            from google import genai
        except ImportError:
            raise RuntimeError(
                "'google-genai' not installed.\n"
                "Run:  pip install google-genai"
            )

        self._gemini_client = genai.Client(api_key=api_key)
        logger.info("[GEMINI] Client initialised (google-genai SDK).")
        return self._gemini_client

    def _throttle(self):
        """Enforce minimum gap between API calls to stay under RPM limit."""
        elapsed = time.time() - self._last_gemini_call
        if elapsed < GEMINI_REQUEST_GAP:
            wait = GEMINI_REQUEST_GAP - elapsed
            logger.info(f"[GEMINI] Throttling {wait:.1f}s to respect RPM limit...")
            time.sleep(wait)
        self._last_gemini_call = time.time()

    def _wait_for_response(self, timeout=90):
        logger.info("Waiting for Claude to respond...")
        for _ in range(timeout // 2):
            if self.b.driver.find_elements(By.CSS_SELECTOR,
                    '[data-testid="assistant-message"]'):
                break
            time.sleep(2)

        prev, stable = "", 0
        for _ in range(60):
            els = self.b.driver.find_elements(By.CSS_SELECTOR,
                '[data-testid="assistant-message"]')
            cur = els[-1].text if els else ""
            if cur and cur == prev:
                stable += 1
                if stable >= 2:
                    logger.info("Response done.")
                    return
            else:
                stable = 0
            prev = cur
            time.sleep(2)

    # ── Text questions — Claude browser ──────────────────────────

    def ask_claude(self, q_text, options, attempt=1):
        prompt = build_prompt(q_text, options)
        if attempt == 2:
            prompt = (
                "Please answer with ONLY the letter A, B, C, or D.\n\n"
                f"Question: {q_text}\n\nOptions:\n"
                + "\n".join([f"{k}) {v}" for k, v in options.items()])
                + "\n\nAnswer:"
            )

        try:
            self.b.switch_to("claude")
            self.b.go(config.CLAUDE_URL)
            time.sleep(3)

            box = self.b.driver.find_element(By.CSS_SELECTOR,
                'div[contenteditable="true"]')
            box.click()
            time.sleep(0.5)
            slow_type(box, prompt)
            time.sleep(1)
            box.send_keys(Keys.RETURN)

            self._wait_for_response()

            paras = self.b.driver.find_elements(By.CSS_SELECTOR,
                '[data-testid="assistant-message"] p')
            if not paras:
                logger.warning(f"No response found (attempt {attempt}).")
                return None

            raw = paras[-1].text
            letter = extract_letter(raw)
            logger.info(f"Claude attempt {attempt} → '{raw}' → {letter}")
            return letter

        except Exception as e:
            logger.error(f"Claude text error: {e}")
            self.b.screenshot(f"claude_error_{attempt}")
            return None

    # ── Image questions — Gemini Vision API (FREE) ────────────────

    def ask_gemini_with_image(self, image_path, options):
        """
        Sends a question screenshot to Gemini (free tier).

        Behaviours:
          - Throttles to 7s gap between calls (free tier = 10 RPM)
          - On 429, reads retryDelay from Google's error and waits it out
          - Falls back: gemini-2.5-flash → gemini-2.5-flash-lite
          - Every step is logged so failures are obvious in the log file
        """
        if not image_path or not os.path.exists(image_path):
            logger.error(f"[GEMINI] Image file not found: {image_path}")
            return None

        opts_text = "\n".join([f"{k}) {v}" for k, v in options.items()])
        prompt = (
            "This is a screenshot of a multiple choice question from a Swayam "
            "NPTEL online course about Java programming. "
            "Read the Java code or question text in the image carefully.\n\n"
            f"The answer options are:\n{opts_text}\n\n"
            "Reply with ONLY the single letter of the correct answer: A, B, C, or D. "
            "No explanation. No punctuation. Just one letter.\n\nAnswer:"
        )

        try:
            client = self._get_gemini_client()
        except RuntimeError as e:
            logger.error(str(e))
            return None

        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except Exception as e:
            logger.error(f"[GEMINI] Could not read image: {e}")
            return None

        ext = os.path.splitext(image_path)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg"}.get(ext, "image/png")

        from google.genai import types

        for model_name in GEMINI_MODELS:
            logger.info(f"[GEMINI] Trying model  : {model_name}")
            logger.info(f"[GEMINI] Sending image : {os.path.basename(image_path)}")

            self._throttle()   # respect RPM before every call

            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type=mime),
                        prompt,
                    ],
                )

                raw = response.text.strip() if response.text else ""
                logger.info(f"[GEMINI] Raw response   : '{raw}'")

                if not raw:
                    finish = (response.candidates[0].finish_reason
                              if response.candidates else "unknown")
                    logger.warning(f"[GEMINI] Empty response. Finish reason: {finish}")
                    continue   # try next model

                letter = extract_letter(raw)
                if not letter:
                    logger.warning(f"[GEMINI] Could not extract A/B/C/D from: '{raw}'")
                    continue

                logger.info(f"[GEMINI] ✅ Answer: {letter}  (model: {model_name})")
                return letter

            except Exception as e:
                err_str = str(e)
                logger.error(f"[GEMINI] {model_name} failed")
                logger.error(f"[GEMINI] Type   : {type(e).__name__}")
                logger.error(f"[GEMINI] Detail : {err_str[:300]}")  # trim huge error blobs

                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    delay = _parse_retry_delay(err_str)
                    logger.warning(
                        f"[GEMINI] Rate limit hit. Waiting {delay}s then trying next model..."
                    )
                    time.sleep(delay)
                    continue   # try next model after waiting

                elif "api_key" in err_str.lower() or "invalid" in err_str.lower():
                    logger.error("[GEMINI] Bad API key — check GEMINI_API_KEY in config.py")
                    return None   # no point trying other models

                elif "403" in err_str or "permission" in err_str.lower():
                    logger.error("[GEMINI] Permission denied — check Google Cloud project.")
                    return None

                elif "not found" in err_str.lower() or "404" in err_str:
                    logger.error(f"[GEMINI] Model '{model_name}' not found — trying next...")
                    continue

                else:
                    logger.error("[GEMINI] Unknown error — trying next model...")
                    continue

        logger.error("[GEMINI] ❌ All models exhausted. Could not answer this question.")
        return None

    # ── ask_all ───────────────────────────────────────────────────

    def ask_all(self, q_text, options):
        return {"claude": self.ask_claude(q_text, options)}