import copy
import json
import math
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from .project import default_project, validate_project, load_project, save_project, ProjectError
from .motor import build_motor, read_curve, read_eng
from .pipeline import run_project
from .report import make_figure, summary_text, EVENT_LABELS, STATUS_LABELS
from . import ui_style as ui


COMPONENTS = {
    'nose': ('圆锥头锥', '箭体', 'body.nose_length_m'),
    'tube': ('箭身管', '箭体', 'body.diameter_m'),
    'fins': ('梯形尾翼', '箭体', 'body.fin_root_m'),
    'mass': ('质量部件', '箭体', None),
    'recovery': ('降落伞', '发射', None),
    'motor': ('发动机', '发动机', None),
    'structure': ('壳体与连接件', '结构', None),
}


class ChineseToolbar(NavigationToolbar2Tk):
    toolitems = (('Home', '恢复原始视图', 'home', 'home'),
                 ('Back', '返回上一个视图', 'back', 'back'),
                 ('Forward', '前往下一个视图', 'forward', 'forward'),
                 (None, None, None, None), ('Pan', '拖动以平移视图', 'move', 'pan'),
                 ('Zoom', '框选缩放区域', 'zoom_to_rect', 'zoom'),
                 (None, None, None, None), ('Save', '保存当前图表', 'filesave', 'save_figure'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configure(bg=ui.PANEL, bd=0)
        for child in self.winfo_children():
            child.configure(background=ui.PANEL)
            if isinstance(child, tk.Label):
                child.configure(foreground=ui.MUTED)

    def _Button(self, text, image_file, toggle, command):
        button = super()._Button(text, image_file, toggle, command)
        button.configure(bg=ui.PANEL, fg=ui.TEXT, activebackground=ui.SELECTED,
                         activeforeground=ui.TEXT, highlightthickness=0)
        if toggle:
            button.configure(selectcolor=ui.SELECTED)
        self._set_image_for_button(button)
        return button


def get_value(data, path):
    for key in path.split('.'):
        data = data[key]
    return data


def put_value(data, path, value):
    keys = path.split('.')
    for key in keys[:-1]:
        data = data[key]
    data[keys[-1]] = value


class App:
    def __init__(self, root, project=None):
        self.root = root
        self.project = copy.deepcopy(project or default_project())
        self.result = None
        self.stale = True
        self.dirty = False
        self.loading = False
        self.busy = False
        self.revision = 0
        self.variables, self.fields, self.pages = {}, {}, {}
        self.icons = {}
        self.canvases = []
        self.scrollers = {}
        self.active_component = None
        self.messages = queue.Queue()
        self.cancel = threading.Event()
        self.filepath = None
        self.smoke_path = None
        root.title('模型火箭设计与仿真')
        screen_width, screen_height = root.winfo_screenwidth(), root.winfo_screenheight()
        width, height = min(1450, screen_width-60), min(920, screen_height-90)
        root.geometry(f'{width}x{height}+30+30')
        root.minsize(min(1000, width), min(650, height))
        self.font = ui.configure_theme(root)
        self._layout()
        self._overview_page()
        self._motor_page()
        self._body_page()
        self._structure_page()
        self._launch_page()
        self._results_page()
        self.load_into_form(self.project)
        self.show_page('概览')
        self.poll_id = root.after(100, self._poll)
        root.bind('<Configure>', self._window_resized)
        root.protocol('WM_DELETE_WINDOW', self._close)

    def icon(self, name, color=ui.ACCENT, points=12):
        key = (name, color, points)
        if key not in self.icons:
            self.icons[key] = ui.make_icon(self.root, name, color, points)
        return self.icons[key]

    def tool_button(self, parent, label, command, icon=None, style='Tool.TButton', **options):
        if icon:
            color = '#ffffff' if style == 'Primary.TButton' else ui.ACCENT
            options.update(image=self.icon(icon, color), compound='left')
        return ttk.Button(parent, text=label, command=command, style=style, **options)

    def _layout(self):
        main = ttk.Frame(self.root, style='Shell.TFrame', padding=(12, 8))
        main.pack(expand=True, fill='both')
        toolbar = ttk.Frame(main, style='Shell.TFrame')
        toolbar.pack(fill='x', pady=(0, 9))
        brand_icon = self.icon('project', points=16)
        self.root.iconphoto(True, brand_icon)
        ttk.Label(toolbar, text=' 星云科技', image=brand_icon, compound='left',
                  style='Brand.TLabel').pack(side='left', padx=(0, 16))
        for label, command, glyph, key in [('新建', self.new_project, 'new', 'n'),
                                            ('打开', self.open_project, 'open', 'o'),
                                            ('保存', self.save, 'save', 's')]:
            self.tool_button(toolbar, label, command, glyph).pack(side='left', padx=(0, 5))
            for variant in (key, key.upper()):
                self.root.bind(f'<Control-{variant}>', lambda event, action=command: action())
        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=(6, 10), pady=5)
        self.tool_button(toolbar, '模型说明', self._show_help).pack(side='left')
        self.run_button = self.tool_button(toolbar, '运行仿真', self.run, 'run', 'Primary.TButton')
        self.run_button.pack(side='right')
        self.cancel_button = self.tool_button(toolbar, '取消', self.cancel.set, state='disabled')
        self.export_button = self.tool_button(toolbar, '导出报告', self.export, 'export', state='disabled')
        self.export_button.pack(side='right', padx=(5, 8))
        self.tool_button(toolbar, '检查参数', self.check, 'check').pack(side='right')
        self.root.bind('<F5>', lambda event: self.run())
        self.status = tk.StringVar(value='加载项目中…')
        footer = ttk.Frame(main, style='Shell.TFrame')
        footer.pack(side='bottom', fill='x', pady=(7, 0))
        self.progress = ttk.Progressbar(footer, mode='indeterminate', length=95)
        ttk.Label(footer, text='单级 · 竖直飞行', style='Shell.TLabel').pack(side='right', padx=(15, 0))
        ttk.Label(footer, textvariable=self.status, style='Shell.TLabel', wraplength=780).pack(side='left')
        self.workspace=ttk.Panedwindow(main,orient='vertical');self.workspace.pack(fill='both',expand=True)
        self.main_tabs=ttk.Notebook(self.workspace, style='Workspace.TNotebook')
        self.design_tab,self.motor_tab,self.simulation_tab=[ttk.Frame(self.main_tabs,padding=12) for _ in range(3)]
        for frame,label in [(self.design_tab,'火箭设计'),(self.motor_tab,'发动机与配置'),(self.simulation_tab,'飞行仿真')]:
            self.main_tabs.add(frame,text=label)
        self.workspace.add(self.main_tabs,weight=4)
        split=ttk.Panedwindow(self.design_tab,orient='horizontal');split.pack(fill='both',expand=True)
        tree_width = min(394, max(290, int(self.root.winfo_screenwidth() * .23)))
        tree_panel = ttk.Frame(split, width=tree_width, padding=(0,0,10,0))
        tree_panel.pack_propagate(False)
        self.page_host = ttk.Frame(split, padding=(13,0,0,0))
        split.add(tree_panel, weight=0)
        split.add(self.page_host, weight=1)
        tree_header = ttk.Frame(tree_panel)
        tree_header.pack(fill='x', pady=(0, 7))
        ttk.Label(tree_header, text='组件树', style='PanelTitle.TLabel').pack(side='left')
        ttk.Button(tree_header, text='项目属性', style='Tool.TButton', command=self.open_project_properties).pack(side='right')
        actions=ttk.Frame(tree_panel);actions.pack(side='bottom',fill='x',pady=(7,0))
        self.tool_button(actions,'编辑',self._select_component,'edit').pack(side='left',padx=(0,5))
        self.tool_button(actions,'添加质量部件',self.add_mass_part,'add').pack(side='left')
        tree_host=ttk.Frame(tree_panel);tree_host.pack(fill='both',expand=True)
        self.component_tree=ttk.Treeview(tree_host,show='tree',selectmode='browse',height=8)
        tree_bar=ttk.Scrollbar(tree_host,command=self.component_tree.yview)
        tree_bar.pack(side='right',fill='y');self.component_tree.configure(yscrollcommand=tree_bar.set)
        self.component_tree.pack(side='left',fill='both',expand=True)
        self.component_tree.insert('', 'end',iid='rocket',text=' 模型火箭',image=self.icon('project'),open=True)
        self.component_tree.insert('rocket','end',iid='stage',text=' 单级箭体',image=self.icon('stage'),open=True)
        for key, (label, *_details) in COMPONENTS.items():
            self.component_tree.insert('stage','end',iid=key,text=' '+label,image=self.icon(key),open=False)
        self.component_tree.bind('<<TreeviewSelect>>', self._component_selected)
        self.component_tree.bind('<Double-1>', self._select_component)
        self.component_tree.bind('<Return>', self._select_component)
        self.page_host.columnconfigure(0,weight=1);self.page_host.rowconfigure(1,weight=1)
        inspector_header = ttk.Frame(self.page_host)
        inspector_header.grid(row=0,column=0,sticky='ew',pady=(0,7))
        self.page_title=ttk.Label(inspector_header,text='',style='PanelTitle.TLabel')
        self.page_title.pack(side='left')
        self.component_home = ttk.Button(inspector_header, text='组件面板', style='Tool.TButton',
                                         command=lambda: self.show_page('概览'))
        for key in ['概览','项目','箭体','结构']:
            frame=ttk.Frame(self.page_host);frame.grid(row=1,column=0,sticky='nsew');self.pages[key]=frame
        self.pages['发动机']=self.motor_tab
        self.sim_tabs=ttk.Notebook(self.simulation_tab);self.sim_tabs.pack(fill='both',expand=True)
        for key,title in [('发射','仿真条件'),('结果','结果与曲线')]:
            frame=ttk.Frame(self.sim_tabs,padding=6);self.sim_tabs.add(frame,text=title);self.pages[key]=frame
        self.preview=ttk.Frame(self.workspace,padding=(9,7));self.workspace.add(self.preview,weight=3)
        viewbar=ttk.Frame(self.preview);viewbar.pack(fill='x',pady=(0,6))
        ttk.Label(viewbar,text='设计预览',style='PanelTitle.TLabel').pack(side='left',padx=(0,12))
        ttk.Label(viewbar,text='侧视图',style='Subtitle.TLabel').pack(side='left',padx=(0,9))
        self.tool_button(viewbar,'适应窗口',self.refresh_preview,'fit').pack(side='left',padx=(0,8))
        self.show_markers=tk.BooleanVar(value=True)
        ttk.Checkbutton(viewbar,text='重心 / 压心',variable=self.show_markers,command=self.draw_schematic).pack(side='left')
        self.overview_text=tk.StringVar(value='等待有效的设计参数')
        ttk.Label(viewbar,textvariable=self.overview_text,style='Subtitle.TLabel').pack(side='right')
        self.schematic=tk.Canvas(self.preview,height=300,bg=ui.VIEW,highlightthickness=1,highlightbackground=ui.LINE)
        self.schematic.pack(fill='both',expand=True)
        self.schematic.bind('<Configure>',lambda e:self.draw_schematic())
        self.results_banner=tk.StringVar(value='尚未运行仿真')
        self.main_tabs.bind('<<NotebookTabChanged>>', self._workspace_changed)
        self.layout_job=self.root.after(250,self.arrange_panes)

    def _show_help(self):
        messagebox.showinfo('模型说明', '适用范围为单级、亚声速、一维竖直飞行。\n模型假设及公式见应用附带的模型说明。', parent=self.root)

    def arrange_panes(self):
        self.root.update_idletasks()
        selected_workspace = self.main_tabs.select()
        if self.workspace.winfo_height() > 100 and selected_workspace != getattr(self, 'split_workspace', None):
            self.split_workspace = selected_workspace
            fraction = .53 if selected_workspace == str(self.design_tab) else .71
            self.workspace.sashpos(0, int(self.workspace.winfo_height() * fraction))
        if self.motor_split.winfo_ismapped() and self.motor_split.winfo_width() > 100:
            if not getattr(self, 'motor_split_ready', False):
                self.motor_split.sashpos(0, int(self.motor_split.winfo_width() * .49))
                self.motor_split_ready = True
        if hasattr(self,'results_split') and self.results_split.winfo_ismapped() and self.results_split.winfo_width()>100:
            if not getattr(self, 'results_split_ready', False):
                self.results_split.sashpos(0, min(360, int(self.results_split.winfo_width() * .27)))
                self.results_split_ready = True
        if hasattr(self,'fit_job'):
            self.root.after_cancel(self.fit_job)
        self.fit_job=self.root.after(120,self.fit_plots)

    def _window_resized(self, event):
        if event.widget != self.root:
            return
        if hasattr(self, 'repaint_job'):
            self.root.after_cancel(self.repaint_job)
        self.repaint_job = self.root.after(180, self.repaint_window)

    def fit_plots(self):
        # Windows DPI scaling can update the backing store after the first layout.
        # Fit once the panes are mapped, using actual widget pixels.
        # Only redraw visible plots whose pixel size actually changed.
        for canvas in self.canvases:
            widget=canvas.get_tk_widget()
            if not widget.winfo_ismapped():
                continue
            size=(widget.winfo_width(), widget.winfo_height())
            if size[0]<=50 or size[1]<=50 or getattr(canvas, 'fitted_size', None)==size:
                continue
            canvas.fitted_size=size
            event=tk.Event();event.width,event.height=size
            canvas.resize(event)
            canvas.draw_idle()
        self.repaint_window()

    def repaint_window(self):
        if sys.platform != 'win32' or not self.root.winfo_ismapped():
            return
        # Defer redraw until the pane layout settles so resized native child
        # windows do not retain pixels from the previously visible pane.
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        outer_window = user32.GetParent
        outer_window.argtypes = [wintypes.HWND]
        outer_window.restype = wintypes.HWND
        redraw = user32.RedrawWindow
        redraw.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        invalidate_children_now = 0x0001 | 0x0004 | 0x0080 | 0x0100
        handle = self.root.winfo_id()
        window = outer_window(handle) or handle
        # A one-shot redraw is enough to clear stale pixels. Do not set
        # WS_EX_COMPOSITED: with Tk child windows it causes an endless
        # WM_PAINT storm that keeps the event loop 100% busy (lag, dropped
        # frames, slow clicks).
        redraw(window, None, None, invalidate_children_now)

    def _workspace_changed(self, event=None):
        self.arrange_panes()

    def show_page(self, key, title=None):
        if key=='发动机':
            self.main_tabs.select(self.motor_tab)
        elif key in ['发射','结果']:
            self.main_tabs.select(self.simulation_tab);self.sim_tabs.select(self.pages[key])
        else:
            self.main_tabs.select(self.design_tab);self.pages[key].tkraise()
        self.current_page = key
        if key in ('概览', '项目', '箭体', '结构'):
            self.page_title.configure(text=title or {'概览':'火箭组件', '项目':'项目属性',
                                                       '箭体':'箭体与质量', '结构':'结构与静稳定'}[key])
            if key == '概览':
                self.component_home.pack_forget()
            else:
                self.component_home.pack(side='right')
            if title is None:
                self.active_component = None
                self.draw_schematic()
        if hasattr(self,'show_layout_job'):
            self.root.after_cancel(self.show_layout_job)
        self.show_layout_job=self.root.after_idle(self.arrange_panes)

    def _component_selected(self, event=None):
        selected=self.component_tree.selection()
        self.active_component = selected[0] if selected else None
        self.draw_schematic()

    def _select_component(self, event=None):
        if event and event.type == tk.EventType.ButtonPress:
            item = self.component_tree.identify_row(event.y)
            if not item or self.component_tree.identify_element(event.x, event.y) == 'Treeitem.indicator':
                return
        else:
            selected = self.component_tree.selection()
            item = selected[0] if selected else 'rocket'
        self.open_component(item)

    def open_component(self, key):
        self.component_tree.selection_set(key)
        self.component_tree.focus(key)
        self.component_tree.see(key)
        if key in ('rocket', 'stage'):
            self.show_page('概览')
            return
        label, page, path = COMPONENTS.get(key, COMPONENTS['mass'])
        self.active_component = key
        self.show_page(page, title=label)
        if path:
            self.focus_field(path)
        self.draw_schematic()

    def open_project_properties(self):
        self.component_tree.selection_set('rocket')
        self.component_tree.focus('rocket')
        self.show_page('项目')
        self.focus_field('name')

    def focus_field(self, path):
        widget = self.fields[path][-1]
        self.root.update_idletasks()
        group = widget.master
        inner = group.master
        canvas = self.scrollers.get(inner)
        if canvas:
            y = group.winfo_y() + widget.winfo_y()
            canvas.yview_moveto(max(0, y - 26) / max(1, inner.winfo_height()))
        widget.focus_set()

    def add_mass_part(self):
        name=simpledialog.askstring('添加质量部件','部件名称：',parent=self.root)
        if not name:
            return
        mass=simpledialog.askfloat('添加质量部件','质量 / g：',minvalue=0,parent=self.root)
        if mass is None:
            return
        position=simpledialog.askfloat('添加质量部件','距头锥尖端 / mm：',minvalue=0,parent=self.root)
        if position is None:
            return
        self.parts_text.insert('end',f'\n{name.replace(",","，")}, {mass:g}, {position:g}')
        self.invalidate()
        self.open_component('mass')

    def refresh_preview(self):
        def action():
            self.project=self.get_project();self.draw_schematic()
        self._guard(action)

    def _scroll(self, parent):
        host = ttk.Frame(parent); host.pack(fill='both', expand=True)
        canvas = tk.Canvas(host, background=ui.PANEL, highlightthickness=0)
        scrollbar = ttk.Scrollbar(host, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
        inner = ttk.Frame(canvas, padding=(2, 2, 16, 10))
        self.scrollers[inner] = canvas
        window = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        def wheel(e):
            canvas.yview_scroll(int(-e.delta/120), 'units')
            return 'break'
        # Scope the binding to each page's descendants; do not hijack plot scrolling.
        host.bind('<Enter>', lambda e: canvas.bind_all('<MouseWheel>', wheel))
        def leave(e):
            # Moving onto a child field also sends <Leave>; keep scrolling then.
            under = host.winfo_containing(e.x_root, e.y_root)
            if under is None or not str(under).startswith(str(host)):
                canvas.unbind_all('<MouseWheel>')
        host.bind('<Leave>', leave)
        return inner

    def _group(self, parent, title):
        group = ttk.LabelFrame(parent, text=title, padding=(10, 7))
        group.pack(fill='x', pady=(0, 10))
        group.columnconfigure(1, weight=1)
        return group

    def _field(self, parent, path, label, factor=1., choices=None, boolean=False, optional=False):
        row = len(parent.grid_slaves())//2
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 13), pady=3)
        variable = tk.BooleanVar() if boolean else tk.StringVar()
        if boolean:
            widget = ttk.Checkbutton(parent, variable=variable)
        elif choices:
            widget = ttk.Combobox(parent, textvariable=variable, values=list(choices.values()), state='readonly', width=22)
        else:
            widget = ttk.Entry(parent, textvariable=variable, width=24)
        widget.grid(row=row, column=1, sticky='ew', pady=3)
        self.variables[path] = variable
        self.fields[path] = (factor, choices, boolean, optional, label, widget)
        variable.trace_add('write', lambda *_: self.invalidate())

    def _text(self, parent, height, font=('Consolas', 10)):
        text = tk.Text(parent, height=height, font=font, wrap='none', relief='flat',
                       bg=ui.INPUT, fg=ui.TEXT, insertbackground=ui.ACCENT, padx=10, pady=10,
                       selectbackground=ui.SELECTED, selectforeground=ui.TEXT,
                       highlightbackground=ui.LINE, highlightcolor=ui.ACCENT, highlightthickness=1, undo=True)
        text.bind('<<Modified>>', lambda e, w=text: self._text_changed(w))
        return text

    def _overview_page(self):
        page = self.pages['概览']
        gallery = ttk.Frame(page)
        gallery.pack(fill='x', pady=(0, 5))
        for column in range(4):
            gallery.columnconfigure(column, weight=1, uniform='components')
        for index, (key, (label, _, _)) in enumerate(COMPONENTS.items()):
            tile = ttk.Frame(gallery, style='Metric.TFrame', padding=(1, 1))
            tile.grid(row=index//4, column=index%4, sticky='nsew', padx=(0, 7), pady=(0, 7))
            button = ttk.Button(tile, text=label, image=self.icon(key, points=14),
                                compound='top', style='Component.TButton',
                                command=lambda component=key: self.open_component(component))
            button.pack(fill='both', expand=True)
        top = self._group(self.pages['项目'], '项目资料')
        self._field(top, 'name', '项目名称')
        self._field(top, 'notes', '项目备注')

    def _motor_page(self):
        page = self.pages['发动机']
        columns = ttk.Panedwindow(page, orient='horizontal'); columns.pack(fill='both', expand=True)
        self.motor_split = columns
        left, right = ttk.Frame(columns), ttk.Frame(columns)
        columns.add(left, weight=3); columns.add(right, weight=2)
        inner = self._scroll(left)
        common = self._group(inner, '发动机输入')
        self._field(common, 'motor.mode', '计算模式', choices={'curve':'导入推力曲线', 'computed':'准稳态内弹道'})
        self._field(common, 'motor.dry_mass_kg', '发动机干质量 / g', 1000)
        self._field(common, 'motor.propellant_mass_kg', '曲线模式推进剂质量 / g', 1000)
        self._field(common, 'motor.position_m', '发动机干重心 / mm', 1000)
        self._field(common, 'motor.propellant_position_m', '推进剂轴向重心 / mm', 1000)
        grain = self._group(inner, '计算模式 · 药柱与燃烧室')
        for path, label, factor in [
            ('grain.outer_diameter_m','药柱外径 / mm',1000), ('grain.inner_diameter_m','药柱内径 / mm',1000),
            ('grain.length_m','单段长度 / mm',1000), ('grain.count','等尺寸段数',1),
            ('grain.density_kg_m3','密度 / kg/m³',1), ('chamber_diameter_m','燃烧室内径 / mm',1000),
            ('chamber_length_m','燃烧室长度 / mm',1000), ('throat_diameter_m','喷喉直径 / mm',1000),
            ('expansion_ratio','喷管面积膨胀比',1)]:
            self._field(grain, 'motor.'+path, label, factor)
        for path, label in [('burn_inner','内孔燃烧'), ('burn_outer','外表面燃烧'), ('burn_ends','两端面燃烧')]:
            self._field(grain, 'motor.grain.'+path, label, boolean=True)
        prop = self._group(inner, '计算模式 · 经验参数')
        for path, label, factor in [
            ('burn_a_mm_s','燃速 a / mm·s⁻¹（P取MPa）',1), ('burn_n','燃速指数 n',1),
            ('pressure_min_mpa','参数适用压力下限 / MPa',1), ('pressure_max_mpa','参数适用压力上限 / MPa',1),
            ('cstar_m_s','特征速度 c* / m/s',1), ('gamma','燃气比热比 γ',1),
            ('nozzle_efficiency','推力系数效率（0~1）',1), ('ambient_pressure_pa','固定环境绝对压力 / kPa',.001)]:
            self._field(prop, 'motor.'+path, label, factor)
        ttk.Label(right, text='推力曲线', style='PanelTitle.TLabel').pack(anchor='w', padx=12, pady=(0, 7))
        ttk.Label(right, text='每行：时间(s), 推力(N), 可选剩余质量(kg)\n须从 0 秒开始，时间递增，首尾推力为 0。',
                  wraplength=380, style='Subtitle.TLabel').pack(anchor='w', padx=15, pady=(0, 10))
        self.tool_button(right, '导入 CSV / RASP .eng', self.import_motor, 'open').pack(anchor='w', padx=12, pady=(0, 8))
        self.curve_text = self._text(right, 16)
        self.curve_text.pack(fill='both', expand=True, padx=(15, 0))
        ttk.Label(right, text='未给剩余质量时采用质量流量与推力成比例近似。计算模式不使用右侧曲线，也不会改写原曲线。',
                  wraplength=380, style='Subtitle.TLabel').pack(anchor='w', padx=15, pady=12)

    def _body_page(self):
        page = self.pages['箭体']
        left = ttk.Frame(page); left.pack(side='left', fill='both', expand=True, padx=(0, 20))
        right = ttk.Frame(page); right.pack(side='left', fill='both', expand=True)
        group = self._group(self._scroll(left), '圆锥头锥 · 等直径箭身 · 梯形尾翼')
        for path, label, factor in [
            ('diameter_m','箭体直径 / mm',1000), ('length_m','整箭总长 / mm',1000),
            ('nose_length_m','圆锥头锥长度 / mm',1000), ('drag_coefficient','箭体阻力系数 Cd',1),
            ('fin_count','尾翼数量（3 或 4）',1), ('fin_root_m','尾翼根弦 / mm',1000),
            ('fin_tip_m','尾翼梢弦 / mm',1000), ('fin_span_m','单片外露翼展 / mm',1000),
            ('fin_sweep_m','梢前缘后掠距离 / mm',1000), ('fin_position_m','根前缘距头尖 / mm',1000)]:
            self._field(group, 'body.'+path, label, factor)
        ttk.Label(right, text='整箭干质量分项', style='PanelTitle.TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Label(right, text='每行：部件名称, 质量(g), 重心距头锥尖端(mm)\n不含发动机干质量与推进剂，避免重复计入。',
                  style='Subtitle.TLabel', wraplength=460).pack(anchor='w', pady=(0, 12))
        self.parts_text = self._text(right, 16, font=(self.font, 9))
        self.parts_text.pack(fill='both', expand=True)
        ttk.Label(right, text='轴向坐标统一从头锥尖端向尾部为正。壳体几何计算得到的质量仅作参考；若采用该值，请在这里替换相应部件质量。',
                  wraplength=460, style='Subtitle.TLabel').pack(anchor='w', pady=16)

    def _structure_page(self):
        inner = self._scroll(self.pages['结构'])
        group = self._group(inner, '发动机壳体与端盖连接件 · 简化内压校核')
        self._field(group, 'structure.pressure_pa', '校核表压 / MPa（空白=用内弹道）', 1e-6, optional=True)
        for path, label, factor in [
            ('diameter_m','壳体内径 / mm',1000), ('thickness_m','壳体壁厚 / mm',1000),
            ('length_m','壳体长度 / mm',1000), ('density_kg_m3','壳体密度 / kg/m³',1),
            ('allowable_stress_pa','材料许用应力 / MPa',1e-6), ('safety_factor','额外安全系数',1),
            ('bolt_count','连接件数量',1), ('bolt_effective_area_m2','单件有效受拉面积 / mm²',1e6),
            ('bolt_allowable_pa','连接件许用应力 / MPa',1e-6)]:
            self._field(group, 'structure.'+path, label, factor)
        ttk.Label(inner, text='曲线模式没有室压数据时，校核表压必须单独给定，否则标为“未计算”。\n薄壁条件：壁厚 / 内半径 ≤ 0.1。连接件采用端盖轴向压力载荷与给定有效面积，不包含螺纹啮合、剪切、预紧与热效应。\n静稳定采用原始 Barrowman 小迎角近似，相关尺寸与质量在箭体页编辑。',
                  wraplength=990, style='Subtitle.TLabel').pack(anchor='w', pady=8)
        self.structure_text = tk.StringVar(value='运行后在结果页查看校核结果、压心和静稳定裕度。')
        ttk.Label(inner, textvariable=self.structure_text, wraplength=990).pack(anchor='w', pady=10)

    def _launch_page(self):
        inner = self._scroll(self.pages['发射'])
        group = self._group(inner, '竖直发射 · 静止空气')
        for path, label, factor in [('altitude_m','发射点绝对海拔 / m',1), ('rail_length_m','导轨长度 / m',1),
                                    ('temperature_k','海平面基准温度 / K',1), ('sea_level_pressure_pa','海平面基准压力 / kPa',.001)]:
            self._field(group, 'launch.'+path, label, factor)
        group = self._group(inner, '回收装置')
        self._field(group, 'recovery.mode', '开伞方式', choices={'apogee':'最高点后延时', 'altitude':'下降穿越指定高度', 'none':'不使用降落伞'})
        for path, label in [('delay_s','最高点后延时 / s'), ('deploy_altitude_m','下降开伞高度 / m（相对发射点）'),
                            ('area_m2','降落伞有效面积 / m²'), ('drag_coefficient','降落伞阻力系数 Cd')]:
            self._field(group, 'recovery.'+path, label)
        group = self._group(inner, '数值求解')
        for path, label in [('output_step_s','曲线输出间隔 / s'), ('max_step_s','积分最大步长 / s'),
                            ('rtol','积分相对容差'), ('max_time_s','最大仿真时间 / s')]:
            self._field(group, 'solver.'+path, label)
        ttk.Label(inner, text='高度统一相对发射点；大气密度按绝对海拔计算。降落伞采用瞬时展开近似，不预测真实开伞冲击载荷。',
                  wraplength=990, style='Subtitle.TLabel').pack(anchor='w')

    def _results_page(self):
        row = ttk.Frame(self.pages['结果'])
        row.pack(fill='x', pady=(0, 7))
        ttk.Label(row, textvariable=self.results_banner, style='Subtitle.TLabel').pack(side='left')
        self.popout_button = self.tool_button(row, '打开图表窗口', self.popout_plot, 'fit', state='disabled')
        self.popout_button.pack(side='right')
        strip = ttk.Frame(self.pages['结果'])
        strip.pack(fill='x', pady=(0, 8))
        self.result_metrics = {}
        for i, (key, title) in enumerate([('apogee_m','最高高度'), ('max_speed_m_s','最大速度'),
                                          ('flight_time_s','仿真时长'), ('landing_speed_m_s','落地速度')]):
            card = ttk.Frame(strip, style='Metric.TFrame', padding=(12, 5))
            card.grid(row=0, column=i, sticky='nsew', padx=(0, 5) if i < 3 else 0)
            strip.columnconfigure(i, weight=1, uniform='metric')
            ttk.Label(card, text=title, style='MetricCaption.TLabel').pack(anchor='w')
            value = tk.StringVar(value='—')
            self.result_metrics[key] = value
            ttk.Label(card, textvariable=value, style='MetricValue.TLabel').pack(anchor='w')
        panes = ttk.Panedwindow(self.pages['结果'], orient='horizontal'); panes.pack(fill='both', expand=True)
        self.results_split=panes
        left, right = ttk.Frame(panes,width=350,height=200), ttk.Frame(panes,width=700,height=200)
        left.pack_propagate(False);right.pack_propagate(False)
        panes.add(left, weight=1); panes.add(right, weight=3)
        self.result_text = tk.Text(left, width=30, font=(self.font, 9), wrap='word',
                                   bg=ui.INPUT, fg=ui.TEXT, relief='flat', padx=11, pady=9,
                                   selectbackground=ui.SELECTED, state='disabled')
        summary_bar=ttk.Scrollbar(left,command=self.result_text.yview)
        summary_bar.pack(side='right',fill='y')
        self.result_text.configure(yscrollcommand=summary_bar.set)
        self.result_text.pack(fill='both', expand=True, padx=(0, 10))
        self.plot_tabs = ttk.Notebook(right); self.plot_tabs.pack(fill='both', expand=True)
        self.plot_frames = {}
        for key, title in [('flight','飞行曲线'), ('motor','发动机'), ('stability','静稳定'), ('events','飞行事件')]:
            f = ttk.Frame(self.plot_tabs); self.plot_tabs.add(f, text=title); self.plot_frames[key] = f
        self.event_tree = ttk.Treeview(self.plot_frames['events'], columns=('event','time','height','speed'), show='headings')
        for key, label in [('event','事件'), ('time','时间 / s'), ('height','高度 / m'), ('speed','速度 / m/s')]:
            self.event_tree.heading(key, text=label); self.event_tree.column(key, width=110, anchor='center')
        self.event_tree.pack(fill='both', expand=True, padx=12, pady=12)
        self.plots_built = set()
        self.plot_tabs.bind('<<NotebookTabChanged>>', self._build_visible_plot)

    def _text_changed(self, widget):
        if widget.edit_modified():
            self.invalidate()
            widget.edit_modified(False)

    def invalidate(self):
        if self.loading:
            return
        self.revision += 1
        self.dirty = True
        self.stale = True
        self.export_button.state(['disabled'])
        self.status.set('参数已修改，运行仿真可更新结果。')
        self.results_banner.set('参数已修改 · 以下数据来自上次仿真' if self.result else '等待运行仿真')
        if hasattr(self,'preview_job'):
            self.root.after_cancel(self.preview_job)
        self.preview_job=self.root.after(350,self._update_live_preview)

    def _update_live_preview(self):
        try:
            self.project = self.get_project()
            self._sync_component_tree()
            self.draw_schematic()
        except ProjectError:
            pass

    def load_into_form(self, p):
        self.loading = True
        self.clear_results()
        self.project = copy.deepcopy(p)
        for path, variable in self.variables.items():
            factor, choices, boolean, optional, label, widget = self.fields[path]
            value = get_value(p, path)
            if boolean:
                variable.set(value)
            elif choices:
                variable.set(choices[value])
            elif value is None:
                variable.set('')
            elif isinstance(value, (float, int)):
                variable.set(f'{value*factor:.10g}')
            else:
                variable.set(value)
        self.curve_text.delete('1.0','end')
        self.curve_text.insert('1.0', '\n'.join(', '.join(f'{x:.10g}' for x in row) for row in p['motor']['curve']))
        self.parts_text.delete('1.0','end')
        self.parts_text.insert('1.0', '\n'.join(f"{x['name']}, {x['mass_kg']*1000:.10g}, {x['position_m']*1000:.10g}" for x in p['body']['parts']))
        self.curve_text.edit_modified(False); self.parts_text.edit_modified(False)
        self.loading = False
        self.invalidate()
        self.dirty = False
        self.status.set('项目已载入')
        self._update_title()
        self._sync_component_tree()
        self.draw_schematic()

    def _update_title(self):
        name = self.filepath.name if self.filepath else '未保存的新项目'
        self.root.title(f'{name} - 模型火箭设计与仿真')

    def _sync_component_tree(self):
        self.component_tree.item('rocket', text=' ' + self.project['name'])
        parts = self.project['body']['parts']
        children = self.component_tree.get_children('mass')
        for i, part in enumerate(parts):
            item = f'part_{i}'
            label = f" {part['name']} · {part['mass_kg']*1000:g} g"
            if self.component_tree.exists(item):
                self.component_tree.item(item, text=label)
            else:
                self.component_tree.insert('mass', 'end', iid=item, text=label, image=self.icon('part', ui.MUTED))
        if len(children) > len(parts):
            self.component_tree.delete(*children[len(parts):])

    def clear_results(self):
        self.result=None
        self.overview_text.set('等待有效的设计参数')
        self.structure_text.set('尚未运行当前项目的结构与静稳定计算。')
        self.result_text.configure(state='normal');self.result_text.delete('1.0','end')
        self.result_text.insert('1.0','尚未运行当前项目。');self.result_text.configure(state='disabled')
        for canvas in self.canvases:
            canvas.figure.clear()
        self.canvases=[]
        self.plots_built=set()
        for kind in ['flight','motor','stability']:
            for child in self.plot_frames[kind].winfo_children():
                child.destroy()
            placeholder = ttk.Label(self.plot_frames[kind], text='运行仿真后显示曲线', style='Subtitle.TLabel')
            placeholder.place(relx=.5, rely=.5, anchor='center')
        for child in self.event_tree.get_children():
            self.event_tree.delete(child)
        self.results_banner.set('等待运行仿真')
        self.popout_button.state(['disabled'])
        for value in self.result_metrics.values():
            value.set('—')

    def get_project(self):
        p = copy.deepcopy(self.project)
        for path, variable in self.variables.items():
            factor, choices, boolean, optional, label, widget = self.fields[path]
            raw = variable.get()
            try:
                if choices:
                    value = next(k for k, v in choices.items() if v == raw)
                elif boolean:
                    value = bool(raw)
                elif optional and not str(raw).strip():
                    value = None
                elif isinstance(get_value(default_project(), path), (float, int)) or optional:
                    value = float(raw)/factor
                else:
                    value = str(raw)
            except (ValueError, StopIteration) as e:
                widget.focus_set()
                raise ProjectError(f'{label}：请输入有效数值或选项（{path}）') from e
            put_value(p, path, value)
        try:
            curve = self.curve_text.get('1.0','end').strip()
            p['motor']['curve'] = [[float(v.strip()) for v in line.split(',')] for line in curve.splitlines() if line.strip()]
        except ValueError as e:
            raise ProjectError('推力曲线：每行需要逗号分隔的数值') from e
        parts = []
        for line in self.parts_text.get('1.0','end').splitlines():
            if not line.strip():
                continue
            values = line.split(',')
            try:
                name, mass, pos = values
                parts.append({'name':name.strip(), 'mass_kg':float(mass)/1000, 'position_m':float(pos)/1000})
            except ValueError as e:
                raise ProjectError('质量分项：每行需要“名称,质量(g),位置(mm)”') from e
        p['body']['parts'] = parts
        validate_project(p)
        return p

    def draw_schematic(self):
        if not hasattr(self, 'schematic'):
            return
        p = self.result['project'] if self.result and not self.stale else self.project
        body = p['body']
        c = self.schematic
        c.delete('all')
        width, height = c.winfo_width(), c.winfo_height()
        if width < 120 or height < 90:
            return
        length = body['length_m']
        radius = body['diameter_m']/2
        extent = radius + body['fin_span_m']
        scale = min((width - 145)/length, max(40, height - 98)/(2*extent))
        visible_length = length * scale
        x0, y = (width - visible_length)/2, height/2 + 8
        half = radius * scale
        nose = x0 + body['nose_length_m'] * scale
        tail = x0 + visible_length
        # Pick a readable ruler interval and use the same scale on both axes.
        desired = 96 / scale
        decade = 10 ** math.floor(math.log10(desired))
        step = next(v * decade for v in (1, 2, 5, 10) if v * decade >= desired)
        minor = step/5
        ruler = 32
        for tick in range(math.ceil((27-x0)/(minor*scale)), math.floor((width-14-x0)/(minor*scale))+1):
            xx = x0 + tick * minor * scale
            major = tick % 5 == 0
            c.create_line(xx, ruler, xx, height-13, fill='#2b384b' if major else '#1d2735')
            c.create_line(xx, ruler, xx, ruler+(8 if major else 4), fill=ui.DIM if major else ui.LINE)
            if major:
                c.create_text(xx, ruler-8, text=f'{tick*minor*100:g}', fill=ui.MUTED, font=('Consolas', 8))
        for tick in range(math.ceil((ruler-y)/(minor*scale)), math.floor((height-13-y)/(minor*scale))+1):
            yy = y + tick * minor * scale
            major = tick % 5 == 0
            c.create_line(27, yy, width-14, yy, fill='#2b384b' if major else '#1d2735')
        c.create_line(27, ruler, width-14, ruler, fill=ui.LINE)
        c.create_line(27, ruler, 27, height-13, fill=ui.LINE)
        c.create_text(9, ruler-8, text='cm', fill=ui.MUTED, anchor='w', font=('Consolas', 8))

        def paint(key):
            if self.active_component == key:
                return {'fill': '#324e70', 'outline': '#b8d7ff', 'width': 2}
            return {'fill': '#23334a', 'outline': '#87abe0', 'width': 1.6}

        c.create_polygon(x0, y, nose, y-half, nose, y+half, tags=('nose', 'component'), **paint('nose'))
        c.create_rectangle(nose, y-half, tail, y+half, tags=('tube', 'component'), **paint('tube'))
        fx = x0 + body['fin_position_m'] * scale
        root = body['fin_root_m'] * scale
        sweep = body['fin_sweep_m'] * scale
        tip = body['fin_tip_m'] * scale
        for sign in (-1, 1):
            c.create_polygon(fx, y+sign*half, fx+root, y+sign*half,
                             fx+sweep+tip, y+sign*extent*scale, fx+sweep, y+sign*extent*scale,
                             tags=('fins', 'component'), **paint('fins'))
        c.create_line(27,y,width-14,y,fill='#52657f',dash=(8,6))
        mx = x0 + p['motor']['position_m'] * scale
        motor_color = '#ffd9a3' if self.active_component == 'motor' else '#bf9b75'
        motor_half = min(.04, length / 8)*scale
        c.create_rectangle(max(x0,mx-motor_half), y-half*.6, min(tail,mx+motor_half), y+half*.6,
                           outline=motor_color, dash=(4,3), tags=('motor','component'))
        c.tag_bind('component', '<Double-1>', self._open_preview_component)

        caption = f"全长 {length*1000:g} mm   ·   直径 {body['diameter_m']*1000:g} mm"
        c.create_text(42, 53, text=caption, fill=ui.MUTED, anchor='w', font=(self.font, 8))
        analysis = self._preview_analysis(p)
        if analysis and self.show_markers.get() and height > 105:
            marks = [(analysis['cg_initial_m'],'重心',ui.ACCENT), (analysis['cp_m'],'压心','#f2a2a0')]
            for index, (position, label, color) in enumerate(marks):
                xx = x0 + position*scale
                direction = -1 if index == 0 else 1
                label_y = y + direction * (half + 26)
                c.create_line(xx, y, xx, label_y - direction*9, fill=color, dash=(3,3))
                c.create_oval(xx-5,y-5,xx+5,y+5,fill=ui.VIEW,outline=color,width=2)
                c.create_text(xx,label_y,text=label,fill=color,font=(self.font,8))
        if analysis:
            self.overview_text.set(f"起飞质量 {analysis['initial_mass_kg']*1000:.1f} g   ·   静稳定裕度 {analysis['stability_initial_cal']:.2f} cal")
        else:
            self.overview_text.set('质量与静稳定数据待更新')

    def _preview_analysis(self, project):
        if self.result and not self.stale:
            return self.result['analysis']
        if getattr(self, 'preview_project', None) is not project:
            self.preview_project = project
            self.preview_analysis = None
            try:
                from .analysis import analyze
                self.preview_analysis = analyze(project, build_motor(project))
            except (ValueError, ArithmeticError):
                pass
        return self.preview_analysis

    def _open_preview_component(self, event):
        current = self.schematic.find_withtag('current')
        if current:
            self.open_component(self.schematic.gettags(current[0])[0])

    def _guard(self, function):
        try:
            return function()
        except Exception as e:
            messagebox.showerror('操作未完成', str(e), parent=self.root)
            return None

    def new_project(self):
        if self.busy:
            self.status.set('仿真计算中，请先取消或等待完成后再新建项目。')
            return
        if not self._confirm_discard():
            return
        p = default_project()
        p['name'] = '未命名火箭项目'
        p['notes'] = ''
        self.filepath = None
        self.result = None
        self.load_into_form(p)
        self.component_tree.selection_set('rocket')
        self.component_tree.focus('rocket')
        self.show_page('概览')
        self.status.set('已新建项目（参数取自默认模板，可在组件树中逐项修改）')

    def open_project(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(filetypes=[('火箭项目','*.json')], parent=self.root)
        if path:
            def action():
                p = load_project(path)
                if not self._confirm_discard():
                    return
                self.filepath = Path(path); self.result = None
                self.load_into_form(p)
                self.show_page('概览')
            self._guard(action)

    def save(self):
        def action():
            p = self.get_project()
            path = filedialog.asksaveasfilename(defaultextension='.json', initialfile=(self.filepath.name if self.filepath else '火箭项目.json'), filetypes=[('火箭项目','*.json')], parent=self.root)
            if path:
                save_project(p, path); self.filepath = Path(path)
                self.dirty=False
                self._update_title()
                self.status.set('项目已保存：'+path)
                return True
            return False
        return self._guard(action)

    def _confirm_discard(self):
        if not self.dirty:
            return True
        answer=messagebox.askyesnocancel('未保存的项目','是否保存当前项目？\n“否”放弃编辑，“取消”保留当前项目。',parent=self.root)
        if answer is None:
            return False
        return bool(self.save()) if answer else True

    def check(self):
        def action():
            p = self.get_project(); m = build_motor(p)
            self.project = p; self.draw_schematic()
            self.status.set(f'参数检查通过 · 总冲 {m.total_impulse_ns:.3f} N·s · 推进剂 {m.propellant_mass_kg*1000:.2f} g')
        self._guard(action)

    def import_motor(self):
        path = filedialog.askopenfilename(filetypes=[('推力曲线','*.csv *.eng'),('CSV','*.csv'),('RASP','*.eng')], parent=self.root)
        if not path:
            return
        def action():
            if Path(path).suffix.lower() == '.eng':
                records = read_eng(path)
                index = 0
                if len(records) > 1:
                    label='\n'.join(f"{i+1}. {r['name']}" for i,r in enumerate(records))
                    selected=simpledialog.askinteger('选择发动机记录',label+'\n输入记录序号：',minvalue=1,maxvalue=len(records),parent=self.root)
                    if selected is None:
                        return
                    index=selected-1
                record=records[index]
                curve=record['curve']
            else:
                record=None; curve=read_curve(path)
            # Validate prospective input before replacing the editor.
            p=self.get_project(); p['motor'].update(mode='curve',curve=curve)
            if record:
                p['motor'].update(propellant_mass_kg=record['propellant_mass_kg'],dry_mass_kg=record['dry_mass_kg'])
            build_motor(p)
            self.load_into_form(p)
            self.dirty = True
            self.status.set('已导入发动机曲线 · '+Path(path).name)
        self._guard(action)

    def run(self):
        if self.busy:
            return
        p=self._guard(self.get_project)
        if p is None:
            return
        self.project=copy.deepcopy(p)
        self.busy=True; self.cancel.clear(); self.run_revision=self.revision
        self.run_button.state(['disabled']); self.cancel_button.state(['!disabled']); self.export_button.state(['disabled'])
        self.cancel_button.pack(side='right', padx=(6, 6), before=self.run_button)
        self.progress.pack(side='right', padx=(6, 3))
        self.status.set('正在计算发动机、结构、静稳定与飞行回收…'); self.progress.start(40)
        def work():
            try:
                self.messages.put(('result',run_project(p,self.cancel)))
            except Exception as e:
                self.messages.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()

    def _poll(self):
        try:
            kind,payload=self.messages.get_nowait()
            self.busy=False; self.progress.stop(); self.run_button.state(['!disabled']); self.cancel_button.state(['disabled'])
            self.progress.pack_forget()
            self.cancel_button.pack_forget()
            if kind=='result':
                self.show_page('结果');self.root.update_idletasks()
                self.apply_result(payload)
                if self.revision != self.run_revision:
                    self.invalidate()
                self.show_page('结果')
                if self.smoke_path:
                    self.root.after(800,self._finish_smoke)
            else:
                self.status.set(payload)
                if self.smoke_path:
                    self.smoke_path.mkdir(parents=True,exist_ok=True)
                    (self.smoke_path/'error.txt').write_text(payload,encoding='utf-8')
                    self._close()
                    return
                elif not self.cancel.is_set():
                    messagebox.showerror('计算未完成',payload,parent=self.root)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.poll_id=self.root.after(100,self._poll)

    def apply_result(self, result):
        self.result=result; self.stale=False
        flight = result['flight']
        self.results_banner.set(STATUS_LABELS[flight['status']] + (' · 超出模型适用范围' if not flight['valid_subsonic'] else ' · 当前仿真结果'))
        for key, variable in self.result_metrics.items():
            value = flight['summary'][key]
            unit = {'apogee_m': 'm', 'flight_time_s': 's'}.get(key, 'm/s')
            variable.set(f'{value:.2f} {unit}' if value is not None else '—')
        self.popout_button.state(['!disabled'])
        self.result_text.configure(state='normal'); self.result_text.delete('1.0','end')
        self.result_text.insert('1.0', summary_text(result, include_overview=False))
        self.result_text.configure(state='disabled')
        for canvas in self.canvases:
            canvas.figure.clear()
        self.canvases=[]
        self.plots_built=set()
        for kind in ['flight','motor','stability']:
            for child in self.plot_frames[kind].winfo_children():
                child.destroy()
        # Build figures lazily: only the tab being viewed is rendered now.
        self._build_visible_plot()
        for row in self.event_tree.get_children():
            self.event_tree.delete(row)
        for e in result['flight']['events']:
            self.event_tree.insert('', 'end', values=(EVENT_LABELS[e['event']],f"{e['time_s']:.4f}",f"{e['altitude_m']:.3f}",f"{e['velocity_m_s']:.3f}"))
        a=result['analysis']
        self.structure_text.set(f"压心 {a['cp_m']*1000:.1f} mm；点火/燃尽重心 {a['cg_initial_m']*1000:.1f} / {a['cg_burnout_m']*1000:.1f} mm。\n"
                                f"结构状态详见结果页。几何壳体参考质量 {a['structure']['shell_mass_kg']*1000:.2f} g（未自动计入质量表）。")
        self.export_button.state(['!disabled'])
        self.status.set('仿真完成 · '+STATUS_LABELS[flight['status']])
        self.arrange_panes()
        self.draw_schematic()

    def _build_visible_plot(self, event=None):
        if not self.result:
            return
        selected=self.plot_tabs.select()
        kind=next((k for k,v in self.plot_frames.items() if str(v)==selected),'flight')
        self._build_plot(kind)

    def _build_plot(self, kind):
        if kind not in ('flight','motor','stability') or kind in self.plots_built or not self.result:
            return
        self.plots_built.add(kind)
        parent=self.plot_frames[kind]
        for child in parent.winfo_children():
            child.destroy()
        fig=make_figure(self.result,'flight_combined' if kind=='flight' else kind)
        ui.style_plot(fig)
        canvas=FigureCanvasTkAgg(fig,master=parent)
        toolbar=ChineseToolbar(canvas,parent,pack_toolbar=False)
        toolbar.pack(side='bottom',fill='x'); canvas.get_tk_widget().pack(fill='both',expand=True)
        canvas.draw_idle(); self.canvases.append(canvas)
        if hasattr(self,'fit_job'):
            self.root.after_cancel(self.fit_job)
        self.fit_job=self.root.after(120,self.fit_plots)

    def popout_plot(self):
        if not self.result:
            return
        selected=self.plot_tabs.select()
        kind=next((k for k,v in self.plot_frames.items() if str(v)==selected),'flight')
        if kind=='events':
            kind='flight'
        top=tk.Toplevel(self.root);top.title('仿真图表'+(' · 上次结果（参数已修改）' if self.stale else ''))
        top.geometry(f"{min(1200, top.winfo_screenwidth()-70)}x{min(720, top.winfo_screenheight()-90)}")
        top.configure(bg=ui.PANEL)
        fig=make_figure(self.result,'flight_combined' if kind=='flight' else kind)
        ui.style_plot(fig)
        canvas=FigureCanvasTkAgg(fig,master=top)
        toolbar=ChineseToolbar(canvas,top,pack_toolbar=False);toolbar.pack(side='bottom',fill='x')
        canvas.get_tk_widget().pack(fill='both',expand=True);canvas.draw()
        top.protocol('WM_DELETE_WINDOW',lambda:(fig.clear(),top.destroy()))

    def export(self):
        if not self.result or self.stale:
            return
        folder=filedialog.askdirectory(title='选择报告保存位置（将新建本次报告子目录）',parent=self.root)
        if folder:
            from datetime import datetime
            target=Path(folder)/('火箭仿真报告_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            path=self._guard(lambda: __import__('rocket.report',fromlist=['export_report']).export_report(self.result,target))
            if path:
                self.status.set('报告已导出：'+str(path))
                messagebox.showinfo('报告已导出',str(path)+'\n用浏览器打开 report.html，可打印为 PDF。',parent=self.root)

    def _close(self):
        if not self.smoke_path and not self._confirm_discard():
            return
        self.cancel.set()
        try:
            self.root.after_cancel(self.poll_id)
            if hasattr(self,'preview_job'):
                self.root.after_cancel(self.preview_job)
            for key in ['layout_job','show_layout_job','fit_job','repaint_job']:
                if hasattr(self,key):
                    self.root.after_cancel(getattr(self,key))
        except (tk.TclError,AttributeError):
            pass
        self.root.destroy()

    def start_smoke_test(self,path):
        self.smoke_path=Path(path)
        self.root.after(720, self._capture_opening_view)
        self.root.after(1050,self.run)

    def _capture_opening_view(self):
        self.smoke_path.mkdir(parents=True, exist_ok=True)
        self._capture_window(self.smoke_path/'app-overview.png')

    def _capture_window(self, path):
        from PIL import ImageGrab

        self.root.update_idletasks()
        self.repaint_window()
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.dwmapi.DwmFlush()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        box = (x, y, x + self.root.winfo_width(), y + self.root.winfo_height())
        ImageGrab.grab(bbox=box, include_layered_windows=True).save(path)

    def _finish_smoke(self):
        from .report import export_report
        d=self.smoke_path; d.mkdir(parents=True,exist_ok=True)
        export_report(self.result,d/'report')
        def capture(name):
            self._capture_window(d/f'app-{name}.png')

        def compact():
            width, height = self.root.minsize()
            self.root.geometry(f'{width}x{height}')
            self.show_page('概览')

        views = [('results', lambda: self.show_page('结果')),
                 ('inspector', lambda: self.open_component('fins')), ('design', lambda: self.show_page('概览')),
                 ('motor', lambda: self.show_page('发动机')),
                 ('compact', compact)]

        def next_view(index):
            if index == len(views):
                snapshot = {'ok': True, 'summary': self.result['flight']['summary'], 'status': self.result['flight']['status']}
                (d/'smoke.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
                self._close()
                return
            name, display = views[index]
            display()
            self.root.after(300, lambda: capture_then_advance(name, index))

        def capture_then_advance(name, index):
            capture(name)
            next_view(index + 1)

        next_view(0)
