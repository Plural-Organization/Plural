import asyncio
import io
import re
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from plural.protocol.models import SkillHit, SkillScope, SkillView
from plural.security.secrets import is_denied_path

SKILL_FILE: Final = "SKILL.md"
INSTALL_DIR: Final = (".agents", "skills")
SEARCH_DIRS: Final = (INSTALL_DIR, (".claude", "skills"), (".plural", "skills"))
SEARCH_URL: Final = "https://skills.sh/api/search"
ARCHIVE_URL: Final = "https://codeload.github.com/{repo}/tar.gz/HEAD"
MAX_ARCHIVE_BYTES: Final = 50 * 1024 * 1024
MAX_SKILL_BYTES: Final = 20 * 1024 * 1024
MAX_SKILL_FILES: Final = 500
MAX_DESCRIPTION: Final = 400
HTTP_TIMEOUT_S: Final = 30.0
NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REPO: Final = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")

Fetch = Callable[[str, int], bytes]


class SkillError(Exception):
    pass


class _Listing(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source: str
    skill_id: str = Field(alias="skillId")
    name: str | None = None
    installs: int | None = None


class _Search(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skills: list[_Listing] = Field(default_factory=list[_Listing])


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    path: Path
    scope: SkillScope

    def view(self) -> SkillView:
        return SkillView(name=self.name, description=self.description, scope=self.scope)


@dataclass(frozen=True, slots=True)
class Package:
    repo: str
    skill: str | None

    def __str__(self) -> str:
        return f"{self.repo}@{self.skill}" if self.skill else self.repo


def parse_package(text: str) -> Package:
    spec = text.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    skill: str | None = None
    if "@" in spec:
        spec, skill = spec.split("@", 1)
    else:
        parts = spec.split("/")
        if len(parts) == 3:
            spec, skill = "/".join(parts[:2]), parts[2]
    if not REPO.match(spec) or (skill is not None and not NAME.match(skill)):
        raise SkillError(f"expected owner/repo@skill, got {text!r}")
    return Package(repo=spec, skill=skill)


def frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    key: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if key is not None and (line.startswith((" ", "\t")) or not line.strip()):
            fields[key] = f"{fields[key]} {line.strip()}".strip()
            continue
        name, colon, value = line.partition(":")
        if not colon or name.startswith((" ", "\t")):
            key = None
            continue
        key = name.strip()
        value = value.strip()
        fields[key] = "" if value in {">", "|", ">-", "|-"} else value.strip("'\"")
    return fields


def read_skill(directory: Path, scope: SkillScope) -> Skill | None:
    try:
        text = (directory / SKILL_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields = frontmatter(text)
    name = fields.get("name") or directory.name
    if not NAME.match(name):
        return None
    description = " ".join(fields.get("description", "").split())
    if len(description) > MAX_DESCRIPTION:
        description = f"{description[: MAX_DESCRIPTION - 1]}…"
    return Skill(name=name, description=description, path=directory, scope=scope)


class SkillLibrary:
    def __init__(self, *, project: Path, home: Path, fetch: Fetch | None = None) -> None:
        self._roots = (
            *((project.joinpath(*parts), SkillScope.PROJECT) for parts in SEARCH_DIRS),
            *((home.joinpath(*parts), SkillScope.GLOBAL) for parts in SEARCH_DIRS),
        )
        self._targets = {
            SkillScope.PROJECT: project.joinpath(*INSTALL_DIR),
            SkillScope.GLOBAL: home.joinpath(*INSTALL_DIR),
        }
        self._fetch = fetch or _fetch
        self._skills: tuple[Skill, ...] = ()

    @property
    def skills(self) -> tuple[Skill, ...]:
        return self._skills

    def get(self, name: str) -> Skill | None:
        return next((skill for skill in self._skills if skill.name == name), None)

    def views(self) -> tuple[SkillView, ...]:
        return tuple(skill.view() for skill in self._skills)

    async def refresh(self) -> tuple[Skill, ...]:
        self._skills = await asyncio.to_thread(self._scan)
        return self._skills

    def describe(self) -> str:
        installed = [
            f"- {skill.name}: {skill.description or '(no description)'}" for skill in self._skills
        ]
        return "\n".join(
            (
                "# Skills",
                "Skills are folders of expert instructions for one kind of task. Pick them by "
                "description, the way you pick a tool:",
                "- When a task matches an installed skill, call the skill tool with its name "
                "before you start and follow what it says, loading its other files when it "
                "points to them.",
                "- When a task needs specialist know-how that no installed skill covers, such as "
                "a file format (pdf, docx, xlsx, pptx), a framework's conventions or a deploy "
                "target, call skill_search first. Prefer a well-known source with many installs "
                "that matches the task closely, say in one line which one you chose and why, "
                "install it with skill_install (the host approves it) and then load it.",
                "- Do not search or install for small tasks you can already do well, and never "
                "install a skill the room did not need.",
                "Installed skills:" if installed else "No skills are installed yet.",
                *installed,
            )
        )

    def file(self, name: str, relative: str) -> Path:
        skill = self.get(name)
        if skill is None:
            raise SkillError(f"no skill named {name}; installed: {self._names()}")
        root = skill.path.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise SkillError(f"{relative} is outside the {name} skill")
        if is_denied_path(path):
            raise SkillError(f"{relative} looks like a secret file")
        return path

    async def search(self, query: str, *, limit: int = 10) -> tuple[SkillHit, ...]:
        url = f"{SEARCH_URL}?{urllib.parse.urlencode({'q': query, 'limit': limit})}"
        raw = await asyncio.to_thread(self._fetch, url, 1024 * 1024)
        try:
            found = _Search.model_validate_json(raw).skills
        except ValidationError as error:
            raise SkillError("skills.sh returned an unexpected answer") from error
        hits = [
            SkillHit(
                package=f"{item.source}@{item.skill_id}",
                name=item.name or item.skill_id,
                installs=item.installs or 0,
            )
            for item in found
        ]
        return tuple(sorted(hits, key=lambda hit: -hit.installs)[:limit])

    async def install(self, package: Package, scope: SkillScope) -> Skill:
        url = ARCHIVE_URL.format(repo=package.repo)
        archive = await asyncio.to_thread(self._fetch, url, MAX_ARCHIVE_BYTES)
        target = self._targets[scope]
        installed = await asyncio.to_thread(_unpack, archive, package, target)
        await self.refresh()
        return read_skill(installed, scope) or Skill(
            name=installed.name, description="", path=installed, scope=scope
        )

    async def remove(self, name: str) -> Skill:
        skill = self.get(name)
        if skill is None:
            raise SkillError(f"no skill named {name}; installed: {self._names()}")
        if skill.path.parent not in self._targets.values():
            raise SkillError(f"{name} lives in {skill.path.parent}; remove it there by hand")
        await asyncio.to_thread(shutil.rmtree, skill.path)
        await self.refresh()
        return skill

    def _names(self) -> str:
        return ", ".join(skill.name for skill in self._skills) or "none"

    def _scan(self) -> tuple[Skill, ...]:
        found: dict[str, Skill] = {}
        for root, scope in self._roots:
            try:
                children = sorted(
                    child
                    for child in root.iterdir()
                    if child.is_dir() and not child.name.startswith(".")
                )
            except OSError:
                continue
            for child in children:
                skill = read_skill(child, scope)
                if skill is not None and skill.name not in found:
                    found[skill.name] = skill
        return tuple(found.values())


def _fetch(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "plural-agent"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            data = response.read(limit + 1)
    except OSError as error:
        raise SkillError(f"could not reach {urllib.parse.urlsplit(url).netloc}: {error}") from error
    if len(data) > limit:
        raise SkillError(f"{url} is larger than {limit // (1024 * 1024)} MB")
    return data


def _unpack(archive: bytes, package: Package, target: Path) -> Path:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            return _extract(bundle, package, target)
    except tarfile.TarError as error:
        raise SkillError(f"{package.repo} is not a readable repository archive") from error


def _extract(bundle: tarfile.TarFile, package: Package, target: Path) -> Path:
    members = bundle.getmembers()
    directory = _locate(bundle, members, package)
    files = [
        (member, PurePosixPath(member.name).relative_to(directory))
        for member in members
        if member.isfile() and PurePosixPath(member.name).is_relative_to(directory)
    ]
    if len(files) > MAX_SKILL_FILES:
        raise SkillError(f"the skill has more than {MAX_SKILL_FILES} files")
    if sum(member.size for member, _ in files) > MAX_SKILL_BYTES:
        raise SkillError("the skill is larger than 20 MB")
    name = _skill_name(bundle, directory)
    target.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=target))
    try:
        for member, relative in files:
            if ".." in relative.parts or relative.is_absolute():
                raise SkillError(f"unsafe path in the archive: {member.name}")
            source = bundle.extractfile(member)
            if source is None:
                continue
            destination = staging.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read())
        final = target / name
        if final.exists():
            shutil.rmtree(final)
        staging.rename(final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final


def _locate(
    bundle: tarfile.TarFile, members: Sequence[tarfile.TarInfo], package: Package
) -> PurePosixPath:
    candidates = [
        PurePosixPath(member.name).parent
        for member in members
        if member.isfile() and PurePosixPath(member.name).name == SKILL_FILE
    ]
    if package.skill is None:
        if len(candidates) == 1:
            return candidates[0]
        names = sorted(_skill_name(bundle, candidate) for candidate in candidates)
        raise SkillError(
            f"{package.repo} has {len(candidates)} skills, pick one with @name: "
            f"{', '.join(names) or 'none'}"
        )
    for candidate in candidates:
        if package.skill in {_skill_name(bundle, candidate), candidate.name}:
            return candidate
    raise SkillError(f"{package.repo} has no skill named {package.skill}")


def _skill_name(bundle: tarfile.TarFile, directory: PurePosixPath) -> str:
    member = bundle.extractfile(str(directory / SKILL_FILE))
    text = member.read(64 * 1024).decode(errors="replace") if member is not None else ""
    name = frontmatter(text).get("name") or directory.name
    if not NAME.match(name):
        raise SkillError(f"the skill in {directory} has an invalid name {name!r}")
    return name
