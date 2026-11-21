import time
import unittest
from unittest import mock

from kanjo import quota, quota_fetch


class QuotaRobustnessTest(unittest.TestCase):
    def test_malformed_nested_fields_are_ignored(self):
        self.assertIsNone(quota_fetch.parse_codex_usage({'rate_limit': []}, 100))
        self.assertIsNone(quota_fetch.parse_claude_usage({'seven_day': 'bad'}, 100))
        self.assertIsNone(quota_fetch.parse_grok_usage({'config': {'currentPeriod': 'bad'}}, 100))
        self.assertIsNone(quota_fetch.parse_antigravity_summary({'groups': [{'displayName': 'Gemini', 'buckets': [{'window': 'weekly'}]}]}, 100))

    def test_expired_and_extra_windows_are_sanitized_at_export(self):
        entry = {'weekly_resets_at': '1970-01-01T00:01:00Z', 'weekly_used_percent': 120,
                 'five_hour_resets_at': '1970-01-01T00:01:00Z', 'five_hour_used_percent': 10,
                 'extra_windows': [{'id': 'x', 'resets_at': '1970-01-01T00:01:00Z', 'used_percent': 50}]}
        with mock.patch.object(quota_fetch, 'fetch_all_quotas', return_value={'codex': entry}), mock.patch.dict(quota.TOKEI_READERS, {}, clear=True):
            result = quota.quota_windows(now=100)['codex']
        self.assertIsNone(result['weekly_resets_at'])
        self.assertIsNone(result['weekly_used_percent'])
        self.assertIsNone(result['five_hour_resets_at'])
        self.assertIsNone(result['extra_windows'][0]['used_percent'])

    def test_stale_cache_is_not_returned_or_refreshed_by_other_provider(self):
        cache = {'fetched_at': 0, 'providers': {'codex': {'weekly_resets_at': 'old'}}}
        with mock.patch.dict('os.environ', {'KANJO_NO_NETWORK': '0'}), mock.patch.object(quota_fetch, 'load_quota_cache', return_value=cache), mock.patch.object(quota_fetch, 'save_quota_cache') as save, mock.patch.dict(quota_fetch.FETCHERS, {'grok': lambda now: {'weekly_resets_at': 'new'}}, clear=True):
            result = quota_fetch.fetch_all_quotas(now=1000)
        self.assertEqual(set(result), {'grok'})
        self.assertEqual(set(save.call_args.args[0]['providers']), {'grok'})

    def test_fetches_run_concurrently_with_bounded_wait(self):
        def slow(now):
            time.sleep(0.3)
        with mock.patch.dict('os.environ', {'KANJO_NO_NETWORK': '0'}), mock.patch.object(quota_fetch, 'load_quota_cache', return_value=None), mock.patch.dict(quota_fetch.FETCHERS, {str(i): slow for i in range(8)}, clear=True):
            start = time.monotonic()
            quota_fetch.fetch_all_quotas(now=100)
            self.assertLess(time.monotonic() - start, 0.8)

    def test_codex_epoch_milliseconds_and_iso(self):
        result = quota_fetch.parse_codex_usage({'rate_limit': {'secondary_window': {'reset_at': 2000000000000}, 'primary_window': {'reset_at': '2033-05-18T03:33:20Z'}}}, 100)
        self.assertEqual(result['weekly_resets_at'], '2033-05-18T03:33:20Z')
        self.assertEqual(result['five_hour_resets_at'], '2033-05-18T03:33:20Z')

    def test_http_errors_and_invalid_payloads_do_not_expose_token(self):
        import io
        import urllib.error
        for response in (urllib.error.HTTPError('https://chatgpt.com', 401, 'secret', {}, None),
                         urllib.error.HTTPError('https://chatgpt.com', 429, 'secret', {}, None),
                         urllib.error.HTTPError('https://chatgpt.com', 503, 'secret', {}, None),
                         TimeoutError('secret')):
            stderr = io.StringIO()
            with mock.patch.dict('os.environ', {'KANJO_NO_NETWORK': '0', 'KANJO_QUOTA_DEBUG': '1'}), mock.patch.object(quota_fetch, '_load_codex_auth', return_value=('secret', None)), mock.patch('urllib.request.urlopen', side_effect=response), mock.patch('sys.stderr', stderr):
                self.assertIsNone(quota_fetch.fetch_codex_quota(100))
            self.assertNotIn('secret', stderr.getvalue())
        for body in (b'<html>error</html>', b'{"rate_limit":'):
            response = mock.MagicMock()
            response.__enter__.return_value.geturl.return_value = 'https://chatgpt.com/backend-api/wham/usage'
            response.__enter__.return_value.read.return_value = body
            with mock.patch.dict('os.environ', {'KANJO_NO_NETWORK': '0'}), mock.patch.object(quota_fetch, '_load_codex_auth', return_value=('secret', None)), mock.patch('urllib.request.urlopen', return_value=response):
                self.assertIsNone(quota_fetch.fetch_codex_quota(100))

    def test_authorization_is_not_forwarded_on_redirect(self):
        import urllib.request
        req = urllib.request.Request('https://chatgpt.com/path')
        req.add_unredirected_header('Authorization', 'Bearer secret')
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(req, None, 302, 'Found', {}, 'https://example.com/')
        self.assertNotIn('Authorization', dict(redirected.header_items()))

    def test_claude_credentials_override_avoids_keychain(self):
        import json
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'credentials.json')
            with open(path, 'w') as handle:
                json.dump({'claudeAiOauth': {'accessToken': 'fake-token'}}, handle)
            with mock.patch.dict('os.environ', {'KANJO_CLAUDE_CREDENTIALS': path}), mock.patch.object(quota_fetch.winsupport, 'is_windows', return_value=False), mock.patch.object(quota_fetch.subprocess, 'run') as run:
                self.assertEqual(quota_fetch._load_claude_credentials(), 'fake-token')
                run.assert_not_called()

    def test_expired_provider_windows_do_not_roll_forward(self):
        result = quota_fetch.parse_codex_usage({'rate_limit': {'secondary_window': {'reset_at': 99, 'used_percent': 20}, 'primary_window': {'reset_at': 200, 'used_percent': 10}}}, 100)
        self.assertIsNone(result['weekly_resets_at'])
        self.assertIsNone(result['weekly_used_percent'])

    def test_fetch_budget_bounds_stalled_provider(self):
        def slow(now):
            time.sleep(0.4)
        with mock.patch.dict('os.environ', {'KANJO_NO_NETWORK': '0'}), mock.patch.object(quota_fetch, 'load_quota_cache', return_value=None), mock.patch.object(quota_fetch, 'FETCH_BUDGET', 0.05), mock.patch.dict(quota_fetch.FETCHERS, {'slow': slow}, clear=True):
            start = time.monotonic()
            self.assertEqual(quota_fetch.fetch_all_quotas(now=100), {})
            self.assertLess(time.monotonic() - start, 0.25)

    def test_antigravity_csrf_is_not_forwarded_on_redirect(self):
        import urllib.request
        requests = []
        def fail(req, **kwargs):
            requests.append(req)
            raise OSError('wrong process')
        with mock.patch.dict('os.environ', {'KANJO_NO_NETWORK': '0'}), mock.patch.object(quota_fetch, '_find_antigravity_processes', return_value=[{'pid': 0, 'port': 1234, 'csrf_token': 'fake-secret'}]), mock.patch('urllib.request.urlopen', side_effect=fail):
            self.assertIsNone(quota_fetch.fetch_antigravity_quota(100))
        self.assertTrue(requests)
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(requests[0], None, 302, 'Found', {}, 'http://example.com/')
        self.assertNotIn('X-codeium-csrf-token', dict(redirected.header_items()))
