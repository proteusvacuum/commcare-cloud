import os
import re
from collections import defaultdict

import jinja2
from gevent.pool import Pool
from memoized import memoized

from commcare_cloud.fab.git_repo import _github_auth_provided

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'diff_templates')
LABELS_TO_EXPAND = [
    "reindex/migration",
]


class DeployDiff:
    def __init__(self, repo, last_commit, deploy_commit):
        self.repo = repo
        self.last_commit = last_commit
        self.deploy_commit = deploy_commit
        self.j2 = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIR))

    @property
    def url(self):
        """Human-readable diff URL"""
        return "{}/compare/{}...{}".format(self.repo.html_url, self.last_commit, self.deploy_commit)

    @memoized
    def get_diff_context(self):
        context = {}
        if not (_github_auth_provided() and self.last_commit and self.deploy_commit):
            context["error"] = "Insufficient info to get deploy diff."
            return context

        short, long = sorted([self.last_commit, self.deploy_commit], key=lambda x: len(x))
        if (self.last_commit == self.deploy_commit or (
            long.startswith(short)
        )):
            context["error"] = "Versions are identical. No changes since last deploy."
            return context

        context["compare_url"] = self.url
        pr_numbers = self._get_pr_numbers()
        if len(pr_numbers) > 500:
            context["message"] = "There are too many PRs to display"
            return context
        elif not pr_numbers:
            context["messages"] = "No PRs merged since last release."
            return context

        pool = Pool(5)
        pr_infos = [_f for _f in pool.map(self._get_pr_info, pr_numbers) if _f]

        context["pr_infos"] = pr_infos
        prs_by_label = self._get_prs_by_label(pr_infos)
        context["prs_by_label"] = prs_by_label
        return context

    def print_deployer_diff(self, new_version_details=None):
        register_console_filters(self.j2)
        template = self.j2.get_template('console.j2')
        print(template.render(
            new_version_details=new_version_details,
            **self.get_diff_context())
        )

    def _get_pr_numbers(self):
        comparison = self.repo.compare(self.last_commit, self.deploy_commit)
        return [
            int(re.search(r'Merge pull request #(\d+)',
                          repo_commit.commit.message).group(1))
            for repo_commit in comparison.commits
            if repo_commit.commit.message.startswith('Merge pull request')
        ]

    def _get_pr_info(self, pr_number):
        pr_response = self.repo.get_pull(pr_number)
        if not pr_response.number:
            # Likely rate limited by Github API
            return None
        assert pr_number == pr_response.number, (pr_number, pr_response.number)

        labels = [label.name for label in pr_response.labels]

        return {
            'number': pr_response.number,
            'title': pr_response.title,
            'url': pr_response.html_url,
            'labels': labels,
            'additions': pr_response.additions,
            'deletions': pr_response.deletions,
        }

    def _get_prs_by_label(self, pr_infos):
        prs_by_label = defaultdict(list)
        for pr in pr_infos:
            for label in pr['labels']:
                prs_by_label[label].append(pr)
        return dict(prs_by_label)


def register_console_filters(env):
    from fabric.colors import red, blue, cyan, yellow, green, magenta

    filters = {
        "error": red,
        "success": green,
        "highlight": yellow,
        "summary": blue,
        "warning": magenta,
        "code": cyan,
    }

    for name, filter_ in filters.items():
        env.filters[name] = filter_
