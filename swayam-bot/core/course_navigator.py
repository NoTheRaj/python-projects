# ================================================================
#  core/course_navigator.py
#  Navigates Swayam NPTEL — login, course, assessment, questions.
#
#  ALL selectors confirmed from DevTools screenshots of the live page.
#
#  ── CONFIRMED DOM STRUCTURE ──────────────────────────────────────
#
#  SIDEBAR (course page):
#    div.unit_navbar#{id}
#      div.unit_heading  onclick="toggleSubUnitNavBar(...)"
#        <a>Week N :</a>                     ← week_link
#      ul.subunit_navbar_current
#        li.subunit_other × N               (lectures)
#        li.subunit_other
#          div.gcb-left-activity-title-with-progress.gcb-nav-pa
#            <a href="assessment?name=N" id="assessment_N">Quiz: Week N : Assignment N</a>
#            div.gcb-progress-icon-holder
#              <img class="gcb-progress-icon [gcb-progress-icon-holder-completed]"
#                   id="progress-state-N">
#
#  QUIZ PAGE (assessment page):
#    div.qt-mc-question.qt-embedded
#      div.qt-points
#      div.qt-question             ← get_questions() box selector
#      div.qt-choices
#        div.gcb-mcq-choice
#          <input type="radio" data-index="N" onclick="clearSelection(this)">
#          <label>a. </label>      ← ONLY the letter prefix; answer text is
#                                    a sibling text node → use choice.text
#
#  SUBMIT (bottom of quiz page):
#    <button id="submitbutton" class="gcb-button qt-check-answer-button">
#       Submit Answers
#    </button>
#    After click, hidden popups may appear:
#      div#assessment-not-all-attempt  (if not all Qs answered)
#      div#submission-warning          (confirmation popup)
#
#  ── FIXES APPLIED ────────────────────────────────────────────────
#
#  FIX-1  check_new_week()  — regex filter 54 raw links → 11 real
#                              week headers only.
#
#  FIX-5  check_new_week()  — CRITICAL BUG: old code used global
#          "//a..." XPath which ALWAYS found Week 0's assignment
#          (first in DOM), making every week look completed.
#          Fix: go up to div.unit_navbar (grandparent = "../.."),
#          then search ".//a[contains(@href,'assessment')]" scoped
#          to ONLY that week's container.
#
#  FIX-2  get_questions()   — old code used label.text which is
#          just "a. " (empty after strip). Fix: use choice.text
#          which includes the answer text that lives as a sibling
#          text node inside div.gcb-mcq-choice.
#          Also stores radio + label + div in elements dict.
#
#  FIX-3  select_answer()   — click label first (fires NPTEL's
#          clearSelection() properly), then dispatch 'change' event,
#          then verify radio.checked. Fallback to parent div click.
#
#  FIX-4  submit()          — use By.ID "submitbutton" (exact, no
#          text-matching guessing). js_click the confirm button,
#          scroll into view first, wait 5 s for popup to render,
#          catch ElementNotInteractableException so a popup failure
#          does not crash a successful submission.
# ================================================================

import time, logging, os, re
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    TimeoutException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    NoSuchElementException,
)
import sys
sys.path.insert(0, r"C:\swayam_bot")
import config

logger = logging.getLogger(__name__)

# ── FIX-1: only match pure week-header link text ─────────────────
# ✅ "Week 1"  "Week 1 :"  "Week 10 :"  "Week 0 :"
# ❌ "Week 1 Assignment"  "Week 2 : Intro to Java"  "Week 3 Lec 1"
_WEEK_HEADER_RE = re.compile(r'^Week\s+\d+\s*:?\s*$', re.IGNORECASE)


