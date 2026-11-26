import sys
import tkinter as tk
import unittest
from unittest.mock import patch
from rocket.project import default_project, ProjectError
from rocket.pipeline import run_project
from rocket.gui import App


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root)

    def tearDown(self):
        self.app.dirty=False
        self.root.update_idletasks()
        self.app._close()

    def test_unit_conversion_and_stale_result(self):
        p = self.app.get_project()
        self.assertAlmostEqual(p['body']['diameter_m'], .05)
        self.assertAlmostEqual(p['structure']['bolt_effective_area_m2'], 8e-6)
        self.app.apply_result(run_project(p))
        self.assertFalse(self.app.stale)
        self.app.variables['body.diameter_m'].set('60')
        self.assertTrue(self.app.stale)
        self.assertIn('disabled', self.app.export_button.state())
        self.assertAlmostEqual(self.app.get_project()['body']['diameter_m'], .06)

    def test_text_edits_invalidate_results_and_bad_fields_explain_path(self):
        self.app.apply_result(run_project(self.app.get_project()))
        self.app.parts_text.insert('end', '\n坏数据')
        self.app.parts_text.edit_modified(True)
        self.root.update()
        self.assertTrue(self.app.stale)
        with self.assertRaises(ProjectError):
            self.app.get_project()
        self.app.load_into_form(default_project())
        self.app.variables['body.diameter_m'].set('abc')
        with self.assertRaisesRegex(ProjectError, '直径'):
            self.app.get_project()

    def test_loading_another_project_clears_prior_results(self):
        self.app.apply_result(run_project(self.app.get_project()))
        p = default_project()
        p['name'] = '另一个项目'
        self.app.load_into_form(p)
        self.assertTrue(self.app.result is None)
        self.assertNotIn('已落地', self.app.result_text.get('1.0','end'))
        self.assertNotIn('246', self.app.overview_text.get())
        self.assertEqual(len(self.app.event_tree.get_children()), 0)

    def test_unsaved_edits_can_cancel_new_project(self):
        self.app.variables['name'].set('未保存参数')
        with patch('rocket.gui.messagebox.askyesnocancel', return_value=None) as question:
            self.app.new_project()
        question.assert_called_once()
        self.assertEqual(self.app.variables['name'].get(), '未保存参数')

    def test_new_project_visibly_resets_the_workspace(self):
        from pathlib import Path
        self.app.filepath = Path('旧项目.json')
        self.app.apply_result(run_project(self.app.get_project()))
        self.app.new_project()
        self.assertIsNone(self.app.filepath)
        self.assertIsNone(self.app.result)
        self.assertEqual(self.app.variables['name'].get(), '未命名火箭项目')
        self.assertIn('未保存的新项目', self.root.title())
        self.assertIn('已新建项目', self.app.status.get())
        self.assertFalse(self.app.dirty)

    def test_new_project_while_busy_explains_why(self):
        self.app.busy = True
        self.app.new_project()
        self.assertIn('仿真计算中', self.app.status.get())
        self.app.busy = False

    def test_plots_are_built_lazily_per_tab(self):
        self.app.apply_result(run_project(self.app.get_project()))
        self.assertEqual(self.app.plots_built, {'flight'})
        self.app.plot_tabs.select(self.app.plot_frames['motor'])
        self.root.update()
        self.assertEqual(self.app.plots_built, {'flight', 'motor'})

    @unittest.skipUnless(sys.platform == 'win32', 'Windows only')
    def test_repaint_does_not_enable_composited_window_style(self):
        import ctypes
        self.root.deiconify(); self.root.update()
        self.app.repaint_window()
        user32 = ctypes.windll.user32
        window = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        self.assertFalse(user32.GetWindowLongW(window, -20) & 0x02000000)

    def test_component_shortcut_selects_and_opens_the_matching_inspector(self):
        self.app.open_component('fins')
        self.assertEqual(self.app.component_tree.selection(), ('fins',))
        self.assertEqual(self.app.current_page, '箭体')
        self.assertEqual(self.app.page_title.cget('text'), '梯形尾翼')
        self.app.open_component('recovery')
        self.assertEqual(self.app.main_tabs.select(), str(self.app.simulation_tab))
        self.assertEqual(self.app.sim_tabs.select(), str(self.app.pages['发射']))


if __name__ == '__main__':
    unittest.main()
