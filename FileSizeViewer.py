import os
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
from customtkinter import CTkFrame, StringVar, BooleanVar
from customtkinter import CTkButton, CTkLabel, CTkEntry, CTkScrollbar


class BackgroundProcess:

    def __init__(self):
        self.size_type: tuple = ("mb",)
        self.file: dict = {}
        self.location = None
#         (as default location)
#         self.location = f"{os.environ.get("userprofile")}\\downloads"

    @staticmethod
    def get_size(file_location: str, *, only_size: bool = False):
        value = os.path.getsize(file_location)
        if only_size:
            return value
        kb = value/1024
        mb = kb/1024
        gb = mb/1024

        if int(gb) > 0:
            return f"{gb:.2f} GB"
        elif int(mb) > 0:
            return f"{mb:.2f} MB"
        elif int(kb) > 0:
            return f"{kb:.2f} KB"
        else:
            return f"{value:.2f} BYTE"

    def find(self, get_folder: str):
        try:
            for word in os.listdir(get_folder):
                locate = f"{get_folder}/{word}".lower()
                if os.path.isfile(locate):
                    in_byte: str = self.get_size(locate, only_size=True)
                    converted: str = self.get_size(locate)
                    for i in self.size_type:
                        if converted.endswith(i.upper()):
                            self.file.update({locate: [in_byte, converted]})
                elif os.path.isdir(locate):
                    self.find(locate)
        except Exception as e:
            print(f"Find Error: {e}")
            return None

    def filter(self, size_type: tuple = ('mb',), reverse: bool = False) -> dict:
        self.size_type = size_type
        self.find(self.location.get())
        sorted_value = dict(sorted(self.file.items(), key=lambda item: item[1][0], reverse=reverse))
        return sorted_value


