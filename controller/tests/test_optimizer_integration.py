"""Exercise controller history through the real optimizer runner without a model."""

import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from controller.loop import experiment
from controller.records import load
from evaluator.core import write_json
from controller.tests import test_components as fixtures
from optimizer.run import main as optimizer_main
from optimizer.tests.test_artifacts import response


class OptimizerHistoryIntegrationTests(unittest.TestCase):
    def test_full_history_and_older_base_survive_real_context_checkpoint_and_export(self):
        fixture = fixtures.ComponentTests('test_full_adapter_loop_qualifies_and_links_rich_feedback')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        sessions = []

        def optimize(workspace, context, destination, **settings):
            number = len(sessions) + 1
            ledger = load(context / 'history/ledger.json')
            self.assertEqual(len(ledger['entries']), number - 1)
            self.assertEqual((context / 'books/book-one/src/SUMMARY.md').read_text(), '# Chapter\n')
            self.assertEqual(load(context / 'objective.json')['library_reduction_target_percent'], 20)
            stretch = load(context / 'objective.json')['optimizer_stretch_target']
            self.assertEqual(stretch['time_reduction_percent'], 20 if number == 1 else 30)
            if number > 1:
                self.assertEqual(stretch['best_previous']['candidate_id'], 'attempt-001')
            base = 'attempt-001' if number == 3 else 'original'
            contributors = ['attempt-002'] if number == 3 else []
            request = {'request_id': 'base', 'base_candidate_id': base,
                       'contributing_candidate_ids': contributors, 'reason': 'Use recorded evidence'}
            (workspace / 'base-request.json').write_text(json.dumps(request))
            settings['checkpoint_handler']()
            self.assertEqual(load(workspace / 'base-response.json')['status'], 'ready')
            expected = 'candidate 1\n' if number == 3 else 'original\n'
            self.assertEqual((workspace / 'library/src/lib.rs').read_text(), expected)
            (workspace / 'library/src/lib.rs').write_text(f'candidate {number}\n')
            (workspace / 'proposal.md').write_text('Workload characteristic -> cost -> specialization\n')
            (workspace / 'diagnostic.log').write_text('Diagnostic only; no measured speedup claim.\n')
            if number == 3:
                self.assertEqual(len(ledger['entries'][0]['evaluations']), 1)
                self.assertEqual(ledger['entries'][0]['audits'][0]['outcome'], 'no-issue-found')
                self.assertEqual(ledger['entries'][1]['audits'][0]['outcome'], 'unresolved')
                self.assertTrue(any(name.endswith('workspace/diagnostic.log') for name in ledger['artifacts']))
            sessions.append(ledger)
            value = response()
            value['guarantees'][0]['application_references'] = ['application/src/main.rs:1']
            return value

        def runner(argv, directory, timeout, cwd):
            if Path(argv[1]).parent.name != 'optimizer':
                result = fixture.runner(argv, directory, timeout, cwd)
                if Path(argv[1]).parent.name == 'evaluator' and 'run' in argv:
                    candidate = Path(argv[argv.index('--candidate') + 1])
                    destination = Path(argv[argv.index('--output') + 1])
                    # Real evaluation snapshots source files, excluding export Git metadata.
                    write_json(destination / 'variants/candidate/library-inputs.json',
                               load(candidate.parent / 'candidate-files.json'))
                return result
            fixture.calls.append('optimizer')
            with patch('optimizer.run.runtime', return_value={'codex': 'test-double'}), \
                    patch('optimizer.run.check_login'), \
                    patch('optimizer.run.shutil.which', return_value='/fake/codex'), \
                    patch('optimizer.run.probe_workspace', return_value={'workspace': True, 'context': False}), \
                    patch('optimizer.run.optimize', side_effect=optimize):
                code = optimizer_main(argv[2:])
            return {'execution_status': 'completed', 'exit_code': code, 'elapsed_seconds': .01}

        def findings(component, report):
            if component == 'auditor' and fixture.calls.count('auditor') == 2:
                report.update(status='unresolved', unresolved=['Needs another investigation'])

        fixture.components.runner = runner
        fixture.change_report = findings
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                result = experiment(fixture.records, fixture.components, 3)
            except Exception:
                self.fail(output.getvalue())
        self.assertEqual(result['status'], 'qualified')
        self.assertEqual(len(sessions), 3)
        final = load(fixture.experiment / 'steps/attempt-003-optimize/output/report.json')
        self.assertEqual(final['starting_point']['base_candidate_id'], 'attempt-001')
        self.assertEqual(final['starting_point']['contributing_candidate_ids'], ['attempt-002'])
        self.assertEqual(len(final['base_checkpoints']), 1)
        self.assertEqual((fixture.library / 'src/lib.rs').read_text(), 'original\n')
        fixture.records.verify()
