import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.phase_a_world import COMMITS, NOW, art_signal, blob_source, world
from tools.card_sources import PhaseABlocked, git_blob_source, normalize_text, verify_card
from tools.element_checks import CheckConfigurationError, check_value, parse_check, specific_to_window
from tools.element_contracts import validate_sequence


def failures(value, checks, **inputs):
    return [row['check'] for row in check_value(value, checks, inputs=inputs, ledger={}, previous_answers={})]


class NormalizationTests(unittest.TestCase):
    def test_quote_markers_links_urls_and_ids_are_removed(self):
        self.assertEqual('引用された文章', normalize_text('> 引用された文章'))
        self.assertEqual('詳しくは記事を見る', normalize_text('詳しくは[記事](https://example.test/a)を見る'))
        self.assertEqual('文  の後', normalize_text('文 https://example.test/x の後'))
        self.assertEqual('画家  の作品', normalize_text('画家 P571 の作品'))
        self.assertEqual('P57は残る', normalize_text('P57は残る'))
        self.assertEqual('P5710a', normalize_text('P5710a'))

    def test_line_breaks_join_japanese_and_space_latin(self):
        self.assertEqual('制作過程の記録', normalize_text('制作過程の\n記録'))
        self.assertEqual('the idea is\nx'.replace('\n', ' '), normalize_text('the idea is\nx'))
        self.assertEqual('all of the planning', normalize_text('all of the\n  planning'))
        self.assertEqual('作品のidea', normalize_text('作品の\nidea'))
        self.assertEqual('段落一段落二', normalize_text('段落一\n\n段落二'))
        self.assertEqual('a b', normalize_text('a\r\nb'))

    def test_the_rule_is_idempotent_on_already_normalized_text(self):
        text = '制作過程の記録として立ち上がる自発的な構成 and the plan'
        self.assertEqual(text, normalize_text(normalize_text(text)))


