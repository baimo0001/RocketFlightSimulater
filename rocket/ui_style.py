"""Desktop palette, typography, and small vector-style control icons."""

import tkinter as tk
from tkinter import font, ttk

from PIL import Image, ImageDraw, ImageTk


BG = '#191e26'
PANEL = '#222934'
SURFACE = '#282f3b'
INPUT = '#1a2029'
LINE = '#384353'
TEXT = '#e1e8f2'
MUTED = '#a8b5c8'
DIM = '#8998ad'
ACCENT = '#83b6ff'
BLUE = '#3268b9'
SELECTED = '#2e486c'
WARNING = '#edbd79'
GREEN = '#7bd6bb'
VIEW = '#151c27'


def configure_theme(root):
    available = set(font.families(root))
    family = next((name for name in ('Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC')
                   if name in available), 'TkDefaultFont')
    regular = (family, 9)
    bold = (family, 9, 'bold')
    root.configure(bg=BG)
    root.option_add('*Font', regular)
    root.option_add('*Listbox.background', INPUT)
    root.option_add('*Listbox.foreground', TEXT)
    root.option_add('*Listbox.selectBackground', SELECTED)
    root.option_add('*Listbox.selectForeground', TEXT)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=regular, background=PANEL, foreground=TEXT,
                    bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL, troughcolor=INPUT,
                    selectbackground=SELECTED, selectforeground=TEXT, focuscolor=ACCENT)
    style.configure('Shell.TFrame', background=BG)
    style.configure('Shell.TLabel', background=BG, foreground=MUTED)
    style.configure('Brand.TLabel', background=BG, foreground=TEXT, font=(family, 12, 'bold'))
    style.configure('PanelTitle.TLabel', font=(family, 11, 'bold'))
    style.configure('Subtitle.TLabel', foreground=MUTED)
    style.configure('Warning.TLabel', foreground=WARNING)
    style.configure('Metric.TFrame', background=SURFACE)
    style.configure('MetricCaption.TLabel', background=SURFACE, foreground=MUTED, font=(family, 8))
    style.configure('MetricValue.TLabel', background=SURFACE, foreground=TEXT, font=('Segoe UI', 12, 'bold'))
    style.configure('TButton', background=SURFACE, borderwidth=1, padding=(8, 4), anchor='center', width=0)
    style.map('TButton', background=[('disabled', PANEL), ('pressed', SELECTED), ('active', '#354357')],
              foreground=[('disabled', DIM)], bordercolor=[('focus', ACCENT), ('active', '#526888')])
    style.configure('Primary.TButton', font=bold, background=BLUE, foreground='#ffffff',
                    bordercolor='#4c83d0', padding=(11, 4))
    style.map('Primary.TButton', background=[('disabled', SURFACE), ('pressed', '#285696'), ('active', '#3d79cf')],
              foreground=[('disabled', DIM)], bordercolor=[('focus', ACCENT), ('active', ACCENT)])
    style.configure('Tool.TButton', padding=(7, 4))
    style.configure('Component.TButton', padding=(8, 7), font=bold)
    style.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    tab_surfaces = []
    for color, edge in [(BG, LINE), (PANEL, ACCENT), (SURFACE, LINE)]:
        surface = Image.new('RGB', (8, 8), color)
        ImageDraw.Draw(surface).rectangle((0, 6, 7, 7), fill=edge)
        tab_surfaces.append(ImageTk.PhotoImage(surface, master=root))
    root.nebula_tab_surfaces = tab_surfaces
    normal, selected, hover = tab_surfaces
    style.element_create('NebulaTab.surface', 'image', normal, ('selected', selected),
                         ('active', hover), border=3, sticky='nsew')
    style.layout('TNotebook.Tab', [('NebulaTab.surface', {'sticky': 'nsew', 'children': [
        ('Notebook.padding', {'sticky': 'nsew', 'children': [('Notebook.label', {'sticky': 'nsew'})]})]})])
    style.configure('TNotebook.Tab', background=BG, foreground=MUTED, padding=(13, 6), borderwidth=0)
    style.map('TNotebook.Tab', background=[('selected', PANEL), ('active', SURFACE)],
              foreground=[('selected', ACCENT), ('active', TEXT)])
    style.configure('Workspace.TNotebook.Tab', padding=(17, 8), font=(family, 10, 'bold'))
    style.configure('TEntry', fieldbackground=INPUT, insertcolor=TEXT, padding=(7, 4))
    style.map('TEntry', bordercolor=[('focus', ACCENT)])
    style.configure('TCombobox', fieldbackground=INPUT, arrowcolor=MUTED, padding=(7, 4))
    style.map('TCombobox', fieldbackground=[('readonly', INPUT)], foreground=[('readonly', TEXT)],
              selectbackground=[('readonly', INPUT)], selectforeground=[('readonly', TEXT)],
              bordercolor=[('focus', ACCENT)])
    style.configure('TCheckbutton', indicatorbackground=INPUT, indicatorforeground=TEXT,
                    indicatorcolor=INPUT, padding=(3, 2))
    style.map('TCheckbutton', background=[('active', PANEL)],
              indicatorbackground=[('selected', BLUE)], indicatorcolor=[('selected', BLUE)])
    style.configure('TLabelframe', background=PANEL, borderwidth=1, relief='solid')
    style.configure('TLabelframe.Label', foreground=MUTED, background=PANEL, font=bold)
    style.configure('Treeview', fieldbackground=INPUT, background=INPUT, foreground=TEXT,
                    rowheight=max(23, int(root.winfo_fpixels('1p') * 14)), borderwidth=1, padding=3)
    style.map('Treeview', background=[('selected', SELECTED)], foreground=[('selected', '#ffffff')])
    style.configure('Treeview.Heading', font=bold, background=SURFACE, relief='flat', padding=(5, 5))
    style.map('Treeview.Heading', background=[('active', SURFACE)])
    style.configure('Vertical.TScrollbar', background=SURFACE, arrowcolor=MUTED, gripcount=0, width=13)
    style.map('Vertical.TScrollbar', background=[('active', '#435166')])
    style.configure('TPanedwindow', background=LINE, sashthickness=5)
    style.configure('TSeparator', background=LINE)
    style.configure('Horizontal.TProgressbar', background=BLUE, borderwidth=0, thickness=4)
    return family


