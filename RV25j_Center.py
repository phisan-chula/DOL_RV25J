#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 DeedOCR_App
-------------------------------------------------------------------------------
 DeedOCR_App is an interactive image annotation utility designed for processing
 DOL (Department of Lands, Thailand) scanned deed documents such as RJ25v /
 RV25j style survey sheets.

 The application reads a target folder and automatically discovers all images
 matching the pattern:

        *_rv25j.jpg

 For each document, the user can:

   1. View the DOL document image (middle canvas, 1:1 pixels with scrollbars).

   2. Draw a rectangle (mouse drag UL → LR) marking the parcel/table area.
      - New rectangles are drawn in red.
      - Existing rectangles from *_rect.json are drawn in blue.

   3. Save the rectangle geometry as:

            *_rect.json

      containing UL/LR coordinates in full image-pixel space.

   4. Clip the table region:
      - Using *_rect.json, the app crops the marked region from the original
        image and saves it as:

            *_table.jpg   (downscaled by factor 2)

   5. Right panel (~20% width) shows, for the current *_rv25j.jpg:
      - Top   : *_table.jpg preview (if exists)
      - Middle: *_MAPL1.toml text content (if exists), with auto-hide scrollbar
      - Bottom: *_plot.png polygon preview (if exists)

 Layout ratio (bottom content area):
      left_frame   ≈ 10%  (list of files)
      middle_frame ≈ 70%  (main image + rectangle)
      right_frame  ≈ 20%  (table/TOML/plot)

-------------------------------------------------------------------------------
 Author : Phisan / ChatGPT
 Version: 16 Nov 2025
