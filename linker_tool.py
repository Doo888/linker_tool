# -*- coding: utf-8 -*
import sys
import os
import shutil
import subprocess
import ctypes
import platform
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
from datetime import datetime
import threading
import math

# --- Dependency Check ---
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_SUPPORT = True
except ImportError:
    DND_SUPPORT = False

# --- 默认配置 ---
DEFAULT_TARGET_BASE_DIR = r"F:\AppData"
IS_WINDOWS = platform.system() == "Windows"
LOG_FILE_NAME = "linker_log.json"
CONFIG_FILE_NAME = "linker_config.json"

# --- GUI 类 ---
class FolderLinkerTkinterApp(TkinterDnD.Tk if DND_SUPPORT else tk.Tk):
    def __init__(self):
        super().__init__()

        # --- Early error handling ---
        self.initialization_error = None
        if not DND_SUPPORT:
            self.initialization_error = ("依赖缺失", "未找到 'tkinterdnd2' 库.\n请运行 'pip install tkinterdnd2-universal' 安装后重试。")

        self.title('文件夹链接与空间分析工具')
        self.geometry('900x800')

        # --- 日志和状态变量 ---
        self.log_file = LOG_FILE_NAME
        self.config_file = CONFIG_FILE_NAME
        self.linked_items = {}
        self.custom_protected_paths = []
        self.is_admin_user = self.check_admin()
        self.mode_var = tk.StringVar(value="link")
        self.target_base_dir = tk.StringVar(value=DEFAULT_TARGET_BASE_DIR)
        self.target_dir_ok = False
        self.scan_thread = None

        # --- 构建UI元素 ---
        self.paned_window = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.top_pane = ttk.Frame(self.paned_window, padding="5")
        self.paned_window.add(self.top_pane, weight=1)

        self.bottom_pane = ttk.Notebook(self.paned_window)
        self.paned_window.add(self.bottom_pane, weight=1)

        self.create_config_widgets(self.top_pane)
        self.create_main_controls_widgets(self.top_pane)
        
        scanner_tab = ttk.Frame(self.bottom_pane, padding="5")
        log_tab = ttk.Frame(self.bottom_pane, padding="5")
        self.bottom_pane.add(scanner_tab, text=' 文件夹空间分析 (AppData) ')
        self.bottom_pane.add(log_tab, text=' 日志输出 ')

        self.create_scanner_widgets(scanner_tab)
        self.create_log_widgets(log_tab)

        # --- 初始化操作 ---
        self._load_config()
        self._read_log()
        self.target_dir_ok = self.check_target_base_dir()
        self.initial_log()
        self.on_mode_change()
        style = ttk.Style(self)
        style.configure('Accent.TButton', font=('Segoe UI', 10, 'bold'), padding=6)

        # --- Deferred error showing ---
        if self.initialization_error:
            self.after(100, self.show_initialization_error)

    def show_initialization_error(self):
        title, msg = self.initialization_error
        messagebox.showerror(title, msg)
        self.destroy()

    def create_config_widgets(self, parent):
        config_frame = ttk.LabelFrame(parent, text="配置", padding="5")
        config_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(config_frame, text="目标基目录:").grid(row=0, column=0, padx=(0, 5), sticky=tk.W)
        self.target_dir_entry = ttk.Entry(config_frame, textvariable=self.target_base_dir, state='readonly', width=60)
        self.target_dir_entry.grid(row=0, column=1, padx=(0, 5), sticky=tk.EW)
        self.change_target_button = ttk.Button(config_frame, text="更改...", command=self.change_target_dir)
        self.change_target_button.grid(row=0, column=2, sticky=tk.E)

        self.edit_protected_button = ttk.Button(config_frame, text="编辑保护列表...", command=self.open_protected_paths_editor)
        self.edit_protected_button.grid(row=0, column=3, padx=(10, 0), sticky=tk.E)

        config_frame.columnconfigure(1, weight=1)

    def create_main_controls_widgets(self, parent):
        main_controls_frame = ttk.Frame(parent)
        main_controls_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_controls_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        mode_frame = ttk.LabelFrame(left_frame, text="操作模式", padding="5")
        mode_frame.pack(fill=tk.X)
        self.link_radio = ttk.Radiobutton(mode_frame, text="创建链接", variable=self.mode_var, value="link", command=self.on_mode_change)
        self.restore_radio = ttk.Radiobutton(mode_frame, text="还原链接", variable=self.mode_var, value="restore", command=self.on_mode_change)
        self.link_radio.pack(side=tk.LEFT, padx=5)
        self.restore_radio.pack(side=tk.LEFT, padx=5)

        list_frame = ttk.LabelFrame(left_frame, text="待处理文件夹列表", padding="5")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(5,0))
        
        list_buttons_frame = ttk.Frame(list_frame)
        list_buttons_frame.pack(fill=tk.X, pady=(0,5))
        self.add_button = ttk.Button(list_buttons_frame, text="添加...", command=self.add_folder_dialog)
        self.remove_button = ttk.Button(list_buttons_frame, text="移除选中", command=self.remove_selected)
        self.add_button.pack(side=tk.LEFT)
        self.remove_button.pack(side=tk.LEFT, padx=(5,0))

        list_widget_frame = ttk.Frame(list_frame)
        list_widget_frame.pack(fill=tk.BOTH, expand=True)
        self.list_scrollbar_y = ttk.Scrollbar(list_widget_frame, orient=tk.VERTICAL)
        self.list_widget = tk.Listbox(list_widget_frame, selectmode=tk.EXTENDED, yscrollcommand=self.list_scrollbar_y.set, height=10)
        self.list_scrollbar_y.config(command=self.list_widget.yview)
        self.list_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        if DND_SUPPORT:
            self.list_widget.drop_target_register(DND_FILES)
            self.list_widget.dnd_bind('<<Drop>>', self.handle_drop)

        right_frame = ttk.Frame(main_controls_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)
        self.execute_button = ttk.Button(right_frame, text="执行批量操作", command=self.execute_batch, style='Accent.TButton')
        self.execute_button.pack(expand=True, fill=tk.BOTH, ipadx=10)

    def create_scanner_widgets(self, parent):
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(5,5))
        
        self.scan_tree = ttk.Treeview(tree_frame, columns=("raw_size", "size", "path"), show="headings")
        self.scan_tree['displaycolumns'] = ('size', 'path')

        self.scan_tree.heading("size", text="大小", command=lambda: self.sort_treeview(self.scan_tree, "raw_size", False))
        self.scan_tree.heading("path", text="路径", command=lambda: self.sort_treeview(self.scan_tree, "path", False))
        
        self.scan_tree.column("size", width=120, anchor=tk.E)
        self.scan_tree.column("path", width=500)
        
        tree_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.scan_tree.yview)
        self.scan_tree.configure(yscrollcommand=tree_scrollbar.set)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.scan_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scanner_buttons_frame = ttk.Frame(parent)
        scanner_buttons_frame.pack(fill=tk.X)
        self.scan_button = ttk.Button(scanner_buttons_frame, text="开始扫描", command=self._start_scan)
        self.scan_button.pack(side=tk.LEFT)
        self.add_selected_to_list_button = ttk.Button(scanner_buttons_frame, text="添加选中到待处理", command=self.add_scanned_to_list)
        self.add_selected_to_list_button.pack(side=tk.LEFT, padx=5)
        self.scan_status_label = ttk.Label(scanner_buttons_frame, text="")
        self.scan_status_label.pack(side=tk.RIGHT, padx=5)

    def create_log_widgets(self, parent):
        log_frame = ttk.Frame(parent)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(5,0))
        
        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(fill=tk.BOTH, expand=True)
        self.log_scrollbar = ttk.Scrollbar(log_text_frame)
        self.log_area = tk.Text(log_text_frame, wrap=tk.WORD, yscrollcommand=self.log_scrollbar.set, state=tk.DISABLED, font=("Consolas", 9))
        self.log_scrollbar.config(command=self.log_area.yview)
        self.log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        log_button_frame = ttk.Frame(log_frame)
        log_button_frame.pack(fill=tk.X, pady=(5,0))
        self.open_log_button = ttk.Button(log_button_frame, text="打开日志文件", command=self.open_log_file)
        self.open_log_button.pack(side=tk.LEFT)

        self.log_area.tag_config("info", foreground="black")
        self.log_area.tag_config("warning", foreground="orange")
        self.log_area.tag_config("error", foreground="red", font=("Consolas", 9, "bold"))
        self.log_area.tag_config("success", foreground="green")
        self.log_area.tag_config("header", foreground="blue", font=("Consolas", 9, "bold"))

    def open_log_file(self):
        log_path = os.path.abspath(self.log_file)
        if not os.path.exists(log_path):
            messagebox.showinfo("文件不存在", f"日志文件 {log_path} 还未被创建。", parent=self)
            return
        try:
            if IS_WINDOWS:
                os.startfile(log_path)
            elif sys.platform == "darwin": # macOS
                subprocess.run(["open", log_path])
            else: # Linux
                subprocess.run(["xdg-open", log_path])
        except Exception as e:
            messagebox.showerror("打开失败", f"无法打开日志文件。\n错误: {e}", parent=self)

    def _load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.custom_protected_paths = config.get("custom_protected_paths", [])
                    default_dir = self.target_base_dir.get()
                    self.target_base_dir.set(config.get("target_base_dir", default_dir))
            else:
                self._save_config()
        except (json.JSONDecodeError, IOError) as e:
            self.initialization_error = ("配置错误", f"读取配置文件 {self.config_file} 失败: {e}")

    def _save_config(self):
        config = {
            "target_base_dir": self.target_base_dir.get(),
            "custom_protected_paths": self.custom_protected_paths
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except IOError as e:
            self.log(f"写入配置文件 {self.config_file} 失败: {e}", "error")

    def _read_log(self):
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    self.linked_items = json.load(f)
                self.log(f"成功加载日志文件: {self.log_file}", "info")
            else:
                self.log(f"日志文件 {self.log_file} 不存在，将自动创建。", "info")
        except (json.JSONDecodeError, IOError) as e:
            self.log(f"读取日志文件 {self.log_file} 失败: {e}", "error")
            self.linked_items = {}

    def _write_log(self):
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump(self.linked_items, f, indent=4, ensure_ascii=False)
        except IOError as e:
            self.log(f"写入日志文件 {self.log_file} 失败: {e}", "error")

    def _add_log_entry(self, source_path, target_path):
        entry = {"target": target_path, "timestamp": datetime.now().isoformat()}
        self.linked_items[source_path] = entry
        self._write_log()

    def _remove_log_entry(self, source_path):
        if source_path in self.linked_items:
            del self.linked_items[source_path]
            self._write_log()

    def check_admin(self):
        if IS_WINDOWS:
            try:
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception: return False
        else:
            return os.geteuid() == 0 if hasattr(os, 'geteuid') else False

    def check_target_base_dir(self):
        current_target_dir = self.target_base_dir.get()
        try:
            if not os.path.exists(current_target_dir):
                os.makedirs(current_target_dir)
                self.log(f"已自动创建目标基目录 '{current_target_dir}'。", "success")
            elif not os.path.isdir(current_target_dir):
                 self.log(f"错误: 目标路径 '{current_target_dir}' 已存在但不是一个目录。", "error")
                 return False
            return True
        except Exception as e:
            self.log(f"错误: 检查或创建目标基目录 '{current_target_dir}' 失败: {e}", "error")
            return False

    def process_folder_link(self, source_path):
        current_target_dir = self.target_base_dir.get()
        source_name = os.path.basename(source_path)
        target_data_path = os.path.join(current_target_dir, source_name)
        link_path = source_path
        source_path_temp_backup = source_path + "_tmp_link_backup"

        self.log(f"--- 开始处理: {source_name} ---", "header")
        
        if os.path.exists(target_data_path) or os.path.exists(source_path_temp_backup):
            self.log(f"错误: 目标路径 '{target_data_path}' 或临时备份路径已存在。", "error")
            return False

        try:
            self.log(f"1. 正在复制文件夹到 '{target_data_path}' ...", "info")
            shutil.copytree(source_path, target_data_path, symlinks=True, ignore_dangling_symlinks=True)
        except Exception as e:
            self.log(f"错误: 复制文件夹失败: {e}", "error")
            if os.path.exists(target_data_path): shutil.rmtree(target_data_path, ignore_errors=True)
            return False

        try:
            self.log("2. 正在重命名原始文件夹...", "info")
            os.rename(source_path, source_path_temp_backup)
        except Exception as e:
            self.log(f"错误: 重命名原始文件夹失败: {e}", "error")
            shutil.rmtree(target_data_path, ignore_errors=True)
            return False

        try:
            self.log("3. 正在创建符号链接...", "info")
            if IS_WINDOWS:
                subprocess.run(f'mklink /D "{link_path}" "{target_data_path}"', check=True, capture_output=True, text=True, encoding='gbk', shell=True)
            else:
                os.symlink(target_data_path, link_path, target_is_directory=True)
        except Exception as e:
            self.log(f"错误: 创建符号链接失败: {e}", "error")
            self.log("!!! 关键错误：正在回滚...", "error")
            try:
                os.rename(source_path_temp_backup, source_path)
                shutil.rmtree(target_data_path, ignore_errors=True)
                self.log("回滚成功。", "success")
            except Exception as ce:
                self.log(f"!!! 严重: 自动回滚失败: {ce}", "error")
            return False

        try:
            self.log("4. 正在清理临时备份...", "info")
            shutil.rmtree(source_path_temp_backup)
        except Exception as e:
            self.log(f"警告: 自动清理备份文件夹失败: {e}", "warning")

        self._add_log_entry(link_path, target_data_path)
        self.log(f"--- 处理成功: {source_name} ---", "success")
        return True

    def process_folder_restore(self, link_path):
        link_name = os.path.basename(link_path)
        self.log(f"--- 开始还原: {link_name} ---", "header")

        log_entry = self.linked_items.get(link_path)
        if not log_entry:
            self.log(f"错误: 在日志文件中未找到 '{link_path}' 的记录。", "error")
            return False
        
        target_data_path = log_entry['target']
        if not os.path.isdir(target_data_path):
            self.log(f"错误: 预期的数据源 '{target_data_path}' 不存在或不是目录。", "error")
            return False

        try:
            self.log(f"1. 正在删除符号链接 '{link_path}' ...", "info")
            if IS_WINDOWS: os.rmdir(link_path)
            else: os.unlink(link_path)
        except Exception as e:
            self.log(f"错误: 删除符号链接失败: {e}", "error")
            return False

        try:
            self.log(f"2. 正在将数据移回 '{link_path}' ...", "info")
            shutil.move(target_data_path, link_path)
        except Exception as e:
            self.log("!!! 关键错误：链接已删除，但数据未能移回！", "error")
            self.log(f"数据当前位于: '{target_data_path}'", "error")
            return False

        self._remove_log_entry(link_path)
        self.log(f"--- 还原成功: {link_name} ---", "success")
        return True

    def log(self, message, level="info"):
        if not hasattr(self, 'log_area'): return
        self.log_area.config(state=tk.NORMAL)
        self.log_area.insert(tk.END, f"{message}\n", level)
        self.log_area.config(state=tk.DISABLED)
        self.log_area.see(tk.END)
        self.update_idletasks()

    def initial_log(self):
        self.log("程序已启动。", "info")
        if self.is_admin_user:
            self.log("当前以管理员权限运行。", "success")
        else:
            self.log("警告：未以管理员权限运行，链接操作可能失败！", "warning")

    def change_target_dir(self):
        new_dir = filedialog.askdirectory(title="请选择新的目标基目录", mustexist=False)
        if new_dir:
            self.target_base_dir.set(new_dir)
            self.log(f"目标基目录已更改为: '{new_dir}'", "info")
            self.target_dir_ok = self.check_target_base_dir()
            self._save_config()

    def on_mode_change(self):
        mode = self.mode_var.get()
        action = "创建链接" if mode == "link" else "还原链接"
        self.execute_button.config(text=f"执行批量【{action}】")
        self.add_selected_to_list_button.config(state=tk.NORMAL if mode == 'link' else tk.DISABLED)
        if self.list_widget.size() > 0:
            if messagebox.askyesno("模式更改确认", f"切换到【{action}】模式将清空当前列表，确定吗？"):
                self.list_widget.delete(0, tk.END)
            else:
                self.mode_var.set("restore" if mode == "link" else "link")

    def is_directory_symlink(self, path):
        if not IS_WINDOWS:
            return os.path.islink(path) and os.path.isdir(path)
        else:
            if os.path.isdir(path):
                try:
                    FILE_ATTRIBUTE_REPARSE_POINT = 0x400
                    attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
                    return attributes != -1 and (attributes & FILE_ATTRIBUTE_REPARSE_POINT)
                except Exception: return False
            return False

    def _get_default_protected_paths(self):
        protected = []
        if IS_WINDOWS:
            system_drive = os.environ.get('SystemDrive', 'C:')
            protected.append(os.path.normpath(system_drive + '\\'))
            for key in ['WinDir']:
                path = os.environ.get(key)
                if path: protected.append(os.path.normpath(path))
            try:
                drives = [f"{d}:\\" for d in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' if os.path.exists(f"{d}:")]
                protected.extend([os.path.normpath(d) for d in drives])
            except Exception: pass
        else:
            protected.extend(['/', '/etc', '/bin', '/sbin', '/usr', '/var', '/root'])
            home = os.environ.get('HOME')
            if home: protected.append(os.path.normpath(home))
        return list(set(protected))

    def get_all_protected_paths(self):
        default_paths = self._get_default_protected_paths()
        return list(set(default_paths + self.custom_protected_paths))

    def _validate_and_add_path(self, path):
        path = os.path.normpath(path)
        error_msg = ""

        protected_paths = self.get_all_protected_paths()
        if path in protected_paths:
            error_msg = f"'{os.path.basename(path)}' 是一个受保护的系统关键目录。"
        else:
            for protected in protected_paths:
                if path.startswith(protected + os.sep):
                    error_msg = f"'{os.path.basename(path)}' 位于受保护的目录 '{protected}' 内。"
                    break
        
        if error_msg:
            self.log(f"添加失败: {error_msg}", "error")
            return False

        if not os.path.exists(path):
            error_msg = "路径不存在。"
        else:
            is_link = self.is_directory_symlink(path)
            is_dir = os.path.isdir(path)
            mode = self.mode_var.get()

            if mode == "link" and (not is_dir or is_link):
                error_msg = "创建模式需要一个真实的、非链接的文件夹。"
            elif mode == "restore" and not is_link:
                error_msg = "还原模式需要一个链接文件夹。"
        
        if error_msg:
            self.log(f"添加失败: {os.path.basename(path)} - {error_msg}", "warning")
            return False

        if path not in self.list_widget.get(0, tk.END):
            self.list_widget.insert(tk.END, path)
            self.log(f"已添加: {path}", "info")
            return True
        return False

    def add_folder_dialog(self):
        directory = filedialog.askdirectory(title="请选择一个文件夹")
        if directory:
            self._validate_and_add_path(directory)

    def handle_drop(self, event):
        if not DND_SUPPORT: return
        paths = self.tk.splitlist(event.data)
        for path in paths:
            self._validate_and_add_path(path)

    def remove_selected(self):
        for i in reversed(self.list_widget.curselection()):
            self.list_widget.delete(i)

    def execute_batch(self):
        items = self.list_widget.get(0, tk.END)
        if not items: return
        if not self.check_target_base_dir():
            messagebox.showerror("目标目录错误", f"目标基目录 '{self.target_base_dir.get()}' 无效。")
            return

        mode = self.mode_var.get()
        action_text = "创建链接" if mode == "link" else "还原"
        if not messagebox.askyesno("确认操作", f"确定要对列表中的 {len(items)} 个项目执行【{action_text}】操作吗？"):
            return

        self.set_controls_enabled(False)
        self.config(cursor="watch")
        
        threading.Thread(target=self._execute_batch_worker, args=(items, mode, action_text), daemon=True).start()

    def _execute_batch_worker(self, items, mode, action_text):
        success_count, fail_count = 0, 0
        process_function = self.process_folder_link if mode == "link" else self.process_folder_restore
        
        processed_items = set()
        for item in items:
            if process_function(item):
                success_count += 1
            else:
                fail_count += 1
            processed_items.add(item)
        
        self.after(10, lambda: self.finalize_batch(success_count, fail_count, processed_items, action_text))

    def finalize_batch(self, success, fail, processed_items, action_text):
        self.config(cursor="")
        self.set_controls_enabled(True)
        
        current_items = set(self.list_widget.get(0, tk.END))
        remaining_items = current_items - processed_items
        self.list_widget.delete(0, tk.END)
        for item in sorted(list(remaining_items)):
             self.list_widget.insert(tk.END, item)

        summary = f"批量【{action_text}】完成。\n成功: {success}\n失败: {fail}"
        self.log(summary, "info")
        messagebox.showinfo("处理结果", summary)

    def set_controls_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        for widget in [self.add_button, self.remove_button, self.execute_button, self.change_target_button, self.link_radio, self.restore_radio, self.scan_button, self.add_selected_to_list_button, self.edit_protected_button]:
            widget.config(state=state)

    def _start_scan(self):
        if self.scan_thread and self.scan_thread.is_alive():
            return
        self.set_controls_enabled(False)
        self.scan_status_label.config(text="扫描中...")
        self.scan_tree.delete(*self.scan_tree.get_children())
        self.scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self.scan_thread.start()

    def _get_dir_size(self, path):
        total = 0
        try:
            for entry in os.scandir(path):
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += self._get_dir_size(entry.path)
        except OSError:
            return total
        return total

    @staticmethod
    def _format_size(size_bytes):
        if size_bytes == 0: return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    def _scan_worker(self):
        user_profile = os.environ.get('UserProfile')
        if not user_profile:
            self.after(10, lambda: self.log("无法找到用户配置文件目录。", "error"))
            self.after(10, lambda: self.set_controls_enabled(True))
            return

        scan_targets = ['AppData\Local', 'AppData\LocalLow', 'AppData\Roaming']
        results = []
        for target in scan_targets:
            path = os.path.join(user_profile, target)
            if os.path.isdir(path):
                self.after(10, lambda p=path: self.scan_status_label.config(text=f"分析中: {os.path.basename(p)}..."))
                for entry in os.scandir(path):
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            total_size = self._get_dir_size(entry.path)
                            if total_size > 1024:
                                results.append((total_size, entry.path))
                        except OSError: continue
        
        results.sort(key=lambda x: x[0], reverse=True)
        self.after(10, lambda: self.update_scan_tree(results))

    def update_scan_tree(self, results):
        self.scan_tree.delete(*self.scan_tree.get_children())
        for size, path in results:
            readable_size = self._format_size(size)
            self.scan_tree.insert("", tk.END, values=(size, readable_size, path))
        self.scan_status_label.config(text="扫描完成。")
        self.set_controls_enabled(True)

    def add_scanned_to_list(self):
        for item_id in self.scan_tree.selection():
            path = self.scan_tree.item(item_id, "values")[2]
            self._validate_and_add_path(path)

    def sort_treeview(self, treeview, col, reverse):
        if col == "raw_size":
            data = [(int(treeview.set(child, col)), child) for child in treeview.get_children('')]
        else:
            data = [(treeview.set(child, col), child) for child in treeview.get_children('')]
        
        data.sort(reverse=reverse)
        for index, (val, child) in enumerate(data):
            treeview.move(child, '', index)
        
        treeview.heading(col, command=lambda: self.sort_treeview(treeview, col, not reverse))

    def open_protected_paths_editor(self):
        editor = ProtectedPathsEditor(self)
        editor.grab_set()

class ProtectedPathsEditor(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("编辑自定义保护路径")
        self.geometry("700x500")

        self.default_paths = self.parent._get_default_protected_paths()
        self.custom_paths = list(self.parent.custom_protected_paths)

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        list_frame = ttk.LabelFrame(main_frame, text="当前保护路径", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.path_listbox = tk.Listbox(list_frame, selectmode=tk.SINGLE)
        self.path_listbox.pack(fill=tk.BOTH, expand=True)

        self.populate_listbox()

        add_frame = ttk.LabelFrame(main_frame, text="添加新路径", padding=5)
        add_frame.pack(fill=tk.X)
        self.new_path_entry = ttk.Entry(add_frame, width=60)
        self.new_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        add_button = ttk.Button(add_frame, text="浏览...", command=self.add_path)
        add_button.pack(side=tk.LEFT)

        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))
        
        remove_button = ttk.Button(buttons_frame, text="移除选中 (仅限自定义)", command=self.remove_path)
        remove_button.pack(side=tk.LEFT)

        save_button = ttk.Button(buttons_frame, text="保存并关闭", command=self.save_and_close, style="Accent.TButton")
        save_button.pack(side=tk.RIGHT)
        cancel_button = ttk.Button(buttons_frame, text="取消", command=self.destroy)
        cancel_button.pack(side=tk.RIGHT, padx=5)

    def populate_listbox(self):
        self.path_listbox.delete(0, tk.END)
        for path in sorted(self.default_paths):
            self.path_listbox.insert(tk.END, path)
            self.path_listbox.itemconfig(tk.END, {'fg': 'grey', 'selectbackground': 'grey'})
        for path in sorted(self.custom_paths):
            self.path_listbox.insert(tk.END, path)

    def add_path(self):
        new_path = filedialog.askdirectory(title="请选择要保护的文件夹", mustexist=True, parent=self)
        if not new_path: return
        
        new_path = os.path.normpath(new_path)
        if new_path in self.default_paths or new_path in self.custom_paths:
            messagebox.showwarning("路径已存在", "该路径已经是受保护路径。", parent=self)
            return

        self.custom_paths.append(new_path)
        self.populate_listbox()

    def remove_path(self):
        selection_index = self.path_listbox.curselection()
        if not selection_index: return

        selected_path = self.path_listbox.get(selection_index[0])

        if selected_path in self.default_paths:
            messagebox.showerror("无法移除", "不能移除系统默认的保护路径。", parent=self)
            return
        
        if selected_path in self.custom_paths:
            self.custom_paths.remove(selected_path)
            self.populate_listbox()

    def save_and_close(self):
        self.parent.custom_protected_paths = self.custom_paths
        self.parent._save_config()
        self.parent.log("自定义保护路径已更新。", "success")
        self.destroy()

if __name__ == "__main__":
    app = FolderLinkerTkinterApp()
    app.mainloop()
