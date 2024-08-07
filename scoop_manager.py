import tkinter as tk
from tkinter import messagebox, ttk
import subprocess
import os
import json

CACHE_FILE = "scoop_cache.json"

def get_available_apps(refresh=False):
    if not refresh and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as cache_file:
            return json.load(cache_file)
    try:
        result = subprocess.run('scoop search', shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            apps = result.stdout.splitlines()
            with open(CACHE_FILE, 'w') as cache_file:
                json.dump(apps, cache_file)
            return apps
        else:
            messagebox.showerror("Error", f"Failed to fetch available apps: {result.stderr}")
            return []
    except Exception as e:
        messagebox.showerror("Error", f"Failed to fetch available apps: {str(e)}")
        return []

def get_installed_apps():
    try:
        result = subprocess.run('scoop list', shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            apps = result.stdout.splitlines()
            return apps
        else:
            messagebox.showerror("Error", f"Failed to fetch installed apps: {result.stderr}")
            return []
    except Exception as e:
        messagebox.showerror("Error", f"Failed to fetch installed apps: {str(e)}")
        return []

def install_app(app_name):
    try:
        result = subprocess.run(f'scoop install {app_name}', shell=True, check=True, capture_output=True, text=True)
        messagebox.showinfo("Success", f"{app_name} installed successfully.")
    except subprocess.CalledProcessError as e:
        messagebox.showerror("Error", f"Failed to install {app_name}: {e.stderr}")

def uninstall_app(app_name):
    try:
        result = subprocess.run(f'scoop uninstall {app_name}', shell=True, check=True, capture_output=True, text=True)
        messagebox.showinfo("Success", f"{app_name} uninstalled successfully.")
    except subprocess.CalledProcessError as e:
        messagebox.showerror("Error", f"Failed to uninstall {app_name}: {e.stderr}")

class ScoopManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Scoop Manager")
        self.geometry("1000x600")
        self.create_widgets()
        self.refresh_apps()

    def create_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(1, weight=1)

        # Search box
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(self, textvariable=self.search_var, font=('Arial', 14), width=80)
        self.search_entry.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.search_entry.bind('<KeyRelease>', self.update_app_list)

        # Sidebar - List of installed apps
        sidebar_frame = tk.Frame(self)
        sidebar_frame.grid(row=1, column=0, sticky="nswe", padx=10, pady=10)
        sidebar_frame.grid_rowconfigure(0, weight=1)

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

        # Install and uninstall buttons
        button_frame = tk.Frame(self)
        button_frame.grid(row=2, column=0, columnspan=2, pady=10)

        self.install_button = tk.Button(button_frame, text="Install", command=self.install_selected_app)
        self.install_button.pack(side='left', padx=10)

        self.uninstall_button = tk.Button(button_frame, text="Uninstall", command=self.uninstall_selected_app)
        self.uninstall_button.pack(side='left', padx=10)

        self.refresh_button = tk.Button(button_frame, text="Refresh", command=self.refresh_apps)
        self.refresh_button.pack(side='left', padx=10)

    def refresh_apps(self):
        self.available_apps = get_available_apps(refresh=True)
        self.installed_apps = get_installed_apps()
        self.update_app_list()
        self.update_installed_app_list()

    def update_app_list(self, event=None):
        search_query = self.search_var.get().lower()
        filtered_apps = [app.split('\t') for app in self.available_apps if search_query in app.lower()]
        self.available_apps_tree.delete(*self.available_apps_tree.get_children())
        for app in filtered_apps:
            self.available_apps_tree.insert('', 'end', values=(app[0], app[1] if len(app) > 1 else '', 'Installed' if app[0] in self.installed_apps else 'Available'))

    def update_installed_app_list(self):
        self.installed_apps_listbox.delete(0, tk.END)
        for app in self.installed_apps:
            self.installed_apps_listbox.insert(tk.END, app)

    def install_selected_app(self):
        selected_item = self.available_apps_tree.selection()
        if selected_item:
            app_name = self.available_apps_tree.item(selected_item, 'values')[0]
            install_app(app_name)
            self.refresh_apps()

    def uninstall_selected_app(self):
        selected_app = self.installed_apps_listbox.get(tk.ACTIVE)
        if selected_app:
            uninstall_app(selected_app)
            self.refresh_apps()

if __name__ == "__main__":
    app = ScoopManagerApp()
    app.mainloop()
