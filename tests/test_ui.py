"""Tk layout/interaction checks against isolated in-memory game metadata."""
from pathlib import Path
import threading
import time
import tkinter as tk
from unittest.mock import Mock

import pytest

from app import App
from ui_widgets import ScrollableFrame


def destroy_widget(widget):
    try:
        widget.destroy()
    except tk.TclError:
        # Python 3.14 can retain Tcl callback names after a child widget has
        # already removed them. Still ask Tk to remove the native widget.
        try:widget.tk.call('destroy',widget._w)
        except tk.TclError:pass


@pytest.fixture(scope='module')
def display():
    try:window=tk.Tk()
    except tk.TclError as error:pytest.skip(f'Tk display unavailable: {error}')
    window.title('JAR Revival UI test — test data only')
    yield window
    for callback in window.tk.call('after','info'):window.after_cancel(callback)
    destroy_widget(window)


@pytest.fixture
def root(display):
    display.minsize(1,1)
    yield display
    for callback in display.tk.call('after','info'):display.after_cancel(callback)
    for child in display.winfo_children():destroy_widget(child)


class PreviewLibrary:
    def __init__(self,base,count):
        self.rendered=base/'rendered';self.rendered.mkdir(parents=True)
        self.lock=threading.RLock()
        self.asset_service=Mock()
        self.rows=[{'id':f'{index+1:064x}','name':f'Test game {index+1:02d}',
                    'vendor':'Test data','width':240,'height':320,'assets':0,
                    'status':'Ready','backend':'pixel','compatibility':'Not measured'} for index in range(count)]
        self.deleted=[]

    def games(self):return [dict(row) for row in self.rows]
    def workspace(self,identity):return self.rendered/identity
    def texture_dir(self,folder,backend):return folder/'textures'
    def delete_game(self,identity,progress=lambda text:None):
        self.deleted.append(identity)
        self.rows=[row for row in self.rows if row['id']!=identity]
        return self.workspace(identity)/'saves'


def make_app(root,monkeypatch,base,*,count=20):
    library=PreviewLibrary(base,count)
    monkeypatch.setattr('app.Library',lambda:library)
    monkeypatch.setattr('app.gpu_devices',lambda:[])
    monkeypatch.setattr('ai_backend.available',lambda:False)
    app=App(root)
    root.geometry('980x680')
    root.title('JAR Revival UI check — test data only')
    root.update()
    return app,library


def test_wheel_scrolls_only_the_panel_containing_the_event(root):
    root.geometry('400x260')
    outside=tk.Entry(root);outside.pack(fill='x')
    panel=ScrollableFrame(root,bg='#192636');panel.pack(fill='both',expand=True)
    labels=[]
    for index in range(50):
        label=tk.Label(panel.content,text=f'Row {index}');label.pack(anchor='w');labels.append(label)
    root.update()
    assert panel.scrollbar.winfo_ismapped()
    assert panel.canvas.yview()[1]<1
    labels[0].event_generate('<MouseWheel>',delta=-120);root.update()
    assert panel.canvas.yview()[0]>0
    before=panel.canvas.yview()
    outside.event_generate('<MouseWheel>',delta=-120);root.update()
    assert panel.canvas.yview()==before
    panel.canvas.yview_moveto(1);root.update()
    assert panel.canvas.yview()[1]>=0.999
    assert panel.content.winfo_width()==panel.canvas.winfo_width()


def test_library_and_compatibility_tab_have_working_scrollbars(root,tmp_path,monkeypatch):
    app,_=make_app(root,monkeypatch,tmp_path)
    assert app.library_scrollbar.winfo_ismapped()
    assert not any(child.winfo_class()=='TScrollbar' and str(child.cget('orient'))=='horizontal'
                   for child in app.tree.master.winfo_children())
    assert app.tree['columns']==('actions',)
    assert app.tree.xview()==(0.0,1.0)
    assert app.row_actions.buttons
    assert not hasattr(app,'delete_button')
    assert app.tree.yview()[1]<1
    app.tree.yview_moveto(1);root.update()
    assert app.tree.yview()[0]>0
    app.tabs.select(2);root.update()
    view=app.detail_views[2]
    assert view.scrollbar.winfo_ismapped()
    assert view.canvas.yview()[1]<1
    first=view.content.winfo_children()[0]
    first.event_generate('<MouseWheel>',delta=-120);root.update()
    assert view.canvas.yview()[0]>0
    view.canvas.yview_moveto(1);root.update()
    last=view.content.winfo_children()[-1]
    assert last.winfo_rooty()+last.winfo_height()<=view.canvas.winfo_rooty()+view.canvas.winfo_height()+2


