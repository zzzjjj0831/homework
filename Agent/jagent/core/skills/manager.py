import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml


SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SKILL_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


@dataclass
class Skill:
    name: str
    description: str
    path: Path

    @property
    def skill_file(self) -> Path:
        return self.path / "SKILL.md"


class SkillManager:
    def __init__(
        self,
        project_root: Optional[Path] = None,
        skills_dir: Optional[Path] = None,
        max_name_length: int = MAX_SKILL_NAME_LENGTH,
        max_description_length: int = MAX_DESCRIPTION_LENGTH,
    ):
        self.project_root = (
            Path(project_root) if project_root else Path.cwd()
        ).expanduser().resolve()
        self.skills_dir = (
            Path(skills_dir).expanduser().resolve()
            if skills_dir is not None
            else self.project_root / ".agents" / "skills"
        )
        self.max_name_length = max(1, int(max_name_length))
        self.max_description_length = max(1, int(max_description_length))
        self.skills: Dict[str, Skill] = {}
        self.discover()

    def discover(self) -> None:
        self.skills = {}
        if not self.skills_dir.is_dir():
            return
        for child in sorted(self.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            metadata = self._read_frontmatter(skill_file)
            name = metadata.get("name")
            description = metadata.get("description")
            if not isinstance(name, str) or not isinstance(description, str):
                continue
            name = name.strip()
            description = " ".join(description.split())
            if not name or not description:
                continue
            self.skills.setdefault(
                name,
                Skill(name=name, description=description, path=child.resolve()),
            )

    def get_skills(self) -> List[Skill]:
        return list(self.skills.values())

    def load_skill(self, name: str, filename: Optional[str] = None) -> str:
        name = (name or "").strip()
        skill = self.skills.get(name)
        if skill is None:
            return self._error(
                f"skill not found: {name}",
                available=[item.name for item in self.skills.values()],
            )
        if filename is None or not filename.strip():
            return self._read_skill_file(skill)
        return self._read_attachment(skill, filename.strip())

    def create_skill(self, name: str, skill_context: str) -> str:
        skill_name = self._normalize_skill_name(name)
        if not skill_name or not SKILL_NAME_PATTERN.fullmatch(skill_name):
            return self._error(
                "invalid skill name: use lowercase letters, numbers and hyphens, e.g. my-skill",
                name=name,
            )
        if len(skill_name) > self.max_name_length:
            return self._error(
                f"skill name is too long (max {self.max_name_length} characters)",
                name=skill_name,
            )
        if not isinstance(skill_context, str) or not skill_context.strip():
            return self._error("skillContext 不能为空", name=skill_name)

        target_dir = self.skills_dir / skill_name
        existing = self.skills.get(skill_name)
        if existing is not None:
            return self._error(
                f"skill already exists: {skill_name}",
                name=skill_name,
                path=str(existing.path),
            )
        if target_dir.exists():
            return self._error(
                f"skill already exists: {skill_name}",
                name=skill_name,
                path=str(target_dir.resolve()),
            )

        try:
            metadata, body = self._parse_skill_context(skill_context)
        except (yaml.YAMLError, ValueError) as e:
            return self._error(f"invalid YAML frontmatter in skillContext: {e}", name=skill_name)

        body = body.strip("\r\n")
        if not body.strip():
            return self._error("skillContext 必须包含 SKILL.md 正文内容", name=skill_name)

        description = self._extract_description(metadata.get("description"), body)
        if not description:
            return self._error("skillContext 缺少 description，且无法从正文推导", name=skill_name)

        frontmatter: Dict[str, object] = {"name": skill_name, "description": description}
        for key, value in metadata.items():
            if key not in ("name", "description"):
                frontmatter[key] = value

        try:
            yaml_text = yaml.safe_dump(
                frontmatter,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=4096,
            ).strip()
        except yaml.YAMLError as e:
            return self._error(f"failed to generate YAML frontmatter: {e}", name=skill_name)

        content = f"---\n{yaml_text}\n---\n\n{body}\n"
        skill_file = target_dir / "SKILL.md"
        try:
            target_dir.mkdir(parents=True, exist_ok=False)
            skill_file.write_text(content, encoding="utf-8")
        except FileExistsError:
            return self._error(
                f"skill already exists: {skill_name}",
                name=skill_name,
                path=str(target_dir.resolve()),
            )
        except OSError as e:
            return self._error(f"failed to create skill: {e}", name=skill_name)

        self.discover()
        return json.dumps(
            {
                "created": True,
                "name": skill_name,
                "description": description,
                "path": str(skill_file.resolve()),
                "skill_dir": str(target_dir.resolve()),
            },
            ensure_ascii=False,
        )

    def _normalize_skill_name(self, name: str) -> str:
        if not isinstance(name, str):
            return ""
        raw = name.strip()
        if "/" in raw or "\\" in raw or ".." in raw:
            return ""
        slug = raw.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return re.sub(r"-{2,}", "-", slug).strip("-")

    def _parse_skill_context(self, text: str):
        text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            return {}, text
        end = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end = index
                break
        if end is None:
            return {}, text
        metadata = yaml.safe_load("".join(lines[1:end]))
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("frontmatter must be a YAML mapping")
        return metadata, "".join(lines[end + 1:])

    def _extract_description(self, description: object, body: str) -> str:
        if isinstance(description, str):
            normalized = " ".join(description.split())
            if normalized:
                return normalized[: self.max_description_length].rstrip()
        for line in body.splitlines():
            candidate = line.strip().lstrip("#").strip()
            if candidate:
                return candidate[: self.max_description_length].rstrip()
        return ""

    def _read_skill_file(self, skill: Skill) -> str:
        path = skill.skill_file
        if not path.is_file():
            return self._error(f"SKILL.md not found for skill: {skill.name}")
        content = self._read_text(path)
        if content is None:
            return self._error(f"failed to read file as utf-8 text: {path}")
        return json.dumps(
            {"skill": skill.name, "path": str(path), "content": content},
            ensure_ascii=False,
        )

    def _read_attachment(self, skill: Skill, filename: str) -> str:
        exact_candidates = self._exact_candidates(skill, filename)
        outside_candidates = []
        for candidate in exact_candidates:
            if not self._is_within(candidate, skill.path):
                if candidate.exists():
                    outside_candidates.append(candidate)
                continue
            if candidate.is_file():
                return self._file_result(skill, candidate)
            if candidate.exists():
                return self._error(f"not a file: {candidate}")

        if outside_candidates:
            return self._error(
                "file path is outside the skill directory",
                candidates=[str(path) for path in outside_candidates],
            )

        if self._is_basename(filename):
            matches = self._search_by_name(skill, filename)
            if len(matches) == 1:
                return self._file_result(skill, matches[0])
            if len(matches) > 1:
                return self._error(
                    "multiple files matched, please provide a more specific path",
                    skill=skill.name,
                    candidates=[path.relative_to(skill.path).as_posix() for path in matches],
                )

        return self._error(
            f"file not found in skill directory: {filename}",
            skill=skill.name,
        )

    def _exact_candidates(self, skill: Skill, filename: str) -> List[Path]:
        raw = Path(filename).expanduser()
        if raw.is_absolute():
            candidates = [raw]
        else:
            candidates = [skill.path / raw, self.project_root / raw]

        results = []
        seen = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            key = str(resolved).lower() if os.name == "nt" else str(resolved)
            if key not in seen:
                seen.add(key)
                results.append(resolved)
        return results

    def _search_by_name(self, skill: Skill, filename: str) -> List[Path]:
        target = filename.lower()
        matches = []
        for path in skill.path.rglob("*"):
            if path.is_file() and path.name.lower() == target:
                resolved = path.resolve()
                if self._is_within(resolved, skill.path):
                    matches.append(resolved)
        return sorted(matches)

    def _file_result(self, skill: Skill, path: Path) -> str:
        content = self._read_text(path)
        if content is None:
            return self._error(f"failed to read file as utf-8 text: {path}")
        return json.dumps(
            {
                "skill": skill.name,
                "path": str(path),
                "relative_path": path.relative_to(skill.path).as_posix(),
                "content": content,
            },
            ensure_ascii=False,
        )

    def _read_frontmatter(self, path: Path) -> Dict[str, object]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
                if first_line.lstrip("\ufeff").strip() != "---":
                    return {}
                lines = []
                for line in handle:
                    if line.strip() == "---":
                        break
                    lines.append(line.rstrip("\r\n"))
                else:
                    return {}
        except (OSError, UnicodeError):
            return {}
        try:
            metadata = yaml.safe_load("\n".join(lines))
        except yaml.YAMLError:
            return {}
        return metadata if isinstance(metadata, dict) else {}

    def _read_text(self, path: Path) -> Optional[str]:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None

    def _is_within(self, path: Path, directory: Path) -> bool:
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False

    def _is_basename(self, filename: str) -> bool:
        return "/" not in filename and "\\" not in filename

    def _error(self, message: str, **extra: object) -> str:
        data = {"error": message}
        data.update(extra)
        return json.dumps(data, ensure_ascii=False)
