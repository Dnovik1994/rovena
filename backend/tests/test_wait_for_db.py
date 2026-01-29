from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_wait_for_db_retries_and_succeeds(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "wait-for-db.sh"
    counter_file = tmp_path / "ping-count.txt"
    counter_file.write_text("0", encoding="utf-8")

    fake_python = tmp_path / "python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "if [[ \"$1\" == \"-m\" && \"$2\" == \"app.utils.db_readiness\" ]]; then",
                "  case \"$3\" in",
                "    ping)",
                "      count=$(cat \"$COUNTER_FILE\")",
                "      count=$((count + 1))",
                "      echo \"$count\" > \"$COUNTER_FILE\"",
                "      if [[ \"$count\" -lt 3 ]]; then",
                "        exit 1",
                "      fi",
                "      exit 0",
                "      ;;",
                "    ensure-db|check-tables)",
                "      exit 0",
                "      ;;",
                "  esac",
                "fi",
                "exit 0",
            ]
        ),
        encoding="utf-8",
    )
    os.chmod(fake_python, 0o755)

    env = os.environ.copy()
    env.update(
        {
            "RUN_MIGRATIONS": "0",
            "COUNTER_FILE": str(counter_file),
            "PATH": f"{tmp_path}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
