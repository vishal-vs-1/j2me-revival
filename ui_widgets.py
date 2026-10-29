"""Small reusable Tk containers; scrolling is independent of library/game logic."""
import tkinter as tk
from tkinter import ttk


class HoverLabel:
    def __init__(self,widget,text):
        self.widget,self.text=widget,text
        self.pending=None;self.window=None
        widget.bind('<Enter>',self.schedule,add='+')
        for event in ('<Leave>','<ButtonPress>','<Destroy>'):
            widget.bind(event,self.hide,add='+')

    def schedule(self,event=None):
        self.hide();self.pending=self.widget.after(500,self.show)

    def show(self):
        self.pending=None
        if not self.widget.winfo_exists():return
        self.window=tk.Toplevel(self.widget);self.window.overrideredirect(True)
        label=tk.Label(self.window,text=self.text,bg='#263649',fg='#eff5fc',
                       font=('Segoe UI',9),padx=8,pady=5,relief='solid',borderwidth=1)
        label.pack();self.window.update_idletasks()
        x=min(self.widget.winfo_rootx(),self.widget.winfo_screenwidth()-self.window.winfo_reqwidth()-8)
        y=self.widget.winfo_rooty()+self.widget.winfo_height()+5
        if y+self.window.winfo_reqheight()>self.widget.winfo_screenheight():
            y=self.widget.winfo_rooty()-self.window.winfo_reqheight()-5
        self.window.geometry(f'+{max(0,x)}+{max(0,y)}')

    def hide(self,event=None):
        if self.pending is not None:
            self.widget.after_cancel(self.pending);self.pending=None
        if self.window is not None:self.window.destroy();self.window=None


