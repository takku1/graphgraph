#!/usr/bin/env python3
import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def run_cmd(args, cwd=None, check=True):
    print(f"Executing: {' '.join(args)}")
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)

def main():
    parser = argparse.ArgumentParser(description="Bootstrap and configure GraphGraph setup.")
    parser.add_argument("--openai-key", help="Optional OpenAI API key to store for external model benchmarks.")
    parser.add_argument("--gemini-key", help="Optional Gemini API key to store for external model benchmarks.")
    parser.add_argument("--non-interactive", action="store_true", help="Run without asking for input.")
    args = parser.parse_args()

    repo_dir = Path(__file__).parent.resolve()
    print(f"Setting up GraphGraph in: {repo_dir}")

    # 1. Detect toolchains
    has_uv = shutil.which("uv") is not None
    print(f"Detected uv: {has_uv}")

    venv_dir = repo_dir / ".venv"
    
    # 2. Create virtual environment if missing
    if not venv_dir.exists():
        print("Creating virtual environment...")
        if has_uv:
            run_cmd(["uv", "venv"], cwd=repo_dir)
        else:
            run_cmd([sys.executable, "-m", "venv", ".venv"], cwd=repo_dir)
    else:
        print("Virtual environment already exists.")

    # 3. Determine python and executable paths
    if platform.system() == "Windows":
        pip_exe = str(venv_dir / "Scripts" / "pip.exe")
        python_exe = str(venv_dir / "Scripts" / "python.exe")
        cli_exe = str(venv_dir / "Scripts" / "graphgraph.exe")
    else:
        pip_exe = str(venv_dir / "bin" / "pip")
        python_exe = str(venv_dir / "bin" / "python")
        cli_exe = str(venv_dir / "bin" / "graphgraph")

    # 4. Install package in editable mode
    print("Installing GraphGraph package in editable mode...")
    if has_uv:
        # Resolve using uv pip inside the venv context
        run_cmd(["uv", "pip", "install", "-e", "."], cwd=repo_dir)
    else:
        run_cmd([pip_exe, "install", "-e", "."], cwd=repo_dir)

    # 5. Optionally configure external benchmark API credentials in keyring.
    # Normal GraphGraph scan/query/packet/MCP workflows do not need provider keys.
    openai_key = args.openai_key
    gemini_key = args.gemini_key

    if not args.non_interactive and not (openai_key or gemini_key):
        print("\n--- Optional External Benchmark Credential Setup ---")
        print("GraphGraph local skill/MCP/CLI use does not require provider API keys.")
        use_keyring = input("Store optional API keys for external model benchmarks? (y/n) [n]: ").strip().lower() == 'y'
        if use_keyring:
            o_key = input("Enter OpenAI API Key (leave empty to skip): ").strip()
            if o_key:
                openai_key = o_key
            g_key = input("Enter Gemini API Key (leave empty to skip): ").strip()
            if g_key:
                gemini_key = g_key

    # Save to keyring using python inside the venv
    if openai_key:
        print("Storing optional OpenAI benchmark credential...")
        run_cmd([python_exe, "-c", f"import keyring; keyring.set_password('OpenAI', 'API_KEY', {repr(openai_key)})"])
    if gemini_key:
        print("Storing optional Gemini benchmark credential...")
        run_cmd([python_exe, "-c", f"import keyring; keyring.set_password('Gemini', 'API_KEY', {repr(gemini_key)})"])

    # 6. Register with AI assistant platforms via the CLI's own `install` command.
    # This configures Claude Code (project scope), the Codex plugin (portable
    # .mcp.json), Cursor (project scope), and Gemini/Antigravity (project
    # scope) in one shot, using the freshly-installed graphgraph console script.
    print("\n--- Registering AI assistant integrations ---")
    try:
        run_cmd([cli_exe, "install", "--project", "--platform", "all"], cwd=repo_dir, check=False)
    except Exception as e:
        print(f"Warning: project-scoped 'graphgraph install' failed: {e}")

    # Claude Desktop is a global-only app -- the project-scoped call above
    # intentionally skips it (mirrors install.py's own `not args.project`
    # guard), so register it separately.
    try:
        run_cmd([cli_exe, "install", "--platform", "claude-desktop"], check=False)
    except Exception as e:
        print(f"Warning: 'graphgraph install --platform claude-desktop' failed: {e}")

    # 7. Print verify command
    print("\n--- Installation Verification ---")
    try:
        run_cmd([cli_exe, "--help"])
        print("Verification Succeeded! CLI help output verified.")
    except Exception as e:
        print(f"Warning: CLI verification failed: {e}")

    print("\nSetup finished successfully!")
    print(f"Run '{cli_exe} doctor' to see per-client MCP registration status.")

if __name__ == "__main__":
    main()
