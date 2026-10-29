"""Persistent desktop game library and local artwork preparation."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from engine import Library, ROOT
from app_paths import DATA_ROOT
from gpu_policy import settings as gpu_settings, save_settings as save_gpu_settings, devices as gpu_devices
from ui_widgets import ScrollableFrame, TabNavigation, LibraryRowActions

GPU_CHOICES={'Auto · dedicated first':'auto','Dedicated GPU':'dedicated','Integrated GPU':'integrated','Windows default':'system'}


class App:
    def __init__(self, root):
        self.root, self.library = root, Library()
        self.messages = queue.Queue()
        self._asset_stats = {}
        self.library.asset_service.set_listener(
            lambda game_id, stats: self.messages.put(('asset_stats', (game_id, stats))))
        self.busy = False
        self.deleting_games = {}
        self._delete_workers = ThreadPoolExecutor(max_workers=2,thread_name_prefix='delete-game')
        self.pending_imports = deque()
        self.preparation_paused = False
        self.players = {}
        root.title('JAR Revival — Enhanced Java Games')
        root.geometry('1140x740')
        root.minsize(980, 680)
        self.bg, self.panel, self.card = '#0c121c', '#121c29', '#192636'
        root.configure(bg=self.bg)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI',10), background=self.panel, foreground='#dce7f5')
        # Clam's default active/disabled maps otherwise override the dark palette.
        style.map('.',background=[('disabled',self.panel),('active',self.card)],
                  foreground=[('disabled','#7994ac'),('active','#eff5fc')])
        style.configure('TCheckbutton',background=self.panel,foreground='#dce7f5',
                        indicatorbackground=self.card,indicatorforeground='#102720',
                        bordercolor='#617f98',lightcolor=self.card,darkcolor=self.card)
        style.map('TCheckbutton',background=[('disabled',self.panel),('active','#263649')],
                  foreground=[('disabled','#7994ac'),('active','#eff5fc')],
                  indicatorbackground=[('disabled','#263649'),('selected','#84e4c7'),('active','#354b60')],
                  indicatorforeground=[('disabled','#7994ac'),('selected','#102720')])
        style.configure('TButton',background='#263649',foreground='#dce7f5',padding=(13,9),borderwidth=0)
        style.map('TButton',background=[('active','#354b60')])
        style.configure('Accent.TButton',background='#84e4c7',foreground='#102720',font=('Segoe UI',11,'bold'))
        style.map('Accent.TButton',background=[('disabled','#263649'),('active','#a8f5df')],
                  foreground=[('disabled','#7994ac'),('!disabled','#102720')])
        style.configure('Delete.TButton',foreground='#ffb6b6')
        style.map('Delete.TButton',foreground=[('disabled','#7994ac'),('active','#ffd0d0')])
        for orientation in ('Vertical','Horizontal'):
            style.configure(orientation+'.TScrollbar',background='#4a6378',troughcolor=self.bg,
                            arrowcolor='#b7c9d9',bordercolor='#263649',lightcolor='#4a6378',darkcolor='#4a6378')
            style.map(orientation+'.TScrollbar',background=[('active','#617f98')])
        style.configure('TCombobox',fieldbackground=self.card,background='#2a3d50',foreground='#e8f1fc',arrowcolor='#91b2c6',padding=6)
        style.map('TCombobox',fieldbackground=[('readonly',self.card)],foreground=[('readonly','#e8f1fc')])
        style.configure('Treeview',background=self.panel,foreground='#dce7f5',fieldbackground=self.panel,rowheight=54,borderwidth=0,font=('Segoe UI',11))
        style.map('Treeview',background=[('selected','#254b49')],foreground=[('selected','#c4ffed')])
        style.configure('Treeview.Heading',background=self.panel,foreground='#7994ac',font=('Segoe UI',9,'bold'),padding=(10,12),borderwidth=0)
        style.configure('Horizontal.TProgressbar',background='#84e4c7',troughcolor='#243243',borderwidth=0,thickness=4)
        style.configure('TNotebook',background=self.panel,borderwidth=0)
        style.configure('TNotebook.Tab',background=self.card,foreground='#8ea5b9',padding=(16,9))
        style.map('TNotebook.Tab',background=[('selected','#254b49'),('active','#263649')],
                  foreground=[('selected','#c4ffed'),('active','#eff5fc')])
        style.configure('Content.TNotebook',background=self.panel,borderwidth=0)
        style.layout('Content.TNotebook.Tab',[])
        style.map('Treeview.Heading',background=[('active','#263649')],foreground=[('active','#eff5fc')])
        root.option_add('*TCombobox*Listbox.background',self.card)
        root.option_add('*TCombobox*Listbox.foreground','#e8f1fc')
        rail=tk.Frame(root,bg=self.bg,width=168,padx=20,pady=26)
        rail.pack(side='left',fill='y');rail.pack_propagate(False)
        tk.Label(rail,text='JAR\nREVIVAL',bg=self.bg,fg='#84e4c7',font=('Segoe UI',24,'bold'),justify='left').pack(anchor='w')
        tk.Label(rail,text='KEYPAD CLASSICS\nON YOUR DESKTOP',bg=self.bg,fg='#6e879e',font=('Segoe UI',8),justify='left').pack(anchor='w',pady=(8,32))
        tk.Label(rail,text='  ◉  Your library',bg='#1b3339',fg='#9cf0d5',font=('Segoe UI',10,'bold'),padx=10,pady=12).pack(fill='x')
        ttk.Button(rail,text='Import demo',command=self.import_demo).pack(side='bottom',fill='x',pady=(12,0))
        tk.Label(rail,text='LOCAL & PRIVATE\nNo accounts. No API fees.',bg=self.bg,fg='#6e879e',font=('Segoe UI',8),justify='left').pack(side='bottom',anchor='w')
        main=tk.Frame(root,bg=self.bg,padx=20,pady=22);main.pack(fill='both',expand=True)
        header=tk.Frame(main,bg=self.bg);header.pack(fill='x',pady=(0,20))
        self.add_button=ttk.Button(header,text='+ Add game',style='Accent.TButton',command=self.import_game)
        self.add_button.pack(side='right')
        tk.Label(header,text='Your collection',bg=self.bg,fg='#eff5fc',font=('Segoe UI',23,'bold')).pack(anchor='w')
        tk.Label(header,text='Prepared artwork. Original gameplay.',bg=self.bg,fg='#8ea5b9',font=('Segoe UI',10)).pack(anchor='w',pady=(4,0))
        body=tk.Frame(main,bg=self.bg);body.pack(fill='both',expand=True)
        body.columnconfigure(0,weight=4,minsize=260);body.columnconfigure(1,weight=6,minsize=390);body.rowconfigure(0,weight=1)
        library_card=tk.Frame(body,bg=self.panel,padx=12,pady=12);library_card.grid(row=0,column=0,sticky='nsew',padx=(0,14))
        tk.Label(library_card,text='SEARCH YOUR GAMES',bg=self.panel,fg='#7994ac',font=('Segoe UI',8,'bold')).pack(anchor='w',pady=(0,7))
        searchrow=tk.Frame(library_card,bg=self.panel);searchrow.pack(fill='x',pady=(0,8))
        self.search=tk.StringVar()
        search=tk.Entry(searchrow,textvariable=self.search,bg=self.card,fg='#dce7f5',insertbackground='white',relief='flat',font=('Segoe UI',10))
        search.pack(side='left',fill='x',expand=True,ipady=8,padx=(0,8))
        ttk.Button(searchrow,text='↻',width=2,command=self.refresh).pack(side='right')
        library_list=tk.Frame(library_card,bg=self.panel);library_list.pack(fill='both',expand=True)
        library_list.columnconfigure(0,weight=1);library_list.rowconfigure(0,weight=1)
        self.tree=ttk.Treeview(library_list,height=4,columns=('actions',),show='tree headings',selectmode='browse')
        self.tree.heading('#0',text='GAME')
        self.tree.column('#0',width=165,minwidth=1,stretch=False)
        self.tree.heading('actions',text='')
        self.tree.column('actions',width=84,minwidth=84,stretch=False)
        self.library_scrollbar=ttk.Scrollbar(library_list,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.library_scrollbar.set)
        self.tree.grid(row=0,column=0,sticky='nsew')
        self.library_scrollbar.grid(row=0,column=1,sticky='ns')
        self.row_actions=LibraryRowActions(self.tree,self.library_scrollbar,self.play_row,self.delete_row)
        tk.Label(library_card,text='Deleting a game keeps saved progress.',bg=self.panel,fg='#7994ac',font=('Segoe UI',8)).pack(pady=(8,0))
        self.tree.bind('<Double-1>',self.library_double_click)
        self.tree.bind('<<TreeviewSelect>>', self.selected)
        self.search.trace_add('write',lambda *_:self.refresh())
        detail=tk.Frame(body,bg=self.panel,padx=20,pady=16);detail.grid(row=0,column=1,sticky='nsew')
        self.detail_title=tk.StringVar(value='Select a game')
        self.detail_subtitle=tk.StringVar(value='Add your first Java ME game to get started.')
        tk.Label(detail,textvariable=self.detail_title,bg=self.panel,fg='#eff5fc',font=('Segoe UI',20,'bold'),anchor='w',justify='left',wraplength=420).pack(fill='x')
        tk.Label(detail,textvariable=self.detail_subtitle,bg=self.panel,fg='#8ea5b9',font=('Segoe UI',9),anchor='w',justify='left',wraplength=420).pack(fill='x',pady=(2,12))
        cover=tk.Frame(detail,bg=self.card,padx=14,pady=12);cover.pack(fill='x')
        preview=tk.Frame(cover,bg=self.card,width=96,height=96)
        preview.pack(side='left',padx=(0,12));preview.pack_propagate(False)
        self.cover=tk.Label(preview,text='JAR',bg=self.card,fg='#84e4c7',font=('Segoe UI',28,'bold'),width=0)
        self.cover.pack(fill='both',expand=True)
        info=tk.Frame(cover,bg=self.card);info.pack(fill='both',expand=True)
        self.cover_status=tk.StringVar(value='SAVED & READY')
        tk.Label(info,textvariable=self.cover_status,bg=self.card,fg='#84e4c7',font=('Segoe UI',9,'bold'),anchor='w').pack(fill='x')
        self.cache_info=tk.StringVar(value='No game selected')
        tk.Label(info,textvariable=self.cache_info,bg=self.card,fg='#dce7f5',font=('Segoe UI',10),anchor='w',justify='left',wraplength=280).pack(fill='x',pady=(5,4))
        self.compat=tk.StringVar(value='Compatibility: not checked')
        tk.Label(info,textvariable=self.compat,bg=self.card,fg='#8ea5b9',font=('Segoe UI',9),anchor='w',justify='left',wraplength=280).pack(fill='x')
        self.tabs=tabs=ttk.Notebook(detail,style='Content.TNotebook');tabs.pack(fill='both',expand=True)
        self.detail_views=[ScrollableFrame(tabs,bg=self.panel) for _ in range(4)]
        for view,title in zip(self.detail_views,('Play','Artwork','Compatibility','GPUs')):
            view.content.configure(padx=4,pady=10)
            tabs.add(view,text=title)
        self.tab_navigation=TabNavigation(detail,tabs,bg=self.panel)
        self.tab_navigation.pack(before=tabs,fill='x',pady=(16,8))
        play_panel,art_panel,compatibility_panel,gpu_panel=[view.content for view in self.detail_views]
        gpu_preferences=gpu_settings()
        for title,key in [('GAME PLAYBACK GPU','render_gpu'),('ARTWORK CONVERSION GPU','enhance_gpu')]:
            tk.Label(gpu_panel,text=title,bg=self.panel,fg='#7994ac',font=('Segoe UI',8,'bold')).pack(anchor='w',pady=(3,5))
            combo=ttk.Combobox(gpu_panel,values=list(GPU_CHOICES),state='readonly',width=27)
            combo.set(next(label for label,value in GPU_CHOICES.items() if value==gpu_preferences[key]));combo.pack(anchor='w',pady=(0,8))
            combo.bind('<<ComboboxSelected>>',lambda event,k=key,c=combo:self.set_gpu(k,c.get()))
            setattr(self,key,combo)
        self.gpu_inventory=tk.StringVar(value='Detecting graphics devices…')
        self.active_gpu=tk.StringVar(value='The actual playback GPU appears here after launch.')
        tk.Label(gpu_panel,textvariable=self.gpu_inventory,bg=self.panel,fg='#9db7cc',font=('Segoe UI',9),justify='left',wraplength=420).pack(anchor='w',pady=(3,5))
        tk.Label(gpu_panel,textvariable=self.active_gpu,bg=self.panel,fg='#84e4c7',font=('Segoe UI',9),justify='left',wraplength=420).pack(anchor='w')
        tk.Label(gpu_panel,text='Global settings. Playback changes apply on the next launch.\nWindows/driver overrides are reported using the actual GPU.',bg=self.panel,fg='#7994ac',font=('Segoe UI',8),justify='left',wraplength=420).pack(anchor='w',pady=(6,0))
        settings=tk.Frame(play_panel,bg=self.panel);settings.pack(fill='x',pady=(6,8));settings.columnconfigure(0,weight=1);settings.columnconfigure(1,weight=1)
        tk.Label(settings,text='DISPLAY DETAIL',bg=self.panel,fg='#7994ac',font=('Segoe UI',8,'bold')).grid(row=0,column=0,sticky='w')
        tk.Label(settings,text='DESKTOP VIEW',bg=self.panel,fg='#7994ac',font=('Segoe UI',8,'bold')).grid(row=0,column=1,sticky='w',padx=(12,0))
        self.quality=ttk.Combobox(settings,values=['Balanced · 2×','Detailed · 4×'],state='readonly',width=17)
        self.quality.set('Detailed · 4×');self.quality.grid(row=1,column=0,sticky='ew',pady=(5,0))
        self.quality.bind('<<ComboboxSelected>>',self.set_quality)
        ttk.Label(settings,text='Fit desktop height',padding=(10,8)).grid(row=1,column=1,sticky='ew',padx=(12,0),pady=(5,0))
        tk.Label(compatibility_panel,text='INTERNAL GAME PROFILE',bg=self.panel,fg='#7994ac',font=('Segoe UI',8,'bold')).pack(anchor='w',pady=(5,6))
        self.resolution=ttk.Combobox(compatibility_panel,values=['128 × 160','176 × 208','176 × 220','240 × 320','320 × 240','360 × 640'],state='readonly',width=18)
        self.resolution.set('240 × 320');self.resolution.pack(anchor='w')
        self.resolution.bind('<<ComboboxSelected>>',self.set_resolution)
        tk.Label(compatibility_panel,text='This preserves the original coordinates for game logic.\nThe desktop viewport scales the entire scene to available height.',bg=self.panel,fg='#9db7cc',font=('Segoe UI',9),justify='left').pack(anchor='w',pady=(8,16))
        tk.Label(compatibility_panel,text='RENDERER',bg=self.panel,fg='#7994ac',font=('Segoe UI',8,'bold')).pack(anchor='w',pady=(0,6))
        self.renderer=ttk.Combobox(compatibility_panel,values=['GPU · OpenGL','CPU · compatibility'],state='readonly',width=23)
        self.renderer.set('GPU · OpenGL');self.renderer.pack(anchor='w');self.renderer.bind('<<ComboboxSelected>>',self.set_renderer)
        self.execution_compatibility=tk.BooleanVar(value=False)
        ttk.Checkbutton(compatibility_panel,text='Java compatibility mode (slower)',
            variable=self.execution_compatibility,command=self.set_execution_mode).pack(anchor='w',pady=(12,0))
        tk.Label(compatibility_panel,text='For games that stop responding during scene changes. Applies on the next launch.',
            bg=self.panel,fg='#9db7cc',font=('Segoe UI',9),justify='left',wraplength=420).pack(anchor='w',pady=(4,0))
        self.remove_wrappers=tk.BooleanVar(value=False)
        self.wrapper_option=ttk.Checkbutton(compatibility_panel,text='Skip promotional startup screens (optional)',
            variable=self.remove_wrappers,command=self.set_startup_cleanup)
        self.wrapper_option.pack(anchor='w',pady=(12,0))
        self.startup_info=tk.StringVar(value='Original game startup is used by default.')
        tk.Label(compatibility_panel,textvariable=self.startup_info,bg=self.panel,fg='#9db7cc',font=('Segoe UI',9),
            justify='left',wraplength=420).pack(anchor='w',pady=(5,0))
        self.handling_info=tk.StringVar(value='Game handling analysis appears after selection.')
        tk.Label(compatibility_panel,textvariable=self.handling_info,bg=self.panel,fg='#9db7cc',font=('Segoe UI',9),justify='left',wraplength=420).pack(anchor='w',pady=(9,0))
        tk.Label(play_panel,text='All artwork scales together. Width follows height; proportions stay intact.',bg=self.panel,fg='#7994ac',font=('Segoe UI',8),anchor='w',wraplength=420).pack(fill='x')
        actions=tk.Frame(play_panel,bg=self.panel);actions.pack(fill='x',pady=(14,10))
        self.play_button=ttk.Button(actions,text='▶  Play enhanced',style='Accent.TButton',command=self.play);self.play_button.pack(side='left',fill='x',expand=True,padx=(0,8))
        ttk.Button(actions,text='Compare original',command=lambda:self.play(True)).pack(side='left')
        self.metrics=tk.StringVar(value='Live performance appears while a game is running.')
        tk.Label(play_panel,textvariable=self.metrics,bg=self.panel,fg='#9db7cc',font=('Segoe UI',9),anchor='w',wraplength=420).pack(fill='x',pady=(0,8))
        tk.Label(art_panel,text='Artwork is prepared in batches when you are not playing. During play, small jobs wait for performance headroom. Saved results are reused.',bg=self.panel,fg='#9db7cc',font=('Segoe UI',9),justify='left',anchor='w',wraplength=420).pack(fill='x',pady=(5,14))
        options=tk.Frame(art_panel,bg=self.panel);options.pack(fill='x',pady=(6,0))
        tk.Label(options,text='ARTWORK STYLE',bg=self.panel,fg='#7994ac',font=('Segoe UI',8,'bold')).pack(anchor='w',pady=(0,5))
        convert=tk.Frame(options,bg=self.panel);convert.pack(fill='x')
        from ai_backend import available
        self.backend=ttk.Combobox(convert,values=['Fast pixel','AI cartoon'],state='readonly',width=12)
        self.backend.set('AI cartoon' if available() else 'Fast pixel');self.backend.pack(side='left',padx=(0,8))
        ttk.Button(convert,text='Prepare',command=self.prepare_style).pack(side='right')
        links=tk.Frame(art_panel,bg=self.panel);links.pack(fill='x',pady=(14,0))
        ttk.Button(links,text='Saved files & logs',command=self.open_folder).pack(side='left',padx=(0,8))
        ttk.Button(links,text='AI setup',command=self.install_ai).pack(side='left')
        self.status = tk.StringVar(value='Add a .jar file to begin, or import the included demo.')
        footer=tk.Frame(main,bg=self.bg);footer.pack(side='bottom',before=body,fill='x',pady=(10,0))
        background=tk.Frame(footer,bg=self.bg);background.pack(fill='x',pady=(0,6))
        self.preparation_info=tk.StringVar(value='Artwork cache is ready.')
        tk.Label(background,textvariable=self.preparation_info,bg=self.bg,fg='#7994ac',font=('Segoe UI',9),anchor='w').pack(side='left',fill='x',expand=True)
        self.pause_button=ttk.Button(background,text='Pause background',command=self.toggle_preparation)
        self.pause_button.pack(side='right')
        tk.Label(footer,textvariable=self.status,bg=self.bg,fg='#b7c9d9',font=('Segoe UI',9),anchor='w',wraplength=880).pack(fill='x')
        self.progress=ttk.Progressbar(footer,mode='indeterminate');self.progress.pack(fill='x',pady=(8,10))
        tk.Label(footer,text='MOVE  ↑ ↓ ← →     SELECT  Enter     SOFTKEYS  Q / W     •     Live artwork waits for stable captures and performance headroom',bg=self.bg,fg='#6e879e',font=('Segoe UI',8),anchor='w').pack(fill='x')
        self._last_metrics=0
        self._preview_key=None
        self.refresh()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(120, self.poll)
        root.after(1500, self.capture_tick)
        threading.Thread(target=self.detect_gpus,daemon=True).start()
        threading.Thread(target=self.bootstrap_asset_service,daemon=True).start()

    def bootstrap_asset_service(self):
        from runtime_assets.contracts import Recipe
        from runtime_assets.store import AssetStore
        for metadata_path in self.library.rendered.glob('*/game.json'):
            try:
                # Serialize recovery with import/deletion. Recheck a path captured
                # by the initial scan so a removed game cannot be registered again.
                with self.library.lock:
                    if metadata_path.parent.name.startswith('.') or metadata_path.parent.name in getattr(self.library,'_deleting',set()):continue
                    if not metadata_path.is_file():continue
                    game=json.loads(metadata_path.read_text(encoding='utf-8'))
                    recipe_key=game.get('recipe_key')
                    if not recipe_key:
                        continue
                    raw=AssetStore(metadata_path.parent).recipe_json(recipe_key)
                    if raw is None:
                        continue
                    recipe=Recipe.from_json(raw)
                    ai_recipe=recipe if recipe.algorithm=='realesrgan-x4plus-anime' else None
                    self.library.asset_service.register_game(
                        metadata_path.parent,recipe,game=game,ai_recipe=ai_recipe,
                        queue_missing=False,paused=True)
            except Exception as error:
                self.messages.put(('background_status',f'Artwork cache recovery skipped: {error}'))

    def close(self):
        self._delete_workers.shutdown(wait=False)
        self.library.asset_service.close(timeout=1.0)
        self.root.destroy()

    def detect_gpus(self):
        try:
            found=gpu_devices()
            text='\n'.join(f"{device['kind'].capitalize()}: {device['name']}" for device in found) or 'No Vulkan devices detected. Playback depends on the Windows graphics driver.'
            self.messages.put(('gpu_inventory',text))
        except Exception as error:self.messages.put(('gpu_inventory',f'GPU detection unavailable: {error}'))

    def set_gpu(self,key,label):
        save_gpu_settings(**{key:GPU_CHOICES[label]})
        self.status.set('GPU preference saved. Playback applies on next launch; conversion applies to the next artwork batch.')

    def refresh(self):
        selection = self.tree.selection()
        selected = selection[0] if selection else None
        scroll_position=self.tree.yview()[0]
        self.games = {game['id']: game for game in self.library.games() if game['id'] not in self.deleting_games}
        for game_id, stats in self._asset_stats.items():
            if game_id in self.games:
                self.games[game_id]['asset_work'] = stats
        query=self.search.get().strip().casefold()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for key, game in self.games.items():
            if not query or query in game['name'].casefold():
                self.tree.insert('', 'end', iid=key, text=game['name'], values=('',''))
        visible=self.tree.get_children()
        if selected in visible:
            self.tree.selection_set(selected)
            self.tree.yview_moveto(scroll_position)
        elif visible:
            self.tree.selection_set(visible[0])
        else:
            self.detail_title.set('No games found')
            self.detail_subtitle.set('Add a Java ME game to your collection.')
            self.cache_info.set('No game selected')
            self.compat.set('Saved progress is retained when a game is deleted.')
            self.cover_status.set('YOUR LIBRARY')
            self.cover.configure(image='',text='JAR',width=0)
            self._preview_key=None
            self.metrics.set('Select a game to play.')
            self.handling_info.set('Game handling analysis appears after selection.')
            self.play_button.configure(state='disabled')
        self._update_row_actions()

    def _update_row_actions(self):
        self.row_actions.set_enabled(not self.busy and not self.pending_imports)
        self.row_actions.schedule()

    def play_row(self,identity):
        if identity not in self.games or not self.tree.exists(identity):return
        self.tree.selection_set(identity);self.selected();self.play()

    def library_double_click(self,event):
        if self.tree.identify_region(event.x,event.y)=='tree':
            identity=self.tree.identify_row(event.y)
            if identity:self.play_row(identity)
        return 'break'

    def delete_row(self,identity):
        if identity not in self.games or not self.tree.exists(identity):return
        self.tree.selection_set(identity);self.selected();self.delete_game()

    def game(self):
        if self.busy:
            self.status.set('Finish the current library operation before changing a game.')
            return None
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('Choose a game', 'Select a game in your library first.')
            return None
        return self.games[selected[0]]

    def selected(self, event=None):
        self._update_row_actions()
        selected = self.tree.selection()
        if selected and selected[0] in self.games:
            game = self.games[selected[0]]
            self.resolution.set(f"{game['width']} × {game['height']}")
            self.quality.set('Detailed · 4×' if game.get('render_scale',4)==4 else 'Balanced · 2×')
            self.renderer.set('CPU · compatibility' if game.get('renderer')=='cpu' else 'GPU · OpenGL')
            self.execution_compatibility.set(game.get('execution_mode','normal') in ('compatible','interpreted'))
            from startup_cleaner import supports_cleanup
            supported=supports_cleanup(game['id'])
            self.remove_wrappers.set(bool(game.get('remove_startup_wrappers',False)))
            self.wrapper_option.configure(state='normal' if supported else 'disabled')
            self.startup_info.set(('Verified MobileRated / HOVR repair available. Original JAR is preserved.'
                if supported else 'No verified wrapper repair for this file. Original startup is retained.')+
                ('\nNext launch skips promotional startup screens.' if supported and self.remove_wrappers.get() else ''))
            self.backend.set('AI cartoon' if game.get('backend')=='ai' else 'Fast pixel')
            self.detail_title.set(game['name'])
            self.detail_subtitle.set(f"{game.get('vendor','Java ME')}  ·  Desktop height · Original proportions")
            folder=self.library.workspace(game['id'])
            work=game.get('asset_work',{})
            count=0
            waiting=0
            if work:
                count=work.get('READY',0);waiting=work.get('QUEUED',0)+work.get('DEFERRED',0)
                active=work.get('RUNNING',0);failed=work.get('FAILED',0)
                self.cache_info.set(f'{count} enhanced · {waiting} waiting · {active} active'+(f' · {failed} need attention' if failed else ''))
                live=work.get('live_reason') if work.get('player_active') else None
                self.preparation_info.set(f"Artwork: {count} ready · {waiting} waiting · {active} active"+
                    (f' · {failed} failed' if failed else '')+(f'\nLive artwork: {live}' if live else '')+
                    (f"\n{work['resource_reason']}" if work.get('resource_reason') else ''))
            else:
                count=len(list(self.library.texture_dir(folder,game.get('backend','pixel')).glob('*.png')))
                self.cache_info.set(f'{count} enhanced image'+('s' if count!=1 else '')+' saved  ·  '+('AI cartoon' if game.get('backend')=='ai' else 'Fast pixel'))
            inspection=game.get('graphics_inspection',{})
            strategy=inspection.get('handling_plan',{}).get('primary_strategy','unknown')
            labels={'packed_2d_with_custom_decoding':'Packed 2D graphics · decoder/source tracking needed',
                    'mixed_2d_sources_and_decoding':'Mixed 2D images and decoding · tracked sources use HD',
                    'source_images_and_regions':'Source images and sprite regions · preserve sheet coordinates',
                    'source_images':'Source-image replacement',
                    '3d_or_mixed_2d_3d':'3D or mixed rendering · dedicated 3D enhancement needed',
                    'unknown':'Unknown drawing path · runtime tracing needed'}
            decoding=game.get('asset_decoding',{})
            handling=('Common image resources prepared · runtime discovery is enabled for other decoded artwork'
                      if decoding.get('decision')=='standard-images' else
                      'Unknown archive data · runtime discovery will observe artwork after game decoding'
                      if decoding.get('decision') in ('unknown','unresolved-pixel-path') else labels.get(strategy,strategy))
            self.handling_info.set('HANDLING: '+handling+'\nFull gameplay coverage is not verified.')
            partial=inspection.get('packed_graphics_likely',False) or decoding.get('decision') in ('unknown','unresolved-pixel-path')
            sources=work.get('sources',game.get('assets',0)) if work else game.get('assets',0)
            self.cover_status.set((f'{sources} SOURCES · {count} HD READY' if sources else 'READY TO PLAY')+
                                  (f' · {waiting} WAITING' if waiting else ''))
            self.play_button.configure(text='▶  Play enhanced',state='normal')
            self.compat.set(('Coverage is partial · additional artwork may appear after the game decodes it' if partial else
                             'Prepared sources and runtime-discovered artwork share one cache. Gameplay coverage is not yet measured.')+
                            '\nCompatibility: '+game.get('compatibility','not verified for all gameplay'))
            if self._preview_key!=game['id']:
                self._preview_key=game['id']
                self.cover.configure(image='',text='JAR',width=0)
                try:
                    from PIL import Image,ImageTk,ImageOps
                    catalogue=json.loads((folder/'catalogue.json').read_text(encoding='utf-8'))
                    icon=game.get('manifest',{}).get('MIDlet-Icon','').lstrip('/')
                    record=next(row for row in catalogue if row['resource'].lstrip('/')==icon)
                    path=self.library.texture_dir(folder,game.get('backend','pixel'))/(record['image_id']+'.png')
                    if not path.exists(): path=folder/'original-assets'/(record['image_id']+'.png')
                    with Image.open(path) as image:
                        thumb=ImageOps.contain(image.convert('RGBA'),(88,88),Image.Resampling.LANCZOS)
                    plate=Image.new('RGBA',(96,96),self.card)
                    plate.alpha_composite(thumb,((96-thumb.width)//2,(96-thumb.height)//2))
                    self._cover_image=ImageTk.PhotoImage(plate)
                    self.cover.configure(image=self._cover_image,text='',width=0)
                except (OSError,ValueError,StopIteration,KeyError):
                    pass

    def delete_game(self):
        if self.busy or self.pending_imports:
            self.status.set('Finish the current library operation before deleting a game.')
            return
        game=self.game()
        if game is None:return
        old=self.players.get(game['id'])
        if old and old[0].poll() is None:
            messagebox.showinfo('Game is running','Close this game before deleting it so its saves can finish writing.')
            return
        if not messagebox.askyesno('Delete game?',
                f"Delete {game['name']} from your collection?\n\n"
                'Removes the imported JAR, artwork, caches and logs.\n'
                'Keeps all saved progress. Import the same JAR again to reuse it.',parent=self.root):return
        self.deleting_games[game['id']]=game
        self.refresh()
        self._update_row_actions()
        self.status.set(f'Deleting {len(self.deleting_games)} game(s) in background. Saved progress is kept.')
        def worker():
            try:
                self.library.delete_game(game['id'])
                self.messages.put(('deleted',game))
            except Exception as error:
                self.messages.put(('delete_error',(game,str(error))))
        self._delete_workers.submit(worker)

    def set_quality(self,event=None):
        game=self.game()
        if not game:return
        old=self.players.get(game['id'])
        if old and old[0].poll() is None:
            messagebox.showinfo('Game is running','Close the player before changing display detail.')
            self.selected();return
        game['render_scale']=4 if self.quality.get().startswith('Detailed') else 2
        self.library.save(game)
        self.status.set('Display detail saved. Existing 4× artwork will be reused; no conversion is required.')

    def set_renderer(self,event=None):
        game=self.game()
        if not game:return
        old=self.players.get(game['id'])
        if old and old[0].poll() is None:
            messagebox.showinfo('Game is running','Close the player before changing the renderer.');self.selected();return
        game['renderer']='cpu' if self.renderer.get().startswith('CPU') else 'gpu'
        self.library.save(game)
        self.status.set('Renderer saved. The next launch uses this setting.')

    def set_execution_mode(self):
        game=self.game()
        if not game:return
        player=self.players.get(game['id'])
        if player and player[0].poll() is None:
            messagebox.showinfo('Game is running','Close the player before changing Java compatibility mode.')
            self.selected();return
        game['execution_mode']='compatible' if self.execution_compatibility.get() else 'normal'
        self.library.save(game)
        self.status.set('Java execution setting saved for this game. Applies on the next launch; prepared artwork is reused.')

    def set_startup_cleanup(self):
        game=self.game()
        if not game:return
        game['remove_startup_wrappers']=bool(self.remove_wrappers.get())
        self.library.save(game);self.selected()
        self.status.set('Startup option saved. Applies next time you play; saved artwork is reused.')

    def toggle_preparation(self):
        self.preparation_paused=not self.preparation_paused
        self.pause_button.configure(text='Resume background' if self.preparation_paused else 'Pause background')
        if self.preparation_paused:
            self.library.asset_service.pause_all()
        else:
            self.library.asset_service.resume_all()
        self.preparation_info.set('Preparation paused after current images finish.' if self.preparation_paused else 'Preparation resumed.')

    def set_resolution(self, event=None):
        game = self.game()
        if game:
            if game['id'] in self.players and self.players[game['id']][0].poll() is None:
                messagebox.showinfo('Game is running', 'Close the game before changing its phone screen size.')
                self.selected()
                return
            game['width'], game['height'] = map(int, self.resolution.get().split(' × '))
            game['screen_source']='manual'
            self.library.save(game)
            self.refresh()

    def import_demo(self):
        demo = ROOT / 'fixtures' / 'RevivalDemo.jar'
        if demo.exists():
            self.import_game(demo)
        else:
            messagebox.showerror('Demo not built', 'Run python tools/build.py to build the player and demo.')

    def import_game(self, path=None):
        path = path or filedialog.askopenfilename(title='Choose a Java ME game JAR', filetypes=[('Java ME game', '*.jar')])
        if not path:
            return
        backend = 'ai' if self.backend.get() == 'AI cartoon' else 'pixel'
        self.pending_imports.append((path,backend))
        self.status.set(f'Queued {os.path.basename(path)}. You can add more games while preparation finishes.')
        self.start_pending()

    def start_pending(self):
        if self.busy:return
        if not self.pending_imports or any(p.poll() is None for p,_ in self.players.values()):return
        path,backend=self.pending_imports.popleft()
        self.busy=True
        self.status.set(f'Preparing {os.path.basename(path)} · {len(self.pending_imports)} more games queued')
        self.progress.start()
        def worker():
            try:
                game = self.library.import_game(path, lambda msg: self.messages.put(('status', msg)), backend)
                self.messages.put(('imported', game))
            except Exception as error:
                self.messages.put(('error', str(error)))
            finally:
                self.messages.put(('idle', None))
        threading.Thread(target=worker, daemon=True).start()

    def install_ai(self):
        if self.busy: return
        self.busy=True
        self.progress.start()
        def worker():
            try:
                from tools.setup_ai import install
                install(lambda msg:self.messages.put(('status',msg)))
            except Exception as error:
                self.messages.put(('error',str(error)))
            finally:
                self.messages.put(('idle',None))
        threading.Thread(target=worker,daemon=True).start()

    def prepare_style(self):
        if self.busy: return
        game=self.game()
        if not game: return
        old=self.players.get(game['id'])
        if old and old[0].poll() is None:
            messagebox.showinfo('Game is running','Close the player before changing its artwork style.')
            return
        backend='ai' if self.backend.get()=='AI cartoon' else 'pixel'
        self.busy=True; self.progress.start()
        def worker():
            try:
                game_ready=self.library.prepare_style(game,backend,lambda msg:self.messages.put(('status',msg)))
                self.messages.put(('imported',game_ready))
            except Exception as error:
                self.messages.put(('error',str(error)))
            finally:
                self.messages.put(('idle',None))
        threading.Thread(target=worker,daemon=True).start()

    def play(self, original=False):
        if self.busy:
            self.status.set('Finish preparing artwork before starting the player.')
            return
        game = self.game()
        if not game:
            return
        self.launch_game(game,original)

    def launch_game(self,game,original=False):
        try:
            old = self.players.get(game['id'])
            if old and old[0].poll() is None:
                messagebox.showinfo('Already running', 'This game is already open. Close its player window before launching it again.')
                return
            process,log=self.library.launch(game, original)
            self.players[game['id']] = (process,log)
            try:
                self.library.asset_service.set_player_state(game['id'],True,log.with_suffix('.stats.json'),
                                                            allow_live=not self.preparation_paused)
            except KeyError:
                pass
            hint=' '+game.get('startup_hint','')
            self.status.set(f"Playing {game['name']}. Small live image jobs need fresh frame and input headroom; larger work waits until play ends."+hint)
        except Exception as error:
            try:self.library.asset_service.set_player_state(game['id'],False)
            except KeyError:pass
            if not any(process.poll() is None for process,_ in self.players.values()) and not self.preparation_paused:
                self.library.asset_service.resume_all()
            messagebox.showerror('Could not start game', str(error))

    def open_folder(self):
        game = self.game()
        if game:
            os.startfile(self.library.workspace(game['id']))

    def capture_tick(self):
        if self.preparation_paused:
            self.library.asset_service.pause_all()
        else:
            self.library.asset_service.resume_all()
        active={key:(process,log) for key,(process,log) in self.players.items() if process.poll() is None}
        for game_id in list(self.games):
            player=active.get(game_id)
            try:
                self.library.asset_service.set_player_state(
                    game_id,player is not None,player[1].with_suffix('.stats.json') if player else None,
                    allow_live=not self.preparation_paused)
            except KeyError:
                # Startup metadata can appear in the UI before background registration finishes.
                pass
        self.root.after(1500,self.capture_tick)

    def poll(self):
        # Drain bursts without spending the entire UI tick on progress messages.
        for _ in range(100):
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == 'status':
                self.status.set(value+(f' · {len(self.pending_imports)} games queued' if self.pending_imports else ''))
            elif kind == 'background_status':
                self.preparation_info.set(value)
            elif kind == 'asset_stats':
                game_id,stats=value
                if game_id not in self.games:continue
                self._asset_stats[game_id]=stats
                if game_id in self.games:
                    self.games[game_id]['asset_work']=stats
                selection=self.tree.selection()
                if selection and selection[0]==game_id:
                    self.selected()
            elif kind == 'gpu_inventory':
                self.gpu_inventory.set(value)
            elif kind == 'imported':
                self.search.set('')
                self.refresh()
                self.tree.selection_set(value['id'])
                self.tree.see(value['id'])
                self.status.set(f"{value['name']} is ready to play. Artwork preparation continues in the background.")
            elif kind == 'deleted':
                self.deleting_games.pop(value['id'],None)
                self._asset_stats.pop(value['id'],None)
                self.players.pop(value['id'],None)
                self._preview_key=None
                self.refresh()
                self.status.set(f"{value['name']} deleted. Saved progress kept."+
                    (f' {len(self.deleting_games)} deletion(s) pending.' if self.deleting_games else ''))
            elif kind == 'delete_error':
                failed,error=value
                self.deleting_games.pop(failed['id'],None)
                self.refresh()
                self.status.set((f"{failed['name']} restored after a deletion error." if failed['id'] in self.games else
                                 f"{failed['name']} deletion failed; recovery files have been retained.")+' Saved progress is kept.')
                messagebox.showerror('Could not delete game',error,parent=self.root)
            elif kind == 'idle':
                self.busy = False
                self.progress.stop()
                self.refresh()
            elif kind == 'error':
                self.status.set('Preparation failed. Your original file has not been changed.')
                messagebox.showerror('Preparation failed', value)
            elif kind == 'refresh':
                self.refresh()
        if time.monotonic()-self._last_metrics>1:
            self._last_metrics=time.monotonic()
            self.update_telemetry()
        for key, (process, log) in list(self.players.items()):
            result = process.poll()
            if result is not None:
                del self.players[key]
                try:self.library.asset_service.set_player_state(key,False)
                except KeyError:pass
                if result:
                    reason = ('The GPU player could not continue. Try CPU · compatibility in the Compatibility tab, or check your graphics driver.'
                              if result == 71 else 'The game could not continue. Its diagnostic log may show a compatibility error.'
                              if result == 72 else f'The player exited with code {result}.')
                    messagebox.showerror('Player stopped', f'{reason}\n\nDetails: {log}')
        self.start_pending()
        self._update_row_actions()
        self.root.after(120, self.poll)

    def update_telemetry(self):
        selection=self.tree.selection()
        if not selection:return
        key=selection[0]
        active=self.players.get(key)
        if not active or active[0].poll() is not None:
            self.metrics.set('Saved artwork is reused. Temporary resized sprites do not need AI conversion.')
            return
        _,log=active
        try:
            report=json.loads(Path(str(log.with_suffix('.stats.json'))+'.gpu.json').read_text(encoding='utf-8'))
            suffix='' if report.get('matched',True) else '\nWindows selected a different GPU from the requested preference.'
            self.active_gpu.set('Actual playback: '+report['device']+suffix)
        except (OSError,ValueError,KeyError):pass
        try:
            metrics=json.loads(log.with_suffix('.stats.json').read_text(encoding='utf-8'))
            if time.time()-metrics['updated']<4:
                live=self.games.get(key,{}).get('asset_work',{}).get('live_reason')
                scaler=metrics.get('fast_scaler_submit_ms',0.0)
                detail=f"{metrics.get('backend','Player')}  ·  {metrics['fps']:.1f} game FPS\nInput queue p95 {metrics['input_queue_p95_ms']:.1f} ms  ·  {metrics['scale']}× detail, desktop fit"
                if scaler:detail+=f'\nGPU scaler CPU submission {scaler:.2f} ms (last texture)'
                if metrics.get('gpu_scale_fallbacks',0):
                    detail+='\nGPU filter fallback is in use; details are in the player log.'
                elif metrics.get('gpu_scale_passes',0):
                    detail+='\nLive GPU filter active; detailed artwork prepares in the background.'
                self.metrics.set(detail+(f'\nLive artwork: {live}' if live else ''))
            else:self.metrics.set('Waiting for screen updates; menus may redraw only after input.')
        except (OSError,ValueError,KeyError):
            self.metrics.set('Player starting… waiting for frame measurements.')
        try:
            with log.open('rb') as file:
                file.seek(0,2);end=file.tell();file.seek(max(0,end-8192));text=file.read().decode('utf-8',errors='replace')
            if 'Exception in thread' in text or 'MIDlet event failed' in text:
                self.compat.set('Compatibility: an error was detected — see saved logs')
        except OSError:pass


def main():
    # A second launcher could otherwise keep converting on the same GPU during play.
    import msvcrt
    lock_path=DATA_ROOT/'library/.launcher.lock'
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open('a+b') as lock:
        lock.seek(0,2)
        if not lock.tell():lock.write(b'1');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            notice=tk.Tk();notice.withdraw()
            messagebox.showinfo('JAR Revival is already open','Use the existing JAR Revival window. Only one library runs at a time to avoid competing conversion jobs.')
            notice.destroy();return
        root=tk.Tk()
        App(root)
        root.mainloop()


if __name__ == '__main__':
    main()
