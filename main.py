import tkinter as tk
from tkinter import ttk
from sim_runner import run_voxelyze
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.backend_bases import NavigationToolbar2
import matplotlib
matplotlib.use('TkAgg')
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Grid dimensions ───────────────────────────────────────────
X, Y = 20, 20

# ── History state ─────────────────────────────────────────────
history    = []
redo_stack = []

# ── Color map ─────────────────────────────────────────────────
COLOR_EMPTY = [1.0, 1.0, 1.0, 1.0]  # white

# ── Grid data (0 = empty, 1 = painted) ───────────────────────
grid = np.zeros((Y, X), dtype=int)
active_material = {'name': 'MagSoElas_default', 'id': 1}

# ── File management state ─────────────────────────────────────
current_file = None
has_unsaved_changes = False

# ── Clipboard for Edit menu ───────────────────────────────────
clipboard = {'data': None, 'mag': {}, 'offset_x': 0, 'offset_y': 0}

# ── Per-voxel magnetisation grid ──────────────────────────────
# None = use default alternating pattern
# (Mx, My, Mz) = custom magnetisation direction
mag_grid = {}  # dict: (ix, iy) → (Mx, My, Mz)

# Arrow overlay artist
mag_arrow_artists = []
mag_hover_voxel   = {'pos': None}  # currently hovered voxel

# Varialbes for alternating magnetisation pattern in mag tool
alternator_axis = 'z'
alternator_counter = 0

# ── RGBA image array ──────────────────────────────────────────
def make_image(g):
    """Convert grid int array → RGBA float array for imshow."""
    img = np.ones((g.shape[0], g.shape[1], 4))
    img[g == 0] = COLOR_EMPTY
    for name, props in materials.items():
        mid   = props['id']
        color = props['color']
        # convert hex color to RGBA
        r = int(color[1:3], 16) / 255
        green = int(color[3:5], 16) / 255
        b = int(color[5:7], 16) / 255
        img[g == mid] = [r, green, b, 1.0]
    return img

# ── Helper Functions for Menu Features ────────────────────────

def mark_unsaved():
    """Mark the document as having unsaved changes."""
    global has_unsaved_changes
    has_unsaved_changes = True
    _update_window_title()

def _update_window_title():
    """Update window title with file name and unsaved indicator."""
    title = "Magnetic Soft Materials Designer"
    if current_file:
        filename = os.path.basename(current_file)
        title = f"{filename} - {title}"
    if has_unsaved_changes:
        title = "● " + title
    root.title(title)

def new_file():
    """Create a new grid (reset to default)."""
    global grid, X, Y, history, redo_stack, current_file, has_unsaved_changes
    
    if has_unsaved_changes:
        from tkinter import messagebox
        response = messagebox.askyesno("Unsaved Changes", 
                                        "Do you want to save changes before creating a new file?")
        if response:
            save_file()
    
    X, Y = 20, 20
    grid = np.zeros((Y, X), dtype=int)
    mag_grid.clear()
    clear_mag_arrows()
    mag_hover_voxel['pos'] = None
    history.clear()
    redo_stack.clear()
    current_file = None
    has_unsaved_changes = False
    
    # Update display
    im.set_data(make_image(grid))
    im.set_extent([0, X, 0, Y])
    ax.set_xlim(0, X)
    ax.set_ylim(0, Y)
    draw_grid_lines()
    ax.set_xlabel('X — Voxel Index', loc='right', fontsize=8)
    ax.set_ylabel('Y — Voxel Index', loc='top', fontsize=8)
    canvas.draw()
    
    _update_window_title()
    set_status("New file created", 'green')

def save_file():
    global current_file, has_unsaved_changes
    
    if current_file is None:
        return save_file_as()
    
    try:
        import json
        data = {
            'grid':            grid.tolist(),
            'X':               X,
            'Y':               Y,
            'materials':       materials,
            'active_material': active_material,
            'next_mat_id':     next_mat_id['val'],
            'mag_grid':        {f"{k[0]},{k[1]}": list(v)
                        for k, v in mag_grid.items()},
            'sim_params': {
                'SIM_TIME':        param_entries['SIM_TIME'].get(),
                'DT_FRAC':         param_entries['DT_FRAC'].get(),
                'KIN_E_THRESHOLD': param_entries['KIN_E_THRESHOLD'].get(),
                'DAMPING_BOND_Z':  param_entries['DAMPING_BOND_Z'].get(),
                'COL_BOND_Z':      param_entries['COL_BOND_Z'].get(),
                'SLOW_BOND_Z':     param_entries['SLOW_BOND_Z'].get(),
                'GRAVITY_ENABLED': param_entries['GRAVITY_ENABLED'].get(),
                'IS_MAG_FORCE_ON': param_entries['IS_MAG_FORCE_ON'].get(),
            }
        }
        with open(current_file, 'w') as f:
            json.dump(data, f, indent=2)

        has_unsaved_changes = False
        _update_window_title()
        set_status(f"Saved: {os.path.basename(current_file)}", 'green')
        return True
    except Exception as e:
        from tkinter import messagebox
        messagebox.showerror("Error", f"Failed to save: {str(e)}")
        return False

def save_file_as():
    """Save the current grid to a new file."""
    global current_file
    
    from tkinter import filedialog
    filepath = filedialog.asksaveasfilename(
        defaultextension=".vsm",
        initialfile="untitled.vsm",
        filetypes=[("Vox Sim File", "*.vsm"),
                   ("JSON File", "*.json"),
                   ("All Files", "*.*")])
    
    if not filepath:
        return False
    
    current_file = filepath
    return save_file()

def open_file():
    global grid, X, Y, history, redo_stack, current_file
    global has_unsaved_changes, materials, active_material

    if has_unsaved_changes:
        from tkinter import messagebox
        response = messagebox.askyesno("Unsaved Changes",
                                        "Save changes before opening?")
        if response:
            save_file()

    from tkinter import filedialog
    filepath = filedialog.askopenfilename(
        filetypes=[("Vox Sim File", "*.vsm"),
                   ("JSON File",    "*.json"),
                   ("All Files",    "*.*")])
    if not filepath:
        return

    try:
        import json
        with open(filepath, 'r') as f:
            data = json.load(f)

        # ── Restore grid ──────────────────────────────────────
        X    = data.get('X', 20)
        Y    = data.get('Y', 20)
        grid = np.array(data.get('grid', np.zeros((Y, X))), dtype=int)

        # ── Restore materials ─────────────────────────────────
        loaded_mats = data.get('materials', {})
        materials.clear()
        for name, props in loaded_mats.items():
            # Convert lists back to floats in case JSON changed types
            materials[name] = {
                'id':          int(props['id']),
                'color':       props['color'],
                'LATTICE_DIM': float(props['LATTICE_DIM']),
                'ELASTIC_MOD': float(props['ELASTIC_MOD']),
                'DENSITY':     float(props['DENSITY']),
                'POISSONS':    float(props['POISSONS']),
                'M_PER_VOL':   float(props['M_PER_VOL']),
            }

        mag_grid.clear()
        saved_mag = data.get('mag_grid', {})
        for key_str, vec in saved_mag.items():
            ix, iy = map(int, key_str.split(','))
            mag_grid[(ix, iy)] = tuple(vec)

        # ── Restore active material ───────────────────────────
        saved_active = data.get('active_material', {})
        active_material['name'] = saved_active.get(
            'name', list(materials.keys())[0])
        active_material['id']   = saved_active.get('id', 1)

        # ── Restore next material ID ──────────────────────────
        next_mat_id['val'] = data.get('next_mat_id', 
                             max(p['id'] for p in materials.values()) + 1)

        # ── Restore sim params ────────────────────────────────
        sim_params = data.get('sim_params', {})
        for key, ent in param_entries.items():
            if key in sim_params:
                ent.delete(0, tk.END)
                ent.insert(0, sim_params[key])

        # ── Clear history ─────────────────────────────────────
        history.clear()
        redo_stack.clear()
        current_file        = filepath
        has_unsaved_changes = False

        # ── Update display ────────────────────────────────────
        refresh_listbox()                       # rebuild material list
        sel_overlay.set_data(np.zeros((Y, X, 4)))
        sel_overlay.set_extent([0, X, 0, Y])
        selected_voxels.clear()
        _clear_sel_rect()

        im.set_data(make_image(grid))           # uses restored materials
        im.set_extent([0, X, 0, Y])
        ax.set_xlim(0, X)
        ax.set_ylim(0, Y)
        ax.set_aspect('equal')
        draw_grid_lines()
        ax.set_xlabel('X — Voxel Index', loc='right', fontsize=8)
        ax.set_ylabel('Y — Voxel Index', loc='top', fontsize=8)
        canvas.draw()

        _update_window_title()
        set_status(f"Opened: {os.path.basename(filepath)}", 'green')

    except Exception as e:
        from tkinter import messagebox
        messagebox.showerror("Error", f"Failed to open: {str(e)}")

def do_cut():
    if not selected_voxels:
        set_status("Select voxels first!", 'orange')
        return
    clipboard['data'] = {pos: int(grid[pos[1], pos[0]])
                         for pos in selected_voxels
                         if grid[pos[1], pos[0]] != 0}
    clipboard['mag'] = {pos: mag_grid[pos]
                        for pos in selected_voxels
                        if pos in mag_grid}
    cut_snapshot = []
    for ix, iy in selected_voxels:
        if grid[iy, ix] != 0:
            cut_snapshot.append((ix, iy, int(grid[iy, ix])))
            grid[iy, ix] = 0
    history.append(cut_snapshot)
    redo_stack.clear()
    im.set_data(make_image(grid))
    canvas.draw_idle()
    mark_unsaved()
    clear_selection()
    set_status(f"Cut {len(clipboard['data'])} voxels", 'green')

def do_copy():
    if not selected_voxels:
        set_status("Select voxels first!", 'orange')
        return
    clipboard['data'] = {pos: int(grid[pos[1], pos[0]])
                         for pos in selected_voxels
                         if grid[pos[1], pos[0]] != 0}
    clipboard['mag'] = {pos: mag_grid[pos]
                        for pos in selected_voxels
                        if pos in mag_grid}
    set_status(f"Copied {len(clipboard['data'])} voxels", 'green')

def do_paste():
    if not clipboard['data']:
        set_status("Clipboard is empty", 'orange')
        return
    if not selected_voxels:
        set_status("Select a target area first, then paste", 'orange')
        return
    _paste_at_selection_center()

def select_all():
    global selected_voxels
    selected_voxels = {(ix, iy) for ix in range(X) for iy in range(Y)}
    draw_selection_highlight()
    set_status(f"Selected all {len(selected_voxels)} voxels", '#0078d7')

