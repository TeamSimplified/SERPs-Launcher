import os
import ctypes
import customtkinter as ctk
import json
import shutil
import subprocess
import tkinter as tk
import zipfile
import rarfile
import py7zr
import errno
import threading
import time
import psutil
import msvcrt
import sys

from ctypes import wintypes
from ctypes import windll
from datetime import datetime, timedelta
from functools import partial
from PIL import Image
from tkinter import Tk, Label, Button, filedialog, messagebox, IntVar, StringVar, Frame, Scrollbar, RIGHT, Y, LEFT, BOTH, Checkbutton, PhotoImage, simpledialog, ttk, Canvas
from tkinterdnd2 import DND_FILES, TkinterDnD

MODS_FOLDER = "mods"
APP_FOLDER = "app"
BACKUP_FOLDER = os.path.join(APP_FOLDER, "backups")

GAME_DIRECTORY_FILE = os.path.join(APP_FOLDER, "game_directory.serps")
INSTALLED_MODS_FILE = os.path.join(APP_FOLDER, "installed_mods.serps")
RECENT_FILE = os.path.join(APP_FOLDER, "recent_mods.serps")
FAVORITES_FILE = os.path.join(APP_FOLDER, "favorites.serps")
LAST_VIEW_FILE = os.path.join(APP_FOLDER, "last_view.serps")

SUPPORTED_EXTENSIONS = (".erp", ".bk2", ".bdl", ".png", ".mipmaps", ".pdf", ".lng")

LOCKFILE = os.path.join(APP_FOLDER, "instance.serps")
lock_file_handle = None

def is_mod_signature_folder(name: str) -> bool:
    lower = name.lower()
    return (
        name == "2025_asset_groups" or
        name == "shader_package_2025" or
        name == "localisatioa" or
        name == "audio"        or
        name == "videos"
    )

def path_has_signature(path: str) -> bool:
    return any(is_mod_signature_folder(seg) for seg in path.split("/"))

def find_signature_index(parts: list[str]) -> int | None:
    for i, p in enumerate(parts):
        if is_mod_signature_folder(p):
            return i
    return None

def is_already_running():
    global lock_file_handle
    try:
        lock_file_handle = open(LOCKFILE, "w")
        msvcrt.locking(lock_file_handle.fileno(), msvcrt.LK_NBLCK, 1)
        return False  # Lock acquired
    except OSError:
        return True  # Another instance is already running

def make_window_rounded(hwnd):
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWCP_ROUND = 2
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        hwnd,
        DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
        ctypes.sizeof(ctypes.c_int())
    )

def get_hwnd(window):
    window.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
    return hwnd

class ToolTip:
    """
    A tooltip that can display either:
      - a single plain string (old behavior, via `text=…`)
      - a list of (text, font, fg) tuples (new "rich_lines" behavior)
    """

    def __init__(self, widget, *, text=None, rich_lines=None, bg="#333333", padx=4, pady=2):
        """
        widget:     the tkinter widget to which this tooltip is attached
        text:       plain string (old behavior)
        rich_lines: list of (text:str, font:tuple, fg:str) if you want per-line styling
        bg:         background color for the tooltip window
        padx/pady:  internal padding around each Label
        """
        self.widget = widget
        self.text = text
        self.rich_lines = rich_lines
        self.bg = bg
        self.padx = padx
        self.pady = pady

        self._tipwindow = None
        self.widget.bind("<Enter>",   self._enter)
        self.widget.bind("<Leave>",   self._leave)
        self.widget.bind("<ButtonPress>", self._leave)

    def _enter(self, event=None):
        # 1) If the widget has a “state” option and is disabled, do nothing:
        try:
            if self.widget.cget("state") == "disabled":
                return
        except Exception:
            pass

        # 2) Otherwise, show the tooltip as before:
        if not self._tipwindow:
            self.showtip()

    def _leave(self, event=None):
        self.hidetip()

    def showtip(self):
        # create a Toplevel window that floats above all
        self._tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.configure(bg=self.bg)

        # Position the tooltip near the mouse pointer
        x = self.widget.winfo_pointerx() + 10
        y = self.widget.winfo_pointery() + 10
        tw.wm_geometry(f"+{x}+{y}")

        # If user passed a list of rich_lines, pack a Label per line:
        if self.rich_lines:
            # Use a Frame so that you can pack multiple Labels inside:
            top_bar = tk.Frame(tw, bg="#5345ff", height=4)  # Use your brand blue
            top_bar.pack(fill="x", side="top")
            frame = tk.Frame(tw, bg="#333333")
            frame.pack(padx=16, pady=8)

            for (line_text, font_spec, fg_color) in self.rich_lines:
                lbl = tk.Label(
                    frame,
                    text=line_text,
                    font=font_spec,
                    fg=fg_color,
                    bg=self.bg,
                    anchor="w"
                )
                lbl.pack(fill="x", expand=True)
        else:
            # Fallback to old behavior (single string)
            top_bar = tk.Frame(tw, bg="#5345ff", height=4)  # Use your brand blue
            top_bar.pack(fill="x", side="top")
            lbl = tk.Label(
                tw,
                text=self.text or "", padx=16, pady=8,
                justify=tk.LEFT,
                background="#333333",
                foreground="white",
                font=("Segoe UI", 9),
            )
            lbl.pack(ipadx=self.padx, ipady=self.pady)

    def hidetip(self):
        tw = self._tipwindow
        if tw:
            tw.destroy()
        self._tipwindow = None

