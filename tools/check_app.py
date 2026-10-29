"""Exercise the real Tk application callbacks and cached import without manual input."""
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import messagebox
import json
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import App

root=tk.Tk()
root.withdraw()
app=App(root)
app.preparation_paused=True
ui_errors=[]
messagebox.showerror=lambda *args:ui_errors.append(args)
try:
    app.import_demo()
    start=time.monotonic()
    while app.busy and time.monotonic()-start<20:
        root.update(); time.sleep(0.05)
    assert not app.busy,'Cached import did not complete'
    assert app.tree.selection(),'Imported game not selected'
    game=app.game()
    assert game['status']=='Ready'
    testlog=ROOT/'build/ui-metrics-test.log';testlog.write_text('')
    testlog.with_suffix('.stats.json').write_text(json.dumps({'fps':29.5,'frame_p95_ms':35.2,'input_queue_p95_ms':2.1,'scale':2,'updated':time.time()}))
    Path(str(testlog.with_suffix('.stats.json'))+'.gpu.json').write_text(json.dumps({'device':'NVIDIA GeForce RTX 2050','matched':True}))
    fake=Mock();fake.poll.return_value=None
    app.players[game['id']]=(fake,testlog)
    app.update_telemetry()
    assert '29.5 game FPS' in app.metrics.get() and '2.1 ms' in app.metrics.get()
    assert 'RTX 2050' in app.active_gpu.get(),'The actual GPU must be displayed'
    with patch('app.save_gpu_settings') as save:
        app.set_gpu('render_gpu','Integrated GPU')
        save.assert_called_once_with(render_gpu='integrated')
    app.capture_tick()
    root.update()
    app.players.clear()
    # Foreground imports queue without blocking the UI or disabling the button.
    app.busy=True
    app.import_demo()
    assert len(app.pending_imports)==1,'Import must queue during background work'
    assert 'disabled' not in app.add_button.state(),'Add game must remain available'
    app.busy=False;app.start_pending()
    start=time.monotonic()
    while app.busy and time.monotonic()-start<10:root.update();time.sleep(.03)
    assert not app.busy and not app.pending_imports,'Queued import must finish'

    # Playback starts immediately; the shared service gates optional live work.
    fake.poll.return_value=None
    with patch.object(app.library,'launch',return_value=(fake,testlog)) as launch, \
         patch.object(app.library.asset_service,'set_player_state') as player_state:
        app.play()
        launch.assert_called_once()
        player_state.assert_called_once()
        assert player_state.call_args.args[1] is True
    app.players.clear()

    with patch.object(app.library.asset_service,'pause_all') as pause, \
         patch.object(app.library.asset_service,'resume_all') as resume:
        app.toggle_preparation()
        assert not app.preparation_paused and resume.call_count==1
        app.toggle_preparation()
        assert app.preparation_paused and pause.call_count==1
    from startup_cleaner import MRBEAN
    if MRBEAN in app.games:
        app.tree.selection_set(MRBEAN);app.selected()
        assert 'disabled' not in app.wrapper_option.state(),'Verified repair must be selectable'
        profiled=app.games[MRBEAN];previous=profiled.get('remove_startup_wrappers')
        app.remove_wrappers.set(True)
        with patch.object(app.library,'save') as save:
            app.set_startup_cleanup()
            save.assert_called_once_with(profiled)
        assert profiled['remove_startup_wrappers'] is True
        if previous is None:profiled.pop('remove_startup_wrappers')
        else:profiled['remove_startup_wrappers']=previous
        app.selected()
    for unknown in app.games:
        if unknown!=MRBEAN:
            app.tree.selection_set(unknown);app.selected()
            assert 'disabled' in app.wrapper_option.state(),'Unknown JARs must not offer unverified removal'
            break
    app.search.set('no-matching-game-xyz');root.update()
    assert not app.tree.get_children(),'Search must filter the library'
    app.search.set('');root.update()
    root.update_idletasks()
    assert not ui_errors, f'Unexpected launcher error dialog: {ui_errors}'
    print('PASS: GPU settings, queued imports, shared-service pause/play coordination, optional verified startup and search.')
finally:
    app.library.asset_service.close(timeout=1.0)
    root.destroy()
