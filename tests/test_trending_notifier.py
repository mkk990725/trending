import unittest
from unittest.mock import Mock

from trending_notifier import (
    Repository,
    find_new_repositories,
    format_message,
    parse_trending,
    serverchan_endpoint,
    summarize_in_chinese,
)


def article(name: str, description: str) -> str:
    return f"""
    <article class="Box-row">
      <h2><a href="/{name}">{name}</a></h2>
      <p class="col-9 color-fg-muted">{description}</p>
    </article>
    """


class TrendingNotifierTests(unittest.TestCase):
    def test_parse_trending_returns_only_first_three(self) -> None:
        html = "".join(
            article(f"owner/repo-{number}", f"Description {number}")
            for number in range(1, 5)
        )

        repositories = parse_trending(html)

        self.assertEqual([repo.name for repo in repositories], [
            "owner/repo-1",
            "owner/repo-2",
            "owner/repo-3",
        ])
        self.assertEqual(repositories[0].description, "Description 1")

    def test_dedupes_against_union_of_previous_weekly_and_monthly_lists(self) -> None:
        old_weekly = Repository("owner/old-weekly", "https://example.com/1", "old")
        old_monthly = Repository("owner/old-monthly", "https://example.com/2", "old")
        new_repo = Repository("owner/new", "https://example.com/3", "new")
        current = {
            "weekly": [old_monthly, new_repo],
            "monthly": [old_weekly, new_repo],
        }
        state = {
            "weekly": [{"name": old_weekly.name}],
            "monthly": [{"name": old_monthly.name}],
        }

        result = find_new_repositories(current, state)

        self.assertEqual(result, {"weekly": [new_repo], "monthly": [new_repo]})

    def test_message_omits_period_without_new_repositories(self) -> None:
        repo = Repository("owner/new", "https://github.com/owner/new", "A useful tool")

        message = format_message({"weekly": [repo], "monthly": []})

        self.assertIn("每周榜新入选", message)
        self.assertIn("A useful tool", message)
        self.assertNotIn("每月榜", message)

    def test_summarizes_new_repositories_in_chinese_with_one_model_call(self) -> None:
        repo = Repository("owner/new", "https://github.com/owner/new", "A useful tool")
        response = Mock()
        response.json.return_value = {
            "choices": [
                {"message": {"content": '{"owner/new":"一个实用的开发工具。"}'}}
            ]
        }
        session = Mock()
        session.post.return_value = response

        result = summarize_in_chinese(
            {"weekly": [repo], "monthly": [repo]}, "github-token", session
        )

        self.assertEqual(result["weekly"][0].description, "一个实用的开发工具。")
        self.assertEqual(result["monthly"][0].description, "一个实用的开发工具。")
        session.post.assert_called_once()

    def test_keeps_original_description_without_github_token(self) -> None:
        repo = Repository("owner/new", "https://github.com/owner/new", "A useful tool")
        repositories = {"weekly": [repo], "monthly": []}

        self.assertIs(summarize_in_chinese(repositories, None), repositories)

    def test_serverchan_endpoint_supports_wechat_and_app_keys(self) -> None:
        self.assertEqual(
            serverchan_endpoint("SCT123"),
            "https://sctapi.ftqq.com/SCT123.send",
        )
        self.assertEqual(
            serverchan_endpoint("sctp42tABC"),
            "https://42.push.ft07.com/send/sctp42tABC.send",
        )


if __name__ == "__main__":
    unittest.main()
