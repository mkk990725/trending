from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Iterable
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


TRENDING_URL = "https://github.com/trending"
GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_MODEL = "openai/gpt-4.1"
PERIODS = ("weekly", "monthly")
PERIOD_LABELS = {"weekly": "每周榜", "monthly": "每月榜"}
DEFAULT_STATE_PATH = Path("data/state.json")


@dataclass(frozen=True)
class Repository:
    name: str
    url: str
    description: str


def parse_trending(html: str, limit: int = 3) -> list[Repository]:
    soup = BeautifulSoup(html, "html.parser")
    repositories: list[Repository] = []

    for article in soup.select("article.Box-row"):
        link = article.select_one("h2 a[href]")
        if link is None:
            continue

        path = link.get("href", "").strip()
        parts = [part for part in path.split("/") if part]
        if len(parts) != 2:
            continue

        name = "/".join(parts)
        description_node = article.find("p")
        description = (
            description_node.get_text(" ", strip=True)
            if description_node is not None
            else "暂无项目简介"
        )
        repositories.append(
            Repository(
                name=name,
                url=f"https://github.com/{name}",
                description=description,
            )
        )
        if len(repositories) == limit:
            break

    if len(repositories) < limit:
        raise RuntimeError(
            f"GitHub Trending 页面只解析到 {len(repositories)} 个项目，预期至少 {limit} 个"
        )
    return repositories


def fetch_trending(period: str, session: requests.Session | None = None) -> list[Repository]:
    if period not in PERIODS:
        raise ValueError(f"不支持的榜单周期: {period}")

    client = session or requests.Session()
    response = client.get(
        TRENDING_URL,
        params={"since": period},
        headers={
            "User-Agent": "github-trending-wechat-notifier/1.0",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        timeout=30,
    )
    response.raise_for_status()
    return parse_trending(response.text)


def load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"date": None, "weekly": [], "monthly": []}
    with path.open("r", encoding="utf-8") as state_file:
        state = json.load(state_file)
    return {
        "date": state.get("date"),
        "weekly": state.get("weekly", []),
        "monthly": state.get("monthly", []),
    }


def previous_names(state: dict[str, object]) -> set[str]:
    names: set[str] = set()
    for period in PERIODS:
        entries = state.get(period, [])
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, str):
                    names.add(entry)
                elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
                    names.add(entry["name"])
    return names


def find_new_repositories(
    current: dict[str, list[Repository]], state: dict[str, object]
) -> dict[str, list[Repository]]:
    seen_yesterday = previous_names(state)
    return {
        period: [repo for repo in current[period] if repo.name not in seen_yesterday]
        for period in PERIODS
    }


def summarize_in_chinese(
    repositories_by_period: dict[str, list[Repository]],
    github_token: str | None,
    session: requests.Session | None = None,
) -> dict[str, list[Repository]]:
    if not github_token:
        return repositories_by_period

    unique_repositories = {
        repository.name: repository
        for repositories in repositories_by_period.values()
        for repository in repositories
    }
    if not unique_repositories:
        return repositories_by_period

    projects = [
        {"name": repository.name, "description": repository.description}
        for repository in unique_repositories.values()
    ]
    client = session or requests.Session()

    try:
        response = client.post(
            GITHUB_MODELS_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {github_token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            json={
                "model": GITHUB_MODEL,
                "temperature": 0.2,
                "max_tokens": 600,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是中文开源项目编辑。根据项目名称和原始简介，用一句不超过50个汉字的中文"
                            "说明准确概括每个项目的用途，保留必要的产品名，不使用营销套话。"
                            "只输出JSON对象，键必须是项目name，值是中文说明。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(projects, ensure_ascii=False),
                    },
                ],
            },
            timeout=45,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        summaries = json.loads(content)
        if not isinstance(summaries, dict):
            raise ValueError("模型返回结果不是 JSON 对象")
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as error:
        print(f"中文总结生成失败，使用原始项目简介: {error}")
        return repositories_by_period

    return {
        period: [
            Repository(
                name=repository.name,
                url=repository.url,
                description=(
                    summaries.get(repository.name, repository.description).strip()
                    if isinstance(summaries.get(repository.name, repository.description), str)
                    else repository.description
                ),
            )
            for repository in repositories_by_period[period]
        ]
        for period in PERIODS
    }


def format_message(new_repositories: dict[str, list[Repository]]) -> str:
    sections: list[str] = []
    for period in PERIODS:
        repositories = new_repositories[period]
        if not repositories:
            continue
        lines = [f"## {PERIOD_LABELS[period]}新入选"]
        for repo in repositories:
            lines.extend(
                [
                    f"### [{repo.name}]({repo.url})",
                    repo.description,
                ]
            )
        sections.append("\n\n".join(lines))
    return "\n\n---\n\n".join(sections)


def serverchan_endpoint(sendkey: str) -> str:
    if sendkey.startswith("SCT"):
        return f"https://sctapi.ftqq.com/{sendkey}.send"
    match = re.fullmatch(r"sctp(\d+)t.+", sendkey)
    if match:
        return f"https://{match.group(1)}.push.ft07.com/send/{sendkey}.send"
    raise ValueError("SERVERCHAN_SENDKEY 格式无效，应以 SCT 或 sctp 开头")


def push_to_wechat(sendkey: str, message: str) -> None:
    response = requests.post(
        serverchan_endpoint(sendkey),
        data={"title": "GitHub 趋势新项目", "desp": message},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Server酱推送失败: {result.get('message', '未知错误')}")


def save_state(path: Path, current: dict[str, list[Repository]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        **{
            period: [asdict(repository) for repository in current[period]]
            for period in PERIODS
        },
    }
    temporary_path = path.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, ensure_ascii=False, indent=2)
        state_file.write("\n")
    temporary_path.replace(path)


def has_repositories(groups: Iterable[list[Repository]]) -> bool:
    return any(groups)


def run(state_path: Path, dry_run: bool = False) -> None:
    current = {period: fetch_trending(period) for period in PERIODS}
    state = load_state(state_path)
    new_repositories = find_new_repositories(current, state)

    if has_repositories(new_repositories.values()):
        new_repositories = summarize_in_chinese(
            new_repositories, os.environ.get("GITHUB_TOKEN")
        )
        message = format_message(new_repositories)
        if dry_run:
            print(message)
            return
        sendkey = os.environ.get("SERVERCHAN_SENDKEY")
        if not sendkey:
            raise RuntimeError("发现新项目，但未配置环境变量 SERVERCHAN_SENDKEY")
        push_to_wechat(sendkey, message)
        print("已将新入选项目推送到微信")
    else:
        print("今日榜单与前一次记录重复，不推送")

    save_state(state_path, current)


def main() -> None:
    parser = argparse.ArgumentParser(description="推送 GitHub 周榜/月榜新入选项目前三名")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--dry-run", action="store_true", help="只打印消息，不推送或更新状态")
    args = parser.parse_args()
    run(args.state, args.dry_run)


if __name__ == "__main__":
    main()
