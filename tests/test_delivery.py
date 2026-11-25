import csv
import json
import tempfile
import unittest
from pathlib import Path
from rocket.project import default_project, load_project
from rocket.pipeline import run_project
from rocket.report import export_report


class DeliveryTests(unittest.TestCase):
    def test_source_notes_are_optional_and_excluded_from_exports(self):
        project = default_project()
        project['motor'].pop('source', None)
        project['structure'].pop('source', None)
        clean = run_project(project)
        project['motor']['source'] = 'LEGACY_MOTOR_SOURCE'
        project['structure']['source'] = 'LEGACY_STRUCTURE_SOURCE'
        old = run_project(project)
        self.assertEqual(clean['flight']['summary'], old['flight']['summary'])
        with tempfile.TemporaryDirectory() as d:
            export_report(old, d)
            for name in ('report.html', 'project.json', 'result.json'):
                contents = (Path(d)/name).read_text(encoding='utf-8')
                self.assertNotIn('数据来源', contents)
                self.assertNotIn('LEGACY_MOTOR_SOURCE', contents)
                self.assertNotIn('LEGACY_STRUCTURE_SOURCE', contents)
            self.assertEqual(load_project(Path(d)/'project.json'), clean['project'])

    def test_report_contains_real_snapshot_and_offline_assets(self):
        p = default_project()
        p['name'] = '<中文项目>'
        result = run_project(p)
        p['body']['diameter_m'] = 99  # Subsequent mutation must not alter this run.
        with tempfile.TemporaryDirectory() as d:
            path = export_report(result, d)
            text = path.read_text(encoding='utf-8')
            self.assertIn('&lt;中文项目&gt;', text)
            self.assertNotIn('<中文项目>', text)
            self.assertIn('flight.png', text)
            self.assertGreater((Path(d)/'flight.png').stat().st_size, 10000)
            saved = load_project(Path(d)/'project.json')
            self.assertEqual(saved['body']['diameter_m'], .05)
            again = run_project(saved)
            self.assertAlmostEqual(again['flight']['summary']['apogee_m'], result['flight']['summary']['apogee_m'])
            with open(Path(d)/'flight.csv', encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(float(rows[-1]['altitude_m']), 0)
            self.assertEqual(json.loads((Path(d)/'result.json').read_text(encoding='utf-8'))['flight']['status'], 'landed')


if __name__ == '__main__':
    unittest.main()