===============================================================================
"""

import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import pandas as pd

RV_SUFFIX = "_rv25j.jpg"   # strict suffix we support


# ---------------------------------------------------------------------------
# Auto-hide scrollbar for TOML text widget (right frame)
# ---------------------------------------------------------------------------
class AutoHideScrollbar(tk.Scrollbar):
    """
    A scrollbar that hides itself if the content fits in the widget.

    Use with 'yscrollcommand=self_scrollbar.set' on the scrolled widget.
    """

    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._pack_kw = None

    def pack(self, **kw):
        # Remember pack options so we can re-pack when needed
        self._pack_kw = kw
        super().pack(**kw)

    def pack_forget(self):
        super().pack_forget()

    def set(self, lo, hi):
        lo = float(lo)
        hi = float(hi)
        if lo <= 0.0 and hi >= 1.0:
            # Content fits → hide scrollbar
            if self.winfo_ismapped():
                super().pack_forget()
        else:
            # Content larger than view → show scrollbar (if not visible)
            if not self.winfo_ismapped():
                kw = self._pack_kw or {"side": tk.RIGHT, "fill": tk.Y}
                super().pack(**kw)
        super().set(lo, hi)


class ImageBrowserApp:
    def __init__(self, master):
        self.master = master
        self.master.title("DeedOCR_App - RV25j Table Clip Tool")

        # Data
        self.df = None
        self.current_idx = None

        # Keep references to PhotoImage
        self.photo_main = None       # middle canvas (full deed image)
        self.photo_table = None      # right top canvas (*_table.jpg)
        self.photo_plot = None       # right bottom canvas (*_plot.png)

        # Text widget for TOML
        self.text_toml = None

        # Geometry / rect state for main image
        self.main_img_size = None      # (width, height) in image pixels
        self.main_scale = None         # scale factor image→canvas
        self.main_offset = None        # (offset_x, offset_y) on canvas
        self.rect_canvas_id = None     # current rectangle item on canvas
        self.current_rect_img = None   # (ulx, uly, lrx, lry) in image coords

        # For mouse dragging
        self.dragging = False
        self.rect_start_canvas = None  # (x, y) canvas coords
        self.rect_start_img = None     # (x, y) image coords

        self.create_widgets()

    # ------------------------------------------------------------------
    # UI creation
    # ------------------------------------------------------------------
    def create_widgets(self):
        # ---------- Top ribbon ----------
        ribbon = tk.Frame(self.master)
        ribbon.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        btn_open = tk.Button(ribbon, text="Open folder...", command=self.open_folder)
        btn_open.pack(side=tk.LEFT, padx=5)

        btn_prev = tk.Button(ribbon, text="Previous", command=self.show_previous)
        btn_prev.pack(side=tk.LEFT, padx=5)

        btn_next = tk.Button(ribbon, text="Next", command=self.show_next)
        btn_next.pack(side=tk.LEFT, padx=5)

        # Big orange: Write *_rect.json
        btn_write_json = tk.Button(
            ribbon,
            text="Write *_rect.json",
            command=self.write_rect_json,
            bg="orange",
            fg="black",
            font=("Arial", 12, "bold"),
            width=20,
        )
        btn_write_json.pack(side=tk.LEFT, padx=5)

        # Big red: Clip to *_table.jpg (skip existing)
        btn_clip = tk.Button(
            ribbon,
            text="Clip to *_table.jpg",
            command=self.clip_all_missing,
            bg="red",
            fg="white",
            font=("Arial", 12, "bold"),
            width=20,
        )
        btn_clip.pack(side=tk.LEFT, padx=10)

        # Big red: FORCED clip (overwrite existing)
        btn_clip_force = tk.Button(
            ribbon,
            text="Force clip ALL to *_table.jpg",
            command=lambda: self.clip_all_missing(force=True),
            bg="red",
            fg="white",
            font=("Arial", 12, "bold"),
            width=24,
        )
        btn_clip_force.pack(side=tk.LEFT, padx=5)

        spacer = tk.Frame(ribbon)
        spacer.pack(side=tk.LEFT, expand=True, fill=tk.X)
        btn_quit = tk.Button(ribbon, text="Quit", command=self.master.quit)
        btn_quit.pack(side=tk.RIGHT, padx=5)

        # ---------- Bottom content using grid ----------
        content = tk.Frame(self.master)
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Ratio 10 : 70 : 20  →  1 : 7 : 2
        content.grid_columnconfigure(0, weight=1)   # left
        content.grid_columnconfigure(1, weight=8)   # middle
        content.grid_columnconfigure(2, weight=1)   # right
        content.grid_rowconfigure(0, weight=1)

        # ----- Left frame (~10%) -----
        left_frame = tk.Frame(content, bd=1, relief=tk.SUNKEN)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        tk.Label(left_frame, text="*_rv25j.jpg files").pack(anchor="w")

        self.listbox = tk.Listbox(left_frame, width=20,  font=("Arial", 14) )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        self.listbox.bind("<<ListboxSelect>>", self.on_listbox_select)

        # ----- Middle frame (~70%) -----
        middle_frame = tk.Frame(content, bd=1, relief=tk.SUNKEN)
        middle_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        tk.Label(middle_frame, text="Main deed image (draw rect here)").pack(anchor="w")

        canvas_container = tk.Frame(middle_frame)
        canvas_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        vbar = tk.Scrollbar(canvas_container, orient=tk.VERTICAL)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)

        hbar = tk.Scrollbar(middle_frame, orient=tk.HORIZONTAL)
        hbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.canvas_main = tk.Canvas(
            canvas_container,
            bg="gray",
            xscrollcommand=hbar.set,
            yscrollcommand=vbar.set,
        )
        self.canvas_main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vbar.config(command=self.canvas_main.yview)
        hbar.config(command=self.canvas_main.xview)

        # Mouse events for drawing rectangle
        self.canvas_main.bind("<ButtonPress-1>", self.on_canvas_main_press)
        self.canvas_main.bind("<B1-Motion>", self.on_canvas_main_drag)
        self.canvas_main.bind("<ButtonRelease-1>", self.on_canvas_main_release)

        # ----- Right frame (~20%) -----
        self.right_frame = tk.Frame(content, bd=1, relief=tk.SUNKEN)
        self.right_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        # Top: *_table.jpg preview
        tk.Label(self.right_frame, text="*_table.jpg (clipped table preview)").pack(anchor="w")
        self.canvas_table = tk.Canvas(self.right_frame, width=150, height=300, bg="gray")
        self.canvas_table.pack(fill=tk.BOTH, expand=True)

        # Middle: *_MAPL1.toml with auto-hide scrollbar
        #tk.Label(self.right_frame, text="*_MAPL1.toml").pack(anchor="w")
        # Middle: *_MAPL1(.x).toml with auto-hide scrollbar
        self.label_toml = tk.Label(self.right_frame, text="TOML file here")
        self.label_toml.pack(anchor="w")
        toml_frame = tk.Frame(self.right_frame)
        toml_frame.pack(fill=tk.BOTH, expand=False)

        self.text_toml = tk.Text(toml_frame, wrap="none", font=("Courier", 14), height=20, width=20) 
        # MODIFIED HEIGHT=4
        self.text_toml.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        toml_scroll = AutoHideScrollbar(toml_frame, orient=tk.VERTICAL, command=self.text_toml.yview)
        toml_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_toml.config(yscrollcommand=toml_scroll.set)

        # Bottom: *_plot.png
        tk.Label(self.right_frame, text="*_plot.png (polygon preview)").pack(anchor="w")
        self.canvas_plot = tk.Canvas(self.right_frame, width=150, height=300, bg="gray")
        self.canvas_plot.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Folder + DataFrame loading
    # ------------------------------------------------------------------
    def open_folder(self):
        folder = filedialog.askdirectory(title="Select base folder (e.g. ./Narativas/)")
        if not folder:
            return

        records = []
        for root, dirs, files in os.walk(folder):
            for fname in files:
                lower = fname.lower()
                if lower.endswith(RV_SUFFIX):
                    full_path = os.path.join(root, fname)

                    prefix = fname[:-len(RV_SUFFIX)]
                    table_name = prefix + "_table.jpg"
                    table_path = os.path.join(root, table_name)
                    table_exists = os.path.isfile(table_path)

                    records.append(
                        {
                            "name": fname,
                            "rv_path": full_path,
                            "table_path": table_path if table_exists else None,
                        }
                    )

        if not records:
            messagebox.showwarning("No images", f"No *{RV_SUFFIX} files found.")
            return

        self.df = pd.DataFrame(records)
        self.current_idx = 0

        self.listbox.delete(0, tk.END)
        for i, row in self.df.iterrows():
            rel = os.path.relpath(row["rv_path"], folder)
            self.listbox.insert(tk.END, rel)

        self.listbox.select_set(0)
        self.listbox.event_generate("<<ListboxSelect>>")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def show_previous(self):
        if self.df is None or self.current_idx is None:
            return
        if self.current_idx > 0:
            self.current_idx -= 1
            self.listbox.select_clear(0, tk.END)
            self.listbox.select_set(self.current_idx)
            self.listbox.see(self.current_idx)
            self.update_images()

    def show_next(self):
        if self.df is None or self.current_idx is None:
            return
        if self.current_idx < len(self.df) - 1:
            self.current_idx += 1
            self.listbox.select_clear(0, tk.END)
            self.listbox.select_set(self.current_idx)
            self.listbox.see(self.current_idx)
            self.update_images()

    def on_listbox_select(self, event):
        if self.df is None:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        self.current_idx = sel[0]
        self.update_images()

    # ------------------------------------------------------------------
    # JSON rect path helper
    # ------------------------------------------------------------------
    def get_rect_json_path(self, rv_path: str) -> str:
        folder, fname = os.path.split(rv_path)
        prefix = fname[:-len(RV_SUFFIX)]  # strict
        rect_name = prefix + "_rect.json"
        return os.path.join(folder, rect_name)

    # ------------------------------------------------------------------
    # Image display helpers
    # ------------------------------------------------------------------
    def update_images(self):
        # Reset rectangle state
        self.main_img_size = None
        self.main_scale = None
        self.main_offset = None
        self.current_rect_img = None
        if self.rect_canvas_id is not None:
            self.canvas_main.delete(self.rect_canvas_id)
            self.rect_canvas_id = None

        if self.df is None or self.current_idx is None:
            return

        row = self.df.iloc[self.current_idx]
        rv_path = row["rv_path"]
        table_path = row["table_path"]

        folder, fname = os.path.split(rv_path)
        prefix = fname[:-len(RV_SUFFIX)]
        toml_path = os.path.join(folder, f"{prefix}_MAPL1.toml")
        toml_x_path = os.path.join(folder, f"{prefix}_MAPL1x.toml")  # side-file
        plot_path = os.path.join(folder, f"{prefix}_plot.png")

        # Middle: main image
        self.display_image_on_canvas(rv_path, self.canvas_main, is_main=True)
        self.load_existing_rect(rv_path)

        # Right top: *_table.jpg
        if table_path and os.path.isfile(table_path):
            self.display_table_image(table_path)
        else:
            self.canvas_table.delete("all")
            self.canvas_table.create_text(
                self.canvas_table.winfo_width() // 2,
                self.canvas_table.winfo_height() // 2,
                text="No *_table.jpg",
                fill="white",
            )

        # Right middle: *_MAPL1.toml text
        #self.text_toml.config(state="normal")
        #self.text_toml.delete("1.0", tk.END)
        #if os.path.isfile(toml_path):
        #    try:
        #        txt = open(toml_path, "r", encoding="utf-8").read()
        #        self.text_toml.insert("1.0", txt)
        #    except Exception as e:
        #        self.text_toml.insert("1.0", f"Error reading {toml_path}:\n{e}")
        #else:
        #    self.text_toml.insert("1.0", "No *_MAPL1.toml")
        #self.text_toml.config(state="disabled")
        # Right middle: *_MAPL1.toml / *_MAPL1x.toml text
        self.text_toml.config(state="normal", bg="white")  # reset default
        self.text_toml.delete("1.0", tk.END)

        # Determine TOML source
        if os.path.isfile(toml_x_path):
            path_to_show = toml_x_path
            use_side = True
            self.label_toml.config(text="*_MAPL1x.toml (override)")  # update label
        else:
            path_to_show = toml_path
            use_side = False
            self.label_toml.config(text="*_MAPL1.toml")

        # Load TOML
        if os.path.isfile(path_to_show):
            try:
                with open(path_to_show, "r", encoding="utf-8") as f:
                    txt = f.read()
                self.text_toml.insert("1.0", txt)

                # Pink highlight when side file is active
                if use_side:
                    self.text_toml.config(bg="pink")

            except Exception as e:
                self.text_toml.insert("1.0", f"Error reading {path_to_show}:\n{e}")
        else:
            self.text_toml.insert("1.0", "No *_MAPL1.toml / *_MAPL1x.toml")

        self.text_toml.config(state="disabled")
        ##################################################################
        # Right bottom: *_plot.png
        if os.path.isfile(plot_path):
            self.display_plot_image(plot_path)
        else:
            self.canvas_plot.delete("all")
            self.canvas_plot.create_text(
                self.canvas_plot.winfo_width() // 2,
                self.canvas_plot.winfo_height() // 2,
                text="No *_plot.png",
                fill="white",
            )

    def display_image_on_canvas(self, path, canvas, is_main=True):
        try:
            img = Image.open(path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open image:\n{path}\n\n{e}")
            return

        orig_w, orig_h = img.size

        if is_main:
            self.photo_main = ImageTk.PhotoImage(img)
            canvas.delete("all")
            canvas.create_image(0, 0, image=self.photo_main, anchor="nw")
            canvas.config(scrollregion=(0, 0, orig_w, orig_h))

            self.main_img_size = (orig_w, orig_h)
            self.main_scale = 1.0
            self.main_offset = (0.0, 0.0)

    def display_table_image(self, path):
        try:
            img = Image.open(path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open image:\n{path}\n\n{e}")
            return

        orig_w, orig_h = img.size
        canvas = self.canvas_table
        canvas_width = max(canvas.winfo_width(), 200)
        canvas_height = max(canvas.winfo_height(), 100)

        img_ratio = orig_w / orig_h
        canvas_ratio = canvas_width / canvas_height

        if img_ratio > canvas_ratio:
            new_width = canvas_width
            new_height = int(canvas_width / img_ratio)
        else:
            new_height = canvas_height
            new_width = int(canvas_height * img_ratio)

        img_resized = img.resize((new_width, new_height), Image.LANCZOS)
        self.photo_table = ImageTk.PhotoImage(img_resized)

        canvas.delete("all")
        canvas.create_image(
            canvas_width // 2,
            canvas_height // 2,
            image=self.photo_table,
        )

    def display_plot_image(self, path):
        try:
            img = Image.open(path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open image:\n{path}\n\n{e}")
            return

        orig_w, orig_h = img.size
        canvas = self.canvas_plot
        canvas_width = max(canvas.winfo_width(), 200)
        canvas_height = max(canvas.winfo_height(), 100)

        img_ratio = orig_w / orig_h
        canvas_ratio = canvas_width / canvas_height

        if img_ratio > canvas_ratio:
            new_width = canvas_width
            new_height = int(canvas_width / img_ratio)
        else:
            new_height = canvas_height
            new_width = int(canvas_height * img_ratio)

        img_resized = img.resize((new_width, new_height), Image.LANCZOS)
        self.photo_plot = ImageTk.PhotoImage(img_resized)

        canvas.delete("all")
        canvas.create_image(
            canvas_width // 2,
            canvas_height // 2,
            image=self.photo_plot,
        )

    # ------------------------------------------------------------------
    # Existing rect.json
    # ------------------------------------------------------------------
    def load_existing_rect(self, rv_path: str):
        rect_path = self.get_rect_json_path(rv_path)
        if not os.path.isfile(rect_path):
            return

        try:
            with open(rect_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showwarning("JSON error", f"Failed to read {rect_path}:\n{e}")
            return

        try:
            ul = data["rect"]["ul"]
            lr = data["rect"]["lr"]
            ulx, uly = float(ul[0]), float(ul[1])
            lrx, lry = float(lr[0]), float(lr[1])
        except Exception as e:
            messagebox.showwarning("JSON format", f"Invalid rect format in {rect_path}:\n{e}")
            return

        self.current_rect_img = (ulx, uly, lrx, lry)
        self.draw_rect_from_image_coords(self.current_rect_img, color="blue")

    # ------------------------------------------------------------------
    # Coordinate transforms
    # ------------------------------------------------------------------
    def canvas_to_image(self, cx, cy):
        if not self.main_img_size or self.main_scale is None or not self.main_offset:
            return None
        ox, oy = self.main_offset
        ix = (cx - ox) / self.main_scale
        iy = (cy - oy) / self.main_scale
        w, h = self.main_img_size
        ix = max(0, min(w - 1, ix))
        iy = max(0, min(h - 1, iy))
        return ix, iy

    def image_to_canvas(self, ix, iy):
        if self.main_scale is None or not self.main_offset:
            return None
        ox, oy = self.main_offset
        cx = ox + ix * self.main_scale
        cy = oy + iy * self.main_scale
        return cx, cy

    def draw_rect_from_image_coords(self, rect, color="red"):
        if not rect or self.main_scale is None or not self.main_offset:
            return
        ulx, uly, lrx, lry = rect
        p1 = self.image_to_canvas(ulx, uly)
        p2 = self.image_to_canvas(lrx, lry)
        if p1 is None or p2 is None:
            return
        x1, y1 = p1
        x2, y2 = p2

        if self.rect_canvas_id is not None:
            self.canvas_main.delete(self.rect_canvas_id)
        self.rect_canvas_id = self.canvas_main.create_rectangle(
            x1, y1, x2, y2, outline=color, width=2
        )

    # ------------------------------------------------------------------
    # Mouse events: draw rectangle
    # ------------------------------------------------------------------
    def on_canvas_main_press(self, event):
        if self.main_img_size is None:
            return

        cx = self.canvas_main.canvasx(event.x)
        cy = self.canvas_main.canvasy(event.y)

        self.dragging = True
        self.rect_start_canvas = (cx, cy)
        img_pt = self.canvas_to_image(cx, cy)
        if img_pt is None:
            self.rect_start_img = None
            return
        self.rect_start_img = img_pt

        if self.rect_canvas_id is not None:
            self.canvas_main.delete(self.rect_canvas_id)
        self.rect_canvas_id = self.canvas_main.create_rectangle(
            cx, cy, cx, cy, outline="red", width=2
        )

    def on_canvas_main_drag(self, event):
        if not self.dragging or self.rect_start_canvas is None:
            return
        if self.rect_canvas_id is None:
            return

        cx = self.canvas_main.canvasx(event.x)
        cy = self.canvas_main.canvasy(event.y)
        x0, y0 = self.rect_start_canvas
        self.canvas_main.coords(self.rect_canvas_id, x0, y0, cx, cy)

    def on_canvas_main_release(self, event):
        if not self.dragging:
            return
        self.dragging = False

        if self.rect_start_img is None:
            return

        cx = self.canvas_main.canvasx(event.x)
        cy = self.canvas_main.canvasy(event.y)
        end_img = self.canvas_to_image(cx, cy)
        if end_img is None:
            return

        x0_img, y0_img = self.rect_start_img
        x1_img, y1_img = end_img

        ulx = min(x0_img, x1_img)
        uly = min(y0_img, y1_img)
        lrx = max(x0_img, x1_img)
        lry = max(y0_img, y1_img)

        self.current_rect_img = (ulx, uly, lrx, lry)
        self.draw_rect_from_image_coords(self.current_rect_img, color="red")

    # ------------------------------------------------------------------
    # Write *_rect.json
    # ------------------------------------------------------------------
    def write_rect_json(self):
        if self.df is None or self.current_idx is None:
            messagebox.showwarning("No image", "No image selected.")
            return
        if not self.current_rect_img:
            messagebox.showwarning("No rectangle", "Draw a rectangle on the main image first.")
            return

        row = self.df.iloc[self.current_idx]
        rv_path = row["rv_path"]
        rect_path = self.get_rect_json_path(rv_path)
        ulx, uly, lrx, lry = self.current_rect_img

        data = {
            "image": os.path.basename(rv_path),
            "rect": {"ul": [ulx, uly], "lr": [lrx, lry]},
        }

        try:
            with open(rect_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Saved", f"Wrote rectangle to:\n{rect_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write {rect_path}: {e}")

    # ------------------------------------------------------------------
    # Clip to *_table.jpg
    # ------------------------------------------------------------------
    def clip_all_missing(self, force: bool = False):
        if self.df is None:
            messagebox.showwarning("No data", "Please open a folder first.")
            return

        created = 0
        skipped_no_rect = 0
        skipped_existing = 0

        for idx, row in self.df.iterrows():
            rv = row["rv_path"]
            table = row["table_path"]

            if (not force) and table is not None and os.path.isfile(table):
                skipped_existing += 1
                continue

            folder = os.path.dirname(rv)
            base = os.path.basename(rv)
            prefix = base[:-len(RV_SUFFIX)]
            table_name = prefix + "_table.jpg"
            table_path = os.path.join(folder, table_name)

            rect_path = self.get_rect_json_path(rv)
            if not os.path.isfile(rect_path):
                skipped_no_rect += 1
                print(f"⚠ No rect json for {rv}")
                continue

            try:
                with open(rect_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ul = data["rect"]["ul"]
                lr = data["rect"]["lr"]
                ulx, uly = float(ul[0]), float(ul[1])
                lrx, lry = float(lr[0]), float(lr[1])
            except Exception as e:
                print(f"❌ Invalid rect in {rect_path}: {e}")
                skipped_no_rect += 1
                continue

            try:
                img = Image.open(rv)
            except Exception as e:
                print(f"❌ Failed to open {rv}: {e}")
                continue

            w, h = img.size
            x0 = max(0, min(w, ulx))
            y0 = max(0, min(h, uly))
            x1 = max(0, min(w, lrx))
            y1 = max(0, min(h, lry))

            if x1 <= x0 or y1 <= y0:
                print(f"⚠ Invalid rect for {rv} -> skipped")
                continue

            table_img = img.crop((x0, y0, x1, y1))

            # Downscale by factor of 2
            new_w = max(1, table_img.width // 2)
            new_h = max(1, table_img.height // 2)
            table_img = table_img.resize((new_w, new_h), Image.LANCZOS)

            try:
                table_img.save(table_path, quality=95)
            except Exception as e:
                print(f"❌ Failed to save {table_path}: {e}")
                continue

            self.df.at[idx, "table_path"] = table_path
            created += 1
            print(f"✔ Created: {table_path}")

        msg = (
            f"Created {created} *_table.jpg files.\n"
            f"Skipped (no valid *_rect.json): {skipped_no_rect}"
        )
        if not force:
            msg += f"\nSkipped (existing *_table.jpg): {skipped_existing}"
        else:
            msg += "\nForce mode: existing *_table.jpg were overwritten."
        messagebox.showinfo("Clip to *_table.jpg DONE", msg)


def main():
    root = tk.Tk()
    root.geometry("1600x900")
    app = ImageBrowserApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()