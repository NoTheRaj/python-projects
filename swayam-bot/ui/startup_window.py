# ================================================================
#  ui/startup_window.py
#  The startup popup. Uses only tkinter which is built into Python.
# ================================================================

import tkinter as tk
from tkinter import ttk, simpledialog
import threading, logging, sys, time
sys.path.insert(0, r"C:\swayam_bot")

logger = logging.getLogger(__name__)


class StartupWindow:

    # Colour scheme — dark GitHub-style
    BG      = "#0d1117"
    CARD    = "#161b22"
    ACCENT  = "#238636"   # green
    TEXT    = "#e6edf3"
    MUTED   = "#8b949e"
    SUCCESS = "#3fb950"
    WARN    = "#d29922"
    ERROR   = "#f85149"
    BLUE    = "#58a6ff"

    def __init__(self):
        self.root            = tk.Tk()
        self._running        = False
        self._continue_event = threading.Event()  # ← used for CAPTCHA pause
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    def _on_close(self):
        """Stop the bot and close Chrome when window is closed."""
        if self._running:
            self._log("Window closed — stopping bot...", "warn")
        self.root.destroy()
        # Force kill Chrome and chromedriver
        import subprocess
        subprocess.Popen("taskkill /F /IM chrome.exe /T", shell=True)
        subprocess.Popen("taskkill /F /IM chromedriver.exe /T", shell=True)

    def _build(self):
        r = self.root
        r.title("Swayam Bot")
        r.configure(bg=self.BG)
        r.resizable(False, False)
        r.attributes("-topmost", True)

        # Centre on screen
        w, h = 540, 520
        x = (r.winfo_screenwidth()  - w) // 2
        y = (r.winfo_screenheight() - h) // 2
        r.geometry(f"{w}x{h}+{x}+{y}")

        # Top accent bar
        tk.Frame(r, bg=self.ACCENT, height=4).pack(fill="x")

        # Header
        hdr = tk.Frame(r, bg=self.BG, pady=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🎓  Swayam Bot  —  v1",
                 font=("Segoe UI", 17, "bold"),
                 fg=self.TEXT, bg=self.BG).pack()
        tk.Label(hdr, text="Powered by Claude  ·  Single model mode",
                 font=("Segoe UI", 9), fg=self.MUTED, bg=self.BG).pack()

        # Main card
        card = tk.Frame(r, bg=self.CARD, padx=26, pady=20)
        card.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        tk.Label(card,
            text="Should the bot check for a new week\nand complete the assessment?",
            font=("Segoe UI", 12), fg=self.TEXT, bg=self.CARD,
            justify="center").pack(pady=(0, 18))

        # ── YES / Not Now buttons ─────────────────────────────────
        bf = tk.Frame(card, bg=self.CARD)
        bf.pack()

        self.yes_btn = tk.Button(bf,
            text="  ▶   YES — Run Now  ",
            font=("Segoe UI", 11, "bold"),
            bg=self.ACCENT, fg="white", activebackground="#2ea043",
            relief="flat", padx=14, pady=10, cursor="hand2",
            command=self._on_yes)
        self.yes_btn.grid(row=0, column=0, padx=8)

        self.no_btn = tk.Button(bf,
            text="  ✕   Not Now  ",
            font=("Segoe UI", 11),
            bg="#21262d", fg=self.MUTED,
            relief="flat", padx=14, pady=10, cursor="hand2",
            command=r.destroy)
        self.no_btn.grid(row=0, column=1, padx=8)

        # ── Continue button (hidden until CAPTCHA detected) ───────
        self._continue_btn = tk.Button(card,
            text="  ✅   Continue (CAPTCHA solved)  ",
            font=("Segoe UI", 11, "bold"),
            bg="#1f6feb", fg="white", activebackground="#388bfd",
            relief="flat", padx=14, pady=10, cursor="hand2",
            command=self._on_continue)
        # NOT packed here — only shown when CAPTCHA is detected

        # ── Live log box ──────────────────────────────────────────
        lf = tk.Frame(card, bg=self.CARD)
        lf.pack(fill="both", expand=True, pady=(20, 0))

        self.log_box = tk.Text(lf, height=10, wrap="word",
            bg="#010409", fg=self.TEXT,
            font=("Consolas", 9), relief="flat",
            state="disabled", padx=8, pady=6)
        sb = ttk.Scrollbar(lf, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Colour tags
        self.log_box.tag_config("ok",   foreground=self.SUCCESS)
        self.log_box.tag_config("warn", foreground=self.WARN)
        self.log_box.tag_config("err",  foreground=self.ERROR)
        self.log_box.tag_config("head", foreground=self.BLUE,
                                font=("Consolas", 9, "bold"))

        # Progress bar
        self.bar = ttk.Progressbar(card, mode="indeterminate", length=466)
        self.bar.pack(pady=(10, 0))

    # ── Button actions ────────────────────────────────────────────

    def _on_yes(self):
        if self._running: return
        self._running = True
        self.yes_btn.config(state="disabled", text="  ⏳  Running...  ")
        self.no_btn.config(state="disabled")
        self.bar.start(10)
        self._log("Starting...", "head")
        threading.Thread(target=self._run_bot, daemon=True).start()

    def _on_continue(self):
        """User clicked Continue after solving CAPTCHA."""
        self._continue_event.set()
        # Hide the button again
        self._continue_btn.pack_forget()
        self._log("▶️  Continuing bot...", "head")

    def _show_continue_btn(self):
        """Show the Continue button — called from bot thread via root.after."""
        self._continue_btn.pack(pady=(10, 0))

    def _run_bot(self):
        from core.orchestrator import Orchestrator

        # ── Wire the CAPTCHA pause hook ───────────────────────────
        def _wait_for_user():
            self._continue_event.clear()
            self.root.after(0, self._show_continue_btn)  # show button on main thread
            self._continue_event.wait()                  # block bot thread until clicked

        bot = Orchestrator(
            status_cb=self._log_safe,
            manual_answer_cb=lambda q: None   # no manual answers — bot handles all
        )
        bot._wait_for_user = _wait_for_user   # attach CAPTCHA hook to bot
        ok = bot.run()
        self.root.after(0, self._finish, ok)

    def _finish(self, ok):
        self.bar.stop()
        self._running = False
        if ok:
            self.yes_btn.config(
                text="  ✅  Done — Close  ",
                bg=self.SUCCESS, fg="#000",
                state="normal", command=self.root.destroy)
            self._log("Completed successfully!", "ok")
        else:
            self.yes_btn.config(
                text="  ↺  Try Again  ",
                bg=self.WARN, fg="#000",
                state="normal", command=self._retry)
            self._log("Something went wrong. See swayam_bot.log for details.", "err")
        self.no_btn.config(state="normal", text="  Close  ")

    def _retry(self):
        self._running = False
        self.yes_btn.config(
            text="  ▶   YES — Run Now  ",
            bg=self.ACCENT, fg="white",
            state="normal", command=self._on_yes)

    # ── Logging ───────────────────────────────────────────────────

    def _log(self, msg, tag=""):
        if not tag:
            if   any(c in msg for c in ["✅", "🎉", "Done", "success"]): tag = "ok"
            elif any(c in msg for c in ["❌", "error", "Error", "fail"]): tag = "err"
            elif any(c in msg for c in ["⚠️", "⏭️", "unclear", "stuck"]): tag = "warn"
            elif any(c in msg for c in ["🌐","📂","🔑","📚","🔍","📝","🤖","📤","🗂️"]): tag = "head"
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"  {msg}\n", tag)
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def _log_safe(self, msg):
        """Thread-safe log — called from the background thread."""
        self.root.after(0, self._log, msg)

    def run(self):
        self.root.mainloop()