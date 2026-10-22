#!/usr/bin/env python3
"""
convert_to_arcane.py
Converts Portainer templates.json into an Arcane-compliant template registry (registry.json)
matching Arcane's official schema (https://registry.getarcane.app/schema.json).
Generates compose.yaml and .env.example for container templates so that ALL templates
can be deployed directly through Arcane.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_REPO_URL = "https://github.com/jojirokuNet/portainer-templates"
DEFAULT_RAW_BASE = "https://raw.githubusercontent.com/jojirokuNet/portainer-templates/main"
DEFAULT_ENV_URL = f"{DEFAULT_RAW_BASE}/.env.example"


def clean_id(name_str: str) -> str:
    s = re.sub(r"[^a-z0-9-]", "-", str(name_str).lower().strip())
    s = re.sub(r"-+", "-", s)
    return s.strip("-") or "template"


def clean_tag(tag_str: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9-]", "-", str(tag_str).strip())
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def get_raw_compose_url(repo_url: str | None, stackfile: str | None) -> str | None:
    if not repo_url or not stackfile:
        return None
    repo_url = str(repo_url).strip().rstrip("/")
    stackfile = str(stackfile).strip().lstrip("./")

    if "raw.githubusercontent.com" in repo_url:
        return f"{repo_url}/{stackfile}"

    if "github.com" in repo_url:
        clean = repo_url.replace("https://github.com/", "").replace("http://github.com/", "")
        parts = clean.split("/")
        if len(parts) >= 2:
            owner = parts[0]
            repo = parts[1].removesuffix(".git")
            return f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{stackfile}"

    if "gitlab.com" in repo_url:
        clean = repo_url.replace("https://gitlab.com/", "").replace("http://gitlab.com/", "")
        parts = clean.split("/")
        if len(parts) >= 2:
            repo_path = "/".join(parts).removesuffix(".git")
            return f"https://gitlab.com/{repo_path}/-/raw/HEAD/{stackfile}"

    return None


def generate_compose_for_container(template: dict, template_id: str) -> str:
    service_name = re.sub(r"[^a-zA-Z0-9_-]", "", template_id) or "app"
    lines = [
        "services:",
        f"  {service_name}:",
        f"    image: {template.get('image', 'scratch')}",
        "    restart: unless-stopped",
    ]

    platform = template.get("platform")
    if platform:
        lines.append(f"    platform: \"{platform}\"")

    ports = template.get("ports", [])
    if ports:
        lines.append("    ports:")
        for p in ports:
            p_str = str(p).lstrip(":")
            lines.append(f"      - \"{p_str}\"")

    volumes = template.get("volumes", [])
    if volumes:
        lines.append("    volumes:")
        for v in volumes:
            if not isinstance(v, dict):
                continue
            container_path = v.get("container")
            bind_path = v.get("bind")
            if not container_path:
                continue
            if bind_path:
                lines.append(f"      - \"{bind_path}:{container_path}\"")
            else:
                lines.append(f"      - \"{container_path}\"")

    envs = template.get("env", [])
    if envs:
        lines.append("    environment:")
        for e in envs:
            if isinstance(e, dict):
                name = e.get("name")
                default = e.get("default", e.get("set", ""))
                if name:
                    val_str = str(default).replace("\n", " ")
                    lines.append(f"      - {name}=${{{name}:-{val_str}}}")
            elif isinstance(e, str) and "=" in e:
                name, val = e.split("=", 1)
                lines.append(f"      - {name}=${{{name}:-{val}}}")

    labels = template.get("labels", [])
    if labels:
        lines.append("    labels:")
        for l in labels:
            if isinstance(l, dict) and l.get("name") and l.get("value"):
                lines.append(f"      - \"{l['name']}={l['value']}\"")

    return "\n".join(lines) + "\n"


def generate_env_for_template(template: dict) -> str:
    lines = [
        "# Environment configuration for Arcane",
        "# Review and adjust values before deploying.",
        "",
    ]
    envs = template.get("env", [])
    for e in envs:
        if isinstance(e, dict):
            name = e.get("name")
            default = e.get("default", e.get("set", ""))
            desc = e.get("label") or e.get("description")
            if name:
                if desc:
                    lines.append(f"# {desc}")
                lines.append(f"{name}={default}")
        elif isinstance(e, str) and "=" in e:
            lines.append(e)
    return "\n".join(lines) + "\n"


def convert_templates(
    templates_path: str = "templates.json",
    output_registry_path: str = "registry.json",
    compose_dir: str = "compose",
    raw_base_url: str = DEFAULT_RAW_BASE,
    repo_url: str = DEFAULT_REPO_URL,
    author: str = "jojirokuNet",
) -> dict:
    with open(templates_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    templates_list = data.get("templates", [])
    arcane_templates = []
    seen_ids: set[str] = set()

    compose_path = Path(compose_dir)
    compose_path.mkdir(parents=True, exist_ok=True)

    for item in templates_list:
        tmpl_type = item.get("type", 1)
        repo_info = item.get("repository") if isinstance(item.get("repository"), dict) else None

        raw_id = item.get("name") or item.get("title") or "template"
        template_id = clean_id(raw_id)
        if not template_id:
            template_id = f"template-{item.get('id', len(arcane_templates) + 1)}"

        # Unique ID collision handling
        original_id = template_id
        count = 1
        while template_id in seen_ids:
            template_id = f"{original_id}-{count}"
            count += 1
        seen_ids.add(template_id)

        title = str(item.get("title") or item.get("name") or template_id).strip()
        description = str(item.get("description") or f"Docker Compose template for {title}").strip()
        if not description:
            description = f"Docker Compose template for {title}"

        # Clean tags with uniqueness & regex check
        raw_categories = item.get("categories") or ["utilities"]
        tags: list[str] = []
        for c in raw_categories:
            ct = clean_tag(c)
            if ct and ct not in tags:
                tags.append(ct)
        if not tags:
            tags = ["utilities"]

        maintainer = str(item.get("maintainer") or author).strip() or author

        # Determine compose_url and env_url
        compose_url = None
        env_url = None
        doc_url = None

        if tmpl_type in (2, 3) and repo_info:
            upstream_repo = repo_info.get("url")
            stackfile = repo_info.get("stackfile")
            compose_url = get_raw_compose_url(upstream_repo, stackfile)
            doc_url = upstream_repo or repo_url
            env_url = DEFAULT_ENV_URL
        elif item.get("image"):
            # Generate single container compose file
            td = compose_path / template_id
            td.mkdir(parents=True, exist_ok=True)

            compose_content = generate_compose_for_container(item, template_id)
            env_content = generate_env_for_template(item)

            (td / "docker-compose.yml").write_text(compose_content, encoding="utf-8")
            (td / "compose.yaml").write_text(compose_content, encoding="utf-8")
            (td / ".env.example").write_text(env_content, encoding="utf-8")

            compose_url = f"{raw_base_url}/{compose_dir}/{template_id}/docker-compose.yml"
            env_url = f"{raw_base_url}/{compose_dir}/{template_id}/.env.example"
            doc_url = repo_url
        elif repo_info:
            upstream_repo = repo_info.get("url")
            stackfile = repo_info.get("stackfile")
            compose_url = get_raw_compose_url(upstream_repo, stackfile)
            doc_url = upstream_repo or repo_url
            env_url = DEFAULT_ENV_URL

        if not compose_url:
            continue

        if not doc_url or not doc_url.startswith("http"):
            doc_url = repo_url

        if not env_url or not env_url.startswith("http"):
            env_url = DEFAULT_ENV_URL

        # Hash computed from compose_url + title
        content_hash = hashlib.sha256(f"{compose_url}:{title}:{template_id}".encode("utf-8")).hexdigest()

        template_entry = {
            "id": template_id,
            "name": title,
            "description": description,
            "version": "1.0.0",
            "author": maintainer,
            "compose_url": compose_url,
            "env_url": env_url,
            "documentation_url": doc_url,
            "content_hash": content_hash,
            "tags": tags,
        }

        # Optional icon_url if valid URI
        logo = item.get("logo")
        if isinstance(logo, str) and (logo.startswith("http://") or logo.startswith("https://")):
            template_entry["icon_url"] = logo

        arcane_templates.append(template_entry)

    registry = {
        "$schema": "https://registry.getarcane.app/schema.json",
        "name": "Portainer Stacks for Arcane",
        "description": "500+ Docker Compose templates converted from jojirokuNet/portainer-templates for Arcane",
        "version": "1.0.0",
        "author": author,
        "url": repo_url,
        "templates": arcane_templates,
    }

    with open(output_registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Successfully converted {len(arcane_templates)} templates into {output_registry_path}")
    return registry


def main():
    parser = argparse.ArgumentParser(description="Convert Portainer templates.json to Arcane registry.json")
    parser.add_argument("--templates", default="templates.json", help="Path to templates.json")
    parser.add_argument("--output", default="registry.json", help="Path to output registry.json")
    parser.add_argument("--compose-dir", default="compose", help="Directory for generated compose files")
    parser.add_argument("--raw-base", default=DEFAULT_RAW_BASE, help="Raw GitHub base URL")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="GitHub repository URL")
    parser.add_argument("--author", default="jojirokuNet", help="Registry author")

    args = parser.parse_args()
    convert_templates(
        templates_path=args.templates,
        output_registry_path=args.output,
        compose_dir=args.compose_dir,
        raw_base_url=args.raw_base,
        repo_url=args.repo_url,
        author=args.author,
    )


if __name__ == "__main__":
    main()
