"""Turning what a session wrote into links: each resolver, and what they refuse.

The interesting assertions here are the negative ones. A link that goes somewhere
plausible and wrong is worse than no link, because nobody checks it.
"""

from __future__ import annotations

import pytest

from crowsnest.links import (
    Link,
    from_commits,
    from_issue_refs,
    from_markdown_links,
    from_repo_refs,
    from_urls,
    github_ref,
    identity,
    label_for,
    resolve,
)

REPO = {"repo_url": "https://github.com/i2mint/mergeset"}


# --------------------------------------------------------------------------------------
# The bare `#N` -- the one that needs crowsnest


def test_a_bare_issue_number_resolves_against_the_sessions_own_repository():
    found = from_issue_refs("fixed in #17, see also #3", REPO)
    assert [(link.url, link.text) for link in found] == [
        ("https://github.com/i2mint/mergeset/issues/17", "mergeset#17"),
        ("https://github.com/i2mint/mergeset/issues/3", "mergeset#3"),
    ]


def test_a_bare_issue_number_resolves_to_nothing_without_a_repository():
    """A wrong repository is worse than no link."""
    assert from_issue_refs("fixed in #17", {}) == []
    assert from_issue_refs("fixed in #17", {"repo_url": ""}) == []


def test_a_repository_that_is_not_on_github_resolves_nothing():
    assert from_issue_refs("#17", {"repo_url": "https://gitlab.com/o/r"}) == []
    assert from_issue_refs("#17", {"repo_url": "/local/bare/repo.git"}) == []


@pytest.mark.parametrize(
    "text",
    [
        "colour #ff00aa",  # a hex colour
        "issue no. 17",  # no hash at all
        "o/r#17",  # belongs to from_repo_refs, which names its own repo
        "&#8212;",  # an HTML entity
        "path/to/thing#17",  # a fragment, not an issue
    ],
)
def test_things_that_look_like_an_issue_number_and_are_not(text):
    assert [link.url for link in from_issue_refs(text, REPO)] == []


# --------------------------------------------------------------------------------------
# The others


def test_owner_repo_hash_number_names_its_own_repository():
    found = from_repo_refs("see i2mint/mergeset#12 for why", {})
    assert found[0].url == "https://github.com/i2mint/mergeset/issues/12"
    assert found[0].text == "mergeset#12"


def test_a_markdown_link_keeps_the_name_its_author_chose():
    found = from_markdown_links(
        "see [the release PR](https://github.com/o/r/pull/27)", {}
    )
    assert (found[0].text, found[0].type) == ("the release PR", "pr")


def test_a_bare_url_is_typed_by_where_it_points():
    text = (
        "https://github.com/o/r/issues/3 "
        "https://github.com/o/r/pull/4 "
        "https://github.com/o/r/discussions/5 "
        "https://github.com/o/r/actions/runs/99 "
        "https://claude.ai/code/artifact/abc "
        "https://team.slack.com/archives/C1/p2 "
        "https://example.org/whatever"
    )
    assert [link.type for link in from_urls(text, {})] == [
        "issue",
        "pr",
        "discussion",
        "run",
        "artifact",
        "slack",
        "link",
    ]


def test_a_url_inside_a_markdown_link_is_not_also_read_as_a_bare_one():
    assert from_urls("[label](https://github.com/o/r/pull/27)", {}) == []


def test_trailing_punctuation_is_not_part_of_a_url():
    assert from_urls("see https://github.com/o/r/pull/27.", {})[0].url.endswith("/27")


def test_a_commit_sha_resolves_against_the_sessions_repository():
    found = from_commits("landed as 7d30838", REPO)
    assert found[0].url == "https://github.com/i2mint/mergeset/commit/7d30838"
    assert found[0].text == "mergeset@7d30838"


def test_a_long_number_is_a_number_and_not_a_sha():
    assert from_commits("run 1234567890 finished", REPO) == []


def test_a_sha_needs_a_repository_too():
    assert from_commits("landed as 7d30838", {}) == []


