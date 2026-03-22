# ================================================================
#  core/answer_picker.py
#  V1: One model → just return its answer.
#  V2: Three models → majority vote kicks in automatically.
#  No changes needed when upgrading — just add models to ask_all().
# ================================================================

import logging
from collections import Counter
import sys
sys.path.insert(0, r"C:\swayam_bot")

logger = logging.getLogger(__name__)


class AnswerPicker:

    def pick(self, answers, q_index):
        """
        answers = {'claude': 'A'}                      ← V1
        answers = {'claude':'A', 'gemini':'A', ...}    ← V2 (no change here)

        Returns (chosen_letter_or_None, explanation_string)
        """
        valid  = {m: a for m, a in answers.items() if a is not None}
        failed = [m for m, a in answers.items() if a is None]

        if failed:
            logger.warning(f"Q{q_index}: these models gave no answer: {failed}")

        if not valid:
            return None, "No model returned a valid answer."

        # Only one model (V1) — just return it directly
        if len(valid) == 1:
            model, letter = list(valid.items())[0]
            return letter, f"{model} answered: {letter}"

        # Multiple models (V2) — majority vote
        counts = Counter(valid.values())
        top_letter, top_count = counts.most_common(1)[0]

        if top_count >= 2:
            agreeing = [m for m, a in valid.items() if a == top_letter]
            return top_letter, f"Majority ({' + '.join(agreeing)}) → {top_letter}"

        # All three disagree — fall back to Claude, then Gemini, then ChatGPT
        for preferred in ["claude", "gemini", "chatgpt"]:
            if preferred in valid:
                return valid[preferred], \
                    f"All disagree {dict(counts)} — using {preferred}: {valid[preferred]}"

        return top_letter, f"Default → {top_letter}"

    def log_result(self, question, answers, chosen, explanation):
        opts = "  |  ".join([f"{k}) {v}" for k, v in question["options"].items()])
        logger.info(
            f"\n── Q{question['index']} {'─'*40}\n"
            f"{question['text']}\n"
            f"{opts}\n"
            f"  " + "  ".join([f"{m.upper()}={a or 'FAIL'}"
                                for m, a in answers.items()]) + "\n"
            f"  ✅ ANSWER: {chosen or '?'}  ({explanation})"
        )