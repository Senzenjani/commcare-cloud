import requests
from github.GithubException import GithubException
from jsonobject.base import namedtuple

from commcare_cloud.colors import color_error

ISO_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

FILE_STATUS = {
    "added": "A",
    "modified": "M",
    "renamed": "M",
    "deleted": "D",
    "removed": "D"
}


def update_sentry_post_deploy(environment, sentry_project, github_repo, diff, deploy_start, deploy_end):
    localsettings = environment.public_vars["localsettings"]
    try:
        sentry_api_key = environment.get_secret('SENTRY_API_KEY')
    except KeyError:
        return
    client = SentryClient(
        sentry_api_key,
        localsettings.get('SENTRY_ORGANIZATION_SLUG', 'dimagi'),
        sentry_project
    )
    if client.is_valid():
        # this must match the release name used in commcare-hq when configuring the Sentry API
        release_name = f"{environment.release_name}-{environment.meta_config.env_monitoring_id}"
        if environment.fab_settings_config.generate_deploy_diffs:
            try:
                commits = get_release_commits(diff)
            except GithubException as e:
                commits = None
                print(color_error(f"Error getting release commits: {e}"))
        else:
            commits = None
        client.create_release(release_name, commits)
        client.create_deploy(
            release_name, environment.meta_config.env_monitoring_id,
            deploy_start, deploy_end
        )


class SentryClient(namedtuple("SentryClient", "api_key, org_slug, project_slug")):
    def is_valid(self):
        return all(self)

    def create_release(self, release_name, commit_data):
        payload = {
            'version': release_name,
            'projects': [self.project_slug],
        }
        if commit_data is not None:
            payload['commits'] = commit_data

        headers = {'Authorization': 'Bearer {}'.format(self.api_key), }
        releases_url = f"https://sentry.io/api/0/organizations/{self.org_slug}/releases/"
        response = requests.post(releases_url, headers=headers, json=payload)
        if response.status_code == 208:
            # already created so update
            payload.pop('version')
            requests.put('{}{}/'.format(releases_url, release_name), headers=headers, json=payload)

    def create_deploy(self, release_name, env_name, deploy_start, deploy_end):
        payload = {
            'environment': env_name,
            'dateStarted': f"{deploy_start.isoformat()}Z",
            'dateFinished': f"{deploy_end.isoformat()}Z",
        }

        headers = {'Authorization': 'Bearer {}'.format(self.api_key), }
        releases_url = f'https://sentry.io/api/0/organizations/{self.org_slug}/releases/{release_name}/deploys/'
        requests.post(releases_url, headers=headers, json=payload)


def get_release_commits(diff):
    # https://docs.sentry.io/product/releases/setup/manual-setup-releases/
    comparison = diff.git_comparison
    commits = []
    for commit in comparison.commits:
        author = commit.commit.author
        commits.append({
            "repository": diff.repo.full_name,
            "author_name": author.name,
            "author_email": author.email,
            "timestamp": author.date.strftime(ISO_DATETIME_FORMAT),
            "message": commit.commit.message,
            "id": commit.sha,
            "patch_set": [
                {"path": file.filename, "type": FILE_STATUS.get(file.status, "M")}
                for file in commit.files
            ],
        })
    return commits
