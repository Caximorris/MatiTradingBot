import json
from pathlib import Path

from tools.context_pack import PACKS, build_pack
from tools.instruction_budget import violations


ROOT = Path(__file__).resolve().parents[1]


def test_context_packs_are_bounded_and_reference_existing_files() -> None:
    for name in PACKS:
        pack = build_pack(name)
        assert len(pack["files"]) <= 8
        assert len(pack["tests"]) <= 4
        assert len(pack["commands"]) <= 3
        assert all((ROOT / relative).is_file() for relative in pack["files"] + pack["tests"])


def test_instruction_budget_accepts_current_repository() -> None:
    assert violations() == []


def test_instruction_budget_reports_excessive_file(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("one\ntwo\n", encoding="utf-8")
    (tmp_path / "SESSION.md").write_text("one\n", encoding="utf-8")
    skills = tmp_path / ".codex" / "skills" / "example"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("one\n", encoding="utf-8")
    config = tmp_path / "budget.json"
    config.write_text(json.dumps({"files": {"AGENTS.md": 1, "SESSION.md": 1}, "skill_max_lines": 1, "skill_total_lines": 1}), encoding="utf-8")
    assert violations(tmp_path, config) == ["AGENTS.md: 2 lines exceeds 1"]