class LibraryRowActions:
    """Visible row buttons follow the tree's layout and scrolling."""
    def __init__(self,tree,scrollbar,on_play,on_delete):
        self.tree,self.scrollbar=tree,scrollbar
        self.callbacks=(on_play,on_delete)
        self.buttons={};self.enabled=True;self.pending=None
        self.icons=[self._icon('play','#102720'),self._icon('delete','#ffb6b6')]
        tree.configure(yscrollcommand=self._scrolled)
        tree.bind('<Configure>',self.schedule,add='+')
        tree.bind('<Destroy>',self._destroy,add='+')
        tree.bind('<Button-1>',self._block_resize,add='+')
        tree.bind('<B1-Motion>',self._block_resize,add='+')
        tree.bind('<Motion>',self._separator_cursor,add='+')

    def _icon(self,kind,color):
        icon=tk.PhotoImage(master=self.tree,width=18,height=18)
        if kind=='play':
            for x in range(5,14):
                half=int((13-x)*0.65)
                icon.put(color,to=(x,9-half,x+1,10+half))
        else:
            for box in [(4,4,14,6),(7,2,11,4),(5,7,6,15),(12,7,13,15),
                        (5,14,13,15),(8,8,9,13),(10,8,11,13)]:icon.put(color,to=box)
        return icon

    def _block_resize(self,event):
        if self.tree.identify_region(event.x,event.y)=='separator':return 'break'

    def _separator_cursor(self,event):
        self.tree.configure(cursor='arrow')
        if self.tree.identify_region(event.x,event.y)=='separator':return 'break'

    def _destroy(self,event):
        if event.widget is self.tree and self.pending is not None:
            self.tree.after_cancel(self.pending);self.pending=None

    def _scrolled(self,first,last):
        self.scrollbar.set(first,last);self.schedule()

    def set_enabled(self,enabled):
        if self.enabled!=enabled:self.enabled=enabled;self.schedule()

    def schedule(self,event=None):
        if self.pending is None:self.pending=self.tree.after_idle(self.refresh)

    def _wheel(self,event):
        if event.delta:self.tree.yview_scroll(-3 if event.delta>0 else 3,'units')
        return 'break'

    def refresh(self):
        self.pending=None
        action_width=84
        self.tree.column('actions',width=action_width,minwidth=action_width,stretch=False)
        self.tree.column('#0',width=max(1,self.tree.winfo_width()-action_width-4),minwidth=1,stretch=False)
        visible={self.tree.identify_row(y) for y in range(0,self.tree.winfo_height(),10)}-{''}
        for identity in set(self.buttons)-visible:
            for button in self.buttons.pop(identity):button.destroy()
        for identity in visible:
            if identity not in self.buttons:
                pair=[]
                for index,text in enumerate(('Play','Delete')):
                    button=tk.Button(self.tree,image=self.icons[index],text='',
                        bg='#84e4c7' if index==0 else '#192636',fg='#102720' if index==0 else '#ffb6b6',
                        activebackground='#a8f5df' if index==0 else '#354b60',
                        activeforeground='#102720' if index==0 else '#ffd0d0',
                        relief='flat',borderwidth=0,highlightthickness=0,padx=0,pady=0,cursor='hand2',
                        command=lambda key=identity,action=index:self.callbacks[action](key))
                    button.bind('<MouseWheel>',self._wheel);pair.append(button)
                    button.hover_label=HoverLabel(button,text+' '+self.tree.item(identity,'text'))
                self.buttons[identity]=pair
            for index,button in enumerate(self.buttons[identity]):
                bounds=self.tree.bbox(identity,'actions')
                if not bounds:button.place_forget();continue
                x,y,w,h=bounds
                button.configure(state='normal' if self.enabled else 'disabled')
                size=min(32,max(1,h-12))
                button.place(x=x+4+index*40,y=y+(h-size)//2,width=size,height=size)


class TabNavigation(tk.Frame):
    """Explicitly painted navigation independent of native notebook tab elements."""
    def __init__(self,parent,notebook,*,bg):
        super().__init__(parent,bg=bg)
        self.notebook=notebook
        self.buttons=[]
        for index,tab in enumerate(notebook.tabs()):
            self.columnconfigure(index,weight=1,uniform='tabs')
            button=tk.Button(self,text=notebook.tab(tab,'text'),width=1,
                font=('Segoe UI',10,'bold'),padx=4,pady=10,relief='flat',borderwidth=0,
                highlightthickness=1,highlightbackground=bg,highlightcolor='#84e4c7',cursor='hand2',
                command=lambda i=index:notebook.select(i))
            button.grid(row=0,column=index,sticky='ew',padx=(0,4 if index<len(notebook.tabs())-1 else 0))
            button.bind('<Left>',lambda event,i=index:self.choose((i-1)%len(self.buttons)))
            button.bind('<Right>',lambda event,i=index:self.choose((i+1)%len(self.buttons)))
            self.buttons.append(button)
        notebook.bind('<<NotebookTabChanged>>',self.update_selection,add='+')
        self.update_selection()

    def choose(self,index):
        self.notebook.select(index);self.buttons[index].focus_set()
        return 'break'

    def update_selection(self,event=None):
        selected=self.notebook.index('current')
        for index,button in enumerate(self.buttons):
            active=index==selected
            button.configure(bg='#84e4c7' if active else '#192636',
                fg='#102720' if active else '#9db7cc',
                activebackground='#a8f5df' if active else '#263649',
                activeforeground='#102720' if active else '#eff5fc')


class ScrollableFrame(tk.Frame):
    """A width-fitting panel with a visible scrollbar and locally routed wheel input."""

    def __init__(self,parent,*,bg,**kwargs):
        super().__init__(parent,bg=bg,**kwargs)
        self.columnconfigure(0,weight=1)
        self.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(self,bg=bg,highlightthickness=0,borderwidth=0,
                              width=1,height=1,yscrollincrement=24)
        self.scrollbar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        self.scrollbar.grid(row=0,column=1,sticky='ns')
        self.content=tk.Frame(self.canvas,bg=bg)
        self._window=self.canvas.create_window(0,0,window=self.content,anchor='nw')
        self._bound=set()
        self.canvas.bind('<Configure>',self._layout)
        self.content.bind('<Configure>',self._layout)
        self.content.bind('<Map>',self._layout)

    def _layout(self,event=None):
        width=max(1,self.canvas.winfo_width())
        height=max(self.canvas.winfo_height(),self.content.winfo_reqheight())
        self.canvas.itemconfigure(self._window,width=width,height=height)
        self.canvas.configure(scrollregion=(0,0,width,height))
        self._bind_wheel(self.canvas)

    def _bind_wheel(self,widget):
        if widget not in self._bound:
            for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'):
                widget.bind(sequence,self._wheel,add='+')
            self._bound.add(widget)
        for child in widget.winfo_children():self._bind_wheel(child)

    def _wheel(self,event):
        first,last=self.canvas.yview()
        if last-first>=0.999:return
        if getattr(event,'num',None) in (4,5):units=-3 if event.num==4 else 3
        else:
            delta=getattr(event,'delta',0)
            if not delta:return
            units=-max(1,abs(int(delta/120)))*3 if delta>0 else max(1,abs(int(delta/120)))*3
        self.canvas.yview_scroll(units,'units')
        return 'break'