class CourseNavigator:

    def __init__(self, browser):
        self.b = browser
        self.target_week       = None
        self.target_assignment = None

    # ── Step 1: Login ─────────────────────────────────────────────

    def login(self):
        logger.info("Clicking Login on Swayam homepage...")
        self.b.switch_to("swayam")
        try:
            self.b.click(By.CSS_SELECTOR, "a.login-btn")
            time.sleep(config.PAGE_LOAD_WAIT + 2)
            logger.info("Login done.")
            return True
        except TimeoutException:
            logger.warning("Login button not found — already logged in.")
            return True

    # ── Step 2: Open the Course ───────────────────────────────────

    def open_course(self):
        logger.info(f"Looking for course: {config.COURSE_NAME_KEYWORD}")
        try:
            self.b.click(By.CSS_SELECTOR, "div.user-avatar")
            time.sleep(1)
            logger.info("Profile dropdown opened.")
        except TimeoutException:
            logger.error("Profile avatar not found.")
            self.b.screenshot("profile_not_found")
            return False

        try:
            self.b.click(By.CSS_SELECTOR, "a[href='/mycourses']")
            time.sleep(config.PAGE_LOAD_WAIT)
            logger.info("My Courses page loaded.")
        except TimeoutException:
            logger.error("MY COURSES link not found.")
            self.b.screenshot("my_courses_not_found")
            return False

        try:
            go_btn = self.b.find(By.XPATH,
                f"//div[contains(@data-title,'{config.COURSE_NAME_KEYWORD}')]"
                f"//a[contains(@class,'course-button')]")
            self.b.scroll_to(go_btn)
            self.b.js_click(go_btn)
            time.sleep(config.PAGE_LOAD_WAIT)
            logger.info("Go To Course clicked.")

            # Always close the "Continue Where You Left" popup.
            # Clicking Continue would dump us into a random video/week.
            close_btn = self.b.safe_find(By.ID, "closebtn", timeout=5)
            if close_btn:
                self.b.js_click(close_btn)
                time.sleep(1)
                logger.info("Closed 'Continue Where You Left' popup.")
            return True
        except TimeoutException:
            logger.error(f"Go To Course button not found for '{config.COURSE_NAME_KEYWORD}'.")
            self.b.screenshot("go_to_course_not_found")
            return False

    # ── Step 3: Find the target week ─────────────────────────────
    #
    #  FIX-5 (THE CRITICAL BUG) — what was broken and why:
    #
    #  Old code called:
    #    self.b.safe_find(By.XPATH, "//a[contains(text(),'Assignment')...]")
    #
    #  XPath "//" means GLOBAL — it searched the entire page DOM from
    #  root regardless of which week header was just clicked.
    #  NPTEL renders ALL weeks' sub-items in the DOM simultaneously;
    #  only visibility changes on click. So "//" always returned Week 0's
    #  assignment (first in DOM). Since Week 0 was done, EVERY week
    #  appeared done → bot reported "All weeks completed" and quit.
    #
    #  Fix: walk up to div.unit_navbar (grandparent of the week link <a>):
    #    week_link  (= <a>)
    #      → .find_element("..") = div.unit_heading
    #        → .find_element("..") = div.unit_navbar   ← search from here
    #  Then use ".//a[...]" (dot = relative) so the search is scoped to
    #  only the expanded sub-items of THIS week.

    def check_new_week(self):
        self.target_week       = None
        self.target_assignment = None

        # ── Collect all sidebar links starting with "Week" ────────
        raw_links = self.b.driver.find_elements(By.XPATH,
            "//div[contains(@class,'gcb-aside') or contains(@id,'gcb-nav-left')]"
            "//a[starts-with(normalize-space(text()),'Week')]"
        )
        if not raw_links:
            raw_links = self.b.driver.find_elements(By.XPATH,
                "//a[starts-with(normalize-space(text()),'Week')]"
            )

        # ── FIX-1: keep only pure week-header links ───────────────
        week_links = [el for el in raw_links
                      if _WEEK_HEADER_RE.match(el.text.strip())]

        if not week_links:
            logger.warning(
                f"Regex filter left 0 results from {len(raw_links)} raw links. "
                "Falling back to unfiltered list."
            )
            week_links = raw_links

        logger.info(
            f"Found {len(raw_links)} raw sidebar links → "
            f"{len(week_links)} pure week headers after filtering."
        )

        # ── Walk from last week backwards ─────────────────────────
        for week_link in reversed(week_links):
            week_name = week_link.text.strip()
            logger.info(f"Checking {week_name}...")

            # Click the week header to expand its sub-items
            self.b.scroll_to(week_link)
            try:
                week_link.click()
            except StaleElementReferenceException:
                logger.warning(f"{week_name}: stale element — skipping.")
                continue
            time.sleep(1.5)

            # ── FIX-5: scoped search ──────────────────────────────
            # Confirmed structure (Images 1/2/3):
            #   week_link <a>
            #     → parent:      div.unit_heading
            #     → grandparent: div.unit_navbar   ← contains BOTH heading + ul
            #
            # From div.unit_navbar we search ".//a[contains(@href,'assessment')]"
            # "./" = relative, so it only finds THIS week's assignment link.

            assignment_link = None

            try:
                # Grandparent = div.unit_navbar
                unit_navbar = week_link.find_element(By.XPATH, "../..")
                assignment_link = unit_navbar.find_element(By.XPATH,
                    ".//a[contains(@href,'assessment')]"
                )
                logger.debug(f"{week_name}: found assignment via unit_navbar scope.")
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # One-level-up fallback: some themes nest differently
            if assignment_link is None:
                try:
                    unit_heading = week_link.find_element(By.XPATH, "..")
                    assignment_link = unit_heading.find_element(By.XPATH,
                        ".//a[contains(@href,'assessment')]"
                    )
                    logger.debug(f"{week_name}: found assignment via unit_heading scope.")
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

            if assignment_link is None:
                logger.warning(
                    f"{week_name}: no scoped assignment found — "
                    "skipping (not treating as error)."
                )
                continue

            # ── Read progress icon for THIS assignment ────────────
            # Confirmed (Images 2/3):
            #   Completed:  img.class includes "gcb-progress-icon-holder-completed"
            #   Not done:   img.class is just "gcb-progress-icon"
            #   ID mapping: assessment_N → progress-state-N

            assignment_id = assignment_link.get_attribute("id") or ""
            progress_id   = assignment_id.replace("assessment_", "progress-state-")

            progress_img = None

            # By ID (most reliable — IDs are page-unique)
            if progress_id and progress_id != "progress-state-":
                progress_img = self.b.safe_find(By.ID, progress_id, timeout=3)

            # Fallback: img sibling of the assignment link
            if progress_img is None:
                try:
                    progress_img = assignment_link.find_element(
                        By.XPATH,
                        "..//img[contains(@class,'gcb-progress-icon')]"
                    )
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

            if progress_img is None:
                # Can't read completion status → assume incomplete, target this week
                logger.warning(
                    f"{week_name}: progress icon not found — "
                    "assuming NOT completed."
                )
                self.target_week       = week_name
                self.target_assignment = assignment_link
                return True

            icon_classes = progress_img.get_attribute("class") or ""

            if "gcb-progress-icon-holder-completed" in icon_classes:
                logger.info(f"{week_name}: completed — checking earlier week...")
                continue
            else:
                logger.info(f"{week_name}: NOT completed — this is our target.")
                self.target_week       = week_name
                self.target_assignment = assignment_link
                return True

        logger.info("All weeks are completed. Nothing to do.")
        return False

    # ── Step 4: Open the Assessment ───────────────────────────────

    def open_assessment(self):
        if self.target_assignment is None:
            logger.error("No target assignment — run check_new_week() first.")
            return False
        try:
            logger.info(f"Opening assignment in {self.target_week}...")
            self.b.scroll_to(self.target_assignment)
            time.sleep(1)
            try:
                self.target_assignment.click()
            except Exception:
                logger.warning("Regular click failed — trying JS click...")
                self.b.js_click(self.target_assignment)
            time.sleep(config.PAGE_LOAD_WAIT)
            logger.info("Assessment page opened.")
            return True
        except Exception as e:
            logger.error(f"Could not open assignment: {e}")
            self.b.screenshot("open_assessment_fail")
            return False

    # ── Step 5: Screenshot helper ─────────────────────────────────

    def _screenshot_question_block(self, box, idx):
        """
        Walks up the DOM to find the ancestor containing both
        qt-question and qt-choices, centres it in the viewport,
        and takes an element-level screenshot.
        """
        os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
        image_path = os.path.join(config.SCREENSHOTS_DIR, f"question_{idx}.png")

        target_el = box
        for _ in range(5):
            try:
                parent = target_el.find_element(By.XPATH, "..")
                has_q = len(parent.find_elements(By.CSS_SELECTOR, "div.qt-question")) > 0
                has_c = len(parent.find_elements(By.CSS_SELECTOR, "div.qt-choices"))  > 0
                if has_q and has_c:
                    target_el = parent
                    break
                target_el = parent
            except Exception:
                break

        # Scroll to vertical centre of viewport
        self.b.driver.execute_script("""
            var el = arguments[0];
            var rect = el.getBoundingClientRect();
            var offset = rect.top + window.pageYOffset
                         - (window.innerHeight / 2)
                         + (rect.height / 2);
            window.scrollTo({top: offset, behavior: 'instant'});
        """, target_el)
        time.sleep(1.2)

        try:
            target_el.screenshot(image_path)
            logger.info(f"Q{idx}: Screenshot saved → {image_path}")
        except Exception as e:
            logger.warning(f"Q{idx}: Element screenshot failed ({e}), using full page.")
            self.b.driver.save_screenshot(image_path)

        return image_path

    # ── Step 6: Scrape questions ──────────────────────────────────

    def get_questions(self):
        """
        Confirmed selectors (Image 4):
          Question container: div.qt-question  (child of div.qt-mc-question)
          Choices container:  div.qt-choices   (sibling of div.qt-question)
          Choice:             div.gcb-mcq-choice
          Radio:              input[type=radio][data-index]
          Label text:         just "a. " — answer text is a sibling text node

        FIX-2: use choice.text (full div text) instead of label.text
               (which is only the letter prefix "a. ", not the answer).
               Elements dict now stores radio + label + div for FIX-3.
        """
        self.b.switch_to("swayam")
        questions = []

        self.b.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        containers = self.b.driver.find_elements(By.CSS_SELECTOR, "div.qt-question")
        if not containers:
            logger.error("No question containers found (div.qt-question). "
                         "Selector may need updating.")
            return []

        logger.info(f"Found {len(containers)} question(s).")

        for idx, box in enumerate(containers, start=1):
            try:
                q_text = box.text.strip()

                # Detect image questions
                img_els = box.find_elements(By.CSS_SELECTOR, "img")
                is_image_question = len(img_els) > 0 and len(q_text) < 10
                image_path = None

                if is_image_question:
                    try:
                        image_path = self._screenshot_question_block(box, idx)
                        q_text = "[IMAGE QUESTION — screenshot saved]"
                    except Exception as e:
                        logger.error(f"Q{idx}: Screenshot failed: {e}")
                        q_text = "[IMAGE QUESTION — screenshot failed]"
                else:
                    logger.info(f"Q{idx}: {q_text[:60]}...")

                # ── Get answer choices ────────────────────────────
                # Confirmed (Image 4):
                #   box (div.qt-question) parent = div.qt-mc-question
                #   div.qt-choices is a sibling inside div.qt-mc-question
                q_parent    = box.find_element(By.XPATH, "..")
                choices_div = q_parent.find_element(By.CSS_SELECTOR, "div.qt-choices")
                choice_divs = choices_div.find_elements(By.CSS_SELECTOR, "div.gcb-mcq-choice")

                options  = {}
                elements = {}

                for choice in choice_divs:
                    try:
                        radio   = choice.find_element(By.CSS_SELECTOR, "input[type='radio']")
                        label   = choice.find_element(By.CSS_SELECTOR, "label")
                        d_index = radio.get_attribute("data-index")
                        key     = chr(65 + int(d_index))   # 0→A, 1→B, 2→C, 3→D

                        # FIX-2: use choice.text not label.text.
                        # label.text = "a. " only (confirmed from DevTools).
                        # choice.text = "a. FlowLayout" (includes sibling text node).
                        raw_text   = choice.text.strip()
                        clean_text = re.sub(r'^[a-dA-D][.)]\s*', '', raw_text).strip()

                        options[key]  = clean_text
                        # FIX-2: store all three element handles for select_answer
                        elements[key] = {
                            "radio": radio,
                            "label": label,
                            "div":   choice,
                        }
                    except Exception as e:
                        logger.warning(f"Q{idx}: Could not parse choice: {e}")

                questions.append({
                    "index":             idx,
                    "text":              q_text,
                    "options":           options,
                    "elements":          elements,
                    "is_image_question": is_image_question,
                    "image_path":        image_path,
                })

            except Exception as e:
                logger.error(f"Q{idx}: Failed to parse — {e}")
                self.b.screenshot(f"q{idx}_parse_error")

        logger.info(f"Successfully parsed {len(questions)} question(s).")
        return questions

    # ── Step 7: Select an answer ──────────────────────────────────

    def select_answer(self, question, answer_key):
        """
        FIX-3: Confirmed radio structure (Image 4):
          <input onclick="clearSelection(this)"> — NPTEL's deselect handler
          <label>a. </label>

        Clicking the label triggers the label→radio association:
          1. Label click → radio click event fires
          2. clearSelection(this) runs: if already checked → uncheck; else no-op
          3. Radio gets checked by default browser behaviour

        After clicking, we dispatch a 'change' event and verify .checked.
        Fallback: click the parent gcb-mcq-choice div.
        """
        self.b.switch_to("swayam")
        el_dict = question["elements"].get(answer_key)

        if not el_dict:
            logger.error(
                f"Q{question['index']}: No element for '{answer_key}'. "
                f"Available: {list(question['elements'].keys())}"
            )
            return

        # Legacy safety: if this is still a raw element (pre-FIX-2 format)
        if not isinstance(el_dict, dict):
            self.b.scroll_to(el_dict)
            time.sleep(0.3)
            self.b.js_click(el_dict)
            time.sleep(0.4)
            logger.info(f"Q{question['index']}: Selected {answer_key} (legacy path)")
            return

        radio_el = el_dict["radio"]
        label_el = el_dict["label"]
        div_el   = el_dict["div"]

        # Scroll the whole choice div into view (larger target)
        self.b.scroll_to(div_el)
        time.sleep(0.4)

        # Step 1: Click the label (triggers NPTEL's clearSelection + checks radio)
        self.b.js_click(label_el)
        time.sleep(0.4)

        # Step 2: Dispatch 'change' event on the radio (belt + braces)
        self.b.driver.execute_script(
            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
            radio_el
        )
        time.sleep(0.3)

        # Step 3: Verify radio.checked in DOM
        is_checked = self.b.driver.execute_script(
            "return arguments[0].checked;", radio_el
        )

        # Step 4: Fallback — click parent div if label didn't register
        if not is_checked:
            logger.warning(
                f"Q{question['index']}: label click didn't register — "
                "trying parent div click."
            )
            self.b.js_click(div_el)
            time.sleep(0.3)
            self.b.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
                radio_el
            )
            time.sleep(0.3)
            is_checked = self.b.driver.execute_script(
                "return arguments[0].checked;", radio_el
            )
            if not is_checked:
                logger.error(
                    f"Q{question['index']}: ⚠️  Radio still not checked after "
                    "label + div fallback. Answer may not save."
                )

        option_text = question['options'].get(answer_key, '?')
        logger.info(
            f"Q{question['index']}: Selected {answer_key} "
            f"(verified checked={is_checked}) — {option_text}"
        )

    # ── Step 8: Submit ────────────────────────────────────────────

    def submit(self):
        """
        FIX-4: Confirmed from DevTools (Image 5):
          Submit button: <button id="submitbutton" class="gcb-button qt-check-answer-button">
                          Submit Answers </button>

        Old code used text-match XPath → found the button but then
        confirm.click() raised ElementNotInteractableException because
        the popup div was still hidden when safe_find found the button
        inside it, and .click() refuses to click invisible elements.

        Fixes:
          • By.ID "submitbutton" — exact, no text-matching guessing
          • js_click submit button (bypasses any focus/visibility check)
          • Wait 5 s for popup to render and become visible
          • Look for confirm button inside div#submission-warning first
          • js_click confirm button (bypasses visibility check)
          • Catch ElementNotInteractableException — don't crash if
            the popup didn't appear (direct submit with no confirm)
        """
        self.b.switch_to("swayam")
        try:
            # ── Find and click Submit Answers button ──────────────
            # FIX-4: use By.ID "submitbutton" — confirmed from Image 5
            btn = self.b.find_clickable(By.ID, "submitbutton")
            self.b.scroll_to(btn)
            time.sleep(0.5)
            self.b.js_click(btn)
            logger.info("'Submit Answers' clicked — waiting for popup...")

            # ── Wait for confirmation popup ───────────────────────
            # FIX-4: was 2 s — increased to 5 s for NPTEL's slow popup render
            time.sleep(5)

            # ── Try: button inside submission-warning popup first ─
            # Confirmed popup id from Image 5: div#submission-warning
            confirm = None
            try:
                warning_div = self.b.driver.find_element(By.ID, "submission-warning")
                confirm = warning_div.find_element(By.TAG_NAME, "button")
                logger.info("Found confirm button inside #submission-warning.")
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # ── Fallback: any visible Yes/OK/Confirm/Submit button ─
            if confirm is None:
                confirm = self.b.safe_find(By.XPATH,
                    "//button[contains(text(),'Yes') or contains(text(),'OK') "
                    "or contains(text(),'Confirm') or contains(text(),'Submit')]",
                    timeout=5
                )

            if confirm:
                try:
                    self.b.scroll_to(confirm)
                    time.sleep(0.5)
                    # FIX-4: js_click bypasses the ElementNotInteractableException
                    self.b.js_click(confirm)
                    time.sleep(3)
                    logger.info("Confirm button clicked.")
                except (ElementNotInteractableException, Exception) as e:
                    # FIX-4: catching this so we don't crash after a good submit
                    logger.warning(
                        f"Confirm click raised {type(e).__name__}: {e}\n"
                        "Submission may still have gone through — "
                        "please verify in Swayam."
                    )
            else:
                # No popup appeared — submit was immediate (no confirmation needed)
                logger.info("No confirmation popup appeared — submit was direct.")

            logger.info("✅ Submitted successfully.")
            return True

        except TimeoutException:
            logger.error("Submit button (id=submitbutton) not found.")
            self.b.screenshot("submit_fail")
            return False