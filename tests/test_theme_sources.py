import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.theme_sources import _document, _evidence, projections
from tests.test_theme_elements import signals


class PublicThemeSourceTests(unittest.TestCase):
    def test_evidence_prose_excludes_predictions_and_preserves_exact_text(self):
        body = '# 合成\n\n## 足元の根拠（完了した事実）\n\n選択を後に回した記録。\n\n## 見出している未来\n\n将来の未検証予測。\n'
        self.assertEqual('選択を後に回した記録。', _evidence(body))
        self.assertEqual('', _evidence('## 予測\n根拠を探す予定。'))
        self.assertEqual(({}, body), _document(body.encode()))

    def test_native_git_projection_uses_pinned_blob_not_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            rows = signals()
            owners = []
            for identifier in ('art-history', 'marketing-trends'):
                repo = root / identifier
                repo.mkdir()
                def git(*args):
                    return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
                git('init', '-q')
                git('config', 'user.name', 'Synthetic Fixture')
                git('config', 'user.email', 'fixture@example.invalid')
                if identifier == 'art-history':
                    (repo / 'entities').mkdir()
                    (repo / 'entities/target.md').write_text('---\nid: artist-entity-001\nlabel_ja: 合成参照名\n---\n# Synthetic\n')
                else:
                    (repo / 'trend.md').write_text('---\nid: trend-entity-001\n---\n## 足元の根拠\n決定を後に回した合成記録。\n## 予測\n未検証の予測。\n')
                    rows[2]['source']['locators'] = ['trend.md']
                git('add', '.')
                git('commit', '-qm', 'Add synthetic public knowledge')
                commit = git('rev-parse', 'HEAD')
                owners.append({'id': identifier, 'path': identifier, 'observed_commit': commit,
                               'knowledge_profile': {'retrieval_entry_points': [{'kind': 'directory', 'locator': 'entities'}]}})
                kind = 'marketing' if identifier == 'marketing-trends' else identifier
                for row in rows:
                    if row['signal_kind'] == kind: row['source']['commit'] = commit
                if identifier == 'marketing-trends':
                    (repo / 'trend.md').write_text('DIRTY_MUTABLE_BODY')
            with patch('tools.theme_sources.load_yaml', return_value={'repositories': owners}):
                result = projections(rows, root)
            evidence = result['evidence'][rows[2]['signal_id']]
            self.assertEqual('決定を後に回した合成記録。', evidence['text'])
            self.assertEqual('合成参照名', result['targets']['artist-entity-001']['text'])
            original = '---\nid: trend-entity-001\n---\n## 足元の根拠\n決定を後に回した合成記録。\n## 予測\n未検証の予測。\n'
            self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), evidence['source']['sha256'])
            self.assertEqual('DIRTY_MUTABLE_BODY', (root / 'marketing-trends/trend.md').read_text())

    def test_ambiguous_public_commit_is_rejected_before_reading_git(self):
        rows = signals()
        rows.append({**rows[1], 'source': {**rows[1]['source'], 'commit': 'b' * 40}})
        with patch('tools.theme_sources._git') as git, self.assertRaisesRegex(ValueError, 'AMBIGUOUS'):
            projections(rows, Path('/not-used'))
        git.assert_not_called()

    def test_source_matching_uses_actual_evidence_prose_and_excludes_target_label(self):
        from tools.theme_elements import ranked
        rows = signals()
        public = {'evidence': {rows[2]['signal_id']: {'text': '保留の観測', 'source': {'commit': 'a' * 40}}},
                  'targets': {'artist-entity-001': {'text': '合成対象', 'source': {'commit': 'c' * 40}}}}
        market = ranked('保留', rows, 'marketing', public)[0]
        self.assertGreater(market['score'], 0)
        art = ranked('合成対象', rows, 'art-history', public)[0]
        self.assertEqual(art['score'], 0)
        self.assertTrue(art['public_source_refs'])


class ProjectElementDestinationTests(unittest.TestCase):
    def test_repo_local_state_requires_explicit_validated_project_root(self):
        from tools.element import Engine
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve() / 'project'
            project.mkdir()
            (project / '.git').mkdir()
            state = project / '.agentic-art/state'
            with self.assertRaises(ValueError):
                Engine('project-test', state)
            resolution = {'destinations': {'state_root': {'path': str(state)}}}
            with patch('tools.repo_local_destinations.resolve_project_root', return_value=resolution) as resolver:
                engine = Engine('project-test', state, project_root=project)
                self.assertEqual(state / 'project-test/element-state.json', engine.path)
                resolver.assert_called_once_with(project, run_id='project-test')
                with self.assertRaisesRegex(ValueError, 'differs'):
                    Engine('wrong', project / '.agentic-art/wrong', project_root=project)
            self.assertFalse(state.exists())
