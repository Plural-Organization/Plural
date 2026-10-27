import io
import tarfile
from pathlib import Path

import pytest

from plural.agent.skills import (
    ARCHIVE_URL,
    SkillError,
    SkillLibrary,
    frontmatter,
    parse_package,
)
from plural.agent.tools.base import ToolCtx, ToolError
from plural.agent.tools.skills import SkillInstallTool, SkillTool
from plural.core.policy.engine import Policy, ToolInvocation, evaluate
from plural.core.provenance import direct
from plural.protocol.models import PolicyAction, Role, SkillScope, ToolRisk


def skill_md(name: str, description: str = "Does things.") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\nSteps.\n"


def tarball(files: dict[str, str], *, links: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            bundle.addfile(info)
    return buffer.getvalue()


REPO = tarball(
    {
        "agent-skills-HEAD/README.md": "# repo",
        "agent-skills-HEAD/skills/react-best-practices/SKILL.md": skill_md(
            "vercel-react-best-practices", "React and Next.js performance."
        ),
        "agent-skills-HEAD/skills/react-best-practices/rules/memo.md": "use memo wisely",
        "agent-skills-HEAD/skills/deploy/SKILL.md": skill_md("deploy-to-vercel"),
    },
    links={"agent-skills-HEAD/skills/react-best-practices/secret": "/etc/passwd"},
)


class Web:
    def __init__(self, answers: dict[str, bytes]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, url: str, limit: int) -> bytes:
        self.asked.append(url)
        for prefix, body in self.answers.items():
            if url.startswith(prefix):
                return body
        raise SkillError(f"offline: {url}")


def library(tmp_path: Path, answers: dict[str, bytes] | None = None) -> SkillLibrary:
    return SkillLibrary(project=tmp_path / "ws", home=tmp_path / "home", fetch=Web(answers or {}))


def write_skill(root: Path, folder: str, text: str) -> None:
    (root / folder).mkdir(parents=True)
    (root / folder / "SKILL.md").write_text(text)


@pytest.mark.parametrize(
    ("text", "repo", "skill"),
    [
        (
            "vercel-labs/agent-skills@vercel-react-best-practices",
            "vercel-labs/agent-skills",
            "vercel-react-best-practices",
        ),
        ("vercel-labs/agent-skills/deploy", "vercel-labs/agent-skills", "deploy"),
        ("https://github.com/anthropics/skills.git", "anthropics/skills", None),
    ],
)
def test_packages_accept_the_usual_spellings(text: str, repo: str, skill: str | None) -> None:
    package = parse_package(text)
    assert (package.repo, package.skill) == (repo, skill)


@pytest.mark.parametrize("text", ["nope", "a/b@../x", "../../etc@x", "a/b/c/d"])
def test_bad_packages_are_refused(text: str) -> None:
    with pytest.raises(SkillError):
        parse_package(text)


def test_frontmatter_reads_folded_descriptions() -> None:
    fields = frontmatter("---\nname: tdd\ndescription: >\n  Write the test\n  first.\n---\nbody")
    assert fields == {"name": "tdd", "description": "Write the test first."}
    assert frontmatter("no header") == {}


async def test_project_skills_win_and_half_installed_folders_are_skipped(tmp_path: Path) -> None:
    write_skill(tmp_path / "ws" / ".agents" / "skills", "tdd", skill_md("tdd", "project"))
    write_skill(tmp_path / "home" / ".claude" / "skills", "tdd", skill_md("tdd", "global"))
    write_skill(tmp_path / "home" / ".agents" / "skills", "grill", skill_md("grill"))
    write_skill(tmp_path / "ws" / ".agents" / "skills", ".tdd-x1", skill_md("tdd", "staging"))
    skills = library(tmp_path)
    await skills.refresh()
    found = {(skill.name, skill.description, skill.scope) for skill in skills.skills}
    assert found == {
        ("tdd", "project", SkillScope.PROJECT),
        ("grill", "Does things.", SkillScope.GLOBAL),
    }
    assert "- tdd: project" in skills.describe()


async def test_the_agent_is_told_to_find_a_skill_even_when_none_is_installed(
    tmp_path: Path,
) -> None:
    skills = library(tmp_path)
    await skills.refresh()
    catalog = skills.describe()
    assert "call skill_search first" in catalog
    assert "No skills are installed yet." in catalog


async def test_install_finds_a_skill_by_its_declared_name(tmp_path: Path) -> None:
    url = ARCHIVE_URL.format(repo="vercel-labs/agent-skills")
    skills = library(tmp_path, {url: REPO})
    skill = await skills.install(
        parse_package("vercel-labs/agent-skills@vercel-react-best-practices"), SkillScope.PROJECT
    )
    folder = tmp_path / "ws" / ".agents" / "skills" / "vercel-react-best-practices"
    assert skill.path == folder
    assert (folder / "rules" / "memo.md").read_text() == "use memo wisely"
    assert not (folder / "secret").exists()
    assert [s.name for s in skills.skills] == ["vercel-react-best-practices"]

    global_skill = await skills.install(
        parse_package("vercel-labs/agent-skills@deploy"), SkillScope.GLOBAL
    )
    assert global_skill.path == tmp_path / "home" / ".agents" / "skills" / "deploy-to-vercel"


async def test_install_explains_what_is_in_the_repository(tmp_path: Path) -> None:
    url = ARCHIVE_URL.format(repo="vercel-labs/agent-skills")
    skills = library(tmp_path, {url: REPO})
    with pytest.raises(SkillError, match="deploy-to-vercel, vercel-react-best-practices"):
        await skills.install(parse_package("vercel-labs/agent-skills"), SkillScope.PROJECT)
    with pytest.raises(SkillError, match="no skill named missing"):
        await skills.install(parse_package("vercel-labs/agent-skills@missing"), SkillScope.PROJECT)


async def test_install_refuses_paths_that_escape_the_skill(tmp_path: Path) -> None:
    evil = tarball(
        {
            "r-HEAD/s/SKILL.md": skill_md("evil"),
            "r-HEAD/s/../../../outside.txt": "pwned",
        }
    )
    skills = library(tmp_path, {ARCHIVE_URL.format(repo="o/r"): evil})
    with pytest.raises(SkillError, match="unsafe path"):
        await skills.install(parse_package("o/r@evil"), SkillScope.PROJECT)
    target = tmp_path / "ws" / ".agents" / "skills"
    assert list(target.iterdir()) == []


async def test_search_lists_packages_by_installs(tmp_path: Path) -> None:
    answer = (
        b'{"skills":[{"source":"a/b","skillId":"few","installs":3},'
        b'{"source":"vercel-labs/agent-skills","skillId":"react","name":"react","installs":900}]}'
    )
    skills = library(tmp_path, {"https://skills.sh/api/search": answer})
    hits = await skills.search("react")
    assert [(hit.package, hit.installs) for hit in hits] == [
        ("vercel-labs/agent-skills@react", 900),
        ("a/b@few", 3),
    ]


async def test_skill_files_stay_inside_the_skill(tmp_path: Path) -> None:
    write_skill(tmp_path / "home" / ".agents" / "skills", "tdd", skill_md("tdd"))
    (tmp_path / "home" / ".agents" / "skills" / "tdd" / "example.md").write_text("an example")
    skills = library(tmp_path)
    await skills.refresh()
    tool = SkillTool(skills)
    ctx = ToolCtx(workspace=None, backend=None)  # pyright: ignore[reportArgumentType]

    loaded = await tool.prepare({"name": "tdd"}).execute(ctx)
    assert "# tdd" in loaded.content
    assert "- example.md" in loaded.content
    assert (
        await tool.prepare({"name": "tdd", "file": "example.md"}).execute(ctx)
    ).content == "an example"
    with pytest.raises(ToolError, match="outside"):
        await tool.prepare({"name": "tdd", "file": "../../../.ssh/id_rsa"}).execute(ctx)
    with pytest.raises(ToolError, match="no skill named nope"):
        await tool.prepare({"name": "nope"}).execute(ctx)


async def test_the_install_tool_tells_the_host_about_the_new_skill(tmp_path: Path) -> None:
    url = ARCHIVE_URL.format(repo="vercel-labs/agent-skills")
    skills = library(tmp_path, {url: REPO})
    changed: list[bool] = []
    tool = SkillInstallTool(skills, lambda: changed.append(True))
    ctx = ToolCtx(workspace=None, backend=None)  # pyright: ignore[reportArgumentType]
    prepared = tool.prepare({"package": "vercel-labs/agent-skills@deploy", "scope": "global"})
    assert prepared.risk is ToolRisk.WRITE
    assert prepared.subject == "vercel-labs/agent-skills@deploy (global)"
    result = await prepared.execute(ctx)
    assert "deploy-to-vercel" in result.content
    assert changed == [True]


async def test_remove_only_touches_folders_plural_installs_into(tmp_path: Path) -> None:
    write_skill(tmp_path / "home" / ".agents" / "skills", "mine", skill_md("mine"))
    write_skill(tmp_path / "home" / ".claude" / "skills", "theirs", skill_md("theirs"))
    skills = library(tmp_path)
    await skills.refresh()
    await skills.remove("mine")
    assert not (tmp_path / "home" / ".agents" / "skills" / "mine").exists()
    with pytest.raises(SkillError, match="by hand"):
        await skills.remove("theirs")


def test_loading_and_searching_are_free_installing_asks() -> None:
    host = direct("p_host", Role.HOST)
    policy = Policy()
    load = ToolInvocation(name="skill", risk=ToolRisk.READ, subject="tdd")
    install = ToolInvocation(name="skill_install", risk=ToolRisk.WRITE, subject="a/b@c")
    assert evaluate(policy, load, host).action is PolicyAction.ALLOW
    assert evaluate(policy, install, host).action is PolicyAction.ASK