class CardSourceTests(unittest.TestCase):
    def setUp(self):
        self.signals, self.blobs = world()
        self.art = next(signal for signal in self.signals if signal['signal_kind'] == 'art-history')
        self.item = self.art['domain']['art_history']['card'][0]

    def test_verbatim_excerpt_in_the_pinned_blob_is_accepted(self):
        self.assertEqual(self.item['text'], verify_card(self.art, self.item, blob_source(self.blobs)))

    def test_the_excerpt_is_checked_after_the_same_normalization_as_the_blob(self):
        path = self.item['source_locator'].split('#')[0]
        head, tail = self.item['text'].split('制作過程の記録として')
        raw = f'---\nid: x\n---\n# 定義\n{head}制作過程の記録として\n{tail}である。\n'
        self.blobs[('art-history', path)] = raw.encode()
        self.item['source_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
        self.assertEqual(self.item['text'], verify_card(self.art, self.item, blob_source(self.blobs)))

    def test_front_matter_is_not_the_body(self):
        path = self.item['source_locator'].split('#')[0]
        raw = f"---\nnote: {self.item['text']}\n---\n別の本文である。\n".encode()
        self.blobs[('art-history', path)] = raw
        self.item['source_sha256'] = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(PhaseABlocked) as caught:
            verify_card(self.art, self.item, blob_source(self.blobs))
        self.assertEqual('excerpt not in blob', caught.exception.details['detail'])

    def test_hash_missing_blob_and_unsafe_locator_each_block_with_their_cause(self):
        read = blob_source(self.blobs)
        bad_hash = {**self.item, 'source_sha256': '0' * 64}
        with self.assertRaises(PhaseABlocked) as caught:
            verify_card(self.art, bad_hash, read)
        self.assertEqual(('CARD_SOURCE_MISMATCH', 'blob sha256 differs'), (caught.exception.reason, caught.exception.details['detail']))
        with self.assertRaises(PhaseABlocked) as caught:
            verify_card(self.art, {**self.item, 'source_locator': 'knowledge/missing.md#x'}, read)
        self.assertEqual('blob unreadable', caught.exception.details['detail'])
        for locator in ('../outside.md', '/etc/passwd', '#only-anchor'):
            with self.assertRaises(PhaseABlocked) as caught:
                verify_card(self.art, {**self.item, 'source_locator': locator}, read)
            self.assertEqual('unsafe locator', caught.exception.details['detail'])

    def test_git_blob_source_reads_the_pinned_commit_not_the_working_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            repo = workspace / 'art-history-notes'
            repo.mkdir()
            def git(*args):
                return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
            git('init', '-q')
            git('config', 'user.name', 'Synthetic')
            git('config', 'user.email', 'synthetic@example.invalid')
            path = self.item['source_locator'].split('#')[0]
            (repo / 'knowledge').mkdir()
            (repo / path).write_bytes(self.blobs[('art-history', path)])
            git('add', '.')
            git('commit', '-qm', 'pin')
            commit = git('rev-parse', 'HEAD')
            (repo / path).write_text('DIRTY WORKTREE')
            signal = {**self.art, 'source': {**self.art['source'], 'commit': commit}}
            self.assertEqual(self.item['text'], verify_card(signal, self.item, git_blob_source(workspace)))
            with self.assertRaises(PhaseABlocked):
                verify_card({**signal, 'source': {**signal['source'], 'commit': COMMITS['art-history']}}, self.item, git_blob_source(workspace))


class CheckTests(unittest.TestCase):
    def test_exact_input_excerpt_is_an_exact_contiguous_passage(self):
        self.assertEqual([], failures('費用の確定', ['exact_input_excerpt:body'], body='本人は費用の確定を避ける'))
        self.assertEqual(['exact_input_excerpt:body'], failures('費用を確定', ['exact_input_excerpt:body'], body='本人は費用の確定を避ける'))
        self.assertEqual(['exact_input_excerpt:body'], failures('x', ['exact_input_excerpt:body']))

    def test_not_label_rejects_the_name_or_a_part_of_it(self):
        spec = ['not_label:label']
        self.assertEqual(['not_label:label'], failures('抽象表現主義', spec, label='抽象表現主義'))
        self.assertEqual(['not_label:label'], failures('抽象表現', spec, label='抽象表現主義'))
        self.assertEqual([], failures('制作過程の記録', spec, label='抽象表現主義'))

    def test_no_reference_tokens_rejects_urls_ids_and_source_notes(self):
        for text in ('https://example.test/a', '詳細[1]を参照', '記事](x', 'P571の値', '未確認: 増えている', '出典はA社', 'B社は拡大と主張している'):
            self.assertEqual(['no_reference_tokens'], failures(text, ['no_reference_tokens']), text)
        for text in ('制作過程の記録として立ち上がる', 'Q4の売上ではなくP57', 'planning is done first'):
            self.assertEqual([], failures(text, ['no_reference_tokens']), text)

    def test_specific_to_window_needs_a_term_only_the_winner_has_and_the_largest_overlap(self):
        spec = {'card': '空き家の増加：所有し続ける方向', 'others': ['不安の多重化：資産と貯蓄', 'デジタル利用：距離を置く意識']}
        self.assertTrue(specific_to_window('空き家を所有し続ける', spec))
        self.assertFalse(specific_to_window('確定の考え方が逆になっている', spec))
        self.assertFalse(specific_to_window('資産と貯蓄と空き家', {**spec, 'others': ['資産と貯蓄と空き家の増加']}))
        self.assertTrue(specific_to_window('空き家', {'card': '空き家の増加', 'others': []}))
        self.assertFalse(specific_to_window('空き家', 'not a spec'))
        self.assertEqual(['specific_to_window:spec'], failures('確定の考え方が逆', ['specific_to_window:spec'], spec=spec))

    def test_expected_choice_open_question_and_not_question(self):
        self.assertEqual([], failures('逆', ['expected_choice:expected'], expected='逆'))
        self.assertEqual(['expected_choice:expected'], failures('同じ', ['expected_choice:expected'], expected='逆'))
        self.assertEqual([], failures('どのように示せるか？', ['open_question']))
        self.assertEqual(['open_question'], failures('示せるか？', ['open_question']))
        for word in ('何', 'なぜ', 'どこまで', 'どんな', 'いかに'):
            self.assertEqual([], failures(f'これは{word}か？', ['open_question']), word)
        self.assertEqual([], failures('これは対比である。', ['not_question']))
        self.assertEqual(['not_question'], failures('これは何か？', ['not_question']))
        self.assertEqual(['not_question'], failures('これは何か?', ['not_question']))

    def test_check_names_stay_closed_and_arguments_are_validated(self):
        for spec in ('no_reference_tokens:x', 'open_question:x', 'not_label', 'specific_to_window:a b', 'expected_choice'):
            with self.assertRaises(CheckConfigurationError):
                parse_check(spec)

    def test_hidden_keys_satisfy_a_sequence_but_a_missing_key_does_not(self):
        element = {'kind': 'element', 'element_id': 'e.1', 'instruction': 'x', 'inputs': {'a': {'literal': 'x'}},
                   'answer_format': {'type': 'text', 'max_chars': 10}, 'checks': ['expected_choice:expected'],
                   'hidden': {'expected': 'x'}}
        sequence = {'contract_version': 'element-sequence/v1', 'elements': [element]}
        self.assertEqual([], validate_sequence(sequence))
        del element['hidden']
        self.assertEqual(['e.1: expected_choice requires a declared input key'], validate_sequence(sequence))


class SignalContractTests(unittest.TestCase):
    def test_cards_and_labels_are_part_of_the_normalized_signal(self):
        from tools.validate import validate_signal
        signals, _ = world()
        self.assertEqual([], [error for signal in signals for error in validate_signal(signal, 'x')])
        art = next(signal for signal in signals if signal['signal_kind'] == 'art-history')
        art['domain']['art_history']['card'][0]['source_sha256'] = 'not-a-hash'
        self.assertTrue(validate_signal(art, 'x'))
        art['domain']['art_history']['card'] = []
        self.assertTrue(validate_signal(art, 'x'))

    def test_adapters_carry_label_ja_and_card_through(self):
        from tools.adapters import adapt_art_history_signal, adapt_marketing_signal
        signals, _ = world()
        for signal, adapt in ((next(s for s in signals if s['signal_kind'] == 'art-history'), adapt_art_history_signal),
                              (next(s for s in signals if s['signal_kind'] == 'marketing'), adapt_marketing_signal)):
            domain = next(iter(signal['domain'].values()))
            record = {'signal_id': signal['signal_id'], 'commit': signal['source']['commit'],
                      'entity_id': signal['source']['entity_ids'][0], 'source_locator': signal['source']['locators'][0],
                      'evidence_locator': signal['evidence_refs'][0]['locator'], 'evidence_kind': signal['evidence_refs'][0]['kind'],
                      'statement': signal['statement'], 'certainty': signal['certainty'], 'unknowns': signal['unknowns'],
                      'constraints': signal['constraints'], 'validity': signal['validity'],
                      'generated_at': signal['generated_at'], 'adapter_version': '1.0.0', **domain,
                      'freshness': signal['freshness']}
            adapted = adapt(record)
            adapted_domain = next(iter(adapted['domain'].values()))
            self.assertEqual(domain['card'], adapted_domain['card'])
            self.assertEqual(domain['label_ja'], adapted_domain['label_ja'])

    def test_card_excerpts_empty_after_normalization_are_dropped_not_fatal(self):
        from tools.adapters import adapt_art_history_signal
        signals, _ = world()
        signal = next(s for s in signals if s['signal_kind'] == 'art-history')
        domain = signal['domain']['art_history']
        record = {'signal_id': signal['signal_id'], 'commit': signal['source']['commit'],
                  'entity_id': signal['source']['entity_ids'][0], 'source_locator': signal['source']['locators'][0],
                  'evidence_locator': signal['evidence_refs'][0]['locator'], 'evidence_kind': signal['evidence_refs'][0]['kind'],
                  'statement': signal['statement'], 'certainty': signal['certainty'], 'unknowns': signal['unknowns'],
                  'constraints': signal['constraints'], 'validity': signal['validity'],
                  'generated_at': signal['generated_at'], 'adapter_version': '1.0.0', **domain,
                  'freshness': signal['freshness']}
        good = domain['card'][0]
        empty = {**good, 'text': '[https://example.org/gold-weights](https://example.org/gold-weights) P571'}
        kept = adapt_art_history_signal({**record, 'card': [empty, good]})
        self.assertEqual([good], kept['domain']['art_history']['card'])
        none = adapt_art_history_signal({**record, 'card': [empty]})
        self.assertNotIn('card', none['domain']['art_history'])

    def test_a_card_only_art_entity_is_a_valid_signal(self):
        from tools.validate import validate_signal
        blobs = {}
        art = art_signal(0, blobs)
        art['domain']['art_history']['relations'] = []
        self.assertEqual([], validate_signal(art, 'x'))
        del art['domain']['art_history']['card']
        self.assertTrue(validate_signal(art, 'x'))


if __name__ == '__main__':
    unittest.main()