class FileSizeViewer(BackgroundProcess):

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode('system')
        ctk.set_default_color_theme('blue')
        self.root = ctk.CTk()
        self.root.resizable(False, False)
        self.root.title("FileSizeViewer")
        self.root.geometry("800x525")

        self.location = StringVar()
        self.byte_var = BooleanVar()
        self.kb_var = BooleanVar()
        self.mb_var = BooleanVar()
        self.gb_var = BooleanVar()
        self.sort_order = BooleanVar()
        self.frame_top = CTkFrame(self.root)
        self.frame_mid = CTkFrame(self.root)
        self.frame_bottom = CTkFrame(self.root)

        self.tree_box = None
        self.ck_btn_byte = None
        self.ck_btn_kb = None
        self.ck_btn_mb = None
        self.ck_btn_gb = None
        self.ck_btn_sort = None
        self.entry_value = None
        self.folder = None
        self.total_tag = None

    def select_type(self):
        ls = []
        ls.append("BYTES") if self.byte_var.get() else None
        ls.append("KB") if self.kb_var.get() else None
        ls.append("MB") if self.mb_var.get() else None
        ls.append("GB") if self.gb_var.get() else None
        self.size_type = tuple(ls)

    def add_list(self):
        if not os.path.exists(self.location.get()):
            return messagebox.showinfo("No folder found", "Location not found\nplease select a existing folder")
        self.file.clear()
        self.select_type()
        data = self.filter(self.size_type, self.sort_order.get())
        for item in self.tree_box.get_children():
            self.tree_box.delete(item)
        if data == {}:
            messagebox.showinfo("No data found", f"There is no data!\n try with other type.")
        self.total_tag.configure(text=f"Total: {len(data)}")
        for loc, size in data.items():
            self.tree_box.insert("", 'end', values=[loc, size[1]], tags=loc)

    def change_mode(self):
        if self.sort_order.get():
            self.ck_btn_sort.configure(text="Small-Big")
            self.sort_order.set(False)
        else:
            self.ck_btn_sort.configure(text="Big-Small")
            self.sort_order.set(True)

    def take_location(self):
        self.folder = filedialog.askdirectory(title="Select folder", mustexist=True)
        return self.location.set(self.folder)

    def save_log(self):
        diary = filedialog.askdirectory(title="Save log to...", mustexist=True)
        if not self.file:
            return messagebox.showinfo("Can't Process", "please choose a type and execute to save log")
        with open(f"{diary}/log.txt", 'w', encoding='utf-8') as log:
            log.write(f"{self.entry_value.get()}\n")
            for name, size in self.file.items():
                log.write(f'{name} -> {size[1]} | BYTES - {size[0]}\n')
                log.write("\n")
            log.write(f"\n")
            messagebox.showinfo("Log saved", "Log saved")

    def gui(self):
        self.frame_top.pack(side="top", fill="x")
        CTkLabel(self.frame_top, text="File Size Viewer", font=("Aptos", 34)).pack(side='top', anchor='n')
        CTkLabel(self.frame_top, text="Select Folder", font=("Aptos", 34)).pack(side='left', anchor='n', padx=50, pady=5)

        CTkButton(self.frame_top, text="Browser", font=("Comic", 34),
                  command=self.take_location).pack(side='right', anchor='n', padx=50, pady=5)

        self.entry_value = CTkEntry(self.root, placeholder_text="Paste / Browse folder directory",
                                    textvariable=self.location, font=('comic', 24))
        self.entry_value.pack(side='top', anchor='w', padx=50, pady=20, fill='x')

        self.frame_mid.pack(side="top", fill="x", anchor='center', padx=50)

        self.ck_btn_gb = ctk.CTkCheckBox(self.frame_mid, text="GB", variable=self.gb_var)
        self.ck_btn_gb.pack(side='right', anchor='e', padx=20, pady=10)
        self.ck_btn_mb = ctk.CTkCheckBox(self.frame_mid, text="MB", variable=self.mb_var)
        self.ck_btn_mb.pack(side='right', anchor='e', padx=20, pady=10)
        self.ck_btn_kb = ctk.CTkCheckBox(self.frame_mid, text="KB", variable=self.kb_var)
        self.ck_btn_kb.pack(side='right', anchor='e', padx=20, pady=10)
        self.ck_btn_byte = ctk.CTkCheckBox(self.frame_mid, text="BYTES", variable=self.byte_var)
        self.ck_btn_byte.pack(side='right', anchor='e', padx=20, pady=10)
        self.ck_btn_sort = ctk.CTkButton(self.frame_mid, text="Small-Big", command=self.change_mode)
        self.ck_btn_sort.pack(side='right', anchor='e', padx=20, pady=10)

        self.frame_bottom.pack(side='top', fill='both')

        self.tree_box = ttk.Treeview(self.frame_bottom, columns=("Directory", "Size"))
        self.tree_box.heading("#0", text="")
        self.tree_box.heading("#1", text="Directory", anchor='center')
        self.tree_box.heading("#2", text="Size", anchor='center')
        self.tree_box.column("#0", width=1, stretch=False)
        self.tree_box.column("#1", width=625, stretch=False)
        self.tree_box.column("#2", width=75, stretch=False)

        y_scroll = CTkScrollbar(self.frame_bottom, orientation='vertical', command=self.tree_box.yview)
        self.tree_box.configure(yscrollcommand=y_scroll.set)

        y_scroll.pack(side='right', anchor="n", fill='y')
        self.tree_box.pack()

        CTkButton(self.frame_bottom, text="Save Log", font=("Comic", 24), command=self.save_log).pack(
            side="left", anchor="w", padx=50, pady=5)
        self.total_tag = CTkLabel(self.frame_bottom, text="Total: 0", font=("Comic", 22))
        self.total_tag.pack(side="left", anchor="w", padx=50, pady=5)
        CTkButton(self.frame_bottom, text="Search", font=("Comic", 24), command=self.add_list).pack(
            side="right", anchor="e", padx=50, pady=5)

        self.root.mainloop()


if __name__ == "__main__":
    f = FileSizeViewer()
    f.gui()


