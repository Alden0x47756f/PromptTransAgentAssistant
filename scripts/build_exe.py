"""Build a windowed single EXE; config.toml and prompts stay beside it."""
from pathlib import Path
import os
import subprocess
import sys
import argparse

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--name', default='PromptTransAgentAssistant', help='Executable name, without .exe')
args = parser.parse_args()
subprocess.run([sys.executable, str(root / 'scripts' / 'prepare_logo.py')],
               cwd=root, check=True)
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
           '--name', args.name, '--distpath', str(root),
           '--workpath', str(root / 'build' / 'work'), '--specpath', str(root / 'build'),
           '--add-data', str(root / 'frontend') + ';frontend',
           '--icon', str(root / 'frontend' / 'branding' / 'app.ico'),
           '--version-file', str(root / 'scripts' / 'windows-version.txt'),
           '--exclude-module', 'pytest', '--exclude-module', 'unittest',
           str(root / 'main.py')]
# Native tools on the host can ship an incompatible ICU DLL with the same name
# as Windows' ICU. Restrict dependency discovery to Python and Windows runtimes.
environment = os.environ.copy()
windows = Path(environment.get('SystemRoot', r'C:\Windows'))
environment['PATH'] = os.pathsep.join(str(path) for path in (
    Path(sys.executable).parent, Path(sys.base_prefix), Path(sys.base_prefix) / 'DLLs',
    windows / 'System32', windows,
))
result = subprocess.call(command, cwd=root, env=environment)
if result == 0:
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                    '-File', str(root / 'RefreshIcon.ps1'),
                    '-IconPath', str(root / (args.name + '.exe'))], cwd=root)
raise SystemExit(result)
