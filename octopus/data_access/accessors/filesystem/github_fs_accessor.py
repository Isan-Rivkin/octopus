from octopus.data_access.access_controller_pool import AccessControllerPool
import os
from collections import defaultdict
from itertools import groupby
import datetime
import dateutil.parser

class GithubFSAccessor:
    def __init__(self, workspace_path):
        self.__workspace_path = workspace_path
        self.__fs_ctrl = AccessControllerPool().generate_access_controller(name='fs',
        base_path=workspace_path, create_base_path=False)

    def __remap_commits(self, commits_json, branch_info, repo):
        # Group by objects and then sort by datetime
        # Then create a final json which has all the commits along with the full line counts
        # Afterwards remap commits to a list by hash
        commits_objects = sorted(commits_json, key=lambda x: x['object'])
        commits_json = []
        for k, g in groupby(commits_objects, lambda x: x['object']):
            object_group = list(g)
            # Sort list by datetime
            object_group = sorted(object_group, key=lambda x: dateutil.parser.parse(x['timestamp']))
            # Cumolative count and add to each object in the group
            current_line_count = 0
            for obj in object_group:
                current_line_count = current_line_count + obj['insertions'] - obj['deletions']
                obj['file_line_count'] = current_line_count
            # Flatten the list back to the json
            commits_json = commits_json + object_group
        groups = []
        commits_json = sorted(commits_json, key=lambda x: x['commit'])
        for k, g in groupby(commits_json, lambda x: x['commit']):
            changes = list(g)
            groups.append({'id': k, 'commit_time': changes[0]['timestamp'], 'file_changes': changes, 
                            'pre_commit': {'file_amount': 0, 'branch_size': 0},
                            'post_commit': {'file_amount': 0, 'branch_size': 0}})
        # Sort the commits by datetime and start adding pre / post commits
        groups = sorted(groups, key=lambda x: dateutil.parser.parse(x['commit_time']))

        for idx, commit in enumerate(groups):
            # Pre commit is the post commit of the commit before
            # Post commit is pre commit + the additions / removals
            if idx == 0 and branch_info['parent']:
                # Has parent, find the fitting commit hash and take the pre commit to start with
                hash_id = branch_info['parent']['id']
                branch_name = branch_info['parent']['name']
                for parent_cmt in repo['branches'][branch_name]['commits']:
                    if parent_cmt['id'] == hash_id:
                        commit['pre_commit'] = parent_cmt['post_commit'].copy()
            if idx > 0:
                commit['pre_commit'] = groups[idx-1]['post_commit'].copy()
            # Count the additions / removals of files
            commit['post_commit'] = commit['pre_commit'].copy()
            
            for change in commit['file_changes']:
                if change['type'] == 'A':
                    commit['post_commit']['file_amount'] += 1
                elif change['type'] == 'D':
                    commit['post_commit']['file_amount'] -= 1
                commit['post_commit']['branch_size'] += change['size']
                commit['post_commit']['file_amount'] = max(commit['post_commit']['file_amount'], 0)
                commit['post_commit']['branch_size'] = max(commit['post_commit']['branch_size'], 0)
        return groups

    def __read_branch_commits(self, repo_path, branch_info, repo):
        # First check if the branch has a parent branch, if so, read it first
        if branch_info['parent']:
            parent_branch = branch_info['parent']['name']
            branch = repo['branches'][parent_branch]
            branch['commits'] = self.__read_branch_commits(repo_path, branch, repo)
        if self.__fs_ctrl.engine().exists(repo_path):
            commits_path = os.path.join(repo_path, 'commits/' + master_branch_name + '_meta.json')
            # Check if the commits folder exists and go over every json commit
            if self.__fs_ctrl.engine().exists(commits_path):
                commits_json = self.__fs_ctrl.engine().load_json(commit_file)
                commits_json = self.__remap_commits(commits_json, branch_info, repo)
                # branch_name = self.__fs_ctrl.engine().filename(commit_file, strip_ext=True)
                # return {'name': branch_name, 'commits': commits_json}
                return commits_json

    def __read_repo_inpr(self, repo_path):
        if self.__fs_ctrl.engine().exists(repo_path):
            inpr_path = os.path.join(repo_path, 'inprs.json')
            if self.__fs_ctrl.engine().exists(inpr_path):
                # Read the issues n pullreqs json
                return self.__fs_ctrl.engine().load_json(inpr_path)
        return None
            
    def acquire_additional_repos_info(self, repos):
        # For every repo read the commits of all branches
        # One branch can be dependent on another, read the origin branch first
        # Afterwards read other branches which might be recursive dependent
        # After this is done, read the repo inpr
        for repo in repos:
            repo_path = repo['repo_local_path']
            for branch in repo['branches']:
                branch['commits'] = self.__read_branch_commits(commits_path, branch, repo)
            # Read the repo inpr
            inpr = self.__read_repo_inpr(repo_path)
            repo['issues'] = inpr['issue']
            repo['pullreqs'] = inpr['pr']

    def read_repo_commits(self, repo_path, repo_info):
        commits = {}
        # Check if the given repo path exists
        if self.__fs_ctrl.engine().exists(repo_path):
            commits_path = os.path.join(repo_path, 'commits')
            # Check if the commits folder exists and go over every json commit
            if self.__fs_ctrl.engine().exists(commits_path):
                commit_files = self.__fs_ctrl.engine().list_files_with_ext(commits_path, ['.json'])
                # Read the default branch first
                for commit_file in commit_files:
                    commits_json = self.__fs_ctrl.engine().load_json(commit_file)
                    commits_json = self.__remap_commits(commits_json)
                    branch_name = self.__fs_ctrl.engine().filename(commit_file, strip_ext=True)
                    commits.append({'name': branch_name, 'commits': commits_json})
        return commits

    def read_user_metadata(self):
        if self.__fs_ctrl.engine().exists('profile_meta.json'):
            user_meta = self.__fs_ctrl.engine().load_json('profile_meta.json')
            return user_meta
        return None

    def read_user_repos_metadata(self):
        repos_metadata = []
        # Assert user workspace path
        if self.__fs_ctrl.engine().exists('profile_meta.json'):
            repos_dirs = self.__fs_ctrl.engine().get_dir_entries('repositories/repositories')
            for repo_dir in repos_dirs:
                repo_name = os.path.basename(repo_dir)
                repo_meta_path = os.path.join(repo_dir, repo_name + '_meta.json')
                if self.__fs_ctrl.engine().exists(repo_meta_path):
                    repo_meta = self.__fs_ctrl.engine().load_json(repo_meta_path)
                    repo_meta['repo_local_path'] = repo_dir
                    repos_metadata.append(repo_meta)
        return repos_metadata
        # if 
        # if os.path.exists(os.path.join(self.__user_workspace_path, 'profile_meta.json')):
        #     # Read the user metadata
        #     with open(os.path.join(self.__user_workspace_path, 'profile_meta.json')) as metafile:
        #         self.__user_metadata = json.load(metafile)

        #     # Read all the repos metadata
        #     repos_dirs = self.__fs_ctrl.engine().get_dir_entries('repositories/repositories')
        #     # repos_path = os.path.join(self.__user_workspace_path, 'repositories/repositories')
        #     # repos_dirs = [os.path.join(repos_path, subdir) for subdir in os.listdir(repos_path)
        #                                                    if os.path.isdir(os.path.join(repos_path, subdir))] 
        #     # Iterate over all the repos
        #     for repo_dir in repos_dirs:
        #         # Read the repo name as the dir name
        #         repo_name = os.path.basename(repo_dir)
        #         # Read the metadata of the repo
        #         repo_meta_path = os.path.join(repo_dir, repo_name + "_meta.json")
        #         if os.path.exists(repo_meta_path):
        #             with open(repo_meta_path) as repo_metafile:
        #                 self.__user_repos_metadata.append(json.load(repo_metafile))