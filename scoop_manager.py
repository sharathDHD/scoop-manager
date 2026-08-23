import tkinter as tk
from tkinter import messagebox, ttk
import threading
import os
import json
import queue

import scoop_core

CACHE_FILE = "scoop_cache.json"

STATUS_INSTALLED = "Installed"
STATUS_AVAILABLE = "Available"


def get_available_apps(refresh=False):
    if not refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as cache_file:
                return json.load(cache_file)
        except (OSError, ValueError):
            pass  # corrupt cache -> refetch below
    try:
        returncode, out, err = scoop_core.run_scoop_command(*scoop_core.cmd_search()[1:])
        if returncode == 0:
            apps = [line for line in out.splitlines() if line.strip()]
            with open(CACHE_FILE, 'w') as cache_file:
                json.dump(apps, cache_file)
            return apps
        messagebox.showerror("Error", f"Failed to fetch available apps: {err}")
        return []
    except Exception as e:
        messagebox.showerror("Error", f"Failed to fetch available apps: {str(e)}")
        return []


class ScoopManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Scoop Manager")
        self.geometry("1000x700")
        self.available_apps = []
        self.installed_apps = []      # normalized dicts from scoop_core
        self.busy = False             # one background scoop job at a time
        self.log_queue = queue.Queue()
        self.create_widgets()
        self.refresh_apps()
        self.after(100, self.poll_log_queue)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def create_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(1, weight=3)

        # Search box
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(self, textvariable=self.search_var, font=('Arial', 14), width=80)
        self.search_entry.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.search_entry.bind('<KeyRelease>', self.update_app_list)

        # Sidebar - List of installed apps
        sidebar_frame = tk.Frame(self)
        sidebar_frame.grid(row=1, column=0, sticky="nswe", padx=10, pady=10)
        sidebar_frame.grid_rowconfigure(1, weight=1)

        tk.Label(sidebar_frame, text="Installed Applications", font=('Arial', 14)).pack(anchor='w')
        self.installed_apps_listbox = tk.Listbox(sidebar_frame, height=20, font=('Arial', 12))
        self.installed_apps_listbox.pack(fill='both', expand=True, pady=5)

        # Main content - List of available apps
        main_frame = tk.Frame(self)
        main_frame.grid(row=1, column=1, sticky="nswe", padx=10, pady=10)
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        self.available_apps_tree = ttk.Treeview(main_frame, columns=('Name', 'Description', 'Status'), show='headings', height=20)
        self.available_apps_tree.heading('Name', text='Name')
        self.available_apps_tree.heading('Description', text='Description')
        self.available_apps_tree.heading('Status', text='Status')
        self.available_apps_tree.column('Name', width=200)
        self.available_apps_tree.column('Description', width=400)
        self.available_apps_tree.column('Status', width=100)
        self.available_apps_tree.pack(fill='both', expand=True)

        # Log box for asynchronous command output
        log_frame = tk.LabelFrame(self, text="Output", height=140)
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 5))
        log_frame.grid_propagate(False)
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=6, state='disabled', font=('Consolas', 10), wrap='none')
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scrollbar = ttk.Scrollbar(log_frame, orient='vertical', command=self.log_text.yview)
        log_scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        # Action buttons
        button_frame = tk.Frame(self)
        button_frame.grid(row=3, column=0, columnspan=2, pady=(0, 10))

        self.install_button = tk.Button(button_frame, text="Install", command=self.install_selected_app)
        self.install_button.pack(side='left', padx=10)

        self.uninstall_button = tk.Button(button_frame, text="Uninstall", command=self.uninstall_selected_app)
        self.uninstall_button.pack(side='left', padx=10)

        self.update_button = tk.Button(button_frame, text="Update", command=self.update_selected_app)
        self.update_button.pack(side='left', padx=10)

        self.update_all_button = tk.Button(button_frame, text="Update All", command=self.update_all_apps)
        self.update_all_button.pack(side='left', padx=10)

        self.refresh_button = tk.Button(button_frame, text="Refresh", command=self.refresh_apps_threaded)
        self.refresh_button.pack(side='left', padx=10)

    # ------------------------------------------------------------------
    # Data loading / rendering
    # ------------------------------------------------------------------
    def refresh_apps(self):
        self.available_apps = get_available_apps(refresh=True)
        try:
            self.installed_apps = scoop_core.get_installed_apps()
        except scoop_core.ScoopError as exc:
            messagebox.showerror("Error", f"Failed to fetch installed apps: {exc}")
            self.installed_apps = []
        self.update_app_list()
        self.update_installed_app_list()

    def refresh_apps_threaded(self):
        def work():
            available = get_available_apps(refresh=True)
            installed = []
            error = None
            try:
                installed = scoop_core.get_installed_apps()
            except scoop_core.ScoopError as exc:
                error = str(exc)
            self.log_queue.put(('refresh_done', available, installed, error))

        self.run_busy(work)

    def update_app_list(self, event=None):
        search_query = self.search_var.get().lower()
        filtered_apps = [app.split('\t') for app in self.available_apps if search_query in app.lower()]
        self.available_apps_tree.delete(*self.available_apps_tree.get_children())
        for app in filtered_apps:
            name = app[0]
            description = app[1] if len(app) > 1 else ''
            status = STATUS_INSTALLED if scoop_core.is_installed(name, self.installed_apps) else STATUS_AVAILABLE
            self.available_apps_tree.insert('', 'end', values=(name, description, status))

    def update_installed_app_list(self):
        self.installed_apps_listbox.delete(0, tk.END)
        for app in self.installed_apps:
            label = app['name']
            if app.get('version'):
                label = f"{label}  ({app['version']})"
            self.installed_apps_listbox.insert(tk.END, label)

    # ------------------------------------------------------------------
    # Actions (all run through scoop_core on a worker thread)
    # ------------------------------------------------------------------
    def install_selected_app(self):
        selected_item = self.available_apps_tree.selection()
        if not selected_item:
            return
        app_name = self.available_apps_tree.item(selected_item, 'values')[0]
        self.run_scoop_async(scoop_core.cmd_install(app_name), f"Installing {app_name}")

    def uninstall_selected_app(self):
        selected_app = self.installed_apps_listbox.get(tk.ACTIVE)
        if not selected_app:
            return
        app_name = selected_app.split()[0]
        self.run_scoop_async(scoop_core.cmd_uninstall(app_name), f"Uninstalling {app_name}")

    def update_selected_app(self):
        selected_item = self.available_apps_tree.selection()
        if selected_item:
            app_name = self.available_apps_tree.item(selected_item, 'values')[0]
        else:
            selected_app = self.installed_apps_listbox.get(tk.ACTIVE)
            app_name = selected_app.split()[0] if selected_app else None
        if app_name:
            self.run_scoop_async(scoop_core.cmd_update(app_name), f"Updating {app_name}")

    def update_all_apps(self):
        self.run_scoop_async(scoop_core.cmd_update_all(), "Updating all apps")

    def run_scoop_async(self, argv, label):
        def work():
            scoop_core.stream_scoop_async(
                argv,
                on_line=lambda line: self.log_queue.put(('line', line)),
                on_finish=lambda rc: self.log_queue.put(('job_done', label, rc)),
            )

        self.run_busy(work)

    # ------------------------------------------------------------------
    # Background-job plumbing
    # ------------------------------------------------------------------
    def run_busy(self, work_factory):
        if self.busy:
            messagebox.showinfo("Busy", "Another operation is already running.")
            return
        self.busy = True
        self._set_buttons_state('disabled')
        threading.Thread(target=self._safe_work(work_factory), daemon=True).start()

    @staticmethod
    def _safe_work(work_factory):
        def wrapper():
            try:
                work_factory()
            except Exception as exc:  # keep Tk thread clean on surprises
                import traceback
                traceback.print_exc()

        return wrapper

    def poll_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind = item[0]
                if kind == 'line':
                    self.append_log(item[1])
                elif kind == 'job_done':
                    _, label, returncode = item
                    outcome = "finished successfully" if returncode == 0 else f"failed (exit code {returncode})"
                    self.append_log(f"[{label}] {outcome}")
                    self.finish_job()
                elif kind == 'refresh_done':
                    _, available, installed, error = item
                    if error:
                        messagebox.showerror("Error", f"Failed to fetch installed apps: {error}")
                    self.available_apps = available
                    self.installed_apps = installed
                    self.update_app_list()
                    self.update_installed_app_list()
                    self.finish_job()
        except queue.Empty:
            pass
        self.after(100, self.poll_log_queue)

    def finish_job(self):
        self.busy = False
        self._set_buttons_state('normal')

    def _set_buttons_state(self, state):
        for button in (self.install_button, self.uninstall_button,
                       self.update_button, self.update_all_button,
                       self.refresh_button):
            button.configure(state=state)

    def append_log(self, message):
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state='disabled')


if __name__ == "__main__":
    app = ScoopManagerApp()
    app.mainloop()
