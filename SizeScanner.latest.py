import os
import threading
import queue
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable, List, Tuple, Optional

# UI
import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox

# Optional pretty numbers; fall back if missing
try:
    from humanfriendly import format_size as hf_format_size
except Exception:
    hf_format_size = None

# ------------- Model

@dataclass(frozen=True)
class FileRecord:
    path: Path
    size_bytes: int

    @property
    def unit_str(self) -> str:
        return human_size(self.size_bytes)

def human_size(b: int) -> str:
    if hf_format_size:
        # SI style (KB=1,000) – closer to Windows Explorer defaults
        return hf_format_size(b, binary=False)
    # Fallback
    kb = b / 1_000
    mb = kb / 1_000
    gb = mb / 1_000
    if gb >= 1: return f"{gb:.2f} GB"
    if mb >= 1: return f"{mb:.2f} MB"
    if kb >= 1: return f"{kb:.2f} KB"
    return f"{b:.0f} B"

UNIT_SUFFIXES = ("GB", "MB", "KB", "B", "BYTE", "BYTES")

def unit_of(size_str: str) -> str:
    for u in UNIT_SUFFIXES:
        if size_str.upper().endswith(u):
            return u
    # best effort
    return size_str.split()[-1].upper() if size_str.strip() else "B"

# ------------- Scanner (multithreaded, cancellable)

