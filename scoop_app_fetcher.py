import requests
import sqlite3
from datetime import datetime, timedelta
from threading import Lock
import logging

class ScoopAppFetcher:
    def __init__(self):
        self.url = 'https://scoopsearch.search.windows.net/indexes/apps/docs/search?api-version=2020-06-30'
        self.headers = {
            'Content-Type': 'application/json',
            'api-key': 'DC6D2BBE65FC7313F2C52BBD2B0286ED'
        }
        self.buckets = {
            "main": "https://github.com/ScoopInstaller/Main",
            "extras": "https://github.com/ScoopInstaller/Extras",
            "versions": "https://github.com/ScoopInstaller/Versions",
            "nirsoft": "https://github.com/niheaven/scoop-sysinternals",
            "php": "https://github.com/ScoopInstaller/PHP",
            "nerd-fonts": "https://github.com/matthewjberger/scoop-nerd-fonts",
            "nonportable": "https://github.com/ScoopInstaller/Nonportable",
            "java": "https://github.com/ScoopInstaller/Java",
            "games": "https://github.com/Calinou/scoop-games"
        }
        self.db_conn = sqlite3.connect('scoop_apps.db', check_same_thread=False)
        self.lock = Lock()
        self._create_tables()
        self.logger = logging.getLogger(__name__)

    def _create_tables(self):
        with self.lock:
            with self.db_conn:
                cursor = self.db_conn.cursor()
                
                # Check if 'apps' table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='apps'")
                if not cursor.fetchone():
                    cursor.execute('''
                        CREATE TABLE apps (
                            id TEXT PRIMARY KEY,
                            name TEXT,
                            name_partial TEXT,
                            name_suffix TEXT,
                            description TEXT,
                            notes TEXT,
                            homepage TEXT,
                            license TEXT,
                            version TEXT,
                            bucket_command TEXT,
                            app_command TEXT,
                            official_repo BOOLEAN,
                            repo_url TEXT,
                            repo_stars INTEGER,
                            file_path TEXT,
                            committed TEXT,
                            sha TEXT
                        )
                    ''')
                
                # Check if 'last_update' table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='last_update'")
                if not cursor.fetchone():
                    cursor.execute('''
                        CREATE TABLE last_update (
                            id INTEGER PRIMARY KEY,
                            last_updated TIMESTAMP
                        )
                    ''')
                    # Add initial timestamp
                    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute('INSERT INTO last_update (last_updated) VALUES (?)', (current_time,))

    def _check_update_needed(self):
        with self.lock:
            with self.db_conn:
                cursor = self.db_conn.execute('SELECT last_updated FROM last_update ORDER BY id DESC LIMIT 1')
                result = cursor.fetchone()
                if result:
                    last_update = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
                    return datetime.now() - last_update > timedelta(days=30)
                return True

    def _update_last_updated(self):
        with self.lock:
            with self.db_conn:
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self.db_conn.execute('INSERT INTO last_update (last_updated) VALUES (?)', (current_time,))

    def update_data(self):
        if self._check_update_needed():
            web_count = self._get_web_count()
            self._fetch_and_store_data_in_chunks(web_count)
            self._update_last_updated()
            self.logger.info("Data updated")
        else:
            self.logger.info("Data is up to date. No update needed.")

    def force_update(self):
        web_count = self._get_web_count()
        self._fetch_and_store_data_in_chunks(web_count)
        self._update_last_updated()
        self.logger.info("Data forcefully updated")

    def _get_web_count(self):
        payload = {
               "count": True,
                "filter": "",
                "highlight": "Name,NamePartial,NameSuffix,Description,Version,License,Metadata/Repository",
                "highlightPostTag": "</mark>",
                "highlightPreTag": "<mark>",
                "orderby": "search.score() desc, Metadata/OfficialRepositoryNumber desc, NameSortable asc",
                "search": "",
                "searchMode": "all",
                "skip": 0,
                "top": 1,
                "select": "Id,Name,NamePartial,NameSuffix,Description,Notes,Homepage,License,Version,Metadata/Repository,Metadata/FilePath,Metadata/OfficialRepository,Metadata/RepositoryStars,Metadata/Committed,Metadata/Sha"
            
        }
        try:
            response = requests.post(self.url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json().get('@odata.count', 0)
        except requests.RequestException as e:
            self.logger.error(f"Error fetching the data count: {e}")
            return 0

    def _fetch_and_store_data_in_chunks(self, total_count):
        chunk_size = 500
        for skip in range(0, total_count, chunk_size):
            payload = {
                 "count": True,
                "filter": "",
                "highlight": "Name,NamePartial,NameSuffix,Description,Version,License,Metadata/Repository",
                "highlightPostTag": "</mark>",
                "highlightPreTag": "<mark>",
                "orderby": "search.score() desc, Metadata/OfficialRepositoryNumber desc, NameSortable asc",
                "search": "",
                "searchMode": "all",
                "skip": skip,
                "top": chunk_size,
                "select": "Id,Name,NamePartial,NameSuffix,Description,Notes,Homepage,License,Version,Metadata/Repository,Metadata/FilePath,Metadata/OfficialRepository,Metadata/RepositoryStars,Metadata/Committed,Metadata/Sha"
            }
            try:
                response = requests.post(self.url, headers=self.headers, json=payload)
                response.raise_for_status()
                apps_info = self._process_data(response.json()['value'])
                self._store_data(apps_info)
                self.logger.info(f"Fetched and stored {skip + chunk_size} records out of {total_count}")
            except requests.RequestException as e:
                self.logger.error(f"Error fetching the data: {e}")
                
                
    def _process_data(self, apps):
        processed_apps = []
        for app in apps:
            try:
                app_name = app.get('Name', 'N/A')
                repo_url = app.get('Metadata', {}).get('Repository', 'N/A')
                bucket_name = next((key for key, value in self.buckets.items() if value == repo_url), 'unknown')
                
                bucket_command = f"scoop bucket add {bucket_name} {self.buckets.get(bucket_name)}" if bucket_name in self.buckets else 'N/A'
                app_command = f"scoop install {bucket_name}/{app_name}" if bucket_name != 'unknown' else 'N/A'
                
                processed_apps.append({
                    'Id': app.get('Id', 'N/A'),
                    'Name': app_name,
                    'NamePartial': app.get('NamePartial', 'N/A'),
                    'NameSuffix': app.get('NameSuffix', 'N/A'),
                    'Description': app.get('Description', 'N/A'),
                    'Notes': app.get('Notes', 'N/A'),
                    'Homepage': app.get('Homepage', 'N/A'),
                    'License': app.get('License', 'N/A'),
                    'Version': app.get('Version', 'N/A'),
                    'Bucket_Command': bucket_command,
                    'App_Command': app_command,
                    'Official_Repository': app.get('Metadata', {}).get('OfficialRepository', False),
                    'Repo_URL': repo_url,
                    'Repo_Stars': app.get('Metadata', {}).get('RepositoryStars', 0),
                    'File_Path': app.get('Metadata', {}).get('FilePath', 'N/A'),
                    'Committed': app.get('Metadata', {}).get('Committed', 'N/A'),
                    'Sha': app.get('Metadata', {}).get('Sha', 'N/A')
                })
            except Exception as e:
                self.logger.error(f"Error processing app data: {e}")

        return sorted(processed_apps, key=lambda x: x['Name'])

    def _store_data(self, apps_info):
        with self.lock:
            with self.db_conn:
                cursor = self.db_conn.cursor()
                cursor.executemany('''
                    INSERT OR REPLACE INTO apps (id, name, name_partial, name_suffix, description, notes, homepage, license, version, bucket_command, app_command, official_repo, repo_url, repo_stars, file_path, committed, sha)
                    VALUES (:Id, :Name, :NamePartial, :NameSuffix, :Description, :Notes, :Homepage, :License, :Version, :Bucket_Command, :App_Command, :Official_Repository, :Repo_URL, :Repo_Stars, :File_Path, :Committed, :Sha)
                ''', apps_info)

    def get_apps_info(self, columns):
        with self.lock:
            with self.db_conn:
                cursor = self.db_conn.execute(f'SELECT {", ".join(columns)} FROM apps')
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_apps_info_paginated(self, columns, page, per_page, search_query=''):
        offset = (page - 1) * per_page
        with self.lock:
            with self.db_conn:
                if search_query:
                    cursor = self.db_conn.execute(f'SELECT {", ".join(columns)} FROM apps WHERE name LIKE ? LIMIT {per_page} OFFSET {offset}', (f'%{search_query}%',))
                else:
                    cursor = self.db_conn.execute(f'SELECT {", ".join(columns)} FROM apps LIMIT {per_page} OFFSET {offset}')
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_column_names(self):
        with self.lock:
            with self.db_conn:
                cursor = self.db_conn.execute('PRAGMA table_info(apps)')
                return [row[1] for row in cursor.fetchall()]

    def print_apps_info(self, apps_info):
        for app in apps_info:
            print('\n'.join(f"{key}: {value}" for key, value in app.items()))
            print('-' * 40)

# Example usage:
# fetcher = ScoopAppFetcher()
# fetcher.force_update()  # Fetch and store data if an update is needed

# # Retrieve and print all app information
# columns = fetcher.get_column_names()
# apps_info = fetcher.get_apps_info(columns)
# fetcher.print_apps_info(apps_info)
