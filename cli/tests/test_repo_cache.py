import unittest
import os
import shutil
import tempfile
import time
from kanjo.cache import RepoCache, NEGATIVE_TTL

class TestRepoCache(unittest.TestCase):
    def test_repo_cache_negative_directory_expiry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a dummy project directory
            project_dir = os.path.join(tmpdir, "my_project")
            os.mkdir(project_dir)
            
            # Initialize cache
            cache = RepoCache(directory=tmpdir)
            
            # Create a negative entry for the directory
            now = time.time()
            cache.put(project_dir, None, now=now)
            cache.save()
            
            # Re-initialize cache to ensure it loads from disk
            cache = RepoCache(directory=tmpdir)
            
            # Check that it's a hit (negative) even after 2 days (less than 7 days)
            hit, repo = cache.get(project_dir, now=now + 2 * 86400)
            self.assertTrue(hit)
            self.assertIsNone(repo)
            
            # Now create .git
            os.mkdir(os.path.join(project_dir, ".git"))
            
            # Check that it's a miss now because .git exists
            hit, repo = cache.get(project_dir, now=now + 2 * 86400)
            self.assertFalse(hit)
