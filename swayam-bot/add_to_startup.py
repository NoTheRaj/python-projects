import winreg, sys

PYTHON_W = sys.executable.replace("python.exe", "pythonw.exe")
COMMAND  = f'"{PYTHON_W}" "C:\\swayam_bot\\main.py"'
KEY      = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME     = "SwayamBot"

def add():
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, COMMAND)
    winreg.CloseKey(k)
    print(f"✅ Added to startup:\n   {COMMAND}")

def remove():
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE)
    winreg.DeleteValue(k, NAME)
    winreg.CloseKey(k)
    print("✅ Removed from startup.")

if __name__ == "__main__":
    if "--remove" in sys.argv: remove()
    else: add()