def test_switching_from_icon_to_jar_placeholder_keeps_preview_size(root,tmp_path,monkeypatch):
    app,_=make_app(root,monkeypatch,tmp_path,count=2)
    icon=tk.PhotoImage(width=96,height=96)
    app.cover.configure(image=icon,text='')
    root.update()
    before=app.cover.master.winfo_width()
    app.tree.selection_set(app.tree.get_children()[1]);root.update()
    assert app.cover.cget('text')=='JAR'
    assert int(app.cover.cget('width'))==0
    assert app.cover.master.winfo_width()==before==96


def test_navigation_has_visible_selection_and_constant_height(root,tmp_path,monkeypatch):
    app,_=make_app(root,monkeypatch,tmp_path,count=1)
    buttons=app.tab_navigation.buttons
    heights=[button.winfo_height() for button in buttons]
    assert len(set(heights))==1
    for index,button in enumerate(buttons):
        button.invoke();root.update()
        assert app.tabs.index('current')==index
        assert button.cget('background')=='#84e4c7'
        assert button.cget('foreground')=='#102720'
        assert [other.winfo_height() for other in buttons]==heights
        assert all(other.cget('background')=='#192636' for other in buttons if other is not button)


def test_delete_ui_requires_selection_confirmation_and_closed_player(root,tmp_path,monkeypatch):
    app,library=make_app(root,monkeypatch,tmp_path,count=1)
    identity=library.rows[0]['id']
    info=Mock();confirm=Mock(return_value=False)
    monkeypatch.setattr('app.messagebox.showinfo',info)
    monkeypatch.setattr('app.messagebox.askyesno',confirm)
    app.delete_game()
    assert library.deleted==[] and not app.busy
    player=Mock();player.poll.return_value=None
    app.players[identity]=(player,Path('unused.log'))
    confirm.return_value=True
    app.delete_game()
    assert library.deleted==[] and info.call_count==1 and confirm.call_count==1
    app.players.clear()
    app.delete_game()
    deadline=time.monotonic()+3
    while app.deleting_games and time.monotonic()<deadline:
        root.update();time.sleep(0.01)
    assert not app.busy and not app.deleting_games
    assert library.deleted==[identity]
    assert app.tree.get_children()==()
    assert app.cache_info.get()=='No game selected'
    assert not app.row_actions.buttons
    assert 'Saved progress kept' in app.status.get()


def test_multiple_deletions_run_in_background_and_error_restores_entry(root,tmp_path,monkeypatch):
    app,library=make_app(root,monkeypatch,tmp_path,count=2)
    first,second=[row['id'] for row in library.rows]
    entered=threading.Barrier(3,timeout=5);release=threading.Event()
    real_delete=library.delete_game
    def remove(identity):
        entered.wait();release.wait(5)
        if identity==first:raise OSError('simulated locked file')
        return real_delete(identity)
    library.delete_game=remove
    monkeypatch.setattr('app.messagebox.askyesno',lambda *args,**kwargs:True)
    error=Mock();monkeypatch.setattr('app.messagebox.showerror',error)
    try:
        app.delete_game();root.update()
        assert first not in app.tree.get_children() and not app.busy
        assert app.row_actions.enabled
        app.delete_game();root.update()
        entered.wait()
        assert len(app.deleting_games)==2 and not app.busy
    finally:release.set()
    deadline=time.monotonic()+5
    while app.deleting_games and time.monotonic()<deadline:root.update();time.sleep(0.01)
    assert not app.deleting_games
    assert app.tree.get_children()==(first,)
    assert library.deleted==[second] and error.call_count==1
    app._delete_workers.shutdown(wait=True)


def test_row_actions_target_clicked_game_and_follow_scroll(root,tmp_path,monkeypatch):
    app,library=make_app(root,monkeypatch,tmp_path,count=20)
    for pair in app.row_actions.buttons.values():
        for button in pair:
            assert button.cget('text')=='' and str(button.cget('image'))
            assert button.winfo_width()==button.winfo_height()==32
    app.tree.column('actions',width=200)
    app.row_actions.schedule();root.update()
    assert app.tree.column('actions','width')==84
    root.geometry('1100x760');root.update()
    assert all(button.winfo_width()==32 for pair in app.row_actions.buttons.values() for button in pair)
    ids=app.tree.get_children()
    launch=Mock();monkeypatch.setattr(app,'launch_game',launch)
    app.row_actions.buttons[ids[1]][0].invoke();root.update()
    assert launch.call_args.args[0]['id']==ids[1]
    app.tree.yview_moveto(1);root.update()
    assert ids[0] not in app.row_actions.buttons
    assert ids[-1] in app.row_actions.buttons
    confirm=Mock(return_value=False);monkeypatch.setattr('app.messagebox.askyesno',confirm)
    app.row_actions.buttons[ids[-1]][1].invoke();root.update()
    assert app.tree.selection()==(ids[-1],)
    assert library.deleted==[] and confirm.call_count==1
    app.search.set('Test game 01');root.update()
    assert set(app.row_actions.buttons)=={ids[0]}
