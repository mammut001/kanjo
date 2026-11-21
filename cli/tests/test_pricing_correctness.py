import unittest
from unittest.mock import patch

from kanjo.pricing import AGENT_DEFAULT, GLOBAL_DEFAULT, PriceBook


class PricingCorrectness(unittest.TestCase):
    def setUp(self):
        self.book = PriceBook()

    def test_normalized_names(self):
        groups = {
            'anthropic/claude-opus-4.5': [
                'claude-opus-4-5', 'ANTHROPIC/claude-opus-4-5',
                'us.anthropic.claude-opus-4-5-20250929-v1:0',
                'bedrock/anthropic.claude-opus-4-5-20250929-v1:0',
                'vertex/claude-opus-4-5@20250929', 'claude-opus-4.5-latest-thinking'],
            'openai/gpt-5.1': ['gpt-5-1', 'openai/GPT-5-1-20250929', 'gpt-5.1-high'],
            'google/gemini-3.5-flash': ['models/gemini-3.5-flash', 'gemini-3.5-flash-low'],
        }
        for expected, names in groups.items():
            for name in names:
                with self.subTest(name=name):
                    self.assertEqual(self.book.resolve(name), (expected, False))

    def test_dated_openai_snapshots(self):
        for name, expected in [('gpt-5-2025-08-07', 'openai/gpt-5'),
                               ('openai/gpt-5-2025-08-07', 'openai/gpt-5'),
                               ('gpt-5-mini-2025-08-07', 'openai/gpt-5-mini'),
                               ('gpt-4-0613', 'openai/gpt-4'),
                               ('gpt-4.1-2025-04-14', 'openai/gpt-4.1')]:
            with self.subTest(name=name):
                self.assertEqual(self.book.resolve(name), (expected, False))
        self.assertAlmostEqual(self.book.cost('gpt-5-2025-08-07', 'codex',
                                              1000000, 100000, 10000000)[0], 3.5)

    def test_fallback_preserves_tier(self):
        for name, tier in [('gpt-5.1-ultra-mini', 'mini'), ('gpt-4.0-mini', 'mini'),
                           ('gpt-99-nano', 'nano'), ('gpt-99-pro', 'pro'),
                           ('claude-opus-99', 'opus'), ('claude-haiku-99', 'haiku'),
                           ('gemini-99-flash', 'flash')]:
            with self.subTest(name=name):
                model, estimated = self.book.resolve(name)
                self.assertTrue(estimated)
                self.assertIn(tier, model)
                self.assertTrue(self.book.known(model))

    def test_cache_and_precision(self):
        p = self.book.price('anthropic/claude-opus-4.5')
        cost, est = self.book.cost('claude-opus-4.5', 'claude', 100, 20, 30, 40, 10)
        self.assertFalse(est)
        self.assertAlmostEqual(cost, (100*p['in'] + 20*p['out'] + 30*p['cache_read'] + 30*p['cache_write'] + 10*p['write1h']) / 1e6)
        pieces = [self.book.cost('claude-opus-4.5', 'claude', 1)[0] for _ in range(1000)]
        self.assertAlmostEqual(sum(pieces), self.book.cost('claude-opus-4.5', 'claude', 1000)[0])

    def test_unknown_tiers_have_nonzero_estimated_cost(self):
        for name, agent in [('anthropic/claude-sonnet-9', 'claude'),
                            ('openai/gpt-9-mini', 'codex'),
                            ('xai/grok-9-nano', 'grok')]:
            with self.subTest(name=name):
                model, estimated = self.book.resolve(name, agent)
                self.assertTrue(estimated)
                if 'sonnet' in name:
                    self.assertEqual(self.book._tiers(model), {'sonnet'})
                if 'mini' in name:
                    self.assertTrue(self.book._tiers(model) == {'mini'} or model == AGENT_DEFAULT[agent])
                if 'nano' in name:
                    self.assertEqual(model, AGENT_DEFAULT[agent])
                cost, estimated = self.book.cost(name, agent, 1000, 1000)
                self.assertTrue(estimated)
                self.assertGreater(cost, 0)

    def test_keyword_fallback_checks_all_representative_tiers(self):
        fallbacks = [('sonnet', 'anthropic/claude-opus-4.8'),
                     ('sonnet', 'anthropic/claude-sonnet-5')]
        with patch('kanjo.pricing.FAMILY_FALLBACK', fallbacks):
            self.assertEqual(self.book.resolve('unknown/other-sonnet-9'),
                             ('anthropic/claude-sonnet-5', True))
            self.assertEqual(self.book.resolve('unknown/other-sonnet-nano-9'),
                             (GLOBAL_DEFAULT, True))

    def test_long_prompt_boundary(self):
        model = 'claude-haiku-5.5'
        base = self.book.price('anthropic/claude-haiku-5.5')['in'] / 1e6
        self.assertAlmostEqual(self.book.cost(model, 'claude', 100000)[0], 100000 * base)
        self.assertAlmostEqual(self.book.cost(model, 'claude', 100001)[0], 100001 * base * 5)

    def test_dynamic_router_sentinels_are_not_negative_costs(self):
        for model in ('openrouter/auto', 'openrouter/fusion'):
            with self.subTest(model=model):
                cost, estimated = self.book.cost(model, 'codex', 1000, 1000)
                self.assertGreaterEqual(cost, 0)
                self.assertTrue(estimated)

    def test_fixture_model_ids_resolve(self):
        import json
        import sqlite3
        from pathlib import Path

        models = set()
        keys = {'model', 'model_id', 'modelid', 'model_name', 'modelname'}

        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.lower() in keys and isinstance(item, str) and item:
                        models.add(item)
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        def parse(text):
            try:
                visit(json.loads(text))
            except (ValueError, TypeError):
                for line in text.splitlines():
                    try:
                        visit(json.loads(line))
                    except ValueError:
                        pass

        for path in (Path(__file__).parent / 'fixtures').rglob('*'):
            if not path.is_file():
                continue
            if path.suffix in ('.db', '.sqlite'):
                with sqlite3.connect('file:' + str(path.resolve()) + '?mode=ro', uri=True) as db:
                    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    for (table,) in tables:
                        quoted = '"' + table.replace('"', '""') + '"'
                        cursor = db.execute('SELECT * FROM ' + quoted)
                        columns = [column[0].lower() for column in cursor.description]
                        for row in cursor:
                            for column, value in zip(columns, row):
                                if isinstance(value, str):
                                    if column in keys and value:
                                        models.add(value)
                                    parse(value)
            else:
                try:
                    parse(path.read_text(encoding='utf-8'))
                except UnicodeError:
                    pass
        self.assertGreater(len(models), 40)
        for model in sorted(models):
            with self.subTest(model=model):
                resolved, estimated = self.book.resolve(model)
                self.assertTrue(self.book.known(resolved), (model, resolved, estimated))
                self.assertGreaterEqual(self.book.price(resolved)['in'], 0)

    def test_non_anthropic_cache_and_output(self):
        for model in ('openai/gpt-5.1', 'google/gemini-3.5-flash'):
            with self.subTest(model=model):
                p = self.book.price(model)
                self.assertEqual(p['write1h'], p['cache_write'])
                # Output counts include reasoning tokens in the normalized message.
                cost, _ = self.book.cost(model, None, 10, 25, 30, 40, 10)
                expected = (10*p['in'] + 25*p['out'] + 30*p['cache_read'] + 40*p['cache_write']) / 1e6
                self.assertAlmostEqual(cost, expected)

    def test_signature_accounts_for_aliases(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            overrides = Path(directory) / 'overrides.json'
            overrides.write_text(json.dumps({'aliases': {'alias': 'openai/gpt-5.1'}}))
            first = PriceBook(overrides_path=str(overrides))
            overrides.write_text(json.dumps({'aliases': {'alias': 'openai/gpt-5-mini'}}))
            second = PriceBook(overrides_path=str(overrides))
            self.assertNotEqual(first.sig, second.sig)