def zoom_in():
    """Zoom in on the grid."""
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    xcenter = (xlim[0] + xlim[1]) / 2
    ycenter = (ylim[0] + ylim[1]) / 2
    factor = 0.8
    
    ax.set_xlim([xcenter + (x - xcenter) * factor for x in xlim])
    ax.set_ylim([ycenter + (y - ycenter) * factor for y in ylim])
    canvas.draw_idle()
    set_status("Zoomed in", 'green')

def zoom_out():
    """Zoom out on the grid."""
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    xcenter = (xlim[0] + xlim[1]) / 2
    ycenter = (ylim[0] + ylim[1]) / 2
    factor = 1.25
    
    ax.set_xlim([xcenter + (x - xcenter) * factor for x in xlim])
    ax.set_ylim([ycenter + (y - ycenter) * factor for y in ylim])
    canvas.draw_idle()
    set_status("Zoomed out", 'green')

def reset_zoom():
    """Reset zoom to show entire grid."""
    ax.set_xlim(0, X)
    ax.set_ylim(0, Y)
    canvas.draw_idle()
    set_status("Zoom reset", 'green')

def show_options():
    """Show options dialog."""
    from tkinter import messagebox
    messagebox.showinfo("Options", "Options dialog coming soon!")

def show_settings():
    """Show settings dialog."""
    from tkinter import messagebox
    messagebox.showinfo("Settings", "Settings dialog coming soon!")

def run_analysis():
    """Run analysis on current grid."""
    if np.sum(grid) == 0:
        from tkinter import messagebox
        messagebox.showwarning("Warning", "Paint some voxels first!")
        return
    
    # Trigger simulation
    run_simulation()

def generate_report():
    """Generate a report of the current design."""
    from tkinter import filedialog, messagebox
    import json
    
    filepath = filedialog.asksaveasfilename(
        defaultextension=".txt",
        initialfile="design_report.txt",
        filetypes=[("Text File", "*.txt"),
                   ("JSON File", "*.json"),
                   ("All Files", "*.*")])
    
    if not filepath:
        return
    
    try:
        n_filled = int(np.sum(grid))
        unique_materials = len(set(grid[grid != 0])) if n_filled > 0 else 0
        
        report = f"""Magnetic Soft Materials Designer - Design Report
====================================================

Grid Dimensions: {X} x {Y}
Total Voxels: {X * Y}
Filled Voxels: {n_filled}
Empty Voxels: {X * Y - n_filled}
Fill Percentage: {n_filled / (X * Y) * 100:.1f}%

Active Material: {active_material['name']} (ID: {active_material['id']})

Materials Used: {unique_materials}
"""
        
        with open(filepath, 'w') as f:
            f.write(report)
        
        messagebox.showinfo("Success", f"Report saved to {os.path.basename(filepath)}")
        set_status(f"Report saved: {os.path.basename(filepath)}", 'green')
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save report: {str(e)}")

# ── Main window ───────────────────────────────────────────────
root = tk.Tk()
root.title("Magnetic Soft Materials Designer")
root.geometry("800x600")
root.configure(bg='white')
root.resizable(True, True)

# ── Menu Bar ──────────────────────────────────────────────────
menubar = tk.Menu(root)
root.config(menu=menubar)

file_menu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="File", menu=file_menu)
file_menu.add_command(label="New", command=new_file, accelerator="Ctrl+N")
file_menu.add_command(label="Open", command=open_file, accelerator="Ctrl+O")
file_menu.add_command(label="Save", command=save_file, accelerator="Ctrl+S")
file_menu.add_command(label="Save As...", command=save_file_as, accelerator="Ctrl+Shift+S")
file_menu.add_separator()
file_menu.add_command(label="Exit", command=root.quit)

edit_menu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="Edit", menu=edit_menu)
edit_menu.add_command(label="Undo", command=lambda: undo(), accelerator="Ctrl+Z")
edit_menu.add_command(label="Redo", command=lambda: redo(), accelerator="Ctrl+Y")
edit_menu.add_separator()
edit_menu.add_command(label="Cut", command=do_cut, accelerator="Ctrl+X")
edit_menu.add_command(label="Copy", command=do_copy, accelerator="Ctrl+C")
edit_menu.add_command(label="Paste", command=do_paste, accelerator="Ctrl+V")
edit_menu.add_separator()
edit_menu.add_command(label="Select All", command=select_all, accelerator="Ctrl+A")

view_menu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="View", menu=view_menu)
view_menu.add_command(label="Zoom In", command=zoom_in, accelerator="Ctrl+=")
view_menu.add_command(label="Zoom Out", command=zoom_out, accelerator="Ctrl+-")
view_menu.add_command(label="Reset Zoom", command=reset_zoom, accelerator="Ctrl+0")

tools_menu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="Tools", menu=tools_menu)
tools_menu.add_command(label="Options", command=show_options)
tools_menu.add_command(label="Settings", command=show_settings)

analyze_menu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="Analyze", menu=analyze_menu)
analyze_menu.add_command(label="Run Analysis", command=run_analysis)
analyze_menu.add_command(label="Generate Report", command=generate_report)

# ── Toolbar ───────────────────────────────────────────────────
COLOR_NORMAL = '#f0f0f0'
COLOR_ACTIVE = '#b0c8f0'

toolbar = tk.Frame(root, bg='#f0f0f0', height=28, relief=tk.RAISED, bd=1)
toolbar.pack(side=tk.TOP, fill=tk.X)
toolbar.pack_propagate(False)

# ── Main container ────────────────────────────────────────────
main_container = tk.Frame(root, bg='white')
main_container.pack(fill=tk.BOTH, expand=True)

# ── Sidebar ───────────────────────────────────────────────────
sidebar = tk.Frame(main_container, bg='#f0f0f0', width=220,
                   bd=1, relief=tk.RAISED)
sidebar.pack(side=tk.RIGHT, fill=tk.Y)
sidebar.pack_propagate(False)

style = ttk.Style()
style.configure('BottomTab.TNotebook', tabposition='sw')
notebook = ttk.Notebook(sidebar, style='BottomTab.TNotebook')
notebook.pack(fill=tk.BOTH, expand=True)

# ── Bottom status bar ─────────────────────────────────────────
bottom_bar = tk.Frame(root, bg='#e8e8e8', height=22,
                      relief=tk.SUNKEN, bd=1)
bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
bottom_bar.pack_propagate(False)

# Status label (left)
status_label = tk.Label(bottom_bar, text="Ready",
                         bg='#e8e8e8', fg='#444',
                         font=('Arial', 8), anchor='w')
status_label.pack(side=tk.LEFT, padx=8)

# ── Status tooltip ────────────────────────────────────────────
status_tooltip = None
full_status_text = {'text': 'Ready'}

def set_status(text, color='#444'):
    """Use this instead of status_label.config() everywhere."""
    full_status_text['text'] = text
    # Truncate if too long
    display = text.replace('\n', ' | ')
    if len(display) > 60:
        display = display[:57] + '...'
    status_label.config(text=display, fg=color)

def show_status_tooltip(event):
    global status_tooltip
    hide_status_tooltip()
    if not full_status_text['text']:
        return
    status_tooltip = tk.Toplevel(root)
    status_tooltip.wm_overrideredirect(True)
    status_tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root - 40}")
    tk.Label(status_tooltip,
             text=full_status_text['text'],
             justify=tk.LEFT,
             bg='#ffffcc', fg='black',
             font=('Arial', 8),
             relief=tk.SOLID, bd=1,
             padx=6, pady=4).pack()

def hide_status_tooltip(event=None):
    global status_tooltip
    if status_tooltip:
        status_tooltip.destroy()
        status_tooltip = None

status_label.bind('<Enter>', show_status_tooltip)
status_label.bind('<Leave>', hide_status_tooltip)

# ── Tab 1: Workspace ──────────────────────────────────────────
workspace_tab = tk.Frame(notebook, bg='#f0f0f0')
notebook.add(workspace_tab, text=" Workspace ")

tk.Label(workspace_tab, text="Grid Dimensions",
         bg='#f0f0f0', font=('Arial', 9, 'bold')).pack(pady=(10, 2))
grid_frame = tk.Frame(workspace_tab, bg='#f0f0f0')
grid_frame.pack(fill=tk.X, padx=10)
grid_entries = {}

for label in ['X Voxels', 'Y Voxels']:
    f = tk.Frame(grid_frame, bg='#f0f0f0')
    f.pack(side=tk.LEFT, expand=True)
    ent = tk.Entry(f, width=5, justify='center')
    ent.insert(0, "20")
    ent.pack()
    grid_entries[label] = ent
    tk.Label(f, text=label, bg='#f0f0f0', font=('Arial', 8)).pack()

tk.Button(workspace_tab, text="Apply Changes",
          command=lambda: update_grid_size()).pack(pady=10, padx=10, fill=tk.X)

tk.Frame(workspace_tab, bg='#cccccc', height=1).pack(fill=tk.X, padx=10, pady=4)

tk.Label(workspace_tab, text="Simulation",
         bg='#f0f0f0', font=('Arial', 9, 'bold')).pack(pady=(6, 2))

b_frame = tk.Frame(workspace_tab, bg='#f0f0f0')
b_frame.pack(fill=tk.X, padx=10, pady=(0, 4))
tk.Label(b_frame, text="B field (mT):", bg='#f0f0f0',
         font=('Arial', 9)).pack(side=tk.LEFT)
b_entry = tk.Entry(b_frame, width=6, justify='center')
b_entry.insert(0, "30")
b_entry.pack(side=tk.LEFT, padx=4)

# ── B field direction ─────────────────────────────────────────
tk.Label(workspace_tab, text="B Field Direction",
         bg='#f0f0f0', font=('Arial', 9, 'bold')).pack(pady=(6, 2))

dir_mode_var = tk.StringVar(value='preset')

dir_mode_frame = tk.Frame(workspace_tab, bg='#f0f0f0')
dir_mode_frame.pack(fill=tk.X, padx=10, pady=2)

# Fixed height container
dir_container = tk.Frame(workspace_tab, bg='#f0f0f0', height=80)
dir_container.pack(fill=tk.X, padx=10, pady=2)
dir_container.pack_propagate(False)

# Preset frame
preset_frame = tk.Frame(dir_container, bg='#f0f0f0')
preset_frame.place(x=0, y=0, relwidth=1.0, relheight=1.0)

preset_dir_var = tk.StringVar(value='+Z')
preset_dirs    = ['+X', '-X', '+Y', '-Y', '+Z', '-Z']
preset_vectors = {
    '+X': ( 1,  0,  0), '-X': (-1,  0,  0),
    '+Y': ( 0,  1,  0), '-Y': ( 0, -1,  0),
    '+Z': ( 0,  0,  1), '-Z': ( 0,  0, -1),
}

row1 = tk.Frame(preset_frame, bg='#f0f0f0')
row1.pack(fill=tk.X)
row2 = tk.Frame(preset_frame, bg='#f0f0f0')
row2.pack(fill=tk.X)

