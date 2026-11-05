"""Tests for Stage 3: Responsive layout, dynamic wraplength, and flexible containers."""
import tkinter as tk
from tkinter import ttk
from unittest.mock import Mock, patch
import pytest

from ui_tokens import WIDTH_TREEVIEW_ACTIONS, WIDTH_RAIL
from ui_widgets import bind_dynamic_wraplength, LibraryRowActions


def destroy_widget(widget):
    try:
        widget.destroy()
    except tk.TclError:
        try:
            widget.tk.call('destroy', widget._w)
        except tk.TclError:
            pass


@pytest.fixture(scope='module')
def display():
    try:
        window = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f'Tk display unavailable: {error}')
    yield window
    for callback in window.tk.call('after', 'info'):
        window.after_cancel(callback)
    destroy_widget(window)


@pytest.fixture
def root(display):
    display.minsize(1, 1)
    yield display
    for callback in display.tk.call('after', 'info'):
        display.after_cancel(callback)
    for child in display.winfo_children():
        destroy_widget(child)


def test_bind_dynamic_wraplength_unit():
    """Test bind_dynamic_wraplength callback logic without requiring a physical screen."""
    container = Mock()
    container.winfo_width.return_value = 500
    label1 = Mock()
    label1.winfo_exists.return_value = True
    label1.cget.return_value = 0
    label2 = Mock()
    label2.winfo_exists.return_value = True
    label2.cget.return_value = 0

    callbacks = []

    def fake_bind(seq, cb, add=None):
        callbacks.append((seq, cb))

    container.bind.side_effect = fake_bind

    bind_dynamic_wraplength(container, label1, label2, padding=30, min_width=100)

    # Initial update called because container.winfo_width() > 1
    label1.configure.assert_called_with(wraplength=470)
    label2.configure.assert_called_with(wraplength=470)

    # Trigger Configure callback with event on container
    on_configure = callbacks[0][1]
    event = Mock()
    event.widget = container
    event.width = 800
    label1.cget.return_value = 470
    label2.cget.return_value = 470
    on_configure(event)
    label1.configure.assert_called_with(wraplength=770)
    label2.configure.assert_called_with(wraplength=770)

    # Event from child should be ignored
    child_event = Mock()
    child_event.widget = Mock()
    child_event.width = 200
    label1.configure.reset_mock()
    on_configure(child_event)
    label1.configure.assert_not_called()

    # Event with string width (like Map event '??') should fall back to container.winfo_width
    container.winfo_width.return_value = 600
    map_event = Mock()
    map_event.widget = container
    map_event.width = '??'
    label1.cget.return_value = 770
    on_configure(map_event)
    label1.configure.assert_called_with(wraplength=570)


def test_dynamic_wraplength_with_tk_widgets(root):
    """Test dynamic wraplength updates live when frame resizes in Tk."""
    f = tk.Frame(root, width=600, height=300)
    f.pack(fill='both', expand=True)
    lbl = tk.Label(f, text='Dynamic wrapping text for testing')
    lbl.pack(fill='x')

    bind_dynamic_wraplength(f, lbl, padding=40, min_width=100)
    root.update()

    initial_wrap = int(lbl.cget('wraplength'))
    assert initial_wrap == max(100, f.winfo_width() - 40)

    # Resize window
    root.geometry('800x400')
    root.update()
    new_wrap = int(lbl.cget('wraplength'))
    assert new_wrap == max(100, f.winfo_width() - 40)
    assert new_wrap > initial_wrap


def test_treeview_column_stretch_and_fixed_actions(root):
    """Verify that #0 column stretches and actions column stays fixed."""
    f = tk.Frame(root)
    f.pack(fill='both', expand=True)
    tree = ttk.Treeview(f, columns=('actions',), show='tree headings')
    tree.heading('#0', text='GAME')
    tree.column('#0', width=165, minwidth=1, stretch=True)
    tree.heading('actions', text='')
    tree.column('actions', width=WIDTH_TREEVIEW_ACTIONS, minwidth=WIDTH_TREEVIEW_ACTIONS, stretch=False)
    tree.pack(fill='both', expand=True)

    scrollbar = ttk.Scrollbar(f, orient='vertical', command=tree.yview)
    row_actions = LibraryRowActions(tree, scrollbar, Mock(), Mock())

    root.update()
    assert tree.column('#0', 'stretch') == 1
    assert tree.column('actions', 'stretch') == 0
    assert tree.column('actions', 'width') == WIDTH_TREEVIEW_ACTIONS

    # Simulate refresh call (which is called on idle and Configure)
    row_actions.refresh()
    root.update()

    # Verify that refresh maintains stretch=True and does not reset stretch to False
    assert tree.column('#0', 'stretch') == 1
    assert tree.column('actions', 'stretch') == 0
    assert tree.column('actions', 'width') == WIDTH_TREEVIEW_ACTIONS


def test_app_layout_sidebar_and_wrapping_integration(root, monkeypatch, tmp_path):
    """Integration test verifying App sidebar sizing, treeview stretch, and dynamic wraplength."""
    import app as app_module
    from tests.test_ui import PreviewLibrary

    library = PreviewLibrary(tmp_path, count=2)
    monkeypatch.setattr('app.Library', lambda *args, **kwargs: library)
    monkeypatch.setattr('app.DATA_ROOT', tmp_path)

    app = app_module.App(root)
    root.update()

    # Verify treeview configuration
    assert app.tree.column('#0', 'stretch') == 1
    assert app.tree.column('actions', 'stretch') == 0
    assert app.tree.column('actions', 'width') == WIDTH_TREEVIEW_ACTIONS

    # Verify sidebar (rail) does not force pack_propagate(False)
    rail = [c for c in root.winfo_children() if isinstance(c, tk.Frame) and c.winfo_x() == 0 and c.winfo_y() == 0][0]
    initial_rail_width = rail.winfo_width()
    assert initial_rail_width > 0

    # Resize window wider: rail must not grow uncontrollably, while tree and detail expand
    initial_detail_wrap = int(app.detail_title_label.cget('wraplength'))
    initial_status_wrap = int(app.status_label.cget('wraplength'))

    current_w = root.winfo_width()
    current_h = root.winfo_height()
    root.geometry(f'{current_w + 200}x{current_h + 100}')
    root.update()

    # Rail width should remain stable (content-driven, no expand=True)
    assert rail.winfo_width() == initial_rail_width

    # Detail label wraplength and status wraplength should have expanded with the window
    assert int(app.detail_title_label.cget('wraplength')) > initial_detail_wrap
    assert int(app.status_label.cget('wraplength')) > initial_status_wrap