def make_icon(root, name, color=ACCENT, points=12):
    """Draw an original pictogram on a proportionally scaled 24-unit grid."""
    size = max(14, round(root.winfo_fpixels(f'{points}p')))
    image = Image.new('RGBA', (96, 96))
    draw = ImageDraw.Draw(image)

    def line(*coords):
        draw.line([(x * 4, y * 4) for x, y in coords], fill=color, width=6, joint='curve')

    def box(x1, y1, x2, y2):
        draw.rounded_rectangle((x1*4, y1*4, x2*4, y2*4), radius=4, outline=color, width=6)

    if name in ('project', 'stage', 'nose'):
        line((2, 12), (10, 6), (20, 6), (20, 18), (10, 18), (2, 12))
        if name != 'nose':
            line((10, 6), (10, 18))
        if name == 'project':
            line((20, 9), (23, 6), (23, 18), (20, 15))
    elif name in ('tube', 'motor', 'mass', 'part', 'structure'):
        box(4, 6, 20, 18)
        if name in ('tube', 'motor', 'structure'):
            line((8, 6), (8, 18)); line((16, 6), (16, 18))
        else:
            line((9, 6), (9, 3), (15, 3), (15, 6))
    elif name == 'fins':
        line((3, 19), (12, 5), (19, 5), (22, 19), (3, 19))
    elif name == 'recovery':
        line((3, 12), (5, 7), (9, 5), (15, 5), (19, 7), (21, 12), (3, 12), (12, 21), (21, 12))
        line((9, 12), (12, 21), (15, 12))
    elif name == 'open':
        line((3, 19), (3, 5), (10, 5), (13, 8), (21, 8), (21, 12))
        line((3, 19), (7, 11), (23, 11), (19, 19), (3, 19))
    elif name == 'save':
        box(4, 4, 20, 20); line((8, 4), (8, 10), (16, 10), (16, 4)); box(8, 14, 16, 20)
    elif name == 'new':
        line((5, 3), (14, 3), (19, 8), (19, 21), (5, 21), (5, 3))
        line((14, 3), (14, 8), (19, 8)); line((8, 14), (16, 14)); line((12, 10), (12, 18))
    elif name == 'run':
        draw.polygon([(8*4, 4*4), (20*4, 12*4), (8*4, 20*4)], fill=color)
    elif name == 'edit':
        line((4, 19), (7, 12), (16, 3), (21, 8), (12, 17), (4, 19)); line((14, 5), (19, 10))
    elif name == 'add':
        line((5, 12), (19, 12)); line((12, 5), (12, 19))
    elif name == 'check':
        line((4, 12), (10, 18), (21, 6))
    elif name == 'export':
        line((5, 13), (5, 20), (20, 20), (20, 13)); line((12, 16), (12, 4), (8, 8))
        line((12, 4), (16, 8))
    elif name == 'fit':
        line((4, 9), (4, 4), (9, 4)); line((15, 4), (20, 4), (20, 9))
        line((4, 15), (4, 20), (9, 20)); line((15, 20), (20, 20), (20, 15))
    return ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=root)


def style_plot(figure):
    """Style embedded plots without changing the exported report theme."""
    figure.set_facecolor(VIEW)
    colors = {'#087f8c': '#67b3f1', '#2479b5': '#83b6ff', '#74a222': GREEN,
              '#d08b26': WARNING, '#b8802c': WARNING, '#c44444': '#e6819b'}
    for axis in figure.axes:
        axis.set_facecolor(VIEW)
        axis.tick_params(colors=MUTED, labelsize=9)
        axis.xaxis.label.set_color(MUTED)
        axis.yaxis.label.set_color(MUTED)
        for spine in axis.spines.values():
            spine.set_color(LINE)
        for grid_line in axis.get_xgridlines() + axis.get_ygridlines():
            grid_line.set_color('#48566e')
        for line in axis.lines:
            line.set_color(colors.get(line.get_color(), line.get_color()))
        for label in axis.texts:
            label.set_color(TEXT)
        legend = axis.get_legend()
        if legend:
            legend.get_frame().set_facecolor(PANEL)
            legend.get_frame().set_edgecolor(LINE)
            for text in legend.get_texts():
                text.set_color(TEXT)
            for line in legend.get_lines():
                line.set_color(colors.get(line.get_color(), line.get_color()))