class SERPsLauncher:
    
    def __init__(self, master):
        self.master = master
        self.master.overrideredirect(True)
        self.master.configure(bg="#1e1e1e")
        
        self.master.title("SERPs Launcher for F1 25")
        self.master.iconbitmap("app/serps.ico")
        
        style = ttk.Style()
        style.theme_use('clam')  # use 'clam' for better customization

        style.configure("CustomCombobox.TCombobox",
        foreground="#333333",
        background="#333333",
        fieldbackground="#2e2e2e",
        bordercolor="#444444",
        arrowcolor="#ffffff",
        lightcolor="#444444",
        darkcolor="#444444",
        borderwidth=1,
        relief="flat"
        )
        
        style.element_create('Custom.Vertical.Scrollbar.trough', 'from', 'clam')
        style.element_create('Custom.Vertical.Scrollbar.thumb', 'from', 'clam')

        style.layout('Custom.Vertical.TScrollbar',
                     [('Vertical.Scrollbar.trough',
                       {'children': [('Vertical.Scrollbar.thumb', {'unit': '1', 'sticky': 'nswe'})],
                        'sticky': 'ns'})])

        style.configure('Custom.Vertical.TScrollbar',
                        background='#444444',
                        troughcolor='#2b2b2b',
                        bordercolor='#1e1e1e',
                        arrowcolor='#ffffff',
                        relief='flat',
                        gripcount=0,
                        lightcolor='#444444',
                        darkcolor='#444444')

        window_width = 600
        window_height = 900
        screen_width = self.master.winfo_screenwidth()
        screen_height = self.master.winfo_screenheight()

        x_coordinate = int((screen_width / 2) - (window_width / 2))
        y_coordinate = int((screen_height / 2) - (window_height / 2))

        self.master.geometry(f"{window_width}x{window_height}+{x_coordinate}+{y_coordinate}")

        hwnd = get_hwnd(self.master)
        make_window_rounded(hwnd)

        os.makedirs(APP_FOLDER, exist_ok=True)
        os.makedirs("presets", exist_ok=True)

        self.game_path = self.load_game_directory()
        
        # somewhere near the top of SERPsLauncher.__init__
        self.ERP_DEPENDENCIES = {
          "markdown_system.erp",
          "credits.erp",
          "achievements.erp",
          "common_flow_customisation.erp",
          "flow_f1_life_driver_tags.erp",
          "flow_fz_environment.erp",
          "flow_loading.erp",
          "flow_persistent.erp",
          "flow_playercard.erp",
          "flow_render_badges.erp",
          "fonts.erp",
          "fonts_efigs_r_p.erp",
          "fonts_standard_icons.erp",
          "vehicle_carbon.nefx2.sm51.erp",
          "vehicle_custom_paint.nefx2.sm51.erp",
          "vehicle_damage_mask.nefx2.sm51.erp",
          "vehicle_floating_decal.nefx2.sm51.erp",
          "vehicle_gloss_paint.nefx2.sm51.erp",
          "vehicle_hologram_paint.nefx2.sm51.erp",
          "vehicle_metallic_paint.nefx2.sm51.erp",
          "vehicle_multi_paint.nefx2.sm51.erp",
          "vehicle_paint_shadowcast.nefx2.sm51.erp",
          "vehicle_rain_beads.nefx2.sm51.erp",
          "vehicle_steering.nefx2.sm51.erp",
          "vehicle_wheels.nefx2.sm51.erp",
          "effects_myteam.nefx2.sm51.erp",
          "photo_mode.nefx2.sm51.erp",
          "sponsor_board.nefx2.sm51.erp",
          "track_info.nefx2.sm51.erp",
          "character_helmet.nefx2.sm51.erp",
          "ui_texture.nefx2.sm51.erp",
          "vehicle_generic.nefx2.sm51.erp",
          "tyre_sidewall.nefx2.sm51.erp",
        }

        self.base_required_icon = ctk.CTkImage(
          light_image=Image.open("app/icons/serps.png"),
          size=(16,16)
        )
        
        self.base_mod_icon = ctk.CTkImage(
            light_image=Image.open("app/icons/base_files.png"),
            size=(16,16)
        )
        
        transparent_img = Image.new("RGBA", (16,16), (0,0,0,0))
        self.base_required_placeholder = ctk.CTkImage(
            light_image=transparent_img,
            size=(16,16)
        )

        self.mods = []
        self.mod_file_map = {}
        self.selected_mods = set()
        self.current_view_mode = self.load_last_view_mode()
        self._current_variant_group_container = None
        self.favorites = self.load_favorites()
        self.recent_mods = self.load_recent_mods()

        rarfile.UNRAR_TOOL = os.path.abspath("app/unrar/UnRAR.exe")

        self.path_var = StringVar()
        self.path_var.set(f"{self.game_path if self.game_path else 'No game directory set...'}")

        self.x = 0
        self.y = 0


        self.setup_ui()
        self.auto_restore_if_needed()
        self.restore_ready = False
        self.mod_context_menu = tk.Menu(self.master, tearoff=0, bg="#333333", fg="white", activebackground="#5345ff", activeforeground="white")
        self.mod_context_menu.add_command(label="Rename Mod", command=self.rename_selected_mod)
        self.mod_context_menu.add_command(label="Delete Mod", command=self.delete_selected_mod)
        self.right_clicked_mod_info = None  # to store which mod was right-clicked
        self.mod_checkbuttons = {}
        self.expanded_categories = {}
        self.expanded_variant_groups = {}
        self.expanded_recent_groups = {}
        self.switch_view(self.current_view_mode)
        self.monitor_game_process()
        self.disable_launch_if_game_running()

        self.master.bind("<Button-1>", self.start_drag)
        self.master.bind("<B1-Motion>", self.on_drag)

    def _archive_contains(self, archive_path: str, target: str) -> bool:
        """
        Return True if the file named `target` (basename, lowercase)
        appears anywhere in the given archive (.zip, .rar, .7z).
        """
        import zipfile, rarfile, py7zr
        target = target.lower()
        try:
            if archive_path.lower().endswith(".zip"):
                namelist = zipfile.ZipFile(archive_path).namelist()
            elif archive_path.lower().endswith(".rar"):
                namelist = [i.filename for i in rarfile.RarFile(archive_path).infolist()]
            elif archive_path.lower().endswith(".7z"):
                namelist = py7zr.SevenZipFile(archive_path).getnames()
            else:
                return False
        except Exception:
            return False

        # compare basenames
        return any(os.path.basename(n).lower() == target for n in namelist)

    def setup_ui(self):
        ### Header
        header = Frame(self.master, bg="#5345ff", height=80)
        header.pack(fill='x', side='top')
        header.pack_propagate(False)

        # Left side: SERPs logo
        self.logo_image = ctk.CTkImage(light_image=Image.open("app/serps.png"), size=(95, 38))

        logo_label = ctk.CTkLabel(
            master=header,
            image=self.logo_image,
            text="",
            bg_color="#5345ff"
        )
        logo_label.pack(side="left", padx=32)
        
        # Load quit icon
        self.quit_icon = ctk.CTkImage(light_image=Image.open("app/icons/clear.png"), size=(20, 20))  # Add an appropriate icon file

        # Quit button (icon)
        self.quit_btn = ctk.CTkButton(
            master=header,
            image=self.quit_icon,
            text="",
            width=40,
            height=40,
            fg_color="#5345ff",
            hover_color="#675fff",
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            command=self.quit_app  # new simple quit method
        )
        self.quit_btn.pack(side="right", padx=(0, 32))  # Slightly left of Discord
        self.quit_tooltip = ToolTip(self.quit_btn, text="Quit SERPs Launcher")

        # Right side: Discord icon
        self.discord_icon = ctk.CTkImage(light_image=Image.open("app/icons/discord.png"), size=(20, 15))

        discord_btn = ctk.CTkButton(
            master=header,
            image=self.discord_icon,
            text="",
            width=40,
            height=40,
            fg_color="#5345ff",
            hover_color="#675fff",
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            command=lambda: subprocess.Popen(["start", "https://discord.gg/HnKASRanTp"], shell=True)
        )
        discord_btn.pack(side="right", padx=(0, 8))  # Make sure vertical padding centers it visually
        ToolTip(discord_btn, text="Join the SERPs Discord server")



        
        ### Game directory
        self.top_frame = ctk.CTkFrame(self.master, fg_color="#1e1e1e", corner_radius=0)
        self.top_frame.pack(fill='x', pady=24, padx=32)

        dir_row = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        dir_row.pack(fill='x', pady=(0, 0))

        # Left side: label + path stacked
        label_path_container = ctk.CTkFrame(dir_row, fg_color="transparent")
        label_path_container.pack(side="left", fill="x", expand=True)

        dir_label = ctk.CTkLabel(
            master=label_path_container,
            text="Set your F1 25 game directory",
            text_color="#ffffff",
            font=("Segoe UI", 16, "bold"),
            anchor="w"
        )
        dir_label.pack(fill="x")

        path_display = ctk.CTkLabel(
            master=label_path_container,
            textvariable=self.path_var,
            text_color="#888888",
            font=("Segoe UI", 12),
            anchor="w",
            wraplength=480,
            justify="left"
        )
        path_display.pack(fill="x")

        # Right side: Browse button
        browse_btn = ctk.CTkButton(
            master=dir_row,
            text="Browse",
            width=144,
            height=40,
            fg_color="#333333",
            text_color="#ffffff",
            hover_color="#444444",
            font=("Segoe UI", 14, "bold"),
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            command=self.select_game_directory
        )
        browse_btn.pack(side="right")


      
        ### === Scrollable Mod Section ===
        list_container = Frame(self.master, bg="#1e1e1e")
        list_container.pack(pady=(0, 0), padx=32, fill=BOTH, expand=True)

        # Left area + dividers
        left_side = Frame(list_container, bg="#1e1e1e")
        left_side.pack(side=LEFT, fill=BOTH, expand=True)

        # Top divider (just above scrollable mods)
        top_line = Canvas(
            master=left_side,
            height=1,
            bg="#888888",
            highlightthickness=0,
            bd=0,
            relief="flat"
        )
        top_line.pack(fill="x", pady=(0, 16))
        
        # === Search Bar with Clear Button ===
        self.search_var = StringVar()

        # Container to hold the entry and clear button
        self.search_container = Frame(left_side, bg="#1e1e1e")
        self.search_container.pack(fill="x", padx=(0, 22), pady=(0, 8))
        
        # Entry field
        # Entry field with manual placeholder support
        self.search_entry = ctk.CTkEntry(
            master=self.search_container,
            textvariable=self.search_var,
            width=400,
            font=("Segoe UI", 12),
            fg_color="#2e2e2e",
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            text_color="#888888"  # Start with gray text
        )
        self.search_entry.insert(0, "Search mods...")  # Set initial placeholder

        def on_focus_in(event):
            if self.search_entry.get() == "Search mods...":
                self.search_entry.delete(0, "end")
                self.search_entry.configure(text_color="#ffffff")

        def on_focus_out(event):
            if self.search_entry.get().strip() == "":
                self.search_entry.insert(0, "Search mods...")
                self.search_entry.configure(text_color="#888888")

        self.search_entry.bind("<FocusIn>", on_focus_in)
        self.search_entry.bind("<FocusOut>", on_focus_out)

        self.search_entry.pack(side="left", fill="x", expand=True)
        
        self.pinned_base_mod_frame = ctk.CTkFrame(
            master=self.master, 
            corner_radius=6,
            fg_color="#1e1e1e",
            border_width=1,
            border_color="#5345ff"
        )

        # Load clear icon
        self.clear_search_icon = ctk.CTkImage(Image.open("app/icons/clear.png"), size=(16, 16))

        # Clear button (initially hidden)
        clear_btn = ctk.CTkButton(
            master=self.search_container,
            image=self.clear_search_icon,
            text="",
            width=28,
            height=28,
            fg_color="#333333",
            hover_color="#444444",
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            command=lambda: self.search_var.set("")
        )
        clear_btn.pack_forget()

        # Show/hide clear button based on input
        def update_clear_btn(*args):
            current_text = self.search_var.get().strip()
            if current_text and current_text.lower() != "search mods...":
                clear_btn.pack(side="right", padx=(8, 0))
            else:
                clear_btn.pack_forget()


        self.search_var.trace_add("write", update_clear_btn)

        # Trigger filtering on type
        self.search_var.trace_add("write", lambda *args: self.load_mods())



        # Scrollable mod list
        self.scroll_frame = Frame(left_side, bg="#1e1e1e")
        self.scroll_frame.pack(fill=BOTH, expand=True)

        canvas = Canvas(self.scroll_frame, bg="#1e1e1e", highlightthickness=0, height=50)
        scrollbar = ttk.Scrollbar(self.scroll_frame, orient="vertical", command=canvas.yview, style="Custom.Vertical.TScrollbar")
        self.list_frame = Frame(canvas, bg="#1e1e1e")

        def update_scroll_region(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if canvas.bbox("all")[3] > canvas.winfo_height():
                scrollbar.pack(side=RIGHT, fill=Y)
            else:
                scrollbar.pack_forget()

        self.list_frame.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_scroll_region)

        canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
       

        self.canvas = canvas  # Save reference
        


        # Bottom divider (just below scrollable mods)
        bottom_line = Canvas(
            master=left_side,
            height=1,
            bg="#888888",
            highlightthickness=0,
            bd=0,
            relief="flat"
        )
        bottom_line.pack(fill="x", pady=(16, 0))

        # Right: view toggle + action buttons (unchanged)
        # Load icons before creating buttons
        def load_icon(path, size):
            return ctk.CTkImage(light_image=Image.open(path), size=size)

        self.icon_all = load_icon("app/icons/all.png", (20, 20))
        self.icon_all_active = load_icon("app/icons/all_active.png", (20, 20))
        self.icon_cat = load_icon("app/icons/categorized.png", (20, 20))
        self.icon_cat_active = load_icon("app/icons/categorized_active.png", (20, 20))
        self.icon_recent = load_icon("app/icons/recent.png", (20, 20))
        self.icon_recent_active = load_icon("app/icons/recent_active.png", (20, 20))
        self.icon_fav = load_icon("app/icons/favorites.png", (20, 20))
        self.icon_fav_active = load_icon("app/icons/favorites_active.png", (20, 20))
        self.icon_reset_all = load_icon("app/icons/reset_all.png", (20, 20))
        self.icon_open = load_icon("app/icons/open_folder.png", (20, 20))
        self.icon_refresh = load_icon("app/icons/refresh.png", (20, 20))
        self.icon_save = load_icon("app/icons/save.png", (20, 20))
        self.icon_delete = load_icon("app/icons/delete.png", (20, 20))

        # Right: tall vertical bar with buttons in it
        button_bar = ctk.CTkFrame(
            master=list_container,
            fg_color="#333333",
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            width=40
        )
        button_bar.pack(side=RIGHT, fill='y', padx=(16, 0), pady=(0, 0))
        button_bar.pack_propagate(False)

        # Top group for view buttons
        top_btns = ctk.CTkFrame(button_bar, fg_color="transparent")
        top_btns.pack(side="top", pady=(12, 0))

        # Bottom group for action buttons
        bottom_btns = ctk.CTkFrame(button_bar, fg_color="transparent")
        bottom_btns.pack(side="bottom", pady=(0, 12))

        def make_view_btn(parent, image_default, image_active, mode):
            btn = ctk.CTkButton(
                master=parent,
                image=image_default,
                text="",
                width=38,
                height=40,
                fg_color="#333333",
                hover_color="#444444",
                corner_radius=6,
                command=lambda: self.switch_view(mode)
            )
            btn.image_default = image_default
            btn.image_active = image_active
            btn.pack(pady=0)
            return btn

        def make_icon_btn(parent, image, command):
            btn = ctk.CTkButton(
                master=parent,
                image=image,
                text="",
                width=38,
                height=40,
                fg_color="#333333",
                hover_color="#444444",
                corner_radius=6,
                command=command
            )
            btn.pack(pady=0)
            return btn

        # View buttons (top aligned)
        self.all_btn = make_view_btn(top_btns, self.icon_all, self.icon_all_active, "all")
        ToolTip(self.all_btn, text="View all mods")
        self.cat_btn = make_view_btn(top_btns, self.icon_cat, self.icon_cat_active, "categorized")
        ToolTip(self.cat_btn, text="View categorized mods")
        self.rec_btn = make_view_btn(top_btns, self.icon_recent, self.icon_recent_active, "recent")
        ToolTip(self.rec_btn, text="View recently played mods")
        self.fav_btn = make_view_btn(top_btns, self.icon_fav, self.icon_fav_active, "favorites")
        ToolTip(self.fav_btn, text="View favorited mods")

        # Action buttons (bottom aligned)
        self.open_btn = make_icon_btn(bottom_btns, self.icon_open, self.open_mods_folder)
        ToolTip(self.open_btn, text="Open mods folder")
        self.refresh_btn = make_icon_btn(bottom_btns, self.icon_refresh, self.refresh_mod_list)
        ToolTip(self.refresh_btn, text="Refresh mod list")
        self.reset_all_btn = make_icon_btn(bottom_btns, self.icon_reset_all, self.reset_everything)
        ToolTip(self.reset_all_btn, text="Clear mod selection and unload preset")

        # View button map for updating highlights
        self.view_buttons = {
            "all": self.all_btn,
            "categorized": self.cat_btn,
            "recent": self.rec_btn,
            "favorites": self.fav_btn
        }
        
        ### presets
        preset_frame = ctk.CTkFrame(self.master, fg_color="transparent")
        preset_frame.pack(fill="x", padx=32, pady=(24, 0))

        # Left side: label + current preset name
        preset_info = ctk.CTkFrame(preset_frame, fg_color="transparent")
        preset_info.pack(side="left", fill="both", expand=True)

        preset_label = ctk.CTkLabel(
            master=preset_info,
            text="Save, delete or load a preset",
            text_color="#ffffff",
            font=("Segoe UI", 16, "bold"),
            anchor="w"
        )
        preset_label.pack(fill="x")

        self.current_preset_var = ctk.StringVar(value="No preset is currently loaded...")

        preset_name_display = ctk.CTkLabel(
            master=preset_info,
            textvariable=self.current_preset_var,
            text_color="#888888",
            font=("Segoe UI", 12),
            anchor="w"
        )
        preset_name_display.pack(fill="x")

        # Right side: action buttons
        preset_buttons = ctk.CTkFrame(preset_frame, fg_color="transparent")
        preset_buttons.pack(side="right")

        # Save preset Button (icon)
        save_preset_btn = ctk.CTkButton(
            master=preset_buttons,
            image=self.icon_save,
            text="",
            width=40,
            height=40,
            fg_color="#333333",
            hover_color="#444444",
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            command=self.save_current_preset
        )
        save_preset_btn.pack(side="left", padx=(0, 8))
        ToolTip(save_preset_btn, text="Save currently selected mods as a preset")

        # Delete preset Button (icon)
        delete_preset_btn = ctk.CTkButton(
            master=preset_buttons,
            image=self.icon_delete,
            text="",
            width=40,
            height=40,
            fg_color="#333333",
            hover_color="#444444",
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            command=self.delete_preset
        )
        delete_preset_btn.pack(side="left", padx=(0, 8))
        ToolTip(delete_preset_btn, text="Delete currently loaded preset")

        # Load preset Button (text)
        browse_presets_btn = ctk.CTkButton(
            master=preset_buttons,
            text="Load preset",
            width=144,
            height=40,
            fg_color="#333333",
            hover_color="#444444",
            text_color="#ffffff",
            font=("Segoe UI", 14, "bold"),
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            command=self.browse_presets
        )
        browse_presets_btn.pack(side="left")
        
       
        
        ### Footer
        footer_frame = ctk.CTkFrame(self.master, fg_color="transparent")
        footer_frame.pack(side="bottom", fill="x", padx=32, pady=(24, 0))
        
        # Thin top border line
        footer_line = tk.Canvas(
            master=footer_frame,
            height=1,
            bg="#888888",
            highlightthickness=0,
            bd=0,
            relief="flat"
        )
        footer_line.pack(fill="x", pady=(0, 24))

        # Launch Game button
        # Container for launch button / progress bar (preserves position)
        self.launch_container = ctk.CTkFrame(footer_frame, fg_color="transparent")
        self.launch_container.pack(fill="x", pady=(0, 12))

        # Launch Game button
        self.launch_btn = ctk.CTkButton(
            master=self.launch_container,
            text="Launch F1 25",
            command=self.start_launch_process,
            fg_color="#5345ff",
            hover_color="#675fff",
            text_color="#ffffff",
            font=("Segoe UI", 14, "bold"),
            border_color="#888888",
            border_width=1,
            corner_radius=6,
            height=54,
        )
        self.launch_btn.pack(fill="x")

        # Attach the rich ToolTip to the launch button
        initial_lines = self._get_launch_tooltip_lines()
        self.launch_tooltip = ToolTip(
            self.launch_btn,
            rich_lines=initial_lines,
            bg="#333333",
            padx=8,
            pady=2
        )
        # ──────────────────────────────────────────

        self.refresh_launch_button()

        # Loading frame (initially hidden)
        self.loading_frame = ctk.CTkFrame(self.launch_container, fg_color="transparent")
        self.loading_frame.pack(fill="x")
        self.loading_frame.pack_forget()

        self.progress_bar = ctk.CTkProgressBar(
            self.loading_frame,
            height=18,
            progress_color="#5345ff",  # Cyan-style color
            fg_color="#333333",        # Background of the bar
            border_color="#888888",    # Optional border
            border_width=1,
            corner_radius=6
        )
        self.progress_bar.pack(fill="x", pady=(0, 6))
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(self.loading_frame, text="", text_color="#888888", font=("Segoe UI", 12))
        self.status_label.pack(fill="x")

        # Footer info text (version + credits)
        footer_label = ctk.CTkLabel(
            master=footer_frame,
            text="SERPs Launcher for F1 25 V1.01 by RK16 and MildtDesign",
            text_color="#666666",
            font=("Segoe UI", 10),
            anchor="center",
            justify="center"
        )
        footer_label.pack(pady=(16, 0))
        
       
        
        self.master.drop_target_register(DND_FILES)
        self.master.dnd_bind('<<Drop>>', self.on_drop_files)
        
        def _on_mousewheel(event):
            if self.is_scroll_needed():
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self.list_frame.bind_all("<MouseWheel>", _on_mousewheel)




    def browse_presets(self):
        selected_path = filedialog.askopenfilename(
            initialdir="presets",
            title="Select a preset",
            filetypes=[("SERPs presets", "*.serpspreset")]
        )
        if selected_path:
            self.load_preset_from_file(selected_path)


    def save_current_preset(self):
        # Count selected mods first
        selected_mods = []
        for mod in self.mods:
            name = mod["name"]
            if name in self.mod_checkbuttons and self.mod_checkbuttons[name][0].var.get() == 1:
                selected_mods.append(name)

        if len(selected_mods) < 2:
            messagebox.showwarning("Not enough mods selected", "Please select at least 2 mods to save a preset.")
            return

        # Continue with save-as dialog
        path = filedialog.asksaveasfilename(
            defaultextension=".serpspreset",
            filetypes=[("SERPs presets", "*.serpspreset")],
            initialdir="presets",
            title="Save preset as"
        )
        if not path:
            return

        try:
            with open(path, "w") as f:
                json.dump(selected_mods, f, indent=4)

            self.current_preset_var.set(os.path.splitext(os.path.basename(path))[0])
            messagebox.showinfo("Preset Saved", f"Preset saved as:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save preset:\n{e}")




    def load_preset_from_file(self, path):
        try:
            with open(path, "r") as f:
                selected_mods = set(json.load(f))

                for mod in self.mods:
                    mod_name = mod["name"]
                    btns = self.mod_checkbuttons.get(mod_name, [])
                    if not btns:
                        continue

                    is_selected = mod_name in selected_mods
                    currently_selected = btns[0].var.get() == 1

                    if is_selected != currently_selected:
                        self.toggle_mod(mod)  # ✅ Use `mod`, which has the correct structure


            raw_name = os.path.splitext(os.path.basename(path))[0]
            self.current_preset_var.set(self.strip_archive_extension(raw_name))

        except Exception as e:
            messagebox.showerror("Error", f"Could not load preset:\n{e}")

    def delete_preset(self):
        current_name = self.current_preset_var.get()
        if current_name in ("", "No preset is currently loaded..."):
            messagebox.showinfo("No Preset", "There is no preset currently loaded.")
            return

        path = os.path.join("presets", f"{current_name}.serpspreset")
        if not os.path.exists(path):
            messagebox.showerror("File Not Found", f"Preset file '{current_name}.serpspreset' could not be found.")
            return

        confirm = messagebox.askyesno("Delete Preset", f"Are you sure you want to delete preset '{current_name}'?")
        if confirm:
            try:
                os.remove(path)
                self.current_preset_var.set("No preset is currently loaded...")
                messagebox.showinfo("Deleted", f"Preset '{current_name}' has been deleted.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete preset:\n{e}")



    
    def load_last_view_mode(self):
        if os.path.exists(LAST_VIEW_FILE):
            with open(LAST_VIEW_FILE, "r") as f:
                mode = f.read().strip()
                if mode in ("all", "categorized", "recent", "favorites"):
                    return mode
        return "all"  # default fallback

    def apply_hover_effects(self, widget, hover_color="#444444", leave_color="#333333"):
        def on_enter(e):
            if getattr(widget, "is_active", False):
                return
            widget.config(bg=hover_color)

        def on_leave(e):
            if getattr(widget, "is_active", False):
                return
            widget.config(bg=leave_color)

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def start_drag(self, event):
        self.x = event.x
        self.y = event.y

    def on_drag(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        self.master.geometry(f'+{self.master.winfo_x() + deltax}+{self.master.winfo_y() + deltay}')

    def select_game_directory(self):
        selected_dir = filedialog.askdirectory()
        if selected_dir:
            if self.is_valid_game_directory(selected_dir):
                self.game_path = selected_dir
                self.path_var.set(f"{self.game_path}")
                self.save_game_directory(self.game_path)
                messagebox.showinfo("Selected", f"Game directory set to:\n{self.game_path}")
                self.refresh_mod_highlights()
                self.refresh_launch_button()
            else:
                messagebox.showerror("Invalid F1 25 game directory", "The selected folder does not contain F1_25.exe.\nPlease select a valid F1 25 game directory.")
                self.refresh_launch_button()


    def is_valid_game_directory(self, path):
        if not path:
            return False
        exe_path = os.path.join(path, "F1_25.exe")
        return os.path.exists(exe_path)


    def save_game_directory(self, directory):
        with open(GAME_DIRECTORY_FILE, 'w') as f:
            f.write(directory)

    def load_game_directory(self):
        if os.path.exists(GAME_DIRECTORY_FILE):
            with open(GAME_DIRECTORY_FILE, 'r') as f:
                return f.read().strip()
        return ""

    def load_mods(self):
        os.makedirs(MODS_FOLDER, exist_ok=True)
        for widget in self.pinned_base_mod_frame.winfo_children():
            widget.destroy()
        needs_base = False

        def is_base_archive(path: str) -> bool:
            # True if this archive contains SERPs Base Files for F1 25 - Read Me.pdf
            return self._archive_contains(path, "SERPs Base Files for F1 25 - Read Me.pdf")

        self.mods.clear()
        self.mod_file_map.clear()

        for widget in self.list_frame.winfo_children():
            widget.destroy()

        self.mod_checkbuttons.clear()
        
        # === Render pinned base mod above scrollable list ===
        pinned_base_zip = None
        for root, _, files in os.walk(MODS_FOLDER):
            for fname in files:
                if not fname.lower().endswith((".zip", ".rar", ".7z")):
                    continue
                candidate = os.path.join(root, fname)
                if is_base_archive(candidate):
                    pinned_base_zip = candidate
                    break
            if pinned_base_zip:
                break

        # If we found a Base-Files archive, render its entries first
        if pinned_base_zip:
            mod_infos = self.read_supported_mod_archives(pinned_base_zip)
            for mod_info in mod_infos:
                if mod_info.get("is_parent"):
                    continue
                self.mods.append(mod_info)
                for f in mod_info["files"]:
                    self.mod_file_map.setdefault(f, []).append(mod_info["name"])
                self.render_mod_row(mod_info, parent=self.pinned_base_mod_frame)
        else:
            # No Base-Files archive (top‐level or nested) was found
            pinned_base_zip = None


        raw_search = self.search_var.get().strip().lower() if hasattr(self, 'search_var') else ""
        search_text = "" if raw_search == "search mods..." else raw_search

        def archive_matches_search(zip_path, mod_infos):
            if not search_text:
                return True
            name = os.path.basename(zip_path).lower()
            if search_text in name:
                return True
            return any(search_text in mi["name"].lower() for mi in mod_infos)

        archive_extensions = (".zip", ".rar", ".7z")

        def should_show(mod):
            name = mod["name"]
            if self.current_view_mode == "all":
                return True
            elif self.current_view_mode == "favorites":
                # show real favorites…
                if name in self.favorites:
                    return True
                # …or our pinned SERPs Base Files for F1 25 - Read Me.pdf mod
                return self._archive_contains(mod["zip_path"], "SERPs Base Files for F1 25 - Read Me.pdf")
            return True  # default to True for others

        def process_archive(zip_path):
            try:
                return self.read_supported_mod_archives(zip_path)
            except Exception as e:
                print(f"Error reading archive {zip_path}: {e}")
                return []

        # === RECENT MODE ===
        if self.current_view_mode == "recent":
            for session in self.recent_mods:
                if not session["mods"]:
                    continue

                # collect exactly those variant entries that were played this session
                mods_by_parent: dict[str, list] = {}
                for mod_name in session["mods"]:
                    parent = mod_name.split("__", 1)[0]
                    zip_path = self.find_mod_path_by_name(parent)
                    if not zip_path:
                        ctk.CTkLabel(
                            self.list_frame,
                            text=f"⚠ Missing mod: {mod_name}",
                            fg_color="#1e1e1e",
                            text_color="#ffcc00",
                            anchor="w",
                            font=("Segoe UI", 10, "bold")
                        ).pack(fill="x", pady=(2,0), padx=(4,0))
                        continue
                    for info in self.read_supported_mod_archives(zip_path):
                        if info.get("is_parent"):
                            continue
                        if info["name"] == mod_name:
                            mods_by_parent.setdefault(parent, []).append(info)

                if not mods_by_parent:
                    continue

                # Session timestamp header
                ctk.CTkLabel(
                    self.list_frame,
                    text=self.format_timestamp(session["timestamp"]),
                    fg_color="#1e1e1e",
                    text_color="#888888",
                    anchor="w",
                    font=("Segoe UI", 11)
                ).pack(fill="x", pady=(8,0))

                # For each parent, either render a lone row or a variant group
                for parent, variants in mods_by_parent.items():
                    if len(variants) == 1:
                        # single‐variant mod
                        mod_info = variants[0]
                        self.mods.append(mod_info)
                        for f in mod_info["files"]:
                            self.mod_file_map.setdefault(f, []).append(mod_info["name"])
                        self.render_mod_row(mod_info)
                    else:
                        # multi‐variant group—use your existing header+rows
                        self.render_variant_group_header(parent)
                        if self.expanded_variant_groups.get(parent, True):
                            for mod_info in variants:
                                self.mods.append(mod_info)
                                for f in mod_info["files"]:
                                    self.mod_file_map.setdefault(f, []).append(mod_info["name"])
                                self.render_variant_row(mod_info)
                        # clear out the container so the next group starts fresh
                        self._current_variant_group_container = None

            return



        # === VIEW MODES ===
        self.expanded_categories = getattr(self, 'expanded_categories', {})

        if self.current_view_mode == "categorized":
        
            # UNCATEGORIZED
            uncategorized = [
                f for f in os.listdir(MODS_FOLDER)
                if os.path.isfile(os.path.join(MODS_FOLDER, f)) and f.lower().endswith(archive_extensions)
            ]
            
            if uncategorized:
                self.render_category_header("Uncategorized Mods")

                if self.expanded_categories.get("Uncategorized Mods", True):
                    for filename in sorted(uncategorized, key=str.lower):
                        zip_path   = os.path.join(MODS_FOLDER, filename)
                        # skip if this is the pinned Base-Files archive
                        if pinned_base_zip and zip_path == pinned_base_zip:
                            continue
                        mod_infos  = process_archive(zip_path)
                        # skip if nothing inside or no match on archive *or* any variant
                        if not mod_infos or not archive_matches_search(zip_path, mod_infos):
                            continue

                        parent_group = None
                        for mod_info in mod_infos:
                            if "is_parent" in mod_info:
                                parent_group = mod_info["name"]
                                self.render_variant_group_header(parent_group)
                                continue

                            # filter variants too (only show matching names)
                            if search_text and search_text not in mod_info["name"].lower():
                                continue
                            if not self.expanded_variant_groups.get(parent_group, True):
                                continue  # group is collapsed, skip rendering

                            if should_show(mod_info):
                                if mod_info.get("is_parent"):
                                    continue  # Don't add group header to self.mods
                                self.mods.append(mod_info)
                                for file in mod_info["files"]:
                                    self.mod_file_map.setdefault(file, []).append(mod_info["name"])
                                if self._current_variant_group_container:
                                    self.render_variant_row(mod_info, parent=self._current_variant_group_container)
                                else:
                                    self.render_mod_row(mod_info)
                        self._current_variant_group_container = None

            # CATEGORIZED
            for category in sorted(os.listdir(MODS_FOLDER), key=str.lower):
                category_path = os.path.join(MODS_FOLDER, category)
                if not os.path.isdir(category_path):
                    continue

                archive_files = [
                    f for f in os.listdir(category_path)
                    if os.path.isfile(os.path.join(category_path, f)) and f.lower().endswith(archive_extensions)
                ]
                
                if not archive_files:
                    continue

                self.render_category_header(category)

                if self.expanded_categories.get(category, True):
                    for filename in sorted(archive_files, key=str.lower):
                        zip_path   = os.path.join(category_path, filename)
                        if pinned_base_zip and zip_path == pinned_base_zip:
                            continue
                        mod_infos  = process_archive(zip_path)
                        # skip non-matching archives (but always keep the pinned Base‐Files)
                        if not mod_infos \
                           or (search_text and not archive_matches_search(zip_path, mod_infos)
                               and not self._archive_contains(zip_path, "SERPs Base Files for F1 25 - Read Me.pdf")):
                            continue

                        parent_group = None
                        for mod_info in mod_infos:
                            if "is_parent" in mod_info:
                                parent_group = mod_info["name"]
                                self.render_variant_group_header(parent_group)
                                continue

                            # filter variants by name too (unless it’s the pinned Base‐Files mod)
                            if search_text \
                               and search_text not in mod_info["name"].lower() \
                               and not self._archive_contains(mod_info["zip_path"], "SERPs Base Files for F1 25 - Read Me.pdf"):
                                continue
                            if not self.expanded_variant_groups.get(parent_group, True):
                                continue  # group is collapsed, skip rendering

                            if should_show(mod_info):
                                if mod_info.get("is_parent"):
                                    continue  # Don't add group header to self.mods
                                self.mods.append(mod_info)
                                for file in mod_info["files"]:
                                    self.mod_file_map.setdefault(file, []).append(mod_info["name"])
                                if self._current_variant_group_container:
                                    self.render_variant_row(mod_info, parent=self._current_variant_group_container)
                                else:
                                    self.render_mod_row(mod_info)
                                    
                        self._current_variant_group_container = None

        else:
            # FLAT VIEW FOR "all" or "favorites"
            all_archives = []
            needs_base = False


            for f in os.listdir(MODS_FOLDER):
                path = os.path.join(MODS_FOLDER, f)
                if os.path.isfile(path) and f.lower().endswith(archive_extensions):
                    all_archives.append(path)
                elif os.path.isdir(path):
                    for subf in os.listdir(path):
                        if subf.lower().endswith(archive_extensions):
                            all_archives.append(os.path.join(path, subf))

            for zip_path in sorted(
                all_archives,
                key=lambda p: (
                    # put SERPs Base Files for F1 25 - Read Me.pdf archive first
                    not self._archive_contains(p, "SERPs Base Files for F1 25 - Read Me.pdf"),
                    os.path.basename(p).lower()
                )
            ):
                if pinned_base_zip and zip_path == pinned_base_zip:
                    continue
                filename = os.path.basename(zip_path)
                mod_infos = process_archive(zip_path)
                if not mod_infos or not archive_matches_search(zip_path, mod_infos):
                    continue

                parent_group = None
                for mod_info in mod_infos:
                    if "is_parent" in mod_info:
                        parent_group = mod_info["name"]

                        # 🧠 Check if any variant in this group is favorited
                        if self.current_view_mode == "favorites":
                            has_favorite_variant = any(
                                # true if user actually favorited this variant…
                                variant["name"] in self.favorites
                                # …or if this archive contains SERPs Base Files for F1 25 - Read Me.pdf (our pinned mod)
                                or self._archive_contains(variant["zip_path"], "SERPs Base Files for F1 25 - Read Me.pdf")
                                for variant in mod_infos
                                if "is_parent" not in variant
                            )
                            if not has_favorite_variant:
                                parent_group = None  # Skip showing this group header
                                continue

                        self.render_variant_group_header(parent_group)
                        continue


                    if search_text and search_text not in mod_info["name"].lower():
                        continue
                    if not self.expanded_variant_groups.get(parent_group, True):
                        continue  # group is collapsed, skip rendering

                    files = { os.path.basename(f).lower() for f in mod_info["files"] }
                    if bool(self.ERP_DEPENDENCIES & files) and "words.erp" not in files:
                        needs_base = True

                    if should_show(mod_info):
                        if mod_info.get("is_parent"):
                            continue  # Don't add group header to self.mods
                        self.mods.append(mod_info)
                        for file in mod_info["files"]:
                            self.mod_file_map.setdefault(file, []).append(mod_info["name"])
                        if self._current_variant_group_container:
                            self.render_variant_row(mod_info, parent=self._current_variant_group_container)
                        else:
                            self.render_mod_row(mod_info)
                self._current_variant_group_container = None

        # if our search pulled in a mod that needs Base Files, 
        # make sure Base Files shows up too
        if search_text and needs_base:
            base_archive = next(
                (p for p in all_archives 
                 if self._archive_contains(
                        p,
                        "SERPs Base Files for F1 25 - Read Me.pdf"
                    )
                ),
                None
            )
            if base_archive:
                for base_info in process_archive(base_archive):
                    if base_info.get("is_parent"):
                        continue
                    if base_info["name"] not in [m["name"] for m in self.mods]:
                        # prepend it so it shows at the top
                        self.mods.insert(0, base_info)
                        for f in base_info["files"]:
                            self.mod_file_map.setdefault(f, []).append(base_info["name"])
                        self.render_mod_row(base_info)

        if self.pinned_base_mod_frame.winfo_children():
            self.pinned_base_mod_frame.pack(fill="x", padx=(0, 22), pady=4, before=self.scroll_frame)
        else:
            self.pinned_base_mod_frame.pack_forget()

        self.refresh_mod_highlights()
        self.canvas.update_idletasks()
        self.canvas.event_generate("<Configure>")


    def toggle_category(self, category):
        current_state = self.expanded_categories.get(category, True)
        self.expanded_categories[category] = not current_state
        self.load_mods()

    def refresh_mod_list(self):
        self.load_mods()

    def refresh_mod_highlights(self):
        installed = self.load_install_record()
        for mod in self.mods:
            if mod["name"] in installed:
                for btn in self.mod_checkbuttons[mod["name"]]:
                    btn.var.set(1)


    def toggle_mod(self, selected_mod):
        mod_name = selected_mod["name"]
        btns = self.mod_checkbuttons.get(mod_name, [])
        if not btns:
            return

        # Check current value from the first var
        var = btns[0].var
        new_state = 1 if var.get() == 0 else 0

        for btn in btns:
            btn.var.set(new_state)
            btn.config(image=btn.image_on if new_state else btn.image_off)

        if new_state:
            # Deactivate conflicting mods
            conflicting_mods = self.check_for_conflicts(selected_mod)
            for conflicting_mod in conflicting_mods:
                for other_btn in self.mod_checkbuttons.get(conflicting_mod, []):
                    other_btn.var.set(0)
                    other_btn.config(image=other_btn.image_off)
                self.selected_mods.discard(conflicting_mod)
            self.selected_mods.add(mod_name)
            

            # --- AUTOMATICALLY SELECT BASE FILES IF NEEDED ----
            # same logic as the badge: does this mod require words.erp?
            file_basenames = {
                os.path.basename(f).lower()
                for f in selected_mod["files"]
            }
            needs_base = bool(self.ERP_DEPENDENCIES & file_basenames) \
                         and "words.erp" not in file_basenames

            if needs_base:
                # try to find & auto-select any mod whose archive contains "SERPs Base Files for F1 25 - Read Me.pdf"
                found = False
                for root, _, files in os.walk(MODS_FOLDER):
                    for fname in files:
                        if not fname.lower().endswith((".zip", ".rar", ".7z")):
                            continue
                        archive_path = os.path.join(root, fname)
                        if not self._archive_contains(archive_path, "SERPs Base Files for F1 25 - Read Me.pdf"):
                            continue

                        # we found the Base Files archive; now grab its mod-info
                        base_mods = self.read_supported_mod_archives(archive_path)
                        # pick the first non-parent entry (or fallback to the parent)
                        base_info = next((m for m in base_mods if not m.get("is_parent")), base_mods[0])

                        # auto-toggle it on (recursive toggle_mod on Base Files won’t re-enter this block)
                        if base_info["name"] not in self.selected_mods:
                            self.toggle_mod(base_info)
                        found = True
                        break
                    if found:
                        break

                # if we still didn’t find it, offer to download
                if not found:
                    download = messagebox.askyesno(
                        "Download SERPs Base Files",
                        "This mod requires the SERPs Base Files to work properly.\nWould you like to download it now?"
                    )
                    if download:
                        subprocess.Popen(
                            ["start", "https://www.overtake.gg/downloads/serps-base-files-for-f1-25-simplified-erps-serps-use-to-play-f1-25-with-serps-compatible-mods.77448/"],
                            shell=True
                        )
                        
                    # disable the mod since Base Files is not installed
                    btns = self.mod_checkbuttons[selected_mod["name"]]
                    for btn in btns:
                        btn.var.set(0)
                        btn.config(image=btn.image_off)
                    self.selected_mods.discard(selected_mod["name"])
                    return
            
        else:
            # If they just turned off the Base Files mod, also turn off
            # any other selected mods that need those base files.
            # (We detect Base Files by looking for the special PDF inside its archive.)
            if self._archive_contains(
                  selected_mod["zip_path"],
                  "SERPs Base Files for F1 25 - Read Me.pdf"
            ):
                # collect names first to avoid mutating the set while iterating
                to_deselect = []
                for other in self.selected_mods:
                    # skip the base mod itself
                    if other == mod_name:
                        continue
                    # look up its mod_info
                    info = next((m for m in self.mods if m["name"] == other), None)
                    if not info:
                        continue
                    files = { os.path.basename(f).lower() for f in info["files"] }
                    needs_base = bool(self.ERP_DEPENDENCIES & files) and "words.erp" not in files
                    if needs_base:
                        to_deselect.append(info)
                # now toggle each one off
                for info in to_deselect:
                    self.toggle_mod(info)

            # finally remove this mod from the set
            self.selected_mods.discard(mod_name)

        self.launch_tooltip.rich_lines = self._get_launch_tooltip_lines()



    def _get_launch_tooltip_lines(self):
        seen = set()
        selected = []
        for mod in self.mods:
            name = mod["name"]
            if name in self.selected_mods and name not in seen:
                selected.append(name)
                seen.add(name)

        mod_names = []
        for name in selected:
            display_name = self.strip_archive_extension(name)
            if "__" in display_name:
                _, raw = display_name.split("__", 1)
            else:
                raw = display_name

            raw = raw.lstrip("_")
            segments = raw.split("/")
            if segments and segments[-1] in ("F1 25", "Mod"):
                segments.pop()

            display_name = " ▶ ".join(segments)
            mod_names.append(display_name)

        # Build the rich_lines list
        if not mod_names:
            title_str = "F1 25 will launch without any mods..."
        else:
            title_str = "F1 25 will launch with these mods:"

        rich_lines = [
            (title_str, ("Segoe UI", 10, "bold"), "#ffffff"),
        ]
        
        if mod_names:
            rich_lines.append((" ", ("Segoe UI", 4, "bold"), "#ffcc00"))
        
        for mod_display in mod_names:
            bullet_line = f"• {mod_display}"
            rich_lines.append((bullet_line, ("Segoe UI", 9), "#ffffff"))

        if mod_names:
            warning_text = "⚠ Please note! Don't play multiplayer when using mods!"
            rich_lines.append((" ", ("Segoe UI", 4, "bold"), "#ffcc00"))
            rich_lines.append((warning_text, ("Segoe UI", 9, "bold"), "#ffcc00"))
        return rich_lines



    def check_for_conflicts(self, selected_mod):
        conflicts = set()
        for file in selected_mod["files"]:
            if file in self.mod_file_map:
                for mod in self.mod_file_map[file]:
                    if mod != selected_mod["name"] and mod in self.selected_mods:
                        conflicts.add(mod)
        return conflicts

    def open_mods_folder(self):
        os.makedirs(MODS_FOLDER, exist_ok=True)
        subprocess.Popen(f'explorer "{os.path.abspath(MODS_FOLDER)}"')



    def launch_f1_game(self):
        exe = os.path.join(self.game_path, "F1_25.exe")
        if not os.path.exists(exe):
            messagebox.showerror("Error", "Could not find the game executable: F1_25.exe")
            return
        subprocess.Popen([exe])

    def load_install_record(self):
        if os.path.exists(INSTALLED_MODS_FILE):
            with open(INSTALLED_MODS_FILE, 'r') as f:
                return json.load(f)
        return {}

    def write_install_record(self, data):
        with open(INSTALLED_MODS_FILE, 'w') as f:
            json.dump(data, f, indent=4)


    def on_drop_files(self, event):
        dropped_files = self.master.tk.splitlist(event.data)
        for file_path in dropped_files:
            if file_path.lower().endswith(".zip"):
                try:
                    dest_path = os.path.join(MODS_FOLDER, os.path.basename(file_path))
                    if not os.path.exists(dest_path):
                        shutil.copy(file_path, dest_path)
                        print(f"Copied: {file_path} to {dest_path}")
                    else:
                        print(f"Skipped (already exists): {file_path}")
                except Exception as e:
                    print(f"Failed to copy {file_path}: {e}")
        self.refresh_mod_list()

    def is_scroll_needed(self):
        self.canvas.update_idletasks()
        content_height = self.list_frame.winfo_height()
        canvas_height = self.canvas.winfo_height()
        return content_height > canvas_height
       
    def load_favorites(self):
        if os.path.exists(FAVORITES_FILE):
            with open(FAVORITES_FILE, 'r') as f:
                return set(json.load(f))
        return set()

    def save_favorites(self):
        with open(FAVORITES_FILE, 'w') as f:
            json.dump(list(self.favorites), f)

    def load_recent_mods(self):
        if os.path.exists(RECENT_FILE):
            with open(RECENT_FILE, 'r') as f:
                return json.load(f)
        return []

    def save_recent_mods(self):
        with open(RECENT_FILE, 'w') as f:
            json.dump(self.recent_mods, f, indent=4)

           
    def switch_view(self, mode):
        self.current_view_mode = mode
        self.save_last_view_mode()
        self.load_mods()
        self.update_view_button_states()
        
        if self.current_view_mode == "recent":
            self.search_container.pack_forget()
            self.pinned_base_mod_frame.pack_forget()
        else:
            self.search_container.pack(fill="x", padx=(0, 22), pady=(0, 8), before=self.scroll_frame)
            if self.pinned_base_mod_frame.winfo_children():
                self.pinned_base_mod_frame.pack(fill="x", padx=(0, 22), pady=4, before=self.scroll_frame)
            else:
                self.pinned_base_mod_frame.pack_forget()

    def save_last_view_mode(self):
        with open(LAST_VIEW_FILE, "w") as f:
            f.write(self.current_view_mode)

    def toggle_favorite(self, mod_name):
        if mod_name in self.favorites:
            self.favorites.remove(mod_name)
        else:
            self.favorites.add(mod_name)

        self.save_favorites()

        # Refresh just the star icon if it exists
        if mod_name in self.mod_checkbuttons:
            for btn in self.mod_checkbuttons.get(mod_name, []):
                star_btn = btn.star_btn
                star_btn.config(image=star_btn.image_on if mod_name in self.favorites else star_btn.image_off)



    def update_view_button_states(self):
        for mode, button in self.view_buttons.items():
            is_active = (mode == self.current_view_mode)
            button.configure(fg_color="#333333" if is_active else "#333333", hover_color="#444444" if is_active else "#444444", image=button.image_active if is_active else button.image_default)
            button.is_active = is_active
            


    def update_status(self, message):
        self.status_label.after(0, lambda: self.status_label.configure(text=message))

    def update_progress(self, value):
        self.progress_bar.after(0, lambda: self.progress_bar.set(value))



    def reset_everything(self):
        self.perform_reset()

    def perform_reset(self):
        for btn_list in self.mod_checkbuttons.values():
            for btn in btn_list:
                btn.var.set(0)
                btn.config(image=btn.image_off)
        self.selected_mods.clear()
        self.current_preset_var.set("No preset is currently loaded...")






    def format_timestamp(self, iso_str):
        dt = datetime.fromisoformat(iso_str)
        now = datetime.now()

        date_part = ""
        if dt.date() == now.date():
            date_part = "Today"
        elif dt.date() == (now - timedelta(days=1)).date():
            date_part = "Yesterday"
        else:
            date_part = dt.strftime("%A %d %B %Y")  # eg. Monday 22 April 2025

        time_part = dt.strftime("%I:%M %p").lstrip("0").replace(" 0", " ")  # eg. 7:13 PM
        return f"{date_part}, {time_part}"

    def find_mod_path_by_name(self, mod_name):
        # Step 1: Try exact match (fast path)
        path = os.path.join(MODS_FOLDER, mod_name)
        if os.path.exists(path):
            return path

        for folder in os.listdir(MODS_FOLDER):
            full = os.path.join(MODS_FOLDER, folder, mod_name)
            if os.path.exists(full):
                return full

        # Step 2: Try loose matching
        mod_name_simple = mod_name.lower().replace(" ", "").replace("_", "").replace("-", "").replace("/", "")

        candidates = []
        for root, dirs, files in os.walk(MODS_FOLDER):
            for file in files:
                base_name = os.path.splitext(file)[0]
                base_simple = base_name.lower().replace(" ", "").replace("_", "").replace("-", "").replace("/", "")
                if base_simple == mod_name_simple:
                    return os.path.join(root, file)
                candidates.append((base_simple, os.path.join(root, file)))

        # Step 3: If still not found, try partial matching
        for base_simple, file_path in candidates:
            if mod_name_simple in base_simple:
                print(f"[Loose Match] {mod_name} -> {os.path.basename(file_path)}")
                return file_path

        # Step 4: Give up
        print(f"[Warning] Could not find archive for mod: {mod_name}")
        return None







    def read_supported_mod_archives(self, archive_path):
        mods = []
        lower_path = str(archive_path).lower()

        def process_entries(entries):
            # 1) discover all variant roots by signature
            variant_roots: set[str|None] = set()
            for path in entries:
                parts = path.split("/")
                idx = find_signature_index(parts)
                if idx is not None:
                    root = "/".join(parts[:idx]) or None
                    variant_roots.add(root)

            # 2) for each entry, include every supported file under its root
            variant_map: dict[str|None, list[str]] = {}
            for path in entries:
                if not path.lower().endswith(SUPPORTED_EXTENSIONS):
                    continue
                parts = path.split("/")
                for root in variant_roots:
                    if root is None:
                        # root-level variant: grab everything
                        rel = path
                    else:
                        prefix = root.split("/")
                        if parts[:len(prefix)] != prefix:
                            continue
                        rel = "/".join(parts[len(prefix):])
                    variant_map.setdefault(root, []).append(rel)
                    # stop after the first matching root
                    break

            return variant_map

        try:
            if lower_path.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as archive:
                    variant_map = process_entries(archive.namelist())

            elif lower_path.endswith(".rar"):
                with rarfile.RarFile(archive_path, "r") as archive:
                    variant_map = process_entries([f.filename for f in archive.infolist()])

            elif lower_path.endswith(".7z"):
                with py7zr.SevenZipFile(archive_path, "r") as archive:
                    variant_map = process_entries(archive.getnames())

            else:
                print(f"Unsupported archive type: {archive_path}")
                return []

            # Structure: one mod per variant
            base_name = self.strip_archive_extension(os.path.basename(archive_path))
            if len(variant_map) <= 1:
                # Single variant — fallback to simple structure
                for variant, files in variant_map.items():
                    mods.append({
                        "name": base_name,
                        "zip_path": archive_path,
                        "files": files
                    })
            else:
                # Multi-variant mod
                mods.append({  # Add parent entry
                    "name": base_name,
                    "zip_path": archive_path,
                    "is_parent": True,
                    "variants": []
                })

                for variant, files in variant_map.items():
                    mods.append({
                        "name": f"{base_name}__{variant}",
                        "zip_path": archive_path,
                        "files": files,
                        "variant": variant,
                        "parent": base_name
                    })

        except Exception as e:
            print(f"Error reading archive {archive_path}: {e}")

        return mods

    def strip_archive_extension(self, name):
        for ext in (".zip", ".rar", ".7z"):
            if name.lower().endswith(ext):
                return name[: -len(ext)]
        return name

    def scan_supported_files(self, archive_path, variant_name=None):
        found_files = []
        archive_path = str(archive_path).lower()

        try:
            if archive_path.endswith(".zip"):
                with zipfile.ZipFile(archive_path, 'r') as archive:
                    for f in archive.namelist():
                        if not f.lower().endswith(SUPPORTED_EXTENSIONS):
                            continue
                        parts = f.split("/")
                        if variant_name is not None:
                            # only files under this variant’s root
                            prefix = variant_name.split("/") if isinstance(variant_name, str) else []
                            if parts[:len(prefix)] != prefix:
                                continue
                            rel_path = "/".join(parts[len(prefix):])
                        else:
                            # root‐variant (signature was at index 0): include everything
                            rel_path = "/".join(parts)
                        found_files.append((f, rel_path))

            elif archive_path.endswith(".rar"):
                with rarfile.RarFile(archive_path, 'r') as archive:
                    for f in archive.namelist():
                        if not f.lower().endswith(SUPPORTED_EXTENSIONS):
                            continue
                        parts = f.split("/")
                        if variant_name is not None:
                            # only files under this variant’s root
                            prefix = variant_name.split("/") if isinstance(variant_name, str) else []
                            if parts[:len(prefix)] != prefix:
                                continue
                            rel_path = "/".join(parts[len(prefix):])
                        else:
                            # root‐variant (signature was at index 0): include everything
                            rel_path = "/".join(parts)
                        found_files.append((f, rel_path))

            elif archive_path.endswith(".7z"):
                with py7zr.SevenZipFile(archive_path, 'r') as archive:
                    for f in archive.namelist():
                        if not f.lower().endswith(SUPPORTED_EXTENSIONS):
                            continue
                        parts = f.split("/")
                        if variant_name is not None:
                            # only files under this variant’s root
                            prefix = variant_name.split("/") if isinstance(variant_name, str) else []
                            if parts[:len(prefix)] != prefix:
                                continue
                            rel_path = "/".join(parts[len(prefix):])
                        else:
                            # root‐variant (signature was at index 0): include everything
                            rel_path = "/".join(parts)
                        found_files.append((f, rel_path))

        except Exception as e:
            print(f"Error scanning archive {archive_path}: {e}")

        return found_files  # returns list of tuples: (archive_path, rel_install_path)

    def extract_files(self, archive_path, extract_to, variant_name=None):
        archive_path = str(archive_path).lower()

        try:
            if archive_path.endswith(".zip"):
                with zipfile.ZipFile(archive_path, 'r') as archive:
                    for f in archive.namelist():
                        if not f.lower().endswith(SUPPORTED_EXTENSIONS):
                            continue
                        parts = f.split("/")
                        if variant_name is not None:
                            prefix = variant_name.split("/") if isinstance(variant_name, str) else []
                            if parts[:len(prefix)] != prefix:
                                continue
                            rel_path = "/".join(parts[len(prefix):])
                        else:
                            rel_path = "/".join(parts)

                        target_path = os.path.join(extract_to, rel_path)
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with archive.open(f) as src, open(target_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)


            elif archive_path.endswith(".rar"):
                with rarfile.RarFile(archive_path, 'r') as archive:
                    for f in archive.namelist():
                        if not f.lower().endswith(SUPPORTED_EXTENSIONS):
                            continue
                        parts = f.split("/")
                        if variant_name is not None:
                            prefix = variant_name.split("/") if isinstance(variant_name, str) else []
                            if parts[:len(prefix)] != prefix:
                                continue
                            rel_path = "/".join(parts[len(prefix):])
                        else:
                            rel_path = "/".join(parts)

                        target_path = os.path.join(extract_to, rel_path)
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with archive.open(f) as src, open(target_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)



            elif archive_path.endswith(".7z"):
                with py7zr.SevenZipFile(archive_path, 'r') as archive:
                    # 1) Gather every supported file, filtering by variant_name if set
                    all_names = archive.getnames()
                    wanted = []
                    for name in all_names:
                        if not name.lower().endswith(SUPPORTED_EXTENSIONS):
                            continue
                        parts = name.split("/")
                        if variant_name is not None:
                            prefix = variant_name.split("/")
                            if parts[:len(prefix)] != prefix:
                                continue
                            rel = "/".join(parts[len(prefix):])
                        else:
                            rel = name

                        # Normalize and strip any ".." segments to avoid invalid paths
                        rel_clean = os.path.normpath(rel)
                        while rel_clean.startswith(".." + os.sep) or rel_clean == "..":
                            rel_clean = rel_clean[len(".." + os.sep):]
                        rel_clean = rel_clean.lstrip(os.sep)

                        wanted.append((name, rel_clean))

                    # 2) If we found any, read them out and write to disk
                    if wanted:
                        data = archive.read([n for n, _ in wanted])
                        for name, rel_clean in wanted:
                            buf = data.get(name)
                            if not buf:
                                continue
                            target = os.path.join(extract_to, rel_clean)
                            os.makedirs(os.path.dirname(target), exist_ok=True)
                            with open(target, "wb") as dst:
                                dst.write(buf.read())
                    
        except Exception as e:
            print(f"Error extracting archive {archive_path}: {e}")

    def render_category_header(self, name):
        self.expanded_categories.setdefault(name, True)

        cat_header = ctk.CTkFrame(self.list_frame, fg_color="#1e1e1e")  # dark background frame
        cat_header.pack(fill='x', pady=6)

        expand_icon = "▼" if self.expanded_categories[name] else "▶"

        header_color = "#888888" if name == "Uncategorized Mods" else "#ffffff"
        cat_btn = ctk.CTkButton(
            cat_header,
            text=f"{expand_icon}  {name}",
            font=("Segoe UI", 12, "bold"),
            fg_color="#2e2e2e",          # background
            hover_color="#3a3a3a",        # hover effect
            text_color=header_color,
            corner_radius=6,
            border_width=1,
            border_color="#444444",
            anchor="w",
            command=partial(self.toggle_category, name),
            height=36,  # Optional: makes button taller
            width=458,
        )
        cat_btn.pack(fill="x", padx=0)

    def render_variant_group_header(self, name):
        self.expanded_variant_groups.setdefault(name, True)

        # Outer boxed frame (the card)
        group_card = ctk.CTkFrame(
            self.list_frame,
            fg_color="#1e1e1e",           # Card background
            border_color="#444444",
            border_width=1,
            corner_radius=6
        )
        group_card.pack(fill='x', padx=0, pady=4)

        expand_icon = "▼" if self.expanded_variant_groups[name] else "▶"

        def toggle():
            self.expanded_variant_groups[name] = not self.expanded_variant_groups[name]
            self.load_mods()

        # Header (mod name button only, no divider)
        header_row = ctk.CTkFrame(group_card, fg_color="transparent")
        header_row.pack(fill="x", padx=2, pady=2)

        group_button = ctk.CTkButton(
            header_row,
            text=f"{expand_icon}  {self.strip_archive_extension(name)}",
            font=("Segoe UI", 11, "bold"),
            fg_color="#1e1e1e",
            hover_color="#3a3a3a",
            text_color="#eeeeee",
            corner_radius=6,
            border_width=0,
            anchor="w",
            height=28,
            width=454,
            command=toggle
        )
        group_button.pack(fill="x")
        
        # Store the parent for rendering variant rows
        self._current_variant_group_container = group_card

    def render_mod_row(self, mod_info, parent=None):
        var = IntVar(value=1 if mod_info["name"] in self.selected_mods else 0)

        container = parent if parent else self.list_frame

        row = ctk.CTkFrame(container, fg_color="#1e1e1e")
        row.pack(fill="x", padx=16, pady=4)

        on_icon = PhotoImage(file="app/icons/checkbox_on.png")
        off_icon = PhotoImage(file="app/icons/checkbox_off.png")
        star_on = PhotoImage(file="app/icons/star_on.png")
        star_off = PhotoImage(file="app/icons/star_off.png")

        checkbox_btn = Button(
            row,
            image=on_icon if var.get() else off_icon,
            bg="#1e1e1e", bd=0, relief="flat",
            highlightthickness=0,
            highlightbackground="#1e1e1e",
            activebackground="#1e1e1e",
            command=lambda m=mod_info: self.toggle_mod(m), cursor="hand2"
        )
        checkbox_btn.image_on = on_icon
        checkbox_btn.image_off = off_icon
        checkbox_btn.pack(side=LEFT, padx=(0, 12))
        
        # which ERP files this mod brings in
        files = { os.path.basename(f).lower() for f in mod_info["files"] }
        # does it have any of the .erp dependencies but omit words.erp?
        needs_base = bool(self.ERP_DEPENDENCIES & files) and "words.erp" not in files
        # does the archive itself contain SERPs Base Files for F1 25 - Read Me.pdf?
        is_base_mod = self._archive_contains(mod_info["zip_path"], "SERPs Base Files for F1 25 - Read Me.pdf")

        # pick which badge to show
        if is_base_mod:
            icon = self.base_mod_icon
            tip  = "SERPs Base Files"
        elif needs_base:
            icon = self.base_required_icon
            tip  = "Requires SERPs Base Files"
        else:
            icon = self.base_required_placeholder
            tip  = None

        badge = ctk.CTkLabel(
            row,
            image=icon,
            text="",
            fg_color="transparent"
        )
        badge.pack(side=LEFT, padx=(0,8))

        # add the right tooltip
        if is_base_mod:
            ToolTip(badge, text="SERPs Base Files")
        elif needs_base:
            ToolTip(badge, text="Requires SERPs Base Files")

        filename = mod_info["name"]
        display_name = self.strip_archive_extension(filename)
        # (a) Determine “category” by looking at where zip_path lives under MODS_FOLDER
        relative = os.path.relpath(mod_info["zip_path"], MODS_FOLDER)
        parent_folder = os.path.dirname(relative)
        category = parent_folder if parent_folder else "Uncategorized Mods"

        # (b) Archive extension:
        _, ext = os.path.splitext(mod_info["zip_path"])

        # (c) Size on disk for the archive:
        size_bytes = os.path.getsize(mod_info["zip_path"])
        size_mb = size_bytes / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB"

        # (d) How many supported files it actually contains:
        file_count = len(mod_info["files"])

        # Build a single string with four lines:
        rich_lines = [
            (f"{display_name}", ("Segoe UI", 10, "bold"), "white"),
            (f"{ext}  -  {size_str} ({file_count} Files)", ("Segoe UI", 9), "#909090"),
            (f" ", ("Segoe UI", 4), "black"),
            (f"{category}", ("Segoe UI", 9), "white"),
        ]

        mod_label = Label(
            row,
            text=display_name,
            bg="#1e1e1e",
            fg="white",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            width=41
            
        )
        mod_label.bind("<Button-1>", lambda e, m=mod_info: self.toggle_mod(m))
        mod_label.bind("<Button-3>", lambda e, m=mod_info: self.show_mod_context_menu(e, m))
        mod_label.pack(side=LEFT, fill="x", expand=True, padx=(0, 10))
        ToolTip(mod_label, rich_lines=rich_lines, bg="#333333")


        fav_btn = Button(
            row,
            image=star_on if filename in self.favorites else star_off,
            bg="#1e1e1e", bd=0, relief="flat",
            highlightthickness=0,
            highlightbackground="#1e1e1e",
            activebackground="#1e1e1e",
            command=partial(self.toggle_favorite, filename), cursor="hand2"
        )
        fav_btn.image_on = star_on
        fav_btn.image_off = star_off
        if not is_base_mod:
            fav_btn.pack(side=RIGHT, padx=(12, 0))


        if filename not in self.mod_checkbuttons:
            self.mod_checkbuttons[filename] = []
        self.mod_checkbuttons[filename].append(checkbox_btn)

        checkbox_btn.var = var
        checkbox_btn.star_btn = fav_btn

    def render_variant_row(self, mod_info, parent=None):
        var = IntVar(value=1 if mod_info["name"] in self.selected_mods else 0)

        container = parent \
            or getattr(self, "_current_variant_group_container", None) \
            or self.list_frame

        row = ctk.CTkFrame(container, fg_color="#1e1e1e")
        row.pack(fill="x", padx=16, pady=(0, 8))

        on_icon = PhotoImage(file="app/icons/checkbox_on.png")
        off_icon = PhotoImage(file="app/icons/checkbox_off.png")
        star_on = PhotoImage(file="app/icons/star_on.png")
        star_off = PhotoImage(file="app/icons/star_off.png")

        checkbox_btn = Button(
            row,
            image=on_icon if var.get() else off_icon,
            bg="#1e1e1e", bd=0, relief="flat",
            highlightthickness=0,
            highlightbackground="#1e1e1e",
            activebackground="#1e1e1e",
            command=lambda m=mod_info: self.toggle_mod(m), cursor="hand2"
        )
        checkbox_btn.image_on = on_icon
        checkbox_btn.image_off = off_icon
        checkbox_btn.pack(side=LEFT, padx=(0, 12))
        
        # which ERP files this mod brings in
        files = { os.path.basename(f).lower() for f in mod_info["files"] }
        # does it have any of the .erp dependencies but omit words.erp?
        needs_base = bool(self.ERP_DEPENDENCIES & files) and "words.erp" not in files
        # does the archive itself contain SERPs Base Files for F1 25 - Read Me.pdf?
        is_base_mod = self._archive_contains(mod_info["zip_path"], "SERPs Base Files for F1 25 - Read Me.pdf")

        # pick which badge to show
        if is_base_mod:
            icon = self.base_mod_icon
            tip  = "SERPs Base Files"
        elif needs_base:
            icon = self.base_required_icon
            tip  = "Requires SERPs Base Files"
        else:
            icon = self.base_required_placeholder
            tip  = None

        badge = ctk.CTkLabel(
            row,
            image=icon,
            text="",
            fg_color="transparent"
        )
        badge.pack(side=LEFT, padx=(0,8))

        # add the right tooltip
        if is_base_mod:
            ToolTip(badge, text="SERPs Base Files")
        elif needs_base:
            ToolTip(badge, text="Requires SERPs Base Files")

        filename = mod_info["name"]
        display_name = self.strip_archive_extension(filename)

        # 🧹 Clean up the raw variant path:
        # Strip off the base-name prefix (everything before the first "__")
        if "__" in filename:
            # filename == "<modbase>__<variant_path>"
            _, raw_variant = filename.split("__", 1)
        else:
            raw_variant = filename

        # Remove any leading underscores (just in case)
        raw_variant = raw_variant.lstrip("_")

        # Split on "/" so we can drop a trailing "F1 25" or "Mod"
        segments = raw_variant.split("/")
        if segments and segments[-1] in ("F1 25", "Mod"):
            segments.pop()

        # Finally, join with arrows for display
        display_name = " ▶ ".join(segments)
        
        relative = os.path.relpath(mod_info["zip_path"], MODS_FOLDER)
        parent_folder = os.path.dirname(relative)
        category = parent_folder if parent_folder else "Uncategorized Mods"

        _, ext = os.path.splitext(mod_info["zip_path"])

        size_bytes = os.path.getsize(mod_info["zip_path"])
        size_mb = size_bytes / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB"

        file_count = len(mod_info["files"])

        rich_lines = [
            (f"{display_name}", ("Segoe UI", 10, "bold"), "white"),
            (f"{ext}  -  {size_str} ({file_count} Files)", ("Segoe UI", 9), "#909090"),
            (f" ", ("Segoe UI", 4), "black"),
            (f"{category}", ("Segoe UI", 9), "white"),
        ]

        mod_label = Label(
            row,
            text=display_name,
            bg="#1e1e1e",
            fg="white",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            width=41
        )
        mod_label.bind("<Button-1>", lambda e, m=mod_info: self.toggle_mod(m))
        mod_label.bind("<Button-3>", lambda e, m=mod_info: self.show_mod_context_menu(e, m))
        mod_label.pack(side=LEFT, fill="x", expand=True, padx=(0, 10))
        ToolTip(mod_label, rich_lines=rich_lines, bg="#333333")


        fav_btn = Button(
            row,
            image=star_on if filename in self.favorites else star_off,
            bg="#1e1e1e", bd=0, relief="flat",
            highlightthickness=0,
            highlightbackground="#1e1e1e",
            activebackground="#1e1e1e",
            command=partial(self.toggle_favorite, filename), cursor="hand2"
        )
        fav_btn.image_on = star_on
        fav_btn.image_off = star_off
        if not is_base_mod:
            fav_btn.pack(side=RIGHT, padx=(12, 0))

        if filename not in self.mod_checkbuttons:
            self.mod_checkbuttons[filename] = []
        self.mod_checkbuttons[filename].append(checkbox_btn)

        checkbox_btn.var = var
        checkbox_btn.star_btn = fav_btn

    def start_launch_process(self):
        # Hide button, show progress
        self.launch_btn.pack_forget()
        self.quit_btn.configure(state="disabled", fg_color="#8079e0", hover_color="#8079e0")
        self.quit_tooltip.text = "SERPs Launcher can't quit when F1 25 is running..."
        self.loading_frame.pack(fill="x")
        self.progress_bar.set(0)
        self.status_label.configure(text="Starting...")

        thread = threading.Thread(target=self.launch_game_with_progress)
        thread.start()

    def launch_game_with_progress(self):   
        self.update_status("Locating F1 25 game directory...")
        time.sleep(0.4)
        
        seen = set()
        mods_to_install = []
        for mod in self.mods:
            if mod["name"] in self.selected_mods and mod["name"] not in seen:
                mods_to_install.append(mod)
                seen.add(mod["name"])


        if not mods_to_install:
            self.update_status("No mods selected. Launching F1 25 without mods...")
            with open(INSTALLED_MODS_FILE, 'w') as f:
                json.dump({}, f)
            self.update_progress(1.0)
            time.sleep(1)
            self.launch_f1_game()
            time.sleep(8.0)
            self.monitor_game_process()
            
            # After launching, wait until game is detected running
            for _ in range(120):  # Max 10 seconds wait (20 x 0.5s)
                time.sleep(0.5)
                if self.is_game_running():
                    print("[SERPs Launcher] Detected F1 25 is running.")
                    
                    # Update Launch button state to "already running"
                    self.master.after(0, lambda: self.refresh_launch_button())
                    self.restore_ready = True
                    time.sleep(8.0)
                    break
            else:
                print("[SERPs Launcher] Warning: F1 25 did not launch within 10 seconds.")

            # After waiting (whether detected or not), hide loading bar and restore Launch button UI
            self.master.after(0, lambda: (self.loading_frame.pack_forget(), self.launch_btn.pack(fill="x"), self.refresh_launch_button()))
            return

        current_step = 0
        total_steps = sum(len(mod["files"]) for mod in mods_to_install)
        install_record = {}
        
        self.update_status("Saving clean backup...")
        time.sleep(0.4)

        for mod in mods_to_install:
            zip_path = mod["zip_path"]
            installed_files = []

            # Open archive
            lower_path = zip_path.lower()
            if lower_path.endswith(".zip"):
                archive_class = zipfile.ZipFile
            elif lower_path.endswith(".rar"):
                archive_class = rarfile.RarFile
            elif lower_path.endswith(".7z"):
                archive_class = py7zr.SevenZipFile
            else:
                print(f"Unsupported archive type: {zip_path}")
                continue

            with archive_class(zip_path, 'r') as archive:
                members = archive.namelist() if lower_path.endswith(".zip") else [f.filename for f in archive.infolist()] if lower_path.endswith(".rar") else archive.getnames()
                normalized_members = [m.lower() for m in members]
                
                variant_name = mod.get("variant", None)
                if variant_name:
                    self.update_status(f"Installing {variant_name}...")
                else:
                    self.update_status(f"Installing {mod['name']}...")
                time.sleep(0.4)
                
                for rel_f1_path in mod["files"]:
                    # Clean the mod path so there are no ".." segments
                    rel_clean = os.path.normpath(rel_f1_path)
                    while rel_clean.startswith(".." + os.sep) or rel_clean == "..":
                        rel_clean = rel_clean[len(".." + os.sep):]
                    rel_clean = rel_clean.lstrip(os.sep)
                    rel_game_path = rel_clean
                    game_file_path = os.path.join(self.game_path, rel_game_path)
                    backup_file_path = os.path.join(BACKUP_FOLDER, rel_game_path)

                    if os.path.exists(game_file_path) and not os.path.exists(backup_file_path):
                        os.makedirs(os.path.dirname(backup_file_path), exist_ok=True)
                        shutil.copy2(game_file_path, backup_file_path)

                    # === Find archive_path_matched logic
                    if "variant" in mod:
                        archive_path = f"{mod['variant']}/{rel_f1_path}"
                    else:
                        archive_path = rel_f1_path

                    archive_path_normalized = archive_path.replace("\\", "/").lower()

                    if archive_path_normalized not in normalized_members:
                        candidates = [m for m in normalized_members if archive_path_normalized in m]
                        if not candidates:
                            print(f"Warning: {archive_path} not found inside archive {zip_path}")
                            continue
                        archive_path_matched = members[normalized_members.index(candidates[0])]
                    else:
                        archive_path_matched = members[normalized_members.index(archive_path_normalized)]

                    # === Step 4: Install mod file
                    if lower_path.endswith(".zip") or lower_path.endswith(".rar"):
                        # Make sure destination folder exists
                        os.makedirs(os.path.dirname(game_file_path), exist_ok=True)
                        with archive.open(archive_path_matched) as src, open(game_file_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                            
                    elif lower_path.endswith(".7z"):
                        # 🧠 Preload all needed files (using the exact matched member names)
                        if not hasattr(self, '_cached_7z_extracted') or self._cached_7z_archive_path != zip_path:
                            needed_members = []
                            for rel in mod["files"]:
                                # build the candidate path including variant
                                orig_rel = f"{mod['variant']}/{rel}" if mod.get("variant") else rel
                                norm = orig_rel.replace("\\", "/").lower()
                                if norm in normalized_members:
                                    member = members[normalized_members.index(norm)]
                                else:
                                    # fallback: partial match
                                    candidates = [m for m in normalized_members if norm in m]
                                    if not candidates:
                                        continue
                                    member = members[normalized_members.index(candidates[0])]
                                needed_members.append(member)
                            # read them all at once into the cache
                            self._cached_7z_extracted = archive.read(needed_members)
                            self._cached_7z_archive_path = zip_path

                        # now write out this file via its exact matched name
                        filedata = self._cached_7z_extracted.get(archive_path_matched)
                        if filedata:
                            os.makedirs(os.path.dirname(game_file_path), exist_ok=True)
                            with open(game_file_path, 'wb') as dst:
                                shutil.copyfileobj(filedata, dst)

                    else:
                        print(f"Unsupported archive type: {zip_path}")
                        continue

                    installed_files.append(rel_game_path)

                    current_step += 1
                    self.update_progress(current_step / total_steps)
                install_record[mod["name"]] = installed_files
    
        self.update_status("Saving install record...")
        time.sleep(0.4)
        self.write_install_record(install_record)

        # === Save recent mods
        from datetime import datetime, timedelta

        now = datetime.now()
        session_mods = sorted([mod["name"] for mod in mods_to_install])

        should_log = True

        if self.recent_mods:
            last = self.recent_mods[0]
            last_mods = sorted(last["mods"])
            last_time = datetime.fromisoformat(last["timestamp"])

            if last_mods == session_mods and (now - last_time) < timedelta(minutes=5):
                should_log = False

        if should_log:
            self.recent_mods.insert(0, {"timestamp": now.isoformat(), "mods": session_mods})
            self.recent_mods = self.recent_mods[:10]

        self.save_recent_mods()
        
        if hasattr(self, '_cached_7z_extracted'):
            del self._cached_7z_extracted
            self._cached_7z_archive_path = None

        # === Launch game
        self.update_status("Launching F1 25...")
        time.sleep(0.4)
        self.launch_f1_game()
        current_step += 1
        self.update_progress(1.0)
        time.sleep(8.0)
        self.monitor_game_process()
        
        # After launching, wait until game is detected running
        for _ in range(120):  # Max 10 seconds wait (20 x 0.5s)
            time.sleep(0.5)
            if self.is_game_running():
                print("[SERPs Launcher] Detected F1 25 is running.")
                
                # Update Launch button state to "already running"
                self.master.after(0, lambda: self.refresh_launch_button())
                self.restore_ready = True
                time.sleep(8.0)
                break
        else:
            print("[SERPs Launcher] Warning: F1 25 did not launch within 10 seconds.")

        # After waiting (whether detected or not), hide loading bar and restore Launch button UI
        self.master.after(0, lambda: (self.loading_frame.pack_forget(), self.launch_btn.pack(fill="x"), self.refresh_launch_button()))

    def is_game_running(self):
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] == 'F1_25.exe':
                return True
        return False

    def monitor_game_process(self):
        def monitor():
            was_running = False

            while True:
                running = self.is_game_running()

                if running and not was_running:
                    was_running = True

                if not running and was_running:
                    print("[SERPs Launcher] F1 25 has closed")
                    if self.launch_btn.cget("state") == "disabled":
                        self.restore_sequence()

                    # ✅ Stop the monitor after restoring!
                    break

                time.sleep(2)

        threading.Thread(target=monitor, daemon=True).start()


    def restore_sequence(self):
        print("[SERPs Launcher] Restoring backup...")
        self.restore_ready = False

        # Hide launch button, show progress UI
        self.launch_btn.pack_forget()
        self.loading_frame.pack(fill="x")
        self.progress_bar.set(0)

        # 1) Gather all backups
        backups = []
        for root, _, files in os.walk(BACKUP_FOLDER):
            for file in files:
                src = os.path.join(root, file)
                rel = os.path.relpath(src, BACKUP_FOLDER)
                dst = os.path.join(self.game_path, rel)
                backups.append((src, dst))

        total = len(backups)
        if total == 0:
            self.update_status("No backup to restore.")
            time.sleep(0.5)
        else:
            # 2) Restore each file with status + progress updates
            for idx, (src, dst) in enumerate(backups, start=1):
                filename = os.path.basename(src)
                self.update_status(f"Restoring backup...")
                # Ensure target dir exists
                os.makedirs(os.path.dirname(dst), exist_ok=True)

                # Attempt copy with retries
                for attempt in range(10):
                    try:
                        shutil.copy2(src, dst)
                        break
                    except PermissionError:
                        if attempt < 9:
                            time.sleep(1)
                        else:
                            print(f"[SERPs Launcher] Failed to restore after retries: {dst}")
                    except FileNotFoundError:
                        print(f"[SERPs Launcher] Missing during restore: {src}")
                        break

                # Update bar (fraction done)
                self.update_progress(idx / total)
                time.sleep(0.1)

            print(f"[SERPs Launcher] Restoring backups completed!")
            
            # 3) Remove the backup folder
            if os.path.exists(BACKUP_FOLDER):
                shutil.rmtree(BACKUP_FOLDER)

            # 4) Final UI update
            self.update_progress(1.0)
            self.update_status("Backups restored!")
            time.sleep(0.5)

        # 5) Clean up and re-enable launch
        if os.path.exists(INSTALLED_MODS_FILE):
            os.remove(INSTALLED_MODS_FILE)
        self.refresh_launch_button()
        self.loading_frame.pack_forget()
        self.launch_btn.pack(fill="x")
        self.quit_btn.configure(state="normal", fg_color="#5345ff", hover_color="#675fff")
        self.quit_tooltip.text = "Quit SERPs Launcher"
        

    def show_mod_context_menu(self, event, mod_info):
        self.mod_context_menu.tk_popup(event.x_root, event.y_root)

        # Detect if this is a variant mod or single mod
        is_variant = "variant" in mod_info and "parent" in mod_info

        if is_variant:
            # For variants
            self.right_clicked_mod_info = {
                "variant": mod_info["variant"],
                "parent": mod_info["parent"],
                "zip_path": mod_info["zip_path"]
            }
        else:
            # For single mods
            self.right_clicked_mod_info = {
                "zip_path": mod_info["zip_path"]
            }


    def rename_selected_mod(self):
        mod_info = self.right_clicked_mod_info
        if not mod_info:
            return

        is_variant = "variant" in mod_info
        archive_path = mod_info["zip_path"]
        lower_path = archive_path.lower()

        if is_variant:
            old_variant = mod_info["variant"]
            parent_name = mod_info["parent"]
            new_variant = simpledialog.askstring("Rename Variant", f"Rename '{old_variant}' to:")
            if not new_variant or new_variant.strip() == "":
                return
            new_variant = new_variant.strip()
        else:
            base_name = os.path.splitext(os.path.basename(archive_path))[0]
            new_name = simpledialog.askstring("Rename Mod", f"Rename '{base_name}' to:")
            if not new_name or new_name.strip() == "":
                return
            new_name = new_name.strip()
            new_archive_path = os.path.join(os.path.dirname(archive_path), new_name + os.path.splitext(archive_path)[1])
            try:
                os.rename(archive_path, new_archive_path)
                self.refresh_mod_list()
                messagebox.showinfo("Success", f"Mod renamed to: {new_name}")
            except Exception as e:
                messagebox.showerror("Rename Error", f"Could not rename mod:\n{e}")
            return

        # === Variant-specific logic below ===
        temp_dir = os.path.join("temp_variant_edit")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)

        try:
            if lower_path.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as archive:
                    archive.extractall(temp_dir)
            elif lower_path.endswith(".rar"):
                with rarfile.RarFile(archive_path, "r") as archive:
                    archive.extractall(temp_dir)
            elif lower_path.endswith(".7z"):
                with py7zr.SevenZipFile(archive_path, "r") as archive:
                    archive.extractall(temp_dir)
            else:
                messagebox.showerror("Unsupported Format", "Cannot rename variant: unsupported archive type.")
                return
        except Exception as e:
            messagebox.showerror("Extraction Error", f"Failed to extract archive:\n{e}")
            return

        # Build and normalize the on‐disk paths
        old_path = os.path.normpath(os.path.join(temp_dir, old_variant))
        new_path = os.path.normpath(os.path.join(temp_dir, new_variant))

        # Ensure the old variant folder is present
        if not os.path.exists(old_path):
            shutil.rmtree(temp_dir, ignore_errors=True)
            messagebox.showerror("Rename Error", f"Variant folder '{old_variant}' not found.")
            return

        # Prevent clobbering an existing variant
        if os.path.exists(new_path):
            shutil.rmtree(temp_dir, ignore_errors=True)
            messagebox.showerror("Rename Error", f"A variant named '{new_variant}' already exists.")
            return

        # Perform the rename
        os.rename(old_path, new_path)

        is_rar = lower_path.endswith(".rar")
        out_path = archive_path if not is_rar else archive_path.rsplit(".", 1)[0] + ".zip"

        try:
            with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, temp_dir)
                        archive.write(full_path, arcname)
            if is_rar:
                os.remove(archive_path)
                messagebox.showinfo("RAR Converted", f".rar archive was converted to .zip: {os.path.basename(out_path)}")
        except Exception as e:
            messagebox.showerror("Repack Error", f"Failed to update archive:\n{e}")
            return
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.refresh_mod_list()
        messagebox.showinfo("Success", f"Variant renamed to: {new_variant}")

    def delete_selected_mod(self):
        mod_info = self.right_clicked_mod_info
        if not mod_info:
            return

        is_variant = "variant" in mod_info
        archive_path = mod_info["zip_path"]
        lower_path = archive_path.lower()

        if is_variant:
            variant_to_delete = mod_info["variant"]
            confirm = messagebox.askyesno("Delete Variant", f"Are you sure you want to delete '{variant_to_delete}'?")
            if not confirm:
                return
        else:
            base_name = os.path.splitext(os.path.basename(archive_path))[0]
            confirm = messagebox.askyesno("Delete Mod", f"Are you sure you want to delete '{base_name}'?")
            if not confirm:
                return
            try:
                os.remove(archive_path)
                self.refresh_mod_list()
                messagebox.showinfo("Success", f"Mod '{base_name}' deleted.")
            except Exception as e:
                messagebox.showerror("Delete Error", f"Could not delete mod:\n{e}")
            return

        # === Variant-specific logic below ===
        temp_dir = os.path.join("temp_variant_delete")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)

        try:
            if lower_path.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as archive:
                    archive.extractall(temp_dir)
            elif lower_path.endswith(".rar"):
                with rarfile.RarFile(archive_path, "r") as archive:
                    archive.extractall(temp_dir)
            elif lower_path.endswith(".7z"):
                with py7zr.SevenZipFile(archive_path, "r") as archive:
                    archive.extractall(temp_dir)
            else:
                messagebox.showerror("Unsupported Format", "Cannot delete variant: unsupported archive type.")
                return
        except Exception as e:
            messagebox.showerror("Extraction Error", f"Failed to extract archive:\n{e}")
            return

        # Normalize and locate the variant folder inside the temp snapshot
        variant_path = os.path.normpath(os.path.join(temp_dir, variant_to_delete))
        if not os.path.exists(variant_path):
            shutil.rmtree(temp_dir, ignore_errors=True)
            messagebox.showerror("Delete Error", f"Variant folder '{variant_to_delete}' not found.")
            return

        # Remove just that subfolder
        shutil.rmtree(variant_path)

        remaining = any(os.scandir(temp_dir))
        is_rar = lower_path.endswith(".rar")
        out_path = archive_path if not is_rar else archive_path.rsplit(".", 1)[0] + ".zip"

        try:
            if not remaining:
                os.remove(archive_path)
            else:
                with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for root, _, files in os.walk(temp_dir):
                        for file in files:
                            full_path = os.path.join(root, file)
                            arcname = os.path.relpath(full_path, temp_dir)
                            archive.write(full_path, arcname)
                if is_rar:
                    os.remove(archive_path)
                    messagebox.showinfo("RAR Converted", f".rar archive was converted to .zip: {os.path.basename(out_path)}")
        except Exception as e:
            messagebox.showerror("Repack Error", f"Failed to update archive:\n{e}")
            return
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.refresh_mod_list()
        messagebox.showinfo("Success", f"Variant '{variant_to_delete}' deleted.")




    def clean_temp_folder(self, temp_folder_path):
        if not os.path.exists(temp_folder_path):
            return

        for root, dirs, files in os.walk(temp_folder_path, topdown=False):
            for name in dirs:
                dir_path = os.path.join(root, name)
                if not os.listdir(dir_path):  # Empty folder
                    os.rmdir(dir_path)

        # Finally, if the temp folder itself is empty
        if not os.listdir(temp_folder_path):
            os.rmdir(temp_folder_path)


    def set_launch_button_state(self, enabled=True, text="Launch F1 25", popup=True):
        color = "#5345ff" if enabled else "#444444"
        hover_color = "#675fff" if enabled else "#555555"
        
        self.launch_btn.configure(
            state="normal" if enabled else "disabled",
            fg_color=color,
            hover_color=hover_color,
            text=text
        )

    def refresh_launch_button(self):
        # 1) No game directory set → prompt to choose
        if not os.path.exists(GAME_DIRECTORY_FILE):
            self.set_launch_button_state(
                enabled=False,
                text="Please set your F1 25 game directory first...",
                popup=False
            )
        # 2) Game already “running” (we treat INSTALLED_MODS_FILE as our lock)
        elif os.path.exists(INSTALLED_MODS_FILE):
            self.set_launch_button_state(
                enabled=False,
                text="F1 25 is already running...",
                popup=False
            )
        # 3) All good → allow launch
        else:
            self.set_launch_button_state(
                enabled=True,
                text="Launch F1 25",
                popup=True
            )

            """Hide the loading bar/status and show the Launch button again."""
            if hasattr(self, "loading_frame") and self.loading_frame:
                self.loading_frame.pack_forget()
            if hasattr(self, "launch_btn") and self.launch_btn:
                self.launch_btn.pack(fill="x")

    def quit_app(self):
        if lock_file_handle:
            try:
                msvcrt.locking(lock_file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                lock_file_handle.close()
                os.remove(LOCKFILE)
            except:
                pass
        self.master.quit()

    def auto_restore_if_needed(self):
        if os.path.exists(INSTALLED_MODS_FILE):
            with open(INSTALLED_MODS_FILE, 'r') as f:
                installed = json.load(f)

            if installed:
                print("[Auto Restore] Running restore sequence due to leftover installed mods...")
                self.restore_sequence()

    def disable_launch_if_game_running(self):
        if self.is_game_running():
            self.launch_btn.configure(state="disabled", fg_color="#444444", hover_color="#555555", text="F1 25 is already running")


    def on_drop_files(self, event):
        dropped_files = self.master.tk.splitlist(event.data)
        supported_exts = (".zip", ".rar", ".7z")

        for file_path in dropped_files:
            file_path = file_path.strip("{").strip("}")  # Handle paths with spaces
            if not file_path.lower().endswith(supported_exts):
                continue

            filename = os.path.basename(file_path)

            categorize = messagebox.askyesno("Categorize Mod?", f"Do you want to place '{filename}' into a category folder?")
            if categorize:
                os.makedirs(MODS_FOLDER, exist_ok=True)
                base_dir = os.path.abspath(MODS_FOLDER)

                self.master.lift()
                self.master.attributes('-topmost', True)
                self.master.after_idle(lambda: self.master.attributes('-topmost', False))

                selected_dir = filedialog.askdirectory(
                    title="Choose a folder inside /mods",
                    initialdir=base_dir,
                    mustexist=True
                )

                if not selected_dir:
                    continue

                selected_dir = os.path.abspath(selected_dir)
                if not selected_dir.startswith(base_dir):
                    messagebox.showwarning("Invalid Selection", "Please select a folder inside the /mods directory.")
                    continue

                dest_path = os.path.join(selected_dir, filename)
            else:
                dest_path = os.path.join(MODS_FOLDER, filename)

            try:
                if os.path.exists(dest_path):
                    overwrite = messagebox.askyesno(
                        "Overwrite Mod?",
                        f"A mod named '{filename}' already exists in this folder.\n\nDo you want to overwrite it?"
                    )
                    if not overwrite:
                        print(f"Skipped (user declined overwrite): {file_path}")
                        continue

                shutil.copy(file_path, dest_path)
                print(f"Copied: {file_path} to {dest_path}")

            except Exception as e:
                print(f"Failed to copy {file_path}: {e}")

        self.refresh_mod_list()

    def find_basefiles_mod(self):
        # Walk every archive in your mods folder
        for root, _, files in os.walk(MODS_FOLDER):
            for fname in files:
                if not fname.lower().endswith((".zip", ".rar", ".7z")):
                    continue
                archive_path = os.path.join(root, fname)
                if self._archive_contains(archive_path, "SERPs Base Files for F1 25 - Read Me.pdf"):
                    # load its mod entries
                    for mod_info in self.read_supported_mod_archives(archive_path):
                        # choose the one whose name includes “basefiles”
                        if "basefiles" in mod_info["name"].lower():
                            return mod_info
        return None

if __name__ == "__main__":
    if is_already_running():
        messagebox.showerror("Already Running", "SERPs Launcher is already running.")
        sys.exit(0)

    root = TkinterDnD.Tk()
    root.overrideredirect(True)
    app = SERPsLauncher(root)

    # Fix to show in taskbar
    GWL_EXSTYLE = -20
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080

    def make_window_appwindow(hwnd):
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = style & ~WS_EX_TOOLWINDOW
        style = style | WS_EX_APPWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        ctypes.windll.user32.ShowWindow(hwnd, 5)

    hasstyle = False

    def set_appwindow():
        global hasstyle
        if not hasstyle:
            hwnd = windll.user32.GetParent(root.winfo_id())
            style = windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = style & ~WS_EX_TOOLWINDOW
            style = style | WS_EX_APPWINDOW
            res = windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            root.withdraw()
            root.after(100, lambda:root.wm_deiconify())
            hasstyle=True

    root.update_idletasks()
    root.withdraw()
    set_appwindow()
           
    hwnd = get_hwnd(root)
    make_window_appwindow(hwnd)

    root.mainloop()

def patch_game_to_support_lng():
    def find_f1_exe():
        possible_folders = [
            "Program Files (x86)\\Steam\\steamapps\\common\\F1 25\\F1_25.exe",
            "SteamLibrary\\steamapps\\common\\F1 25\\F1_25.exe",
            "steamapps\\common\\F1 25\\F1_25.exe"
        ]
        for drive_letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            for folder in possible_folders:
                candidate = f"{drive_letter}:\\{folder}"
                if os.path.exists(candidate):
                    return candidate
        return None

    # Configuration
    exe_path = find_f1_exe()  # Auto-detect game executable
    if not exe_path:
        print("❌ Could not locate F1_25.exe. Please check your installation.")
    steam_command = r'steam://run/3059520'  # F1 25 : 3059520, F1 24 : 2488620
    backup_path = exe_path + ".bak"  # Backup path

    # Process names to monitor
    anti_cheat_process = "EAAntiCheat.GameServiceLauncher.exe"
    game_process = "F1_25.exe"

    # Logging function with elapsed time
    def log(message):
        global last_log_time
        now = time.time()
        if last_log_time is None:
            interval = 0.0
        else:
            interval = now - last_log_time
        last_log_time = now
        print(f"({interval:.1f}s) {message}")

    # Check for administrator rights
    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    # Relaunch with admin if needed
    if not is_admin():
        print("Relaunching with administrator privileges...")
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    # Create a one-time backup of the original file
    def create_backup():
        if not os.path.exists(backup_path):
            with open(exe_path, "rb") as f_in, open(backup_path, "wb") as f_out:
                while True:
                    chunk = f_in.read(1024 * 1024)
                    if not chunk:
                        break
                    f_out.write(chunk)
            log("Backup created.")

    # Toggle the specific string " tionf" to " tioaf" in the executable and back
    def toggle_string():
        with open(exe_path, "r+b") as f:
            data = f.read()
            original = b" tionf"
            patched = b" tioaf"

            index = data.find(original)
            if index != -1:
                f.seek(index)
                f.write(patched)
                log(f"String patched at offset {hex(index)}: '{original.decode()}' → '{patched.decode()}'")
                return index, patched

            index = data.find(patched)
            if index != -1:
                f.seek(index)
                f.write(original)
                log(f"String reverted at offset {hex(index)}: '{patched.decode()}' → '{original.decode()}'")
                return index, original

            log(f"Patch skipped: neither '{original.decode()}' nor '{patched.decode()}' found.")
            return None

    # Check if a specific process is running
    def is_process_running(name):
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and name.lower() in proc.info['name'].lower():
                return True
        return False

    # Launch the game using Steam
    def launch_game():
        log("Launching F1 25 via Steam...")
        subprocess.Popen(['cmd', '/c', 'start', steam_command], shell=True)

    # Main logic
    def main():
        # 1. Backup and launch game
        create_backup()
        launch_game()

        # 2. Wait for anti-cheat process to start
        log(f"Waiting for {anti_cheat_process} to start...")
        anti_proc = None
        while not anti_proc:
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and anti_cheat_process.lower() in proc.info['name'].lower():
                    anti_proc = proc
                    break
            time.sleep(0.5)
        log("Anti-cheat process detected.")

        # 3. Wait until anti-cheat spawns child process and it terminates again
        log("Monitoring anti-cheat child processes...")
        saw_child = False
        while True:
            try:
                children = anti_proc.children()
                if len(children) > 0:
                    saw_child = True
                elif saw_child and len(children) == 0:
                    log("Child process spawned and terminated.")
                    break
            except psutil.NoSuchProcess:
                log("Anti-cheat process exited.")
                return
            time.sleep(0.5)

        # 4. Attempt patching before F1_25.exe starts (200ms interval)
        max_attempts = 50
        attempt = 0
        patched = False

        while not is_process_running(game_process) and attempt < max_attempts:
            try:
                result = toggle_string()
                if result:
                    patched = True
                    log(f"Patch successful (attempt {attempt + 1})")
                    break
            except PermissionError:
                log(f"PermissionError on attempt {attempt + 1}, retrying...")
            attempt += 1
            time.sleep(0.2)

        if not patched:
            log("Patch failed: access denied before game launch.")
            return

        # 5. Wait for F1_25.exe to start
        log("Waiting for F1_25.exe to start...")
        while not is_process_running(game_process):
            time.sleep(0.5)
        log("F1_25.exe detected. Monitoring for exit...")

        # 6. Wait for game to exit
        while is_process_running(game_process):
            time.sleep(1)
        log("F1_25.exe has exited. Reverting in 1 second...")

        # 7. Revert patch after delay
        time.sleep(1)
        toggle_string()

        log("Automation complete.")

    if __name__ == "__main__":
        main()
    if not exe_path:
        print("❌ Could not locate F1_25.exe. Please check your installation.")
        return

    try:
        with open(exe_path, 'rb') as f:
            exe_data = f.read()
        patched_data = exe_data.replace(b"native_language\0", b"language_modded\0")
        if b"language_modded\0" not in patched_data:
            raise Exception("Patch string not found or already patched.")

        if not os.path.exists(backup_path):
            with open(backup_path, 'wb') as f:
                f.write(exe_data)

        with open(exe_path, 'wb') as f:
            f.write(patched_data)
    except Exception as e:
        print(f"❌ Failed to patch executable: {e}")
        return

    subprocess.Popen(["cmd", "/c", "start", "", steam_command])