for i, d in enumerate(preset_dirs):
    parent = row1 if i < 3 else row2
    tk.Radiobutton(parent, text=d, variable=preset_dir_var,
                   value=d, bg='#f0f0f0',
                   font=('Arial', 8)).pack(side=tk.LEFT, expand=True)

# Custom frame
custom_frame = tk.Frame(dir_container, bg='#f0f0f0')

cf_row1 = tk.Frame(custom_frame, bg='#f0f0f0')
cf_row1.pack(fill=tk.X, pady=1)
tk.Label(cf_row1, text="θ° (azimuth XY):",
         bg='#f0f0f0', font=('Arial', 8)).pack(side=tk.LEFT)
theta_entry = tk.Entry(cf_row1, width=6, justify='center', font=('Arial', 8))
theta_entry.insert(0, "0")
theta_entry.pack(side=tk.RIGHT)

cf_row2 = tk.Frame(custom_frame, bg='#f0f0f0')
cf_row2.pack(fill=tk.X, pady=1)
tk.Label(cf_row2, text="φ° (elevation):",
         bg='#f0f0f0', font=('Arial', 8)).pack(side=tk.LEFT)
phi_entry = tk.Entry(cf_row2, width=6, justify='center', font=('Arial', 8))
phi_entry.insert(0, "90")
phi_entry.pack(side=tk.RIGHT)

tk.Label(custom_frame,
         text="φ=90→+Z  φ=0,θ=0→+X  φ=0,θ=90→+Y",
         bg='#f0f0f0', font=('Arial', 7), fg='gray').pack(anchor='w')

def on_dir_mode_change():
    if dir_mode_var.get() == 'preset':
        custom_frame.place_forget()
        preset_frame.place(x=0, y=0, relwidth=1.0, relheight=1.0)
    else:
        preset_frame.place_forget()
        custom_frame.place(x=0, y=0, relwidth=1.0, relheight=1.0)

tk.Radiobutton(dir_mode_frame, text="Preset", variable=dir_mode_var,
               value='preset', bg='#f0f0f0',
               command=on_dir_mode_change).pack(side=tk.LEFT)
tk.Radiobutton(dir_mode_frame, text="Custom Angle", variable=dir_mode_var,
               value='custom', bg='#f0f0f0',
               command=on_dir_mode_change).pack(side=tk.LEFT)

# Initialize the display state
on_dir_mode_change()

def get_b_direction():
    import math
    if dir_mode_var.get() == 'preset':
        return preset_vectors[preset_dir_var.get()]
    else:
        try:
            theta = math.radians(float(theta_entry.get()))
            phi   = math.radians(float(phi_entry.get()))
            bx    = math.cos(theta) * math.cos(phi)
            by    = math.sin(theta) * math.cos(phi)
            bz    = math.sin(phi)
            return (bx, by, bz)
        except ValueError:
            set_status("Invalid angle, using +Z", 'orange')
            return (0, 0, 1)

tk.Frame(workspace_tab, bg='#cccccc', height=1).pack(
    fill=tk.X, padx=10, pady=4)

tk.Button(workspace_tab, text="▶  Run Simulation",
          command=lambda: run_simulation(),
          bg='#27ae60', fg='white',
          font=('Arial', 9, 'bold'),
          relief=tk.FLAT, cursor='hand2').pack(padx=10, pady=4, fill=tk.X)

# ── Tab 2: Material Selection ─────────────────────────────────
palette_tab = tk.Frame(notebook, bg='#f0f0f0')
notebook.add(palette_tab, text=" Material ")

tk.Label(palette_tab, text="Materials",
         bg='#f0f0f0', font=('Arial', 9, 'bold')).pack(pady=(10, 2))

# Material list
mat_list_frame = tk.Frame(palette_tab, bg='white', relief=tk.SUNKEN, bd=1)
mat_list_frame.pack(fill=tk.X, padx=8, pady=4)

# Default material
materials = {
    'MagSoElas_default': {
        'id':          1,
        'color':       '#4a90d9',
        'LATTICE_DIM': 200e-6,
        'ELASTIC_MOD': 150e3,
        'DENSITY':     2.41e3,
        'POISSONS':    0.4,
        'M_PER_VOL':   20e3,
    }
}

# next available material ID
next_mat_id = {'val': 2}

# Scrollbar
mat_scrollbar = tk.Scrollbar(mat_list_frame, orient=tk.VERTICAL, width=10)
mat_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

mat_listbox = tk.Listbox(mat_list_frame, height=5, font=('Arial', 9),
                          selectbackground='#b0c8f0', activestyle='none',
                          bg='white', yscrollcommand=mat_scrollbar.set)
mat_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
mat_scrollbar.config(command=mat_listbox.yview)

def refresh_listbox():
    mat_listbox.delete(0, tk.END)
    for name, props in materials.items():
        # Leading spaces push text right to make room for color square
        mat_listbox.insert(tk.END, f"      {name}")
        idx = mat_listbox.size() - 1
        mat_listbox.itemconfig(idx, bg='white', fg='black')
    draw_color_squares()

# Color squares on canvas overlay — sits on top of listbox left side
mat_canvas = tk.Canvas(mat_list_frame, width=18, bg='white',
                        highlightthickness=0)
mat_canvas.place(x=0, y=0, relheight=1.0)

def draw_color_squares():
    mat_canvas.delete('all')
    # Get actual item height from listbox
    try:
        item_height = mat_listbox.bbox(0)
        if item_height:
            ih = item_height[3]  # height of one item
        else:
            ih = 18
    except:
        ih = 18

    for i, (name, props) in enumerate(materials.items()):
        y     = i * ih + ih // 2
        color = props.get('color', '#4a90d9')
        mat_canvas.create_rectangle(3, y - 5, 15, y + 5,
                                     fill=color, outline='#555',
                                     width=1)

