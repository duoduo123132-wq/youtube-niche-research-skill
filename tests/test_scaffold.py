from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1] / "skills" / "youtube-niche-research"


def test_skill_scaffold_exists():
    assert (SKILL_ROOT / "SKILL.md").is_file()
    assert (SKILL_ROOT / "agents" / "openai.yaml").is_file()
    assert (SKILL_ROOT / "scripts").is_dir()
    assert (SKILL_ROOT / "references").is_dir()
    assert (SKILL_ROOT / "scripts" / ".gitkeep").is_file()
    assert (SKILL_ROOT / "references" / ".gitkeep").is_file()
