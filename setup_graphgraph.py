#!/usr/bin/env python3
import argparse
import json
import os
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
    parser.add_argument("--openai-key", help="OpenAI API key to store in Windows Credential Manager.")
    parser.add_argument("--gemini-key", help="Gemini API key to store in Windows Credential Manager.")
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
        mcp_exe = str(venv_dir / "Scripts" / "graphgraph-mcp.exe")
        cli_exe = str(venv_dir / "Scripts" / "graphgraph.exe")
    else:
        pip_exe = str(venv_dir / "bin" / "pip")
        python_exe = str(venv_dir / "bin" / "python")
        mcp_exe = str(venv_dir / "bin" / "graphgraph-mcp")
        cli_exe = str(venv_dir / "bin" / "graphgraph")

    # 4. Install package in editable mode
    print("Installing GraphGraph package in editable mode...")
    if has_uv:
        # Resolve using uv pip inside the venv context
        run_cmd(["uv", "pip", "install", "-e", "."], cwd=repo_dir)
    else:
        run_cmd([pip_exe, "install", "-e", "."], cwd=repo_dir)

    # 5. Configure API Credentials in Windows Credential Manager / Keyring
    openai_key = args.openai_key
    gemini_key = args.gemini_key

    if not args.non_interactive and not (openai_key or gemini_key):
        print("\n--- Credential Setup ---")
        use_keyring = input("Would you like to store API keys in Windows Credential Manager? (y/n) [n]: ").strip().lower() == 'y'
        if use_keyring:
            o_key = input("Enter OpenAI API Key (leave empty to skip): ").strip()
            if o_key:
                openai_key = o_key
            g_key = input("Enter Gemini API Key (leave empty to skip): ").strip()
            if g_key:
                gemini_key = g_key

    # Save to keyring using python inside the venv
    if openai_key:
        print("Storing OpenAI API Key secure credential...")
        run_cmd([python_exe, "-c", f"import keyring; keyring.set_password('OpenAI', 'API_KEY', {repr(openai_key)})"])
    if gemini_key:
        print("Storing Gemini API Key secure credential...")
        run_cmd([python_exe, "-c", f"import keyring; keyring.set_password('Gemini', 'API_KEY', {repr(gemini_key)})"])

    # 6. Configure Claude Desktop MCP Settings
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            claude_config_dir = Path(appdata) / "Claude"
            claude_config_path = claude_config_dir / "claude_desktop_config.json"
            
            print(f"Configuring Claude Desktop MCP at: {claude_config_path}")
            claude_config_dir.mkdir(parents=True, exist_ok=True)
            
            config_data = {}
            if claude_config_path.exists():
                try:
                    with open(claude_config_path, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception as e:
                    print(f"Warning: Failed to parse existing Claude config: {e}")

            if "mcpServers" not in config_data:
                config_data["mcpServers"] = {}

            # Use forward slashes for Windows paths in JSON configs to avoid escape issues
            mcp_exe_normalized = mcp_exe.replace("\\", "/")
            config_data["mcpServers"]["graphgraph"] = {
                "command": mcp_exe_normalized,
                "args": []
            }

            try:
                with open(claude_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2)
                print("Claude Desktop config updated successfully.")
            except Exception as e:
                print(f"Error: Failed to write Claude config: {e}")

    # 7. Print verify command
    print("\n--- Installation Verification ---")
    try:
        res = run_cmd([cli_exe, "--help"])
        print("Verification Succeeded! CLI help output verified.")
    except Exception as e:
        print(f"Warning: CLI verification failed: {e}")

    cursor_cmd = mcp_exe.replace("\\", "/")
    print("\nSetup finished successfully!")
    print(f"To configure Cursor, use Command: {cursor_cmd}")

if __name__ == "__main__":
    main()