class DirScanner:
    def __init__(self, roots: List[Path], max_workers: int = None):
        self.roots = roots
        self.max_workers = max_workers or min(32, (os.cpu_count() or 8) * 4)
        self._cancel = threading.Event()
        self._produced = queue.Queue(maxsize=10_000)  # backpressure
        self.files_seen = 0
        self.bytes_seen = 0
        self.errors = 0
        self._lock = threading.Lock()

    def cancel(self):
        self._cancel.set()

    def stream(self) -> Iterable[FileRecord]:
        """
        Start scanner threads; yield FileRecord as they appear.
        """
        t = threading.Thread(target=self._walk_many, daemon=True)
        t.start()
        while t.is_alive() or not self._produced.empty():
            try:
                item = self._produced.get(timeout=0.1)
            except queue.Empty:
                if self._cancel.is_set():
                    break
                continue
            if item is None:
                break
            yield item

    def _walk_many(self):
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = []
            for root in self.roots:
                futures.append(ex.submit(self._walk_one, root))
            for f in as_completed(futures):
                _ = f.result()
        # signal completion
        self._produced.put(None)

    def _walk_one(self, root: Path):
        # BFS directory walk for better parallelism
        dq: queue.Queue[Path] = queue.Queue()
        dq.put(root)
        visited_dirs = set()
        while not dq.empty() and not self._cancel.is_set():
            cur = dq.get()
            try:
                # Avoid symlink loops
                stat = os.stat(cur, follow_symlinks=False)
                key = (stat.st_dev, stat.st_ino)
                if key in visited_dirs:
                    continue
                visited_dirs.add(key)
            except Exception:
                pass
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        if self._cancel.is_set():
                            return
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                dq.put(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                size = entry.stat(follow_symlinks=False).st_size
                                rec = FileRecord(Path(entry.path), size)
                                self._produced.put(rec)  # may block (backpressure)
                                with self._lock:
                                    self.files_seen += 1
                                    self.bytes_seen += size
                        except Exception:
                            with self._lock:
                                self.errors += 1
            except Exception:
                with self._lock:
                    self.errors += 1

# ------------- ViewModel (filter/sort without rescanning)

class RecordsVM:
    def __init__(self):
        self._records: List[FileRecord] = []
        self._filtered: List[FileRecord] = []
        # filter flags
        self.allow_gb = True
        self.allow_mb = True
        self.allow_kb = True
        self.allow_b  = True
        self.desc = False

    def append(self, rec: FileRecord):
        self._records.append(rec)

    def apply(self):
        def pass_unit(r: FileRecord) -> bool:
            b = r.size_bytes
            if b >= 1_000_000_000: return self.allow_gb
            if b >= 1_000_000:     return self.allow_mb
            if b >= 1_000:         return self.allow_kb
            return self.allow_b
        self._filtered = [r for r in self._records if pass_unit(r)]
        self._filtered.sort(key=lambda r: r.size_bytes, reverse=self.desc)

    @property
    def total_count(self) -> int:
        return len(self._filtered)

    @property
    def total_bytes(self) -> int:
        return sum(r.size_bytes for r in self._filtered)

    def rows(self) -> Iterable[Tuple[str, str]]:
        for r in self._filtered:
            yield str(r.path), r.unit_str

    def clear(self):
        self._records.clear()
        self._filtered.clear()

# ------------- UI

class SizeScanner:
    def __init__(self):
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("dark-blue")
        self.root = ctk.CTk()
        self.root.title("File Size Viewer")
        self.root.geometry("675x600")
        self.root.minsize(675, 600)
        if os.path.exists("logo.ico"):
            self.root.iconbitmap("logo.ico")

        self.vm = RecordsVM()
        self.scanner: Optional[DirScanner] = None
        self.scan_thread: Optional[threading.Thread] = None
        self.is_scanning = False
        self.start_time = 0.0

        self._build_ui()

    # --- UI layout (compact, like your File-Finder-Pro)

    def _build_ui(self):
        top = ctk.CTkFrame(self.root, corner_radius=10)
        top.pack(fill="x", padx=12, pady=(12,6))

        # Row: title + theme + cancel
        title = ctk.CTkLabel(top, text="File & Folder Size Viewer", font=("Segoe UI Semibold", 20))
        title.grid(row=0, column=0, sticky="w", padx=10, pady=(8,0))

        self.theme_switch = ctk.CTkSwitch(top, text="Dark Mode", command=self._toggle_theme)
        self.theme_switch.select()
        self.theme_switch.grid(row=0, column=1, sticky="e", padx=10, pady=(8,0))

        # Row: path + browse + actions
        self.path_var = ctk.StringVar()
        self.path_entry = ctk.CTkEntry(top, textvariable=self.path_var, placeholder_text="Select a folder...", width=475)
        self.path_entry.grid(row=1, column=0, sticky="we", padx=10, pady=8)
        browse_btn = ctk.CTkButton(top, text="Browse", width=100, command=self._pick_folder)
        browse_btn.grid(row=1, column=1, sticky="e", padx=(0,10), pady=8)

        # Controls row: unit chips + sort + scan/save
        controls = ctk.CTkFrame(top, fg_color="transparent")
        controls.grid(row=2, column=0, columnspan=2, sticky="we", padx=6, pady=(0,8))
        controls.grid_columnconfigure(10, weight=1)

        self.cb_gb = ctk.CTkCheckBox(controls, text="GB", command=self._reapply)
        self.cb_mb = ctk.CTkCheckBox(controls, text="MB", command=self._reapply)
        self.cb_kb = ctk.CTkCheckBox(controls, text="KB", command=self._reapply)
        self.cb_b  = ctk.CTkCheckBox(controls, text="Bytes", command=self._reapply)
        for i, cb in enumerate((self.cb_gb, self.cb_mb, self.cb_kb, self.cb_b)):
            cb.select()
            cb.grid(row=0, column=i, padx=6)


        # Buttons row: unit chips + sort + scan/save
        btn_cmd = ctk.CTkFrame(top, fg_color="transparent")
        btn_cmd.grid(row=3, column=0, columnspan=2, sticky="we", padx=6, pady=(0,8))
        btn_cmd.grid_columnconfigure(10, weight=1)

        self.sort_btn = ctk.CTkSegmentedButton(btn_cmd, values=["Ascending","Descending"], command=self._toggle_sort)
        self.sort_btn.set("Ascending")
        self.sort_btn.grid(row=0, column=5, padx=10)

        self.scan_btn = ctk.CTkButton(btn_cmd, text="Scan", command=self._start_scan)
        self.scan_btn.grid(row=0, column=7, padx=6)
        self.cancel_btn = ctk.CTkButton(btn_cmd, text="Cancel", fg_color="#8a1e1e", hover_color="#6f1515",
                                        state="disabled", command=self._cancel_scan)
        self.cancel_btn.grid(row=0, column=8, padx=6)
        self.save_btn = ctk.CTkButton(btn_cmd, text="Save Log", state="disabled", command=self._save_log)
        self.save_btn.grid(row=0, column=9, padx=6)

        # Progress + stats
        stats = ctk.CTkFrame(self.root, corner_radius=10)
        stats.pack(fill="x", padx=12, pady=(0,6))
        self.progress = ctk.CTkProgressBar(stats)
        self.progress.set(0)  # indeterminate style simulated
        self.progress.pack(fill="x", padx=10, pady=(8,2))
        self.stats_var = ctk.StringVar(value="Ready.")
        ctk.CTkLabel(stats, textvariable=self.stats_var).pack(padx=10, pady=(0,8), anchor="w")

        # Results
        table = ctk.CTkFrame(self.root, corner_radius=10)
        table.pack(fill="both", expand=True, padx=12, pady=(0,12))

        cols = ("path", "size")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", height=18)
        self.tree.heading("path", text="Path")
        self.tree.heading("size", text="Size")
        self.tree.column("path", width=400, anchor="w")
        self.tree.column("size", width=35, anchor="center")
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # --- UI actions

    def _toggle_theme(self):
        ctk.set_appearance_mode("dark" if self.theme_switch.get() else "light")

    def _pick_folder(self):
        path = filedialog.askdirectory(title="Select folder", mustexist=True)
        if path:
            self.path_var.set(path)

    def _toggle_sort(self, *_):
        self.vm.desc = (self.sort_btn.get() == "Descending")
        self._reapply()

    def _reapply(self):
        self.vm.allow_gb = bool(self.cb_gb.get())
        self.vm.allow_mb = bool(self.cb_mb.get())
        self.vm.allow_kb = bool(self.cb_kb.get())
        self.vm.allow_b  = bool(self.cb_b.get())
        self.vm.apply()
        self._render_table()
        self._update_stats()

    def _render_table(self):
        self.tree.delete(*self.tree.get_children())
        rows = list(self.vm.rows())
        for path_str, size_str in rows:
            minus_path = self.path_var.get().replace("/", "\\")
            if minus_path.endswith("\\"):
                minus_path = minus_path[:-1]
            path_str = f"[BROWSE]{path_str.replace(minus_path, '')}"
            self.tree.insert("", "end", values=(path_str, size_str))

    def _start_scan(self):
        root_path = self.path_var.get().strip()
        if not root_path or not os.path.isdir(root_path):
            messagebox.showinfo("Select folder", "Please choose an existing folder.")
            return
        if self.is_scanning:
            return
        self.is_scanning = True
        self.scan_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.save_btn.configure(state="disabled")
        self.vm.clear()
        self._render_table()
        self._update_stats()
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.start_time = time.time()

        self.scanner = DirScanner([Path(root_path)])
        self.scan_thread = threading.Thread(target=self._consume_stream, daemon=True)
        self.scan_thread.start()
        self.root.after(125, self._poll_scanner)

    def _consume_stream(self):
        assert self.scanner is not None
        for rec in self.scanner.stream():
            if rec is None:  # end
                break
            print(rec)
            self.vm.append(rec)

    def _poll_scanner(self):
        if not self.is_scanning:
            return
        # Apply filters and update UI every tick for responsiveness
        self._reapply()
        self._update_stats()
        done = self.scan_thread is not None and not self.scan_thread.is_alive()
        if done:
            self.is_scanning = False
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(1)
            self.scan_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            self.save_btn.configure(state="normal")
            self._update_stats(final=True)
        else:
            self.root.after(250, self._poll_scanner)

    def _cancel_scan(self):
        if self.scanner:
            self.scanner.cancel()
        self.cancel_btn.configure(state="disabled")

    def _update_stats(self, final: bool=False):
        s = self.scanner
        scanned_files = s.files_seen if s else 0
        scanned_bytes = s.bytes_seen if s else 0
        errs = s.errors if s else 0
        elapsed = max(0.0, time.time() - self.start_time) if self.is_scanning or final else 0.0
        # rate = f"{human_size(int(scanned_bytes/elapsed))}/s" if elapsed > 0 and scanned_bytes>0 else "0 B/s"
        msg = (f"Found: {self.vm.total_count:,}  |  Total Size: {human_size(self.vm.total_bytes)}  "
               f"|  Scanned: {scanned_files:,} ({human_size(scanned_bytes)})  "
               f"|  Errors: {errs}  |  Elapsed: {elapsed:.1f}s")
        self.stats_var.set(msg)

    def _save_log(self):
        if self.vm.total_count == 0:
            messagebox.showinfo("Nothing to save", "No results to save. Run a scan first.")
            return
        dst = filedialog.asksaveasfilename(title="Save log", defaultextension=".txt",
                                           filetypes=[("Text", "*.txt")], initialfile="file_size_log.txt")
        if not dst:
            return
        try:
            with open(dst, "w", encoding="utf-8") as f:
                f.write(f"Root: {self.path_var.get()}\n")
                f.write(f"Sorted: {'DESC' if self.vm.desc else 'ASC'}\n")
                f.write(f"Filters: GB={self.vm.allow_gb} MB={self.vm.allow_mb} "
                        f"KB={self.vm.allow_kb} B={self.vm.allow_b}\n")
                f.write(f"Total: {self.vm.total_count} | Total Size: {human_size(self.vm.total_bytes)} "
                        f"({self.vm.total_bytes} bytes)\n\n")
                for r in self.vm._filtered:
                    f.write(f"{r.path} -> {r.unit_str} | BYTES {r.size_bytes}\n")
            messagebox.showinfo("Saved", "Log saved successfully.")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = SizeScanner()
    app.run()