def _is_dark(hex_color):
    """Returns True if color is dark."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return (r * 0.299 + g * 0.587 + b * 0.114) < 128

refresh_listbox()
mat_listbox.select_set(0)

# ── Hover tooltip ─────────────────────────────────────────────
status_tooltip = None

def show_tooltip(event):
    global status_tooltip
    hide_tooltip()
    idx = mat_listbox.nearest(event.y)
    if idx < 0 or idx >= mat_listbox.size():
        return
    name  = list(materials.keys())[idx]
    props = materials[name]
    status_tooltip = tk.Toplevel(root)
    status_tooltip.wm_overrideredirect(True)
    status_tooltip.wm_geometry(f"+{event.x_root + 15}+{event.y_root + 10}")
    text = (f"Material : {name}\n"
            f"ID       : {props['id']}\n"
            f"Color    : {props['color']}\n"
            f"──────────────────────\n"
            f"Lattice  : {props['LATTICE_DIM']}\n"
            f"E Mod    : {props['ELASTIC_MOD']}\n"
            f"Density  : {props['DENSITY']}\n"
            f"Poisson  : {props['POISSONS']}\n"
            f"M/Vol    : {props['M_PER_VOL']}")
    tk.Label(status_tooltip, text=text, justify=tk.LEFT,
             bg='#ffffcc', fg='black', font=('Courier', 8),
             relief=tk.SOLID, bd=1, padx=6, pady=4).pack()

def hide_tooltip(event=None):
    global status_tooltip
    if status_tooltip:
        status_tooltip.destroy()
        status_tooltip = None

mat_listbox.bind('<Motion>', show_tooltip)
mat_listbox.bind('<Leave>',  hide_tooltip)

tk.Frame(palette_tab, bg='#cccccc', height=1).pack(fill=tk.X, padx=8, pady=4)

# ── Add new material ──────────────────────────────────────────
tk.Label(palette_tab, text="Add New Material",
         bg='#f0f0f0', font=('Arial', 9, 'bold')).pack(pady=(2, 4))

mat_params = [
    ("Lattice Dim (m)",  "LATTICE_DIM"),
    ("Elastic Mod (Pa)", "ELASTIC_MOD"),
    ("Density (kg/m³)",  "DENSITY"),
    ("Poisson's Ratio",  "POISSONS"),
    ("M/Vol (A/m)",      "M_PER_VOL"),
]

mat_entries = {}
for label, key in mat_params:
    row = tk.Frame(palette_tab, bg='#f0f0f0')
    row.pack(fill=tk.X, padx=8, pady=1)
    tk.Label(row, text=label, bg='#f0f0f0',
             font=('Arial', 9), anchor='w').pack(side=tk.LEFT,
                                                  fill=tk.X, expand=True)
    ent = tk.Entry(row, width=8, justify='center', font=('Arial', 9))
    ent.pack(side=tk.RIGHT)
    mat_entries[key] = ent

tk.Frame(palette_tab, bg='#cccccc', height=1).pack(fill=tk.X, padx=8, pady=4)

tk.Label(palette_tab, text="Material Name:",
         bg='#f0f0f0', font=('Arial', 9)).pack(anchor='w', padx=8)
mat_name_entry = tk.Entry(palette_tab, width=20, font=('Arial', 9))
mat_name_entry.pack(fill=tk.X, padx=8, pady=2)

# ── Functions ─────────────────────────────────────────────────
def load_material(event=None):
    """Set active paint material immediately on selection."""
    sel = mat_listbox.curselection()
    if not sel:
        return
    idx  = sel[0]
    name = list(materials.keys())[idx]
    active_material['name'] = name
    active_material['id']   = materials[name]['id']
    set_status(f"Active material: {name}", '#4a90d9')

def add_material():
    from tkinter import colorchooser
    name = mat_name_entry.get().strip()
    if not name:
        from tkinter import messagebox
        messagebox.showwarning("Warning", "Please enter a material name.")
        return
    if name in materials:
        from tkinter import messagebox
        messagebox.showwarning("Warning", f"'{name}' already exists.")
        return

    # Validate entries
    for key, ent in mat_entries.items():
        if ent.get().strip() == '':
            from tkinter import messagebox
            messagebox.showwarning("Warning", "Please fill in all properties.")
            return

    # Open color picker
    color_result = colorchooser.askcolor(
        title=f"Pick color for '{name}'",
        color='#ff5555')
    if not color_result or not color_result[1]:
        return  # user cancelled
    chosen_color = color_result[1]  # hex string e.g. '#ff5555'

    try:
        mat_id = next_mat_id['val']
        materials[name] = {
            'id':          mat_id,
            'color':       chosen_color,
            'LATTICE_DIM': float(mat_entries['LATTICE_DIM'].get()),
            'ELASTIC_MOD': float(mat_entries['ELASTIC_MOD'].get()),
            'DENSITY':     float(mat_entries['DENSITY'].get()),
            'POISSONS':    float(mat_entries['POISSONS'].get()),
            'M_PER_VOL':   float(mat_entries['M_PER_VOL'].get()),
        }
        next_mat_id['val'] += 1
        refresh_listbox()
        mat_name_entry.delete(0, tk.END)
        for ent in mat_entries.values():
            ent.delete(0, tk.END)
        set_status(f"'{name}' added!", 'green')
    except ValueError:
        from tkinter import messagebox
        messagebox.showerror("Error", "Invalid property values.")

mat_listbox.bind('<<ListboxSelect>>', load_material)

tk.Button(palette_tab, text="+ Add Material", command=add_material,
          bg='#4a90d9', fg='white', font=('Arial', 8, 'bold'),
          relief=tk.FLAT, cursor='hand2').pack(padx=8, pady=4, fill=tk.X)

# ── Tab 3: Sim Parameters ─────────────────────────────────────
params_tab = tk.Frame(notebook, bg='#f0f0f0')
notebook.add(params_tab, text=" Params ")

tk.Label(params_tab, text="Sim Parameters",
         bg='#f0f0f0', font=('Arial', 9, 'bold')).pack(pady=(10, 4))

sim_params = [
    ("Sim Time (s)",    "SIM_TIME",        "3.0"),
    ("DT Frac",         "DT_FRAC",         "0.9"),
    ("Kin E Threshold", "KIN_E_THRESHOLD", "1e-15"),
    ("Bond Damping Z",  "DAMPING_BOND_Z",  "1.0"),
    ("Col Damping Z",   "COL_BOND_Z",      "0.8"),
    ("Slow Damping Z",  "SLOW_BOND_Z",     "0.01"),
    ("Gravity (0/1)",   "GRAVITY_ENABLED", "0"),
    ("Mag Force (0/1)", "IS_MAG_FORCE_ON", "1"),
]

param_entries = {}
for label, key, default in sim_params:
    row = tk.Frame(params_tab, bg='#f0f0f0')
    row.pack(fill=tk.X, padx=8, pady=2)
    tk.Label(row, text=label, bg='#f0f0f0',
             font=('Arial', 9), anchor='w').pack(side=tk.LEFT, fill=tk.X, expand=True)
    ent = tk.Entry(row, width=8, justify='center', font=('Arial', 9))
    ent.insert(0, default)
    ent.pack(side=tk.RIGHT)
    param_entries[key] = ent

tk.Button(params_tab, text="Apply Params",
          command=lambda: apply_params(),
          bg='#4a90d9', fg='white', font=('Arial', 8, 'bold'),
          relief=tk.FLAT, cursor='hand2').pack(padx=8, pady=8, fill=tk.X)

def apply_params():
    import sim_runner as sr
    try:
        sr.SIM_TIME        = float(param_entries['SIM_TIME'].get())
        sr.DT_FRAC         = float(param_entries['DT_FRAC'].get())
        sr.KIN_E_THRESHOLD = float(param_entries['KIN_E_THRESHOLD'].get())
        sr.DAMPING_BOND_Z  = float(param_entries['DAMPING_BOND_Z'].get())
        sr.COL_BOND_Z      = float(param_entries['COL_BOND_Z'].get())
        sr.SLOW_BOND_Z     = float(param_entries['SLOW_BOND_Z'].get())
        sr.GRAVITY_ENABLED = int(param_entries['GRAVITY_ENABLED'].get())
        sr.IS_MAG_FORCE_ON = int(param_entries['IS_MAG_FORCE_ON'].get())
        set_status("Params applied!", 'green')
    except ValueError:
        from tkinter import messagebox
        messagebox.showerror("Error", "Invalid parameter value.")

# ── Canvas ────────────────────────────────────────────────────
fig = Figure(facecolor='white', tight_layout={'pad': 1.5})
ax  = fig.add_subplot(111)
ax.set_facecolor('#f9f9f9')

# Draw grid using imshow
im = ax.imshow(make_image(grid), origin='lower',
               extent=[0, X, 0, Y], aspect='equal',
               interpolation='nearest')

# Selection highlight overlay
sel_overlay = ax.imshow(
    np.zeros((Y, X, 4)),
    origin='lower', extent=[0, X, 0, Y],
    aspect='equal', interpolation='nearest',
    zorder=3)

def draw_selection_highlight():
    overlay = np.zeros((Y, X, 4))
    for (ix, iy) in selected_voxels:
        if 0 <= ix < X and 0 <= iy < Y:
            overlay[iy, ix] = [0.0, 0.47, 0.84, 0.35]
    sel_overlay.set_data(overlay)
    sel_overlay.set_extent([0, X, 0, Y])
    canvas.draw_idle()

def clear_selection():
    global selected_voxels
    selected_voxels.clear()
    _clear_sel_rect()
    sel_overlay.set_data(np.zeros((Y, X, 4)))
    canvas.draw_idle()
    set_status("Selection cleared", 'green')

# Grid lines overlay
grid_lines = []

def draw_grid_lines():
    global grid_lines
    for line in grid_lines:
        try:
            line.remove()
        except:
            pass
    grid_lines = []

    # Vertical lines
    for x in range(X + 1):
        line, = ax.plot([x, x], [0, Y], color='black',
                        linewidth=0.5, zorder=2, clip_on=True)
        grid_lines.append(line)

    # Horizontal lines
    for y in range(Y + 1):
        line, = ax.plot([0, X], [y, y], color='black',
                        linewidth=0.5, zorder=2, clip_on=True)
        grid_lines.append(line)

    # Strictly lock limits
    ax.set_xlim(0, X)
    ax.set_ylim(0, Y)

draw_grid_lines()

ax.set_xlim(0, X)
ax.set_ylim(0, Y)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.set_xlabel('X — Voxel Index', loc='right', fontsize=8)
ax.set_ylabel('Y — Voxel Index', loc='top', fontsize=8)

# ── Magnetisation arrow overlay ───────────────────────────────
mag_arrow_artists = []

def clear_mag_arrows():
    global mag_arrow_artists
    for a in mag_arrow_artists:
        try:
            a.remove()
        except:
            pass
    mag_arrow_artists = []

def draw_mag_arrow(ix, iy):
    """Draw magnetisation arrow/symbol on voxel (ix, iy) if custom set."""
    import math
    if (ix, iy) not in mag_grid:
        return
    entry = mag_grid[(ix, iy)]
    Mx, My, Mz = entry[0], entry[1], entry[2]
    M_val = entry[3] if len(entry) == 4 else None
    cx = ix + 0.5
    cy = iy + 0.5

    # ── Compute elevation angle φ from Mz ────────────────────
    phi_rad = math.asin(max(-1.0, min(1.0, Mz)))
    phi_abs = abs(phi_rad)
    t = phi_abs / (math.pi / 2)  # 0 at φ=0°, 1 at φ=±90°

    if phi_rad >= 0:
        arrow_color = (1.0 - t, 1.0, 0.0)  # Fades from Yellow (0°) to Green (+90°)
    else:
        arrow_color = (1.0, 1.0 - t, 0.0)  # Fades from Yellow (0°) to Red (-90°)

    # ── Electric blue highlight background ────────────────────
    import matplotlib.patches as mpatches
    bg_rect = mpatches.FancyBboxPatch(
        (cx - 0.4, cy - 0.4), 0.8, 0.8,
        boxstyle='round,pad=0.05',
        facecolor='#00BFFF',   # electric/deep sky blue
        edgecolor='none',
        alpha=0.55,
        zorder=9)
    mag_arrow_artists.append(ax.add_patch(bg_rect))

    # ── Pure Z direction → dot + ⊙/⊗ symbol ──────────────────
    if abs(Mx) < 0.01 and abs(My) < 0.01:
        dot = ax.plot(cx, cy, 'o',
                      color=arrow_color,
                      markersize=8, zorder=10)[0]
        mag_arrow_artists.append(dot)
        symbol = '⊙' if Mz > 0 else '⊗'
        txt = ax.text(cx, cy, symbol,
                      color=arrow_color,
                      ha='center', va='center',
                      fontsize=10, zorder=11)
        mag_arrow_artists.append(txt)

    # ── Draw Arrow in the Grid XY Plane (Handles pure X, pure Y, and Diagonals!) ──
    else:
        arrow_scale = 0.38
        
        # 1. Calculate the magnitude of the vector on the flat screen (XY plane)
        xy_mag = math.sqrt(Mx**2 + My**2)
        
        if xy_mag > 0:
            # 2. Normalize and apply your visual scale factor so it fits nicely
            dx = (Mx / xy_mag) * arrow_scale
            dy = (My / xy_mag) * arrow_scale
        else:
            dx, dy = 0, 0
            
        # 3. Draw the arrow pointing precisely along the custom direction
        arrow = ax.annotate('',
            xy=(cx + dx, cy + dy),      # Arrow Tip
            xytext=(cx - dx, cy - dy),  # Arrow Tail
            arrowprops=dict(
                arrowstyle='->', color=arrow_color,
                lw=1.5, mutation_scale=10),
            zorder=10)
        mag_arrow_artists.append(arrow)

def draw_all_mag_arrows():
    """Draw arrows for ALL voxels with custom mag."""
    clear_mag_arrows()
    for (ix, iy) in mag_grid:
        if 0 <= ix < X and 0 <= iy < Y:
            draw_mag_arrow(ix, iy)
    canvas.draw_idle()

def hover_mag_preview(event):
    """Updates status bar text when freely moving the mouse over the grid."""
    if current_tool['name'] != 'mag' or state['is_dragging']:
        return

    if event.inaxes != ax or event.xdata is None or event.ydata is None:
        return

    ix = int(round(event.xdata))
    iy = int(round(event.ydata))

    if mag_hover_voxel['pos'] == (ix, iy):
        return  # Same voxel, skip redundant processing
    mag_hover_voxel['pos'] = (ix, iy)

    draw_all_mag_arrows()

    if 0 <= ix < X and 0 <= iy < Y:
        if (ix, iy) in mag_grid:
            entry = mag_grid[(ix, iy)]
            Mx, My, Mz = entry[0], entry[1], entry[2]
            M_val = entry[3] if len(entry) == 4 else None
            m_str = f", M={M_val:.0f} A/m" if M_val else ""
            set_status(f"Voxel ({ix},{iy}) custom mag: ({Mx:.2f}, {My:.2f}, {Mz:.2f}){m_str}", '#e67e22')
        else:
            set_status(f"Voxel ({ix},{iy}) — default mag", '#888')

def on_motion(event):
    if not state['is_dragging']:
        if current_tool['name'] == 'mag':
            hover_mag_preview(event)
        return

    if current_tool['name'] == 'select':
        if state['sel_start_data'] and event.inaxes == ax and event.xdata is not None:
            x0, y0 = state['sel_start_data']
            _draw_sel_rect(x0, y0, event.xdata, event.ydata)

    elif current_tool['name'] == 'paint':
        update_paint(event)

    elif current_tool['name'] == 'erase':
        update_erase(event)

    elif current_tool['name'] == 'mag':
        ix = int(event.xdata)
        iy = int(event.ydata)
        if 0 <= ix < X and 0 <= iy < Y:
            update_mag(ix, iy, event)

    elif current_tool['name'] == 'pan':
        if state['pan_start_data'] and event.x is not None:
            # ── Convert pixel delta to data units ─────────────
            dx_px = event.x - state['pan_start_data'][0]
            dy_px = event.y - state['pan_start_data'][1]

            # Get axis size in pixels
            bbox    = ax.get_window_extent()
            ax_w_px = bbox.width
            ax_h_px = bbox.height

            # Get current data range from saved limits
            xlim = state['pan_xlim']
            ylim = state['pan_ylim']
            x_range = xlim[1] - xlim[0]
            y_range = ylim[1] - ylim[0]

            # Convert pixel delta to data delta
            dx_data = -(dx_px / ax_w_px) * x_range
            dy_data = -(dy_px / ax_h_px) * y_range

            ax.set_xlim(xlim[0] + dx_data, xlim[1] + dx_data)
            ax.set_ylim(ylim[0] + dy_data, ylim[1] + dy_data)
            canvas.draw_idle()

canvas = FigureCanvasTkAgg(fig, master=main_container)
canvas.get_tk_widget().pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
canvas.mpl_connect('motion_notify_event', on_motion)

# ── Hidden nav logic ──────────────────────────────────────────
class HiddenToolbar(NavigationToolbar2):
    def __init__(self, canvas):
        self.canvas = canvas
        NavigationToolbar2.__init__(self, canvas)
    def _init_toolbar(self): pass
    def set_message(self, s): pass

nav_logic = HiddenToolbar(canvas)

# ── Tool state ────────────────────────────────────────────────
current_tool = {'name': 'select'}
btn_select_obj = None
btn_paint_obj  = None
btn_erase_obj  = None
btn_mag_obj     = None
btn_pan_obj    = None

selected_voxels = set()

state = {
    'is_dragging':    False,
    'sel_start_data': None,
    'sel_rect_patch': None,
    'pan_start_data': None,
    'pan_xlim':       None,
    'pan_ylim':       None,
}

# Persistent state for magnetisation tool
state['ctrl_pressed'] = False # Persistent tracker for dragging
current_stroke_modified_voxels = set() # Tracks voxels modified in the current drag stroke

def update_button_colors():
    btn_home_obj.config(bg=COLOR_NORMAL)
    btn_select_obj.config(bg=COLOR_NORMAL)
    btn_paint_obj.config(bg=COLOR_NORMAL)
    btn_erase_obj.config(bg=COLOR_NORMAL)
    btn_mag_obj.config(bg=COLOR_NORMAL)
    btn_pan_obj.config(bg=COLOR_NORMAL)
    if current_tool['name'] == 'select':
        btn_select_obj.config(bg=COLOR_ACTIVE)
    elif current_tool['name'] == 'paint':
        btn_paint_obj.config(bg=COLOR_ACTIVE)
    elif current_tool['name'] == 'erase':
        btn_erase_obj.config(bg=COLOR_ACTIVE)
    elif current_tool['name'] == 'mag':
        btn_mag_obj.config(bg=COLOR_ACTIVE)
    elif current_tool['name'] == 'pan':
        btn_pan_obj.config(bg=COLOR_ACTIVE)

def set_select():
    current_tool['name'] = 'select'
    clear_mag_arrows()
    mag_hover_voxel['pos'] = None
    canvas.draw_idle()
    update_button_colors()
    set_status("Select tool — drag to select voxels", 'blue')

def set_paint():
    current_tool['name'] = 'paint'
    clear_mag_arrows()
    mag_hover_voxel['pos'] = None
    canvas.draw_idle()
    update_button_colors()
    set_status("Paint tool — click to add material", 'blue')

def set_erase():
    current_tool['name'] = 'erase'
    clear_mag_arrows()
    mag_hover_voxel['pos'] = None
    canvas.draw_idle()
    update_button_colors()
    set_status("Erase tool — click to remove material", 'blue')

def set_pan():
    current_tool['name'] = 'pan'
    clear_mag_arrows()
    mag_hover_voxel['pos'] = None
    canvas.draw_idle()
    update_button_colors()
    set_status("Pan tool — drag to move view", 'blue')

def set_home():
    ax.set_xlim(0, X)
    ax.set_ylim(0, Y)
    canvas.draw_idle()
    update_button_colors()

def set_mag():
    current_tool['name'] = 'mag'
    update_button_colors()
    draw_all_mag_arrows()   # ← show all immediately on activation
    set_status("Magnetisation tool — click a filled voxel to set direction", 'blue')

# ── Toolbar buttons ───────────────────────────────────────────
btn_home_obj = tk.Button(toolbar, text="⟳", command=set_home,
                          relief=tk.FLAT, bd=0, bg=COLOR_NORMAL,
                          activebackground=COLOR_ACTIVE,
                          highlightthickness=0,
                          font=('Arial', 12), cursor='hand2')
btn_home_obj.pack(side=tk.LEFT, padx=4)

btn_select_obj = tk.Button(toolbar, text="⬚", command=set_select,
                            relief=tk.FLAT, bd=0, bg=COLOR_ACTIVE,
                            activebackground=COLOR_ACTIVE,
                            highlightthickness=0,
                            font=('Arial', 12), cursor='hand2')
btn_select_obj.pack(side=tk.LEFT, padx=4)

btn_paint_obj = tk.Button(toolbar, text="🖊", command=set_paint,
                           relief=tk.FLAT, bd=0, bg=COLOR_NORMAL,
                           activebackground=COLOR_ACTIVE,
                           highlightthickness=0,
                           font=('Arial', 12), cursor='hand2')
btn_paint_obj.pack(side=tk.LEFT, padx=4)

btn_erase_obj = tk.Button(toolbar, text="⌫", command=set_erase,
                           relief=tk.FLAT, bd=0, bg=COLOR_NORMAL,
                           activebackground=COLOR_ACTIVE,
                           highlightthickness=0,
                           font=('Arial', 12), cursor='hand2')
btn_erase_obj.pack(side=tk.LEFT, padx=4)

btn_mag_obj = tk.Button(toolbar, text="🧲", command=set_mag,
                         relief=tk.FLAT, bd=0, bg=COLOR_NORMAL,
                         activebackground=COLOR_ACTIVE,
                         highlightthickness=0,
                         font=('Arial', 12), cursor='hand2')
btn_mag_obj.pack(side=tk.LEFT, padx=4)

btn_pan_obj = tk.Button(toolbar, text="✋", command=set_pan,
                         relief=tk.FLAT, bd=0, bg=COLOR_NORMAL,
                         activebackground=COLOR_ACTIVE,
                         highlightthickness=0,
                         font=('Arial', 12), cursor='hand2')
btn_pan_obj.pack(side=tk.LEFT, padx=4)

btn_undo_obj = tk.Button(toolbar, text="↩", command=lambda: undo(),
                          relief=tk.FLAT, bd=0, bg=COLOR_NORMAL,
                          activebackground=COLOR_NORMAL,
                          highlightthickness=0,
                          font=('Arial', 12), cursor='hand2')
btn_undo_obj.pack(side=tk.LEFT, padx=4)

btn_redo_obj = tk.Button(toolbar, text="↪", command=lambda: redo(),
                          relief=tk.FLAT, bd=0, bg=COLOR_NORMAL,
                          activebackground=COLOR_NORMAL,
                          highlightthickness=0,
                          font=('Arial', 12), cursor='hand2')
btn_redo_obj.pack(side=tk.LEFT, padx=4)

def _clear_sel_rect():
    if state['sel_rect_patch'] is not None:
        try:
            state['sel_rect_patch'].remove()
        except:
            pass
        state['sel_rect_patch'] = None

def _draw_sel_rect(x0, y0, x1, y1):
    _clear_sel_rect()
    import matplotlib.patches as mpatches
    rx = min(x0, x1)
    ry = min(y0, y1)
    rw = abs(x1 - x0)
    rh = abs(y1 - y0)
    patch = mpatches.Rectangle(
        (rx, ry), rw, rh,
        linewidth=1.5, edgecolor='#0078d7',
        facecolor='#0078d7', alpha=0.15,
        zorder=5, clip_on=True)
    state['sel_rect_patch'] = ax.add_patch(patch)
    canvas.draw_idle()

def _finalise_selection(x0, y0, x1, y1):
    global selected_voxels
    ix0 = max(0, int(min(x0, x1)))
    ix1 = min(X,  int(max(x0, x1)) + 1)
    iy0 = max(0, int(min(y0, y1)))
    iy1 = min(Y,  int(max(y0, y1)) + 1)
    selected_voxels = {
        (ix, iy)
        for ix in range(ix0, ix1)
        for iy in range(iy0, iy1)
    }
    draw_selection_highlight()
    set_status(f"Selected {len(selected_voxels)} voxels", '#0078d7')

def update_paint(event):
    if event.inaxes != ax or event.xdata is None:
        return
    ix = int(event.xdata)
    iy = int(event.ydata)
    if 0 <= ix < X and 0 <= iy < Y:
        mid = active_material['id']
        if grid[iy, ix] != mid:
            history.append((ix, iy, int(grid[iy, ix])))
            redo_stack.clear()
            grid[iy, ix] = mid
            im.set_data(make_image(grid))
            canvas.draw_idle()
            mark_unsaved()

def update_erase(event):
    if event.inaxes != ax or event.xdata is None:
        return
    ix = int(event.xdata)
    iy = int(event.ydata)
    if 0 <= ix < X and 0 <= iy < Y:
        if grid[iy, ix] != 0:
            history.append((ix, iy, int(grid[iy, ix])))
            redo_stack.clear()
            grid[iy, ix] = 0
            if (ix, iy) in mag_grid:
                del mag_grid[(ix, iy)]
            im.set_data(make_image(grid))
            canvas.draw_idle()
            mark_unsaved()

def update_mag(ix, iy, event):
    """Handles updating the mag_grid array dynamically.
    
    If Ctrl is held, it paints an alternating sequence across voxels during a drag.
    If Ctrl is not held, it acts as a normal single-click/drag tool.
    """
    global alternator_counter, alternator_axis
    
    if grid[iy, ix] != 0:
        # ── CASE 1: Alternator Paint Brush (Ctrl is active) ──
        if state.get('ctrl_pressed', False) or event.key == 'control':
            # Only update if this is a fresh voxel boundary during the current stroke
            if (ix, iy) not in current_stroke_modified_voxels:
                
                # Determine vector layout based on active Alt axis selection
                if alternator_axis == 'x':
                    dir_vec = (1.0, 0.0, 0.0) if alternator_counter == 0 else (-1.0, 0.0, 0.0)
                elif alternator_axis == 'y':
                    dir_vec = (0.0, 1.0, 0.0) if alternator_counter == 0 else (0.0, -1.0, 0.0)
                else: # Default 'z'
                    dir_vec = (0.0, 0.0, 1.0) if alternator_counter == 0 else (0.0, 0.0, -1.0)
                
                # Update the grid data
                mag_grid[(ix, iy)] = (dir_vec[0], dir_vec[1], dir_vec[2], 20000.0)
                current_stroke_modified_voxels.add((ix, iy))
                
                # Update status text
                sign_str = "+" if alternator_counter == 0 else "-"
                set_status(f"Painting Alternator: {sign_str}{alternator_axis.upper()} at ({ix}, {iy})", '#2ecc71')
                
                # Flip the sequence toggle for the next voxel step
                alternator_counter = 1 - alternator_counter
                canvas.draw_idle()
        
        # ── CASE 2: Normal Click (No Ctrl) ──
        else:
            # Only open the dialog if it's a single click event, not a dragging motion
            if event.name == 'button_press_event':
                open_mag_dialog(ix, iy)
    else:
        if event.name == 'button_press_event':
            set_status("Paint a voxel first before setting magnetisation", 'orange')

def on_press(event):
    if event.button != 1 or event.inaxes != ax:
        return
    state['is_dragging'] = True

    # Reset the drag stroke history when clicking down
    global current_stroke_modified_voxels
    current_stroke_modified_voxels = set()

    if current_tool['name'] == 'select':
        _clear_sel_rect()
        selected_voxels.clear()
        sel_overlay.set_data(np.zeros((Y, X, 4)))
        state['sel_start_data'] = (event.xdata, event.ydata)

    elif current_tool['name'] == 'paint':
        update_paint(event)

    elif current_tool['name'] == 'erase':
        update_erase(event)

    elif current_tool['name'] == 'mag':
        ix = int(event.xdata)
        iy = int(event.ydata)
        if 0 <= ix < X and 0 <= iy < Y:
            update_mag(ix, iy, event)

    elif current_tool['name'] == 'pan':
        state['pan_start_data'] = (event.x, event.y)
        state['pan_xlim']       = ax.get_xlim()
        state['pan_ylim']       = ax.get_ylim()

def mag_key_press(event):
    global alternator_axis
    if event.key == 'control':
        state['ctrl_pressed'] = True
        set_status("Alternator Brush Active (Hold Ctrl + Drag)", '#3498db')
        
    elif current_tool['name'] == 'mag':
        if event.key == 'alt+x':
            alternator_axis = 'x'
            set_status("Alternator Axis set to X", '#2ecc71')
        elif event.key == 'alt+y':
            alternator_axis = 'y'
            set_status("Alternator Axis set to Y", '#2ecc71')
        elif event.key == 'alt+z':
            alternator_axis = 'z'
            set_status("Alternator Axis set to Z", '#2ecc71')

def mag_key_release(event):
    if event.key == 'control':
        state['ctrl_pressed'] = False
        set_status("Standard Brush Active", 'gray')

def on_release(event):
    if event.button != 1:
        return
    state['is_dragging'] = False

    if current_tool['name'] == 'select':
        if state['sel_start_data'] and event.inaxes == ax and event.xdata is not None:
            x0, y0 = state['sel_start_data']
            _finalise_selection(x0, y0, event.xdata, event.ydata)
        state['sel_start_data'] = None
        _clear_sel_rect()
        canvas.draw_idle()

    elif current_tool['name'] == 'pan':
        state['pan_start_data'] = None
        state['pan_xlim']       = None
        state['pan_ylim']       = None

def _paste_at_selection_center():
    if not selected_voxels or not clipboard['data']:
        return
    sel_xs = [pos[0] for pos in selected_voxels]
    sel_ys = [pos[1] for pos in selected_voxels]
    cx = (min(sel_xs) + max(sel_xs)) // 2
    cy = (min(sel_ys) + max(sel_ys)) // 2
    clip_xs = [pos[0] for pos in clipboard['data']]
    clip_ys = [pos[1] for pos in clipboard['data']]
    clip_cx = (min(clip_xs) + max(clip_xs)) // 2
    clip_cy = (min(clip_ys) + max(clip_ys)) // 2
    dx = cx - clip_cx
    dy = cy - clip_cy
    paste_snapshot = []
    for (ix, iy), val in clipboard['data'].items():
        nx = ix + dx
        ny = iy + dy
        if 0 <= nx < X and 0 <= ny < Y:
            paste_snapshot.append((nx, ny, int(grid[ny, nx])))
    history.append(paste_snapshot)
    redo_stack.clear()
    for (nx, ny, _) in paste_snapshot:
        orig_x = nx - dx
        orig_y = ny - dy
        grid[ny, nx] = clipboard['data'].get((orig_x, orig_y), 0)

        orig_pos = (orig_x, orig_y)
        new_pos  = (nx, ny)
        if orig_pos in clipboard.get('mag', {}):
            mag_grid[new_pos] = clipboard['mag'][orig_pos]
        elif new_pos in mag_grid:
            # Clear any existing mag at destination if source had none
            del mag_grid[new_pos]

    im.set_data(make_image(grid))
    draw_selection_highlight()
    canvas.draw_idle()
    mark_unsaved()
    set_status(f"Pasted {len(paste_snapshot)} voxels", 'green')

def on_scroll(event):
    if event.inaxes != ax:
        return
    scale = 1 / 1.15 if event.button == 'up' else 1.15
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    ax.set_xlim([event.xdata + (x - event.xdata) * scale for x in xlim])
    ax.set_ylim([event.ydata + (y - event.ydata) * scale for y in ylim])
    canvas.draw_idle()

def clear_selection():
    global selected_voxels
    selected_voxels.clear()
    _clear_sel_rect()
    # Clear highlight overlay
    sel_overlay.set_data(np.zeros((Y, X, 4)))
    canvas.draw_idle()
    set_status("Selection cleared", 'green')

def undo(event=None):
    if not history:
        return
    entry = history.pop()
    if isinstance(entry, list):
        redo_snapshot = []
        for (ix, iy, old_val) in entry:
            redo_snapshot.append((ix, iy, int(grid[iy, ix])))
            grid[iy, ix] = old_val
        redo_stack.append(redo_snapshot)
    else:
        ix, iy, old_val = entry
        redo_stack.append((ix, iy, int(grid[iy, ix])))
        grid[iy, ix] = old_val
    im.set_data(make_image(grid))
    canvas.draw_idle()
    mark_unsaved()

def redo(event=None):
    if not redo_stack:
        return
    entry = redo_stack.pop()
    if isinstance(entry, list):
        history_snapshot = []
        for (ix, iy, new_val) in entry:
            history_snapshot.append((ix, iy, int(grid[iy, ix])))
            grid[iy, ix] = new_val
        history.append(history_snapshot)
    else:
        ix, iy, new_val = entry
        history.append((ix, iy, int(grid[iy, ix])))
        grid[iy, ix] = new_val
    im.set_data(make_image(grid))
    canvas.draw_idle()
    mark_unsaved()

def open_mag_dialog(ix, iy):
    import math
    import sim_runner as sr

    state['is_dragging']    = False
    state['sel_start_data'] = None
    state['pan_start_data'] = None

    current = mag_grid.get((ix, iy), None)
    if current and len(current) == 4:
        Mx, My, Mz, M_val = current
        init_phi   = round(math.degrees(math.asin(max(-1, min(1, Mz)))), 1)
        init_theta = round(math.degrees(math.atan2(My, Mx)), 1)
        init_m     = M_val
    elif current and len(current) == 3:
        # Legacy 3-tuple support
        Mx, My, Mz = current
        init_phi   = round(math.degrees(math.asin(max(-1, min(1, Mz)))), 1)
        init_theta = round(math.degrees(math.atan2(My, Mx)), 1)
        init_m     = sr.M_PER_VOL
    else:
        init_theta, init_phi = 0.0, 90.0
        init_m = sr.M_PER_VOL

    dialog = tk.Toplevel(root)
    dialog.title(f"Magnetisation — Voxel ({ix}, {iy})")
    dialog.geometry("260x300")   # ← taller for magnitude input
    dialog.resizable(False, False)
    dialog.configure(bg='#f0f0f0')
    dialog.update()
    dialog.grab_set()

    tk.Label(dialog, text=f"Voxel ({ix}, {iy})",
             bg='#f0f0f0', font=('Arial', 9, 'bold')).pack(pady=(8, 4))

    # ── Preset buttons ────────────────────────────────────────
    preset_frame = tk.Frame(dialog, bg='#f0f0f0')
    preset_frame.pack(fill=tk.X, padx=12, pady=2)
    tk.Label(preset_frame, text="Direction Preset:",
             bg='#f0f0f0', font=('Arial', 8)).pack(anchor='w')

    theta_var = tk.DoubleVar(value=init_theta)
    phi_var   = tk.DoubleVar(value=init_phi)
    m_var     = tk.DoubleVar(value=init_m)

    def apply_preset(t, p):
        theta_var.set(t)
        phi_var.set(p)

    presets = [
        ('+X', (0,   0)), ('-X', (180,  0)), ('+Y', (90,  0)),
        ('-Y', (270, 0)), ('+Z', (0,   90)), ('-Z', (0,  -90)),
    ]

    preset_grid_frame = tk.Frame(preset_frame, bg='#f0f0f0')
    preset_grid_frame.pack(fill=tk.X)
    for i, (label, (t, p)) in enumerate(presets):
        tk.Button(preset_grid_frame, text=label, width=4,
                  font=('Arial', 8),
                  command=lambda t=t, p=p: apply_preset(t, p)
                  ).grid(row=i // 3, column=i % 3, padx=2, pady=1)

    # ── Angle inputs ──────────────────────────────────────────
    angle_frame = tk.Frame(dialog, bg='#f0f0f0')
    angle_frame.pack(fill=tk.X, padx=12, pady=4)

    r1 = tk.Frame(angle_frame, bg='#f0f0f0')
    r1.pack(fill=tk.X, pady=2)
    tk.Label(r1, text="θ° azimuth (XY):",
             bg='#f0f0f0', font=('Arial', 8)).pack(side=tk.LEFT)
    tk.Entry(r1, textvariable=theta_var,
             width=7, justify='center').pack(side=tk.RIGHT)

    r2 = tk.Frame(angle_frame, bg='#f0f0f0')
    r2.pack(fill=tk.X, pady=2)
    tk.Label(r2, text="φ° elevation:",
             bg='#f0f0f0', font=('Arial', 8)).pack(side=tk.LEFT)
    tk.Entry(r2, textvariable=phi_var,
             width=7, justify='center').pack(side=tk.RIGHT)

    tk.Label(dialog,
             text="φ=90°→+Z  φ=0°,θ=0°→+X  φ=0°,θ=90°→+Y",
             bg='#f0f0f0', font=('Arial', 7), fg='gray').pack()

    # ── Separator ─────────────────────────────────────────────
    tk.Frame(dialog, bg='#cccccc', height=1).pack(
        fill=tk.X, padx=12, pady=6)

    # ── Magnitude input ───────────────────────────────────────
    mag_frame = tk.Frame(dialog, bg='#f0f0f0')
    mag_frame.pack(fill=tk.X, padx=12, pady=2)

    tk.Label(mag_frame, text="M/Vol (A/m):",
             bg='#f0f0f0', font=('Arial', 8)).pack(side=tk.LEFT)
    tk.Entry(mag_frame, textvariable=m_var,
             width=10, justify='center').pack(side=tk.RIGHT)

    # Reset to material default button
    def reset_to_mat_default():
        m_var.set(sr.M_PER_VOL)

    tk.Button(dialog, text=f"Reset to default ({sr.M_PER_VOL:.0f} A/m)",
              command=reset_to_mat_default,
              bg='#555', fg='white', font=('Arial', 7),
              relief=tk.FLAT).pack(padx=12, pady=2, fill=tk.X)

    # ── Apply / Clear / Cancel ────────────────────────────────
    def on_apply():
        try:
            theta = math.radians(float(theta_var.get()))
            phi   = math.radians(float(phi_var.get()))
            M_val = float(m_var.get())
            if M_val < 0:
                raise ValueError("M/Vol must be positive")
            Mx = math.cos(theta) * math.cos(phi)
            My = math.sin(theta) * math.cos(phi)
            Mz = math.sin(phi)
            mag_grid[(ix, iy)] = (Mx, My, Mz, M_val)
            set_status(
                f"Voxel ({ix},{iy}): "
                f"θ={float(theta_var.get()):.1f}°, "
                f"φ={float(phi_var.get()):.1f}°, "
                f"M={M_val:.0f} A/m",
                'green')
            mark_unsaved()
            dialog.destroy()
        except ValueError as err:
            from tkinter import messagebox
            messagebox.showerror("Error", str(err))

    def on_clear():
        if (ix, iy) in mag_grid:
            del mag_grid[(ix, iy)]
        set_status(f"Voxel ({ix},{iy}) reset to default", 'green')
        mark_unsaved()
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg='#f0f0f0')
    btn_frame.pack(pady=6)
    tk.Button(btn_frame, text="Apply", command=on_apply,
              bg='#27ae60', fg='white', font=('Arial', 9, 'bold'),
              relief=tk.FLAT, width=7).pack(side=tk.LEFT, padx=3)
    tk.Button(btn_frame, text="Clear", command=on_clear,
              bg='#e67e22', fg='white', font=('Arial', 9),
              relief=tk.FLAT, width=7).pack(side=tk.LEFT, padx=3)
    tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
              bg='#888', fg='white', font=('Arial', 9),
              relief=tk.FLAT, width=7).pack(side=tk.LEFT, padx=3)

def update_grid_size():
    global X, Y, grid
    try:
        new_x = int(grid_entries['X Voxels'].get())
        new_y = int(grid_entries['Y Voxels'].get())
        if new_x < 1 or new_y < 1:
            from tkinter import messagebox
            messagebox.showerror("Error", "Grid size must be at least 1.")
            return
        X, Y  = new_x, new_y
        grid  = np.zeros((Y, X), dtype=int)
        mag_grid.clear()
        clear_mag_arrows()
        mag_hover_voxel['pos'] = None
        history.clear()
        redo_stack.clear()
        selected_voxels.clear()
        _clear_sel_rect()
        im.set_data(make_image(grid))
        im.set_extent([0, X, 0, Y])
        sel_overlay.set_data(np.zeros((Y, X, 4)))
        sel_overlay.set_extent([0, X, 0, Y])
        ax.set_xlim(0, X)
        ax.set_ylim(0, Y)
        ax.set_aspect('equal')
        draw_grid_lines()
        ax.set_xlabel('X — Voxel Index', loc='right', fontsize=8)
        ax.set_ylabel('Y — Voxel Index', loc='top', fontsize=8)
        canvas.draw()
        set_status(f"Grid updated to {X} × {Y}", 'green')
    except ValueError:
        from tkinter import messagebox
        messagebox.showerror("Error", "Please enter valid integers.")

def run_simulation():
    import sim_runner as sr
    try:
        B_mT = float(b_entry.get())
    except ValueError:
        set_status("Invalid B field value!", 'red')
        return

    if np.sum(grid) == 0:
        set_status("Paint some voxels first!", 'red')
        return

    # ── Read material from selected item in listbox ───────────
    name  = active_material['name']
    props = materials[name]

    sr.LATTICE_DIM = props['LATTICE_DIM']
    sr.ELASTIC_MOD = props['ELASTIC_MOD']
    sr.DENSITY     = props['DENSITY']
    sr.POISSONS    = props['POISSONS']
    sr.M_PER_VOL   = props['M_PER_VOL']

    b_dir = get_b_direction()

    set_status("Running...", 'orange')
    root.update()

    try:
        result = run_voxelyze(grid=grid, N_X=X, N_Y=Y,
                      B_mT=B_mT, materials=materials, 
                      B_direction=b_dir, 
                      mag_grid=mag_grid, 
                      debug=False)

        metrics = result.get('metrics', {})
        tip = float(metrics.get('tip_deflection_z', result['tip_deflection'])) * 1e3
        max_disp = float(metrics.get('max_displacement', 0.0)) * 1e3
        com_disp = float(metrics.get('com_displacement', 0.0)) * 1e3
        n_filled = int(np.sum(grid))
        set_status(
            f"✓ Done!\nTipZ: {tip:+.4f} mm\nMax: {max_disp:.4f} mm\nCOM: {com_disp:.4f} mm",
            'green')
        show_result_plot(result, B_mT)
    except Exception as e:
        set_status(f"Error: {str(e)[:50]}", 'red')
        print(f"Simulation error: {e}")

def show_result_plot(result, B_mT):
    import sim_runner as sr
    """Opens simulation result in a popup window with menubar and save button."""

    popup = tk.Toplevel(root)
    popup.title("Simulation Result")
    popup.geometry("800x550")
    popup.configure(bg='white')

    # ── Popup menu bar ────────────────────────────────────────
    popup_menubar = tk.Menu(popup)
    popup.config(menu=popup_menubar)

    view_popup_menu = tk.Menu(popup_menubar, tearoff=0)
    popup_menubar.add_cascade(label="View", menu=view_popup_menu)
    view_popup_menu.add_command(label="2D Plot",  command=lambda: show_tab(0))
    view_popup_menu.add_command(label="3D Plot",  command=lambda: show_tab(1))
    view_popup_menu.add_command(label="Morphing",  command=lambda: show_tab(2))

    # ── Popup toolbar ─────────────────────────────────────────
    popup_toolbar = tk.Frame(popup, bg='#f0f0f0', height=30,
                              relief=tk.RAISED, bd=1)
    popup_toolbar.pack(side=tk.TOP, fill=tk.X)
    popup_toolbar.pack_propagate(False)

    tk.Button(popup_toolbar, text="Save", font=('Arial', 9),
              relief=tk.FLAT, bg='#f0f0f0', cursor='hand2',
              command=lambda: save_plot()).pack(side=tk.LEFT, padx=8)

    # ── Notebook ──────────────────────────────────────────────
    plot_notebook = ttk.Notebook(popup)
    plot_notebook.pack(fill=tk.BOTH, expand=True)

    # ── 2D Plot tab — two side by side ───────────────────────────
    tab_2d = tk.Frame(plot_notebook, bg='white')
    plot_notebook.add(tab_2d, text=" 2D Plot ")

    fig2d = Figure(figsize=(10, 4), facecolor='#0d1117', tight_layout=True)

    # Get data directly from result
    all_pos   = result['all_positions']      # deformed positions
    init_pos  = result['initial_positions']  # undeformed positions
    disps     = result['displacements']      # per-voxel displacement vectors

    # ── Left: XZ view — Z displacement vs initial X ──────────────
    ax2d_xz.scatter(
        init_pos[:, 0] * 1e3,   # initial x position (mm)
        disps[:, 2]    * 1e3,   # z displacement (mm)
        c=disps[:, 2]  * 1e3,
        cmap='cool', s=15, alpha=0.8)
    ax2d_xz.axhline(0, color='#555', linewidth=0.8, linestyle='--')
    ax2d_xz.set_xlabel('Initial x position [mm]', color='white', fontsize=9)
    ax2d_xz.set_ylabel('z displacement [mm]',     color='white', fontsize=9)
    ax2d_xz.set_title('XZ View — Vertical Deflection',
                    color='white', fontsize=10)
    ax2d_xz.tick_params(colors='white')
    for spine in ax2d_xz.spines.values():
        spine.set_edgecolor('#444')

    # ── Right: XY view — deformed shape top-down ─────────────────
    ax2d_xy.scatter(
        all_pos[:, 0] * 1e3,   # deformed x (mm)
        all_pos[:, 1] * 1e3,   # deformed y (mm)
        c=disps[:, 2] * 1e3,   # color by z-displacement
        cmap='plasma', s=15, alpha=0.8)
    ax2d_xy.set_xlabel('x position [mm]', color='white', fontsize=9)
    ax2d_xy.set_ylabel('y position [mm]', color='white', fontsize=9)
    ax2d_xy.set_title('XY View — Top Down (deformed)',
                    color='white', fontsize=10)
    ax2d_xy.tick_params(colors='white')
    for spine in ax2d_xy.spines.values():
        spine.set_edgecolor('#444')

    # ── Shared title ──────────────────────────────────────────────
    metrics = result.get('metrics', {})
    tip_z   = metrics.get('tip_deflection_z', result['tip_deflection']) * 1e3
    tip_y   = metrics.get('tip_deflection_y', 0) * 1e3
    max_d   = metrics.get('max_displacement', 0) * 1e3
    fig2d.suptitle(
        f'B = {B_mT:.1f} mT  |  '
        f'Tip Z: {tip_z:+.4f} mm  |  '
        f'Tip Y: {tip_y:+.4f} mm  |  '
        f'Max disp: {max_d:.4f} mm',
        color='white', fontsize=9, y=1.01)

    canvas2d = FigureCanvasTkAgg(fig2d, master=tab_2d)
    canvas2d.draw()
    canvas2d.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ── 3D Plot ───────────────────────────────────────────────
    tab_3d = tk.Frame(plot_notebook, bg='white')
    plot_notebook.add(tab_3d, text=" 3D Plot ")

    fig3d = Figure(figsize=(7, 4), facecolor='#0d1117')
    ax3d  = fig3d.add_subplot(111, projection='3d')
    ax3d.set_facecolor('#0d1117')
    ax3d.xaxis.pane.fill = False
    ax3d.yaxis.pane.fill = False
    ax3d.zaxis.pane.fill = False
    ax3d.xaxis.pane.set_edgecolor('#333')
    ax3d.yaxis.pane.set_edgecolor('#333')
    ax3d.zaxis.pane.set_edgecolor('#333')

    all_pos = result['all_positions']
    ax3d.scatter(all_pos[:, 0] * 1e3,
                 all_pos[:, 1] * 1e3,
                 all_pos[:, 2] * 1e3,
                 c=all_pos[:, 2] * 1e3,
                 cmap='plasma', s=20, alpha=0.8)

    ax3d.set_xlabel('X [mm]', color='white', fontsize=9)
    ax3d.set_ylabel('Y [mm]', color='white', fontsize=9)
    ax3d.set_zlabel('Z [mm]', color='white', fontsize=9)
    ax3d.set_title(f'3D Deformed Shape  |  B = {B_mT:.1f} mT',
                   color='white', fontsize=11)
    for axis in [ax3d.xaxis, ax3d.yaxis, ax3d.zaxis]:
        axis.set_tick_params(labelcolor='white')

    canvas3d = FigureCanvasTkAgg(fig3d, master=tab_3d)
    canvas3d.draw()
    canvas3d.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ── Morphing Animation tab ────────────────────────────────────
    tab_morph = tk.Frame(plot_notebook, bg='#0d1117')
    plot_notebook.add(tab_morph, text=" Morphing ")

    fig_morph = Figure(figsize=(7, 4), facecolor='#0d1117')
    ax_morph  = fig_morph.add_subplot(111, projection='3d')
    ax_morph.set_facecolor('#0d1117')
    ax_morph.xaxis.pane.fill = False
    ax_morph.yaxis.pane.fill = False
    ax_morph.zaxis.pane.fill = False
    ax_morph.xaxis.pane.set_edgecolor('#333')
    ax_morph.yaxis.pane.set_edgecolor('#333')
    ax_morph.zaxis.pane.set_edgecolor('#333')
    ax_morph.grid(True, color='#333', linewidth=0.4)

    canvas_morph = FigureCanvasTkAgg(fig_morph, master=tab_morph)
    canvas_morph.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ── Build before/after position arrays ───────────────────────
    import math as _math

    before_pos = result['initial_positions'] * 1e3  # already in metres, convert to mm
    after_pos  = result['all_positions']     * 1e3

    # Match lengths in case of mismatch
    n = min(len(before_pos), len(after_pos))
    before_pos = before_pos[:n]
    after_pos  = after_pos[:n]

    # ── Compute axis limits from both states ──────────────────────
    all_combined = np.vstack([before_pos, after_pos])
    x_min, x_max = all_combined[:, 0].min(), all_combined[:, 0].max()
    y_min, y_max = all_combined[:, 1].min(), all_combined[:, 1].max()
    z_min, z_max = all_combined[:, 2].min(), all_combined[:, 2].max()

    # Calculate tight padding independently for each axis (matches 2D/3D profile)
    x_pad = (x_max - x_min) * 0.15 if (x_max - x_min) != 0 else 1.0
    y_pad = (y_max - y_min) * 0.15 if (y_max - y_min) != 0 else 1.0
    z_pad = (z_max - z_min) * 0.15 if (z_max - z_min) != 0 else 1.0

    ax_morph.set_xlim(x_min - x_pad, x_max + x_pad)
    ax_morph.set_ylim(y_min - y_pad, y_max + y_pad)
    ax_morph.set_zlim(z_min - z_pad, z_max + z_pad)

    ax_morph.set_xlabel('X [mm]', color='white', fontsize=9)
    ax_morph.set_ylabel('Y [mm]', color='white', fontsize=9)
    ax_morph.set_zlabel('Z [mm]', color='white', fontsize=9)
    ax_morph.set_title(f'Shape Morphing  |  B = {B_mT:.1f} mT',
                    color='white', fontsize=11)
    for axis in [ax_morph.xaxis, ax_morph.yaxis, ax_morph.zaxis]:
        axis.set_tick_params(labelcolor='white')

    # ── Animation state ───────────────────────────────────────────
    N_FRAMES   = 60          # total frames for one full cycle
    anim_state = {
        'running':  False,
        'frame':    0,
        'job':      None,
    }

    # Initial scatter
    scat = ax_morph.scatter(
        before_pos[:, 0], before_pos[:, 1], before_pos[:, 2],
        c=before_pos[:, 2], cmap='plasma',
        s=15, alpha=0.85, zorder=5)

    # Progress label
    prog_label = tk.Label(tab_morph, text="Frame: 0 / 60",
                        bg='#0d1117', fg='#888', font=('Courier', 8))
    prog_label.pack(side=tk.BOTTOM, pady=2)

    def start_anim():
        if not anim_state['running']:
            anim_state['running'] = True
            btn_play.config(text="⏸ Pause")
            animate_frame()

    def pause_anim():
        anim_state['running'] = False
        if anim_state['job']:
            tab_morph.after_cancel(anim_state['job'])
            anim_state['job'] = None
        btn_play.config(text="▶ Play")

    def toggle_anim():
        if anim_state['running']:
            pause_anim()
        else:
            start_anim()

    def reset_anim():
        pause_anim()
        anim_state['frame'] = 0
        scat._offsets3d = (before_pos[:, 0],
                        before_pos[:, 1],
                        before_pos[:, 2])
        scat.set_array(before_pos[:, 2])
        canvas_morph.draw_idle()
        prog_label.config(text="Frame: 0 / 60")
        btn_play.config(text="▶ Play")

    # Stop animation when popup is closed
    def on_popup_close():
        pause_anim()
        popup.destroy()
    popup.protocol("WM_DELETE_WINDOW", on_popup_close)

    # ── Morph controls toolbar ────────────────────────────────────
    morph_ctrl = tk.Frame(tab_morph, bg='#1a1a2e')
    morph_ctrl.pack(side=tk.BOTTOM, fill=tk.X, pady=4)

    btn_play = tk.Button(morph_ctrl, text="▶ Play", command=toggle_anim,
                        bg='#27ae60', fg='white',
                        font=('Arial', 9, 'bold'),
                        relief=tk.FLAT, cursor='hand2', width=8)
    btn_play.pack(side=tk.LEFT, padx=8)

    tk.Button(morph_ctrl, text="⟳ Reset", command=reset_anim,
            bg='#2980b9', fg='white',
            font=('Arial', 9),
            relief=tk.FLAT, cursor='hand2', width=8).pack(side=tk.LEFT, padx=4)

    # Speed slider
    tk.Label(morph_ctrl, text="Speed:",
            bg='#1a1a2e', fg='white',
            font=('Arial', 8)).pack(side=tk.LEFT, padx=(12, 2))

    speed_var = tk.IntVar(value=30)

    def on_speed_change(val):
        speed_var.set(int(float(val)))

    speed_slider = ttk.Scale(morph_ctrl, from_=5, to=100,
                            orient=tk.HORIZONTAL, length=100,
                            variable=speed_var,
                            command=on_speed_change)
    speed_slider.pack(side=tk.LEFT, padx=4)

    tk.Label(morph_ctrl, text="ms/frame",
            bg='#1a1a2e', fg='#888',
            font=('Arial', 7)).pack(side=tk.LEFT)

    # Update animate_frame to use speed slider
    def animate_frame():
        if not anim_state['running']:
            return
        f = anim_state['frame']
        t = (1 - _math.cos(_math.pi * f / N_FRAMES)) / 2
        interp = (1 - t) * before_pos + t * after_pos
        scat._offsets3d = (interp[:, 0], interp[:, 1], interp[:, 2])
        scat.set_array(interp[:, 2])
        canvas_morph.draw_idle()
        prog_label.config(text=f"Frame: {f+1} / {N_FRAMES}")
        anim_state['frame'] = (f + 1) % N_FRAMES
        delay = speed_var.get()
        anim_state['job'] = tab_morph.after(delay, animate_frame)

    canvas_morph.draw()

    def show_tab(index):
        plot_notebook.select(index)

    def save_plot():
        from tkinter import filedialog
        current_tab = plot_notebook.index(plot_notebook.select())
        if current_tab == 0:
            fig_to_save, tab_name = fig2d, "2d"
        elif current_tab == 1:
            fig_to_save, tab_name = fig3d, "3d"
        else:
            fig_to_save, tab_name = fig_morph, "morph"
        filepath = filedialog.asksaveasfilename(
            defaultextension=".png",
            initialfile=f"beam_result_{B_mT:.0f}mT_{tab_name}.png",
            filetypes=[("PNG Image", "*.png"),
                    ("JPEG Image", "*.jpg"),
                    ("All Files",  "*.*")])
        if filepath:
            fig_to_save.savefig(filepath,
                                bbox_inches='tight',
                                facecolor=fig_to_save.get_facecolor())
            tk.Label(popup_toolbar,
                    text=f"Saved: {os.path.basename(filepath)}",
                    bg='#f0f0f0', font=('Arial', 8), fg='green').pack(side=tk.LEFT)

canvas.mpl_connect('button_press_event',   on_press)
canvas.mpl_connect('motion_notify_event',  on_motion)
canvas.mpl_connect('button_release_event', on_release)
canvas.mpl_connect('scroll_event',         on_scroll)
canvas.mpl_connect('key_press_event', mag_key_press)
canvas.mpl_connect('key_release_event', mag_key_release)

canvas.draw()

# ── Keyboard shortcuts ────────────────────────────────────────
root.bind('<Control-n>', lambda e: new_file())
root.bind('<Control-o>', lambda e: open_file())
root.bind('<Control-s>', lambda e: save_file())
root.bind('<Control-S>', lambda e: save_file_as())
root.bind('<Control-z>', undo)
root.bind('<Control-y>', redo)
root.bind('<Control-x>', lambda e: do_cut())
root.bind('<Control-c>', lambda e: do_copy())
root.bind('<Control-v>', lambda e: do_paste())
root.bind('<Control-a>', lambda e: select_all())
root.bind('<Control-equal>', lambda e: zoom_in())   # Ctrl+=
root.bind('<Control-minus>', lambda e: zoom_out())  # Ctrl+-
root.bind('<Control-0>', lambda e: reset_zoom())    # Ctrl+0

# Tool keyboard shortcuts
root.bind('v', lambda e: set_select())   # V for Select
root.bind('p', lambda e: set_paint())    # P for Paint
root.bind('e', lambda e: set_erase())    # E for Erase
root.bind('<Delete>', lambda e: set_erase())  # Delete key for erase
root.bind('<BackSpace>', lambda e: set_erase())  # Backspace for erase
root.bind('<Escape>', lambda e: clear_selection())  # Escape to clear selection

root.mainloop()