# --------------------------------------------------------------------------------------
# resolve: order, de-duplication, the seam


def test_the_same_reference_written_two_ways_is_one_link():
    """`#45` and a link to pull/45 are the same thing; showing both is the noise."""
    found = resolve(
        "see [the PR](https://github.com/i2mint/mergeset/pull/45) which closes #45",
        context=REPO,
    )
    assert len(found) == 1
    assert found[0]["text"] == "the PR"  # the label its author chose wins


def test_a_discussion_is_not_collapsed_into_an_issue_of_the_same_number():
    found = resolve(
        "[disc](https://github.com/i2mint/mergeset/discussions/45) and #45", context=REPO
    )
    assert len(found) == 2


def test_identity_pairs_an_issue_with_its_pull_request_and_nothing_else():
    issue = "https://github.com/o/r/issues/45"
    assert identity(issue) == identity("https://github.com/o/r/pull/45")
    assert identity(issue) != identity("https://github.com/o/r/discussions/45")
    assert identity(issue) != identity("https://github.com/o/other/issues/45")


def test_results_come_in_resolver_order_so_the_best_few_are_the_first_few():
    found = resolve("7d30838 and #1 and [named](https://example.org/x)", context=REPO)
    assert [link["type"] for link in found] == ["link", "issue", "commit"]


def test_resolvers_is_the_seam():
    def only_tickets(text, context):
        return [Link("ticket", f"https://tickets.example/{n}") for n in ("A-1",)]

    found = resolve("anything at all", context=REPO, resolvers=[only_tickets])
    assert [link["url"] for link in found] == ["https://tickets.example/A-1"]


def test_a_resolver_that_raises_does_not_cost_the_others():
    def angry(text, context):
        raise RuntimeError("no")

    found = resolve("#17", context=REPO, resolvers=[angry, from_issue_refs])
    assert [link["text"] for link in found] == ["mergeset#17"]


def test_the_result_is_bounded():
    text = " ".join(f"#{n}" for n in range(1, 40))
    assert len(resolve(text, context=REPO, limit=5)) == 5


def test_empty_text_resolves_to_nothing():
    assert resolve("", context=REPO) == []
    assert resolve(None, context=REPO) == []


# --------------------------------------------------------------------------------------
# Labels


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/o/r/issues/3", "r#3"),
        ("https://github.com/o/r/pull/3", "r#3"),
        ("https://github.com/o/r/commit/abc1234def", "r@abc1234"),
        ("https://github.com/o/r/actions/runs/99", "r run 99"),
        ("https://github.com/o/r", "r"),
        ("https://claude.ai/code/artifact/x", "artifact"),
        ("https://team.slack.com/archives/C1/p2", "slack"),
        ("https://example.org/x", "example.org"),
    ],
)
def test_a_url_with_no_label_is_named_the_way_a_person_says_it(url, expected):
    assert label_for(url) == expected


def test_a_label_that_says_something_is_kept():
    assert (
        label_for("https://github.com/o/r/pull/3", "the release PR") == "the release PR"
    )


def test_github_ref_reads_a_url_apart():
    assert github_ref("https://github.com/i2mint/mergeset/pull/27/files") == (
        "pr",
        "i2mint",
        "mergeset",
        "27",
    )
    assert github_ref("not a url") == ("", "", "", "")


# --------------------------------------------------------------------------------------
# What the roster does with them


def test_the_roster_resolves_a_sessions_references_against_its_own_repository(tmp_path):
    from crowsnest import tools

    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "fixer.md").write_text(
        "# fixer\n\nlast said: 2026-01-01 \u00b7 blocked on #17\n\n## Notes\n\n"
        "Waiting on [the PR](https://github.com/o/r/pull/2).\n",
        encoding="utf-8",
    )
    row = {
        "label": "fixer",
        "repo_url": "https://github.com/i2mint/mergeset",
        "activity": {"last_assistant_text": "also see 7d30838", "locators": []},
    }
    found = tools._links_of(row, ledger_dir=ledger)
    assert {link["url"] for link in found} == {
        "https://github.com/i2mint/mergeset/issues/17",
        "https://github.com/o/r/pull/2",
        "https://github.com/i2mint/mergeset/commit/7d30838",
    }


def test_a_session_with_no_ledger_and_no_references_gets_no_links(tmp_path):
    from crowsnest import tools

    row = {"label": "quiet", "repo_url": "https://github.com/o/r", "activity": {}}
    assert tools._links_of(row, ledger_dir=tmp_path) == []


def test_the_page_renders_a_resolved_reference_as_an_anchor():
    from crowsnest.report import render_report

    roster = {
        "sessions": [
            {
                "label": "fixer",
                "status": "waiting",
                "status_since": 0,
                "project": "demo",
                "waiting_for": "input needed",
                "links": [
                    {
                        "type": "issue",
                        "url": "https://github.com/o/r/issues/17",
                        "text": "r#17",
                    }
                ],
            }
        ],
        "counts": {},
    }
    html = render_report(roster, made_at="2026-01-01T00:00:00Z")
    assert '<a href="https://github.com/o/r/issues/17">r#17</a>' in html


def test_a_reference_that_reached_the_page_unlabelled_still_gets_a_name():
    from crowsnest.report import render_report

    roster = {
        "sessions": [
            {
                "label": "fixer",
                "status": "waiting",
                "status_since": 0,
                "links": [{"type": "pr", "url": "https://github.com/o/r/pull/27"}],
            }
        ],
        "counts": {},
    }
    assert ">r#27</a>" in render_report(roster, made_at="2026-01-01T00:00:00Z")


# --------------------------------------------------------------------------------------
# What an adversarial review proved wrong about the first draft.
#
# Every test below failed before its fix. Several were live on the real fleet at the time:
# `crowsnest show cn-ai-mo` was returning five links to real, unrelated issues.


def test_a_reference_already_written_out_in_full_is_not_re_resolved_wrongly():
    """The `#144` inside a markdown link's LABEL is priv's, not this session's."""
    text = "Group tooling in priv: [#144](https://github.com/thorwhalen/priv/pull/144)"
    context = {"repo_url": "https://github.com/thorwhalen/cosm"}
    assert {link["url"] for link in resolve(text, context=context)} == {
        "https://github.com/thorwhalen/priv/pull/144"
    }


@pytest.mark.parametrize(
    "text, why",
    [
        ("the badge is #336699", "an all-digit CSS colour"),
        ("see src/foo.py#12", "a line reference in a diff"),
        ("checksum 5d41402abc4b2a76b9719d911017c592", "an md5"),
        ("id 123e4567-e89b-12d3-a456-426614174000", "a UUID"),
        ("sha256:" + "a" * 64, "a sha256"),
    ],
)
def test_things_that_are_not_references(text, why):
    assert resolve(text, context=REPO) == [], why


def test_a_url_fragment_is_part_of_the_url_and_not_a_repository():
    found = resolve("https://example.org/doc#12345", context=REPO)
    assert [link["url"] for link in found] == ["https://example.org/doc#12345"]


def test_markdown_emphasis_and_backticks_do_not_end_up_inside_the_href():
    """The ledger is markdown, and this project's style bolds URLs and backticks them."""
    text = "page is **https://claude.ai/code/artifact/abc-123** and `https://github.com`"
    assert [link["url"] for link in resolve(text, context=REPO)] == [
        "https://claude.ai/code/artifact/abc-123",
        "https://github.com",
    ]


def test_a_parenthesis_the_url_opened_is_part_of_the_url():
    found = resolve("https://en.wikipedia.org/wiki/Foo_(bar)", context=REPO)
    assert found[0]["url"] == "https://en.wikipedia.org/wiki/Foo_(bar)"


def test_two_spellings_of_one_commit_are_one_reference():
    short = "https://github.com/o/r/commit/eb0774d0a"
    full = "https://github.com/o/r/commit/eb0774d0a3b31f6a38edd2cfafec8f2b0d7376c6"
    assert identity(short) == identity(full)
    assert len(resolve(f"{short} and {full}", context=REPO)) == 1


def test_www_and_uppercase_github_are_still_github():
    assert identity("https://www.github.com/o/r/issues/45") == identity(
        "https://github.com/o/r/issues/45"
    )
    assert github_ref("https://www.github.com/o/r/issues/45")[0] == "issue"


def test_a_trailing_slash_does_not_make_a_second_reference():
    assert identity("https://example.org/x/") == identity("https://example.org/x")


def test_a_resolver_that_returns_plain_dicts_works():
    """`resolve` returns dicts, so a caller writing one will reasonably return dicts."""

    def as_dicts(text, context):
        return [
            {"type": "issue", "url": "https://github.com/o/r/issues/1", "text": "r#1"}
        ]

    found = resolve("#1", context=REPO, resolvers=[as_dicts])
    assert [link["text"] for link in found] == ["r#1"]


def test_a_url_that_is_itself_a_credential_never_reaches_the_page():
    """A Slack webhook URL *is* the permission; the page is published off the machine."""
    for url in (
        "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX",
        "https://example.com/d?token=abcdef123456",
        "https://user:password@example.com/x",
    ):
        assert resolve(f"see {url}", context=REPO) == [], url
        assert resolve(f"see [hook]({url})", context=REPO) == [], url


def test_a_bad_byte_in_one_ledger_does_not_kill_the_whole_roster(tmp_path):
    """UnicodeDecodeError is a ValueError; `except OSError` never saw it."""
    from crowsnest import tools

    (tmp_path / "bad.md").write_bytes(b"# bad\n\nstate: working\n\n## Notes\n\xff\n")
    row = {"label": "bad", "repo_url": "https://github.com/o/r", "activity": {}}
    assert tools._links_of(row, ledger_dir=tmp_path) == []


def test_a_ledgers_free_prose_does_not_resolve_another_projects_issue_number(tmp_path):
    """The free part is prose about anything; `repo_url` is one repository."""
    from crowsnest import tools

    (tmp_path / "s.md").write_text(
        "# s\n\nlast said: 2026-01-01 \u00b7 closes #17\n\n## Notes\n\n"
        "cosmograph's #573 claim was false, see i2mint/mergeset#12\n",
        encoding="utf-8",
    )
    row = {"label": "s", "repo_url": "https://github.com/i2mint/mergeset", "activity": {}}
    urls = {link["url"] for link in tools._links_of(row, ledger_dir=tmp_path)}
    assert "https://github.com/i2mint/mergeset/issues/17" in urls  # its own words
    assert "https://github.com/i2mint/mergeset/issues/12" in urls  # names its own repo
    assert "https://github.com/i2mint/mergeset/issues/573" not in urls  # someone else's


def test_the_registry_only_roster_stays_instant():
    """`activity=False` promises instant; links follow it unless asked for."""
    from crowsnest import tools

    rows = tools.roster(home="/nonexistent", activity=False)
    assert rows["sessions"] == []
    assert tools.roster(home="/nonexistent", activity=False, links=True)["sessions"] == []


def test_report_can_reach_the_resolver_seam(tmp_path):
    """The surface the feature exists for must be able to reach the seam it renders."""
    from crowsnest import tools

    done = tools.report(
        home="/nonexistent",
        made_at="2026-01-01T00:00:00Z",
        ledger_dir=tmp_path,
        resolvers=[],
        links=False,
    )
    assert "<title>" in done["html"]


def test_a_withheld_or_rewritten_url_is_shown_as_text_not_as_a_link():
    from crowsnest.report import render_report

    roster = {
        "sessions": [
            {
                "label": "s",
                "status": "waiting",
                "status_since": 0,
                "links": [{"type": "link", "url": "javascript:alert(1)", "text": "ref"}],
            }
        ],
        "counts": {},
    }
    html = render_report(roster, made_at="2026-01-01T00:00:00Z")
    assert "javascript:" not in html and ">ref<" not in html
