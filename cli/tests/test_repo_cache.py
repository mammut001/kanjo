import unittest
import os
import shutil
import tempfile
import time
from kanjo.cache import RepoCache, _negative_ttl, NEGATIVE_TTL_MIN, NEGATIVE_TTL_MAX

class TestRepoCache(unittest.TestCase):
    def test_negative_ttl_logic(self):
        # 1. Deterministic and within range
        path1 = "/a/b/c"
        path2 = "/a/b/c"
        ttl1 = _negative_ttl(path1)
        ttl2 = _negative_ttl(path2)
        self.assertEqual(ttl1, ttl2)
        self.assertTrue(NEGATIVE_TTL_MIN <= ttl1 <= NEGATIVE_TTL_MAX)

        # 2. Spread over 1000 paths
        ttls = set()
        for i in range(1000):
            ttls.add(_negative_ttl(f"/path/{i}"))
        
        self.assertTrue(max(ttls) - min(ttls) > 3600)  # > 1h

    def test_repo_cache_negative_ttl_invalidation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "my_project")
            os.mkdir(project_dir)
            
            cache = RepoCache(directory=tmpdir)
            
            now = time.time()
            cache.put(project_dir, None, now=now)
            cache.save()
            
            cache = RepoCache(directory=tmpdir)
            
            # Use _negative_ttl for the path
            ttl = _negative_ttl(project_dir)
            
            # Hit just before
            hit, repo = cache.get(project_dir, now=now + ttl - 1)
            self.assertTrue(hit)
            self.assertIsNone(repo)
            
            # Miss just after
            hit, repo = cache.get(project_dir, now=now + ttl + 1)
            self.assertFalse(hit)

if __name__ == "__main__":
    unittest.main()
