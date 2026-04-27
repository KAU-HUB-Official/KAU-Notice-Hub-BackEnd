import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_incremental_crawl_publish.sh"


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def run_script(tmp_path: Path, final_path: Path, writer_code: str, **env_overrides: str):
    writer = tmp_path / "writer.py"
    writer.write_text(writer_code, encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "NOTICE_JSON_PATH": str(final_path),
            "CRAWLER_COMMAND": f"{sys.executable} {writer}",
            "MIN_RECORDS": "1",
            "MIN_RETAIN_RATIO": "0.5",
        }
    )
    env.update(env_overrides)

    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_crawl_script_replaces_final_file_on_valid_json(tmp_path: Path) -> None:
    final_path = tmp_path / "notices.json"
    write_json(final_path, [{"id": "old"}])

    result = run_script(
        tmp_path,
        final_path,
        """
import json
import os
from pathlib import Path
Path(os.environ["CRAWLER_OUTPUT_PATH"]).write_text(
    json.dumps([{"id": "new"}, {"id": "new-2"}], ensure_ascii=False),
    encoding="utf-8",
)
""",
    )

    assert result.returncode == 0
    assert json.loads(final_path.read_text(encoding="utf-8")) == [
        {"id": "new"},
        {"id": "new-2"},
    ]


def test_crawl_script_keeps_final_file_on_invalid_json(tmp_path: Path) -> None:
    final_path = tmp_path / "notices.json"
    write_json(final_path, [{"id": "old"}])

    result = run_script(
        tmp_path,
        final_path,
        """
import os
from pathlib import Path
Path(os.environ["CRAWLER_OUTPUT_PATH"]).write_text("{ invalid json", encoding="utf-8")
""",
    )

    assert result.returncode != 0
    assert json.loads(final_path.read_text(encoding="utf-8")) == [{"id": "old"}]


def test_crawl_script_blocks_large_record_drop(tmp_path: Path) -> None:
    final_path = tmp_path / "notices.json"
    write_json(final_path, [{"id": str(index)} for index in range(10)])

    result = run_script(
        tmp_path,
        final_path,
        """
import json
import os
from pathlib import Path
Path(os.environ["CRAWLER_OUTPUT_PATH"]).write_text(
    json.dumps([{"id": "only-one"}], ensure_ascii=False),
    encoding="utf-8",
)
""",
    )

    assert result.returncode != 0
    assert len(json.loads(final_path.read_text(encoding="utf-8"))) == 